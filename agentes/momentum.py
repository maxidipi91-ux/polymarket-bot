"""
agentes/momentum.py — Volume Spike + Kalshi Comparison

Estrategia 1 — Volume Spike:
  Detecta mercados donde el volumen subió >50% en la última hora sin
  que el precio se moviera. Señal de traders informados acumulando
  posición antes de que el precio se ajuste.

Estrategia 2 — Kalshi Comparison:
  Compara precios YES/NO de Polymarket vs Kalshi para los mismos eventos.
  Diferencias >10% entre plataformas = edge de arbitraje entre mercados.

Señal combinada: spike + diferencia Kalshi en el mismo mercado = ALTA confianza.
"""

import time
import json
import requests
from datetime import datetime
from core.estado import estado, addlog, insertar_mercado
from config_loader import CONFIG

GAMMA_URL     = "https://gamma-api.polymarket.com"
KALSHI_URL    = "https://api.elections.kalshi.com/trade-api/v2"
INTERVALO     = 300    # 5 minutos

SPIKE_RATIO   = 1.50   # Volumen actual > 1.5x el de hace 1 hora
SPIKE_MIN_VOL = 500    # Al menos $500 de volumen nuevo
KALSHI_EDGE   = 0.10   # Diferencia mínima entre plataformas (10%)
LIQUIDEZ_MIN  = 1000   # Liquidez mínima en Polymarket

_vol_history  = {}     # mercado_id → [(timestamp, volumen), ...]


def parsear_lista(valor):
    if isinstance(valor, list): return valor
    if isinstance(valor, str):
        try: return json.loads(valor)
        except: return []
    return []


# ─── Volume Spike ─────────────────────────────────────────────────────────────

def registrar_volumen(mercados):
    """Guarda snapshot del volumen actual de cada mercado."""
    ahora = time.time()
    for m in mercados:
        mid = m.get("id", "")
        vol = float(m.get("volume", 0) or 0)
        if mid not in _vol_history:
            _vol_history[mid] = []
        _vol_history[mid].append((ahora, vol))
        _vol_history[mid] = _vol_history[mid][-15:]  # últimas 75 min


def detectar_spikes(mercados):
    """
    Compara volumen actual vs hace ~1 hora.
    Retorna mercados donde el volumen creció más de SPIKE_RATIO.
    """
    ahora   = time.time()
    hace_1h = ahora - 3600
    spikes  = []

    for m in mercados:
        mid      = m.get("id", "")
        vol_now  = float(m.get("volume", 0) or 0)
        liquidez = float(m.get("liquidity", 0) or 0)

        if liquidez < LIQUIDEZ_MIN:
            continue

        historial     = _vol_history.get(mid, [])
        vol_anterior  = None
        for ts, vol in historial:
            if ts <= hace_1h:
                vol_anterior = vol

        if vol_anterior is None or vol_anterior <= 0:
            continue

        ratio     = vol_now / vol_anterior
        vol_nuevo = vol_now - vol_anterior

        if ratio >= SPIKE_RATIO and vol_nuevo >= SPIKE_MIN_VOL:
            spikes.append({
                "mercado":   m,
                "ratio":     round(ratio, 2),
                "vol_nuevo": round(vol_nuevo, 0),
            })

    spikes.sort(key=lambda x: x["ratio"], reverse=True)
    return spikes[:5]


# ─── Kalshi Comparison ────────────────────────────────────────────────────────

