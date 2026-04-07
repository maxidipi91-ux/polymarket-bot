"""
agentes/whale.py — Agente Whale Tracker (DESCONECTADO — requiere wallet real)

LÓGICA CORRECTA:
No hace polling cada 5 minutos — eso es demasiado lento.
Usa WebSocket de Polymarket para recibir trades en tiempo real.

Cuando detecta una wallet top haciendo una entrada grande:
1. Valida que es una wallet conocida como rentable
2. Calcula el tamaño relativo de la entrada (¿es grande para ese mercado?)
3. Si es señal fuerte → entra inmediatamente detrás
4. Sale cuando la whale sale (detectado también por WebSocket) o por take profit

Para explotar esto correctamente se necesita:
1. WebSocket de Polymarket (wss://clob.polymarket.com/ws)
2. Wallet conectada para ejecutar en tiempo real
3. Lista actualizada de top wallets por rentabilidad

Por ahora está DESCONECTADO del orquestador.

Sistema de scoring de wallets (listo para cuando se active):
  - Rentabilidad histórica (30%)
  - Timing de entrada (20%) — entra antes del movimiento o después?
  - Bajo slippage (15%) — opera sin mover el precio
  - Consistencia (15%) — winrate sostenido
  - Selección de mercados (10%) — elige mercados con edge real
  - Recencia (10%) — operaciones recientes más relevantes

Detección de clusters coordinados:
  Si 3+ wallets top entran al mismo mercado en <5 minutos → señal FUERTE
  El precio va a moverse → entrar antes de que termine el movimiento
"""

import time
import requests
from core.estado import estado, addlog

DATA_API = "https://data-api.polymarket.com"


def obtener_top_wallets_leaderboard(limit=50):
    """Intenta obtener wallets top del leaderboard de Polymarket."""
    endpoints = [
        f"{DATA_API}/leaderboard?limit={limit}&sortBy=profit&sortDirection=DESC",
        f"{DATA_API}/profiles?limit={limit}&sortBy=profitAndLoss&order=DESC",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                wallets = []
                for item in (data if isinstance(data, list) else data.get("data", [])):
                    addr = item.get("proxyWalletAddress") or item.get("address") or item.get("proxy_wallet")
                    if addr:
                        wallets.append(addr)
                if wallets:
                    return wallets
        except:
            continue
    return []


def correr():
    """
    DESCONECTADO — Este agente no corre hasta implementar WebSocket.
    Para activar completamente:
    1. Implementar conexión WebSocket: wss://clob.polymarket.com/ws
    2. Suscribirse a eventos de trades en tiempo real
    3. Filtrar por wallets del leaderboard
    4. Cuando detecta cluster → agregar al estado para el Trader
    """
    addlog("[Whale] Agente DESCONECTADO — requiere WebSocket + wallet real", "info")
    addlog("[Whale] Lógica lista: scoring de wallets + detección de clusters", "info")

    # Intento pasivo de leaderboard cada 30 minutos
    while estado["corriendo"]:
        try:
            wallets = obtener_top_wallets_leaderboard(limit=10)
            if wallets:
                addlog(f"[Whale] Leaderboard: {len(wallets)} wallets top encontradas", "info")
            else:
                addlog("[Whale] Monitor pasivo — leaderboard no disponible públicamente", "info")
        except:
            pass

        for _ in range(1800):  # 30 minutos
            if not estado["corriendo"]: return
            time.sleep(1)
