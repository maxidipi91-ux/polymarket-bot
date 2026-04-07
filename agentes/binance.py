"""
agentes/binance.py — Arbitraje BTC/ETH en mercados cortos de Polymarket

Lógica:
  1. Cada 15 segundos obtiene el precio spot de BTC/ETH desde Kraken.
  2. Calcula la volatilidad realizada de los últimos 30 minutos.
  3. Busca mercados de Polymarket con vencimiento en los próximos 2 horas
     que pregunten si BTC/ETH estará arriba o abajo de un precio dado.
  4. Calcula la probabilidad "fair value" con un modelo log-normal simple.
  5. Si |fair - precio_polymarket| > EDGE_MIN → marca como APOSTAR.

Sin LLM, sin noticias. Edge puro de precio.
Fuente: Kraken (sin restricciones geo, compatible con VPS en USA).
"""

import time
import math
import re
import json
import requests
from datetime import datetime, timezone

from core.estado import estado, addlog, merge_mercados_binance
from core.database import guardar_mercado, guardar_analisis

KRAKEN_URL     = "https://api.kraken.com/0/public"
GAMMA_URL      = "https://gamma-api.polymarket.com"

# Mapeo symbol Binance → Kraken
KRAKEN_PAIRS   = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD"}

INTERVALO_SEG  = 15     # Revisar cada 15 segundos
EDGE_MIN       = 0.10   # Edge mínimo 10%
MAX_MINS       = 120    # Solo mercados que vencen en las próximas 2 horas
MIN_MINS       = 2      # Descartar si quedan menos de 2 minutos (riesgo de ejecución)
LIQUIDEZ_MIN   = 1000   # Mínimo $1,000 de liquidez


# ─── Kraken: precio y volatilidad ────────────────────────────────────────────

def obtener_precio(symbol):
    """Precio spot actual desde Kraken."""
    try:
        pair = KRAKEN_PAIRS.get(symbol, symbol)
        r = requests.get(f"{KRAKEN_URL}/Ticker", params={"pair": pair}, timeout=5)
        result = r.json().get("result", {})
        if not result:
            return None
        key = list(result.keys())[0]
        return float(result[key]["c"][0])  # "c" = last trade closed price
    except:
        return None


def obtener_volatilidad(symbol, periodos=30):
    """
    Volatilidad realizada sobre los últimos N minutos (OHLC de 1m en Kraken).
    Devuelve volatilidad anualizada. Fallback: 80% para BTC, 90% para ETH.
    """
    fallbacks = {"BTCUSDT": 0.80, "ETHUSDT": 0.90}
    try:
        pair = KRAKEN_PAIRS.get(symbol, symbol)
        r = requests.get(f"{KRAKEN_URL}/OHLC", params={
            "pair":     pair,
            "interval": 1,       # 1 minuto
        }, timeout=5)
        result = r.json().get("result", {})
        if not result:
            return fallbacks.get(symbol, 0.80)
        key = [k for k in result.keys() if k != "last"][0]
        ohlc = result[key][-periodos:]  # últimos N candles
        closes = [float(k[4]) for k in ohlc]
        if len(closes) < 5:
            return fallbacks.get(symbol, 0.80)

        retornos = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        media    = sum(retornos) / len(retornos)
        varianza = sum((r - media) ** 2 for r in retornos) / len(retornos)
        std_min  = math.sqrt(varianza)

        # 525,600 minutos en un año
        vol_anual = std_min * math.sqrt(525_600)
        return max(0.40, min(2.50, vol_anual))
    except:
        return fallbacks.get(symbol, 0.80)


# ─── Modelo de probabilidad ──────────────────────────────────────────────────

def norm_cdf(x):
    """CDF normal estándar — aproximación de Abramowitz & Stegun (error < 1.5e-7)."""
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def prob_arriba(spot, strike, vol_anual, minutos):
    """
    P(precio_final > strike) bajo modelo log-normal.
    Asume drift cero (razonable para timeframes de minutos).
    """
    if minutos <= 0 or strike <= 0 or spot <= 0:
        return 0.5
    t  = minutos / 525_600
    d2 = (math.log(spot / strike) - 0.5 * vol_anual ** 2 * t) / (vol_anual * math.sqrt(t))
    return norm_cdf(d2)


# ─── Parsing de mercados ──────────────────────────────────────────────────────

