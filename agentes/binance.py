"""
agentes/binance.py — Señales de contexto cripto (precios, F&G, funding)

Rol: proveedor de señales de mercado, NO analizador de oportunidades.
  - Publica BTC/ETH precios, volatilidad, Fear & Greed y funding rates
    en estado["señales_cripto"] para que otros agentes (Arbitraje, Trader)
    puedan usarlos como contexto.
  - Los mercados crypto de Polymarket (BTC/ETH preguntas largas) son
    analizados por Arbitraje vía LLM cascade como cualquier otro mercado.

Fuente: Kraken (sin restricciones geo, compatible con VPS en USA).
"""

import time
import math
import requests
from datetime import datetime

from core.estado import estado, addlog

KRAKEN_URL     = "https://api.kraken.com/0/public"
BYBIT_URL      = "https://api.bybit.com/v5/market"
FNG_URL        = "https://api.alternative.me/fng/?limit=1"

KRAKEN_PAIRS   = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD"}
INTERVALO_SEG  = 300    # Actualizar cada 5 minutos

_cache_fng      = {"valor": None, "label": None, "ts": 0}
_cache_funding  = {"BTCUSDT": None, "ETHUSDT": None, "ts": 0}
CACHE_TTL_FNG      = 86400
CACHE_TTL_FUNDING  = 3600


def obtener_fear_greed():
    ahora = time.time()
    if _cache_fng["valor"] is not None and ahora - _cache_fng["ts"] < CACHE_TTL_FNG:
        return _cache_fng["valor"], _cache_fng["label"]
    try:
        r = requests.get(FNG_URL, timeout=5)
        data = r.json()["data"][0]
        _cache_fng["valor"] = int(data["value"])
        _cache_fng["label"] = data["value_classification"]
        _cache_fng["ts"]    = ahora
        return _cache_fng["valor"], _cache_fng["label"]
    except:
        return None, None


def obtener_funding_rates():
    ahora = time.time()
    if _cache_funding["BTCUSDT"] is not None and ahora - _cache_funding["ts"] < CACHE_TTL_FUNDING:
        return dict(_cache_funding)
    try:
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            r = requests.get(f"{BYBIT_URL}/funding/history", params={
                "category": "linear", "symbol": symbol, "limit": 1
            }, timeout=5)
            lista = r.json().get("result", {}).get("list", [])
            if lista:
                _cache_funding[symbol] = float(lista[0]["fundingRate"])
        _cache_funding["ts"] = ahora
    except:
        pass
    return dict(_cache_funding)


def obtener_precio(symbol):
    try:
        pair = KRAKEN_PAIRS.get(symbol, symbol)
        r = requests.get(f"{KRAKEN_URL}/Ticker", params={"pair": pair}, timeout=5)
        result = r.json().get("result", {})
        if not result:
            return None
        key = list(result.keys())[0]
        return float(result[key]["c"][0])
    except:
        return None


def obtener_volatilidad(symbol, periodos=30):
    fallbacks = {"BTCUSDT": 0.80, "ETHUSDT": 0.90}
    try:
        pair = KRAKEN_PAIRS.get(symbol, symbol)
        r = requests.get(f"{KRAKEN_URL}/OHLC", params={"pair": pair, "interval": 1}, timeout=5)
        result = r.json().get("result", {})
        if not result:
            return fallbacks.get(symbol, 0.80)
        key = [k for k in result.keys() if k != "last"][0]
        ohlc   = result[key][-periodos:]
        closes = [float(k[4]) for k in ohlc]
        if len(closes) < 5:
            return fallbacks.get(symbol, 0.80)
        retornos = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        media    = sum(retornos) / len(retornos)
        varianza = sum((r - media) ** 2 for r in retornos) / len(retornos)
        vol_anual = math.sqrt(varianza) * math.sqrt(525_600)
        return max(0.40, min(2.50, vol_anual))
    except:
        return fallbacks.get(symbol, 0.80)


def correr():
    addlog("[Kraken] Agente iniciado — señales BTC/ETH (precios, F&G, funding) | ciclo 5min", "info")

    while estado["corriendo"]:
        try:
            btc = obtener_precio("BTCUSDT")
            eth = obtener_precio("ETHUSDT")

            if not btc:
                addlog("[Kraken] Sin precio BTC — reintentando en 60s", "info")
                for _ in range(60):
                    if not estado["corriendo"]: return
                    time.sleep(1)
                continue

            vol_btc = obtener_volatilidad("BTCUSDT")
            vol_eth = obtener_volatilidad("ETHUSDT")
            fng_valor, fng_label = obtener_fear_greed()
            fundings = obtener_funding_rates()

            estado["señales_cripto"] = {
                "btc":         btc,
                "eth":         eth,
                "vol_btc":     vol_btc,
                "vol_eth":     vol_eth,
                "fng_valor":   fng_valor,
                "fng_label":   fng_label,
                "funding_btc": fundings.get("BTCUSDT"),
                "funding_eth": fundings.get("ETHUSDT"),
                "ts":          datetime.now().isoformat(),
            }

            fng_txt     = f"FnG={fng_valor} ({fng_label})" if fng_valor else "FnG=N/A"
            funding_btc = fundings.get("BTCUSDT")
            funding_txt = f"Funding={round(funding_btc*100,4)}%" if funding_btc else "Funding=N/A"
            addlog(
                f"[Kraken] BTC ${btc:,.0f} | ETH ${eth:,.0f} | "
                f"vol BTC {round(vol_btc*100,0)}% | {fng_txt} | {funding_txt}",
                "info"
            )

        except Exception as e:
            addlog(f"[Kraken] Error: {e}", "error")

        for _ in range(INTERVALO_SEG):
            if not estado["corriendo"]:
                return
            time.sleep(1)
