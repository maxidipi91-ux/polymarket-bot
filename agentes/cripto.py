"""
agentes/cripto.py — Agente Cripto (DESCONECTADO — requiere wallet real)

LÓGICA CORRECTA (inspirada en bot $313 → $414K):
No predice si BTC va a subir o bajar.
Detecta cuando el precio de Polymarket TARDA en actualizar vs Binance.

El lag típico es de 2-10 segundos.
En ese momento, el precio de Polymarket está "viejo" → hay edge.

Para explotar esto correctamente se necesita:
1. Ciclo de 5-10 segundos (no 60s)
2. Wallet conectada para ejecutar en tiempo real
3. Salida inmediata cuando el precio de Polymarket se actualiza

Por ahora está DESCONECTADO del orquestador.
Se activa cuando: wallet real configurada + py-clob-client conectado.

Estrategia adicional (para cuando esté activo):
- Mercados de cripto de corto plazo (15 min, 1h)
- Comparar precio Polymarket vs precio real Binance/CoinGecko
- Si hay >5% de diferencia → entrar inmediatamente
- Salir cuando el precio de Polymarket converge (target: 2-5 min)
"""

import time
import requests
import json
from datetime import datetime
from core.estado import estado, addlog

GAMMA_URL    = "https://gamma-api.polymarket.com"
BINANCE_URLS = [
    "https://api.binance.com/api/v3/ticker/price",
    "https://api1.binance.com/api/v3/ticker/price",
    "https://api2.binance.com/api/v3/ticker/price",
]
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

INTERVALO_ACTIVO = 10   # Cuando esté activo: ciclo de 10 segundos
LAG_MINIMO       = 0.05  # Mínimo 5% de diferencia para considerar lag

CRIPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol",
                   "price above", "price below", "will btc", "will eth"]

BINANCE_SYMBOLS = {
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT",
}


def obtener_precio_cripto(symbol):
    """Obtiene precio actual de Binance con fallback a CoinGecko."""
    # Intentar Binance primero
    for url in BINANCE_URLS:
        try:
            r = requests.get(url, params={"symbol": symbol}, timeout=3)
            if r.status_code == 200:
                return float(r.json()["price"])
        except:
            continue
    # Fallback CoinGecko
    try:
        nombres = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana"}
        nombre = nombres.get(symbol, "bitcoin")
        r = requests.get(COINGECKO_URL,
                        params={"ids": nombre, "vs_currencies": "usd"},
                        timeout=5)
        return float(r.json()[nombre]["usd"])
    except:
        return None


def obtener_precios_cripto():
    """Obtiene BTC, ETH y SOL en tiempo real."""
    precios = {}
    for nombre, symbol in [("btc", "BTCUSDT"), ("eth", "ETHUSDT"), ("sol", "SOLUSDT")]:
        precio = obtener_precio_cripto(symbol)
        if precio:
            precios[nombre] = precio
    return precios


def detectar_lag_polymarket(mercados_raw, precios_reales):
    """
    Detecta mercados de cripto donde el precio de Polymarket
    no refleja el precio real actual.
    Retorna oportunidades ordenadas por tamaño del lag.
    """
    import re
    oportunidades = []

    for m in mercados_raw:
        pregunta = m.get("question", "").lower()
        if not any(k in pregunta for k in CRIPTO_KEYWORDS):
            continue

        liquidez = float(m.get("liquidity", 0) or 0)
        if liquidez < 1000:
            continue

        # Detectar cripto y umbral
        cripto = None
        for k in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"]:
            if k in pregunta:
                cripto = "btc" if k in ["btc", "bitcoin"] else \
                         "eth" if k in ["eth", "ethereum"] else "sol"
                break

        if not cripto or cripto not in precios_reales:
            continue

        precio_real = precios_reales[cripto]

        # Extraer umbral del mercado
        numeros = [float(n.replace(",","")) for n in re.findall(r'[\d,]+', pregunta)
                   if float(n.replace(",","")) > 100]
        if not numeros:
            continue

        umbral = numeros[0]

        # Obtener precio de Polymarket
        precios_poly = m.get("outcomePrices", "[]")
        outcomes_poly = m.get("outcomes", "[]")
        if isinstance(precios_poly, str): precios_poly = json.loads(precios_poly)
        if isinstance(outcomes_poly, str): outcomes_poly = json.loads(outcomes_poly)

        precio_poly_yes = None
        for o, p in zip(outcomes_poly, precios_poly):
            if o == "Yes":
                try: precio_poly_yes = float(p)
                except: pass

        if not precio_poly_yes:
            continue

        # Calcular probabilidad real basada en precio actual vs umbral
        if "above" in pregunta:
            # Si precio real ya está por encima del umbral
            if precio_real > umbral:
                gap = (precio_real - umbral) / umbral
                prob_real = min(0.90, 0.50 + gap * 3)
            else:
                gap = (umbral - precio_real) / umbral
                prob_real = max(0.10, 0.50 - gap * 3)
        else:
            continue

        lag = prob_real - precio_poly_yes

        if abs(lag) >= LAG_MINIMO:
            oportunidades.append({
                "pregunta":    m.get("question", ""),
                "cripto":      cripto.upper(),
                "precio_real": precio_real,
                "umbral":      umbral,
                "prob_real":   round(prob_real, 3),
                "precio_poly": round(precio_poly_yes, 3),
                "lag":         round(lag, 3),
                "liquidez":    liquidez,
                "outcome":     "Yes" if lag > 0 else "No",
            })

    oportunidades.sort(key=lambda x: abs(x["lag"]), reverse=True)
    return oportunidades


def correr():
    """
    DESCONECTADO — Este agente no corre hasta tener wallet real.
    Para activar: agregarlo a AGENTES_ACTIVOS en claudio.py
    """
    addlog("[Cripto] Agente DESCONECTADO — requiere wallet real para explotar lag de precios", "info")
    addlog("[Cripto] Lógica lista: detecta lag Polymarket vs Binance en tiempo real", "info")

    # Loop de monitoreo pasivo — solo muestra precios, no ejecuta
    while estado["corriendo"]:
        try:
            precios = obtener_precios_cripto()
            if precios:
                btc = precios.get("btc", 0)
                eth = precios.get("eth", 0)
                sol = precios.get("sol", 0)
                addlog(f"[Cripto] Monitor pasivo — BTC: ${btc:,.0f} | ETH: ${eth:,.0f} | SOL: ${sol:,.0f}", "info")
        except:
            pass

        # Esperar 5 minutos entre logs (no queremos spam)
        for _ in range(300):
            if not estado["corriendo"]: return
            time.sleep(1)