def extraer_strike(pregunta):
    """
    Extrae el precio strike de preguntas tipo:
      "Will BTC be above $95,000 on ..."
      "Bitcoin above 94500 USDT at ..."
    """
    patrones = [
        r'\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)',              # $95,000
        r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:USDT|USD)',    # 95000 USDT
        r'(?:above|below|over|under)\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',
    ]
    for patron in patrones:
        m = re.search(patron, pregunta, re.IGNORECASE)
        if m:
            try:
                valor = float(m.group(1).replace(",", ""))
                if 100 < valor < 100_000_000:   # rango sensato para BTC/ETH
                    return valor
            except:
                continue
    return None


def minutos_restantes(fecha_fin_str):
    """Minutos hasta el vencimiento. None si no se puede parsear."""
    try:
        ahora = datetime.now(timezone.utc)
        s = fecha_fin_str.rstrip("Z")
        if "+" in s:
            venc = datetime.fromisoformat(fecha_fin_str)
        else:
            venc = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return (venc - ahora).total_seconds() / 60
    except:
        return None


def parsear_lista(valor):
    if isinstance(valor, list): return valor
    if isinstance(valor, str):
        try: return json.loads(valor)
        except: return []
    return []


# ─── Análisis de un mercado ───────────────────────────────────────────────────

def analizar(m_raw, precios_spot, vols):
    """
    Recibe un mercado crudo de Polymarket y los precios/vols de Binance.
    Devuelve un dict enriquecido si hay edge, o None si no lo hay.
    """
    pregunta  = m_raw.get("question", "")
    fecha_fin = m_raw.get("endDate", "")
    liquidez  = float(m_raw.get("liquidity", 0) or 0)
    volumen   = float(m_raw.get("volume",    0) or 0)

    if liquidez < LIQUIDEZ_MIN:
        return None

    # Detectar asset
    pq = pregunta.lower()
    if any(k in pq for k in ["eth", "ethereum"]):
        asset   = "ETH"
        symbol  = "ETHUSDT"
    elif any(k in pq for k in ["btc", "bitcoin"]):
        asset   = "BTC"
        symbol  = "BTCUSDT"
    else:
        return None

    spot = precios_spot.get(symbol)
    vol  = vols.get(symbol)
    if not spot or not vol:
        return None

    # Tiempo restante
    mins = minutos_restantes(fecha_fin)
    if mins is None or mins < MIN_MINS or mins > MAX_MINS:
        return None

    # Strike
    strike = extraer_strike(pregunta)
    if not strike:
        return None

    # Dirección: above o below
    es_above = any(w in pq for w in ["above", "over", "higher", "exceed"])
    es_below = any(w in pq for w in ["below", "under", "lower"])
    if not es_above and not es_below:
        return None   # no podemos determinar dirección → skip

    # Fair value para el outcome YES
    p_arriba  = prob_arriba(spot, strike, vol, mins)
    fair_yes  = p_arriba if es_above else (1 - p_arriba)

    # Buscar outcomes y encontrar el de mayor edge
    outcomes = parsear_lista(m_raw.get("outcomes"))
    precios  = parsear_lista(m_raw.get("outcomePrices"))
    if not outcomes or not precios:
        return None

    mejor_edge     = 0.0
    mejor_outcome  = None
    mejor_precio_pm = None
    fair_elegido   = None

    for outcome, precio_str in zip(outcomes, precios):
        try:
            pm = float(precio_str)
            if pm < 0.05 or pm > 0.95:
                continue
            fair = fair_yes if "yes" in outcome.lower() else (1 - fair_yes)
            edge = fair - pm
            if abs(edge) > abs(mejor_edge):
                mejor_edge      = edge
                mejor_outcome   = outcome
                mejor_precio_pm = pm
                fair_elegido    = fair
        except:
            continue

    if mejor_outcome is None or abs(mejor_edge) < EDGE_MIN:
        return None

    confianza = "ALTA" if abs(mejor_edge) >= 0.15 else "MEDIA"
    mercado_id = f"binance_{asset}_{pregunta[:35]}_{mejor_outcome}"

    return {
        "id":                    mercado_id,
        "pregunta":              pregunta,
        "outcome":               mejor_outcome,
        "precio":                round(mejor_precio_pm, 4),
        "precio_pct":            round(mejor_precio_pm * 100, 1),
        "retorno_pct":           round((1 - mejor_precio_pm) / mejor_precio_pm * 100, 0),
        "liquidez":              round(liquidez, 0),
        "volumen":               round(volumen, 0),
        "fecha_fin":             fecha_fin[:16] if fecha_fin else "N/A",
        "margen":                round(abs(mejor_precio_pm - 0.5), 4),
        "score":                 round(abs(mejor_edge), 4),
        "biases":                [],
        "bias_score":            0.0,
        "tiene_noticias_gdelt":  False,
        "noticias_gdelt":        [],
        "decision":              "OPORTUNIDAD",
        "analizado":             True,
        "urgente":               abs(mejor_edge) >= 0.20,
        "ultima_vez_analizado":  datetime.now(),
        # Campos que el Trader ya sabe leer
        "decision_investigador": "APOSTAR",
        "confianza":             confianza,
        "probabilidad_claudio":  round(fair_elegido, 4),
        "edge_calculado":        round(mejor_edge, 4),
        "metodo_analisis":       f"Binance/{asset}",
        "razonamiento": (
            f"{asset} ${spot:,.0f} | strike ${strike:,.0f} | "
            f"{mins:.0f}min | fair {round(fair_yes*100,1)}% | "
            f"PM {round(mejor_precio_pm*100,1)}% | edge {round(mejor_edge*100,1)}%"
        ),
    }