def kalshi_headers():
    key = CONFIG.get("kalshi_api_key", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def buscar_kalshi(pregunta):
    """
    Busca en Kalshi un mercado equivalente por keywords.
    Retorna (precio_yes_kalshi, ticker) o (None, None).
    """
    headers = kalshi_headers()
    if not headers:
        return None, None
    try:
        keywords = " ".join(pregunta.split()[:5])
        r = requests.get(
            f"{KALSHI_URL}/markets",
            params={"limit": 10, "status": "open", "search": keywords},
            headers=headers,
            timeout=8
        )
        markets = r.json().get("markets", [])
        if not markets:
            return None, None
        best = markets[0]
        yes_price = best.get("yes_ask") or best.get("last_price")
        if yes_price is not None:
            return round(float(yes_price) / 100, 4), best.get("ticker", "")
    except:
        pass
    return None, None


def comparar_kalshi(m_raw):
    """
    Retorna (edge, precio_kalshi) comparando YES de Polymarket vs Kalshi.
    edge > 0 significa Kalshi cree que vale más → comprar YES en Polymarket.
    """
    outcomes = parsear_lista(m_raw.get("outcomes", []))
    precios  = parsear_lista(m_raw.get("outcomePrices", []))
    precio_pm = None
    for o, p in zip(outcomes, precios):
        if "yes" in o.lower():
            try: precio_pm = float(p)
            except: pass
    if not precio_pm:
        return None, None

    precio_kalshi, ticker = buscar_kalshi(m_raw.get("question", ""))
    if not precio_kalshi:
        return None, None

    edge = precio_kalshi - precio_pm
    return round(edge, 4), precio_kalshi


# ─── Crear oportunidad para el Trader ────────────────────────────────────────

def crear_op(m_raw, spike=None, kalshi_edge=None, kalshi_precio=None):
    """Convierte señales de momentum en formato para el Trader."""
    pregunta  = m_raw.get("question", "")
    fecha_fin = (m_raw.get("endDate") or "")[:10] or "N/A"
    liquidez  = float(m_raw.get("liquidity", 0) or 0)
    volumen   = float(m_raw.get("volume", 0) or 0)

    outcomes = parsear_lista(m_raw.get("outcomes", []))
    precios  = parsear_lista(m_raw.get("outcomePrices", []))
    precio_yes = None
    for o, p in zip(outcomes, precios):
        if "yes" in o.lower():
            try: precio_yes = float(p)
            except: pass

    if not precio_yes or precio_yes < 0.10 or precio_yes > 0.90:
        return None

    # Fair value: Kalshi si hay, sino spike heurístico
    if kalshi_precio and kalshi_edge and kalshi_edge > KALSHI_EDGE:
        prob = kalshi_precio
    elif spike:
        prob = min(0.90, precio_yes + 0.08)
    else:
        return None

    edge = prob - precio_yes
    if edge < 0.05:
        return None

    tiene_spike  = spike is not None
    tiene_kalshi = kalshi_edge and kalshi_edge > KALSHI_EDGE
    confianza    = "ALTA" if (tiene_spike and tiene_kalshi) else "MEDIA"

    señales = []
    if tiene_spike:
        señales.append(f"spike x{spike['ratio']} (+${spike['vol_nuevo']:,.0f})")
    if tiene_kalshi:
        señales.append(f"Kalshi {round(kalshi_precio*100,1)}% vs PM {round(precio_yes*100,1)}%")

    return {
        "id":                    f"mom_{m_raw.get('id','')[:25]}_Yes",
        "pregunta":              pregunta,
        "outcome":               "Yes",
        "precio":                round(precio_yes, 4),
        "precio_pct":            round(precio_yes * 100, 1),
        "retorno_pct":           round((1 - precio_yes) / precio_yes * 100, 1),
        "liquidez":              round(liquidez, 0),
        "volumen":               round(volumen, 0),
        "fecha_fin":             fecha_fin,
        "margen":                round(abs(precio_yes - 0.5), 4),
        "score":                 round(edge, 4),
        "biases":                ["momentum"],
        "bias_score":            0.6,
        "tiene_noticias_gdelt":  False,
        "noticias_gdelt":        [],
        "decision":              "OPORTUNIDAD",
        "analizado":             True,
        "urgente":               edge > 0.15,
        "ultima_vez_analizado":  datetime.now(),
        "decision_investigador": "APOSTAR",
        "confianza":             confianza,
        "probabilidad_claudio":  round(prob, 4),
        "edge_calculado":        round(edge, 4),
        "metodo_analisis":       "Momentum",
        "razonamiento":          " | ".join(señales),
    }


# ─── Loop principal ───────────────────────────────────────────────────────────

def correr():
    kalshi_ok = bool(CONFIG.get("kalshi_api_key", ""))
    addlog(
        f"[Momentum] Iniciado — Spike {'✓' if True else ''} | "
        f"Kalshi {'✓' if kalshi_ok else '✗ (sin key)'}",
        "info"
    )
    time.sleep(60)  # Primer ciclo: solo registrar snapshot base

    while estado["corriendo"]:
        try:
            r = requests.get(f"{GAMMA_URL}/markets", params={
                "active": "true", "closed": "false", "limit": 500
            }, timeout=15)
            mercados_raw = r.json()

            registrar_volumen(mercados_raw)
            spikes      = detectar_spikes(mercados_raw)
            encontrados = []
            procesados  = set()

            # Señal 1: Volume spike (+ Kalshi si hay key)
            for spike in spikes:
                m   = spike["mercado"]
                mid = m.get("id", "")
                procesados.add(mid)

                k_edge, k_precio = comparar_kalshi(m) if kalshi_ok else (None, None)
                op = crear_op(m, spike=spike, kalshi_edge=k_edge, kalshi_precio=k_precio)
                if op:
                    encontrados.append(op)
                    insertar_mercado(op)
                    tipo = "SPIKE+KALSHI" if (k_edge and k_edge > KALSHI_EDGE) else "SPIKE"
                    addlog(
                        f"[Momentum] {tipo}: {m.get('question','')[:45]}... "
                        f"| {op['razonamiento']} | {op['confianza']}",
                        "win"
                    )

            # Señal 2: Solo Kalshi (sin spike) para los primeros 100 mercados
            if kalshi_ok:
                for m in mercados_raw[:100]:
                    mid = m.get("id", "")
                    if mid in procesados: continue
                    if float(m.get("liquidity", 0) or 0) < LIQUIDEZ_MIN: continue

                    k_edge, k_precio = comparar_kalshi(m)
                    if k_edge and k_edge > KALSHI_EDGE:
                        op = crear_op(m, spike=None, kalshi_edge=k_edge, kalshi_precio=k_precio)
                        if op:
                            encontrados.append(op)
                            insertar_mercado(op)
                            addlog(
                                f"[Momentum] KALSHI: {m.get('question','')[:45]}... "
                                f"| {op['razonamiento']}",
                                "win"
                            )
                    time.sleep(0.15)  # Respetar rate limit de Kalshi

            if not encontrados:
                n_spikes = len(spikes)
                addlog(
                    f"[Momentum] {'%d spikes sin edge suficiente' % n_spikes if n_spikes else 'Sin señales en este ciclo'}"
                )

        except Exception as e:
            addlog(f"[Momentum] Error: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
