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
from core.estado import estado, addlog

BINANCE_URLS = [
    "https://api.binance.com/api/v3/ticker/price",
    "https://api1.binance.com/api/v3/ticker/price",
    "https://api2.binance.com/api/v3/ticker/price",
]
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


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