# ─── Loop principal ──────────────────────────────────────────────────────────

def correr():
    addlog("[Kraken] Agente iniciado — arbitraje BTC/ETH via Kraken", "info")

    while estado["corriendo"]:
        try:
            # 1. Precios y volatilidades de Binance
            precios_spot = {
                "BTCUSDT": obtener_precio("BTCUSDT"),
                "ETHUSDT": obtener_precio("ETHUSDT"),
            }
            vols = {
                "BTCUSDT": obtener_volatilidad("BTCUSDT"),
                "ETHUSDT": obtener_volatilidad("ETHUSDT"),
            }

            btc = precios_spot.get("BTCUSDT")
            eth = precios_spot.get("ETHUSDT")
            if not btc:
                addlog("[Kraken] Sin precio BTC — reintentando en 60s", "info")
                for _ in range(60):
                    if not estado["corriendo"]: return
                    time.sleep(1)
                continue

            addlog(
                f"[Kraken] BTC ${btc:,.0f} | ETH ${eth:,.0f} | "
                f"vol BTC {round(vols['BTCUSDT']*100,0)}%",
                "info"
            )

            # 2. Mercados activos de Polymarket
            try:
                r = requests.get(f"{GAMMA_URL}/markets", params={
                    "active": "true", "closed": "false", "limit": 500
                }, timeout=15)
                mercados_raw = r.json()
            except Exception as e:
                addlog(f"[Binance] Error Polymarket: {e}", "error")
                time.sleep(INTERVALO_SEG)
                continue

            # 3. Analizar y filtrar
            encontrados = []
            for m in mercados_raw:
                resultado = analizar(m, precios_spot, vols)
                if resultado:
                    encontrados.append(resultado)
                    guardar_mercado(resultado["id"], resultado["pregunta"], resultado["fecha_fin"])
                    guardar_analisis(
                        resultado["id"],
                        resultado["precio"],
                        resultado["probabilidad_claudio"],
                        resultado["margen"],
                        [],
                        resultado["decision_investigador"],
                        resultado["razonamiento"],
                    )

            # 4. Actualizar estado (solo la porción Binance)
            merge_mercados_binance(encontrados)

            if encontrados:
                addlog(
                    f"[Binance] {len(encontrados)} oportunidades — "
                    f"mejor edge: {round(max(abs(m['edge_calculado']) for m in encontrados)*100,1)}%",
                    "win"
                )
                for m in sorted(encontrados, key=lambda x: abs(x["edge_calculado"]), reverse=True)[:3]:
                    addlog(
                        f"[Binance] ✦ {m['pregunta'][:45]}... "
                        f"→ {m['outcome']} | {m['razonamiento']}",
                        "win"
                    )
            else:
                addlog("[Binance] Sin edge suficiente en mercados BTC/ETH activos", "info")

        except Exception as e:
            addlog(f"[Binance] Error inesperado: {e}", "error")

        for _ in range(INTERVALO_SEG):
            if not estado["corriendo"]:
                return
            time.sleep(1)
