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
import json
from datetime import datetime, timedelta
from collections import defaultdict
from core.estado import estado, addlog

DATA_API   = "https://data-api.polymarket.com"
GAMMA_URL  = "https://gamma-api.polymarket.com"

# Parámetros
MIN_ENTRADA_WHALE    = 5000    # Mínimo $5K para considerar entrada de whale
MIN_CLUSTER_SIZE     = 3       # Mínimo 3 whales para señal de cluster
VENTANA_CLUSTER_MIN  = 5       # Detectar cluster en ventana de 5 minutos
SCORE_MINIMO         = 0.60    # Score mínimo de wallet para seguirla


def calcular_score_wallet(historial):
    """
    Calcula el score de una wallet basado en su historial.
    Retorna float entre 0 y 1.
    """
    if not historial:
        return 0

    total    = len(historial)
    ganadas  = sum(1 for h in historial if h.get("ganancia", 0) > 0)
    winrate  = ganadas / total if total > 0 else 0

    # Rentabilidad total
    ganancia_total = sum(h.get("ganancia", 0) for h in historial)
    roi = ganancia_total / sum(h.get("monto", 1) for h in historial) if historial else 0

    # Score compuesto
    score = (winrate * 0.40) + (min(roi, 2) / 2 * 0.40) + (min(total, 50) / 50 * 0.20)
    return round(min(score, 1.0), 3)


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


def monitorear_trades_recientes(wallet, minutos=10):
    """Obtiene trades recientes de una wallet."""
    try:
        params = {"maker": wallet, "limit": 20}
        r = requests.get(f"{DATA_API}/trades", params=params, timeout=8)
        if r.status_code == 200:
            trades = r.json()
            if isinstance(trades, list):
                # Filtrar últimos N minutos
                cutoff = datetime.now() - timedelta(minutes=minutos)
                recientes = []
                for t in trades:
                    try:
                        ts = t.get("timestamp") or t.get("createdAt", "")
                        if ts:
                            recientes.append(t)
                    except:
                        continue
                return recientes
    except:
        pass
    return []


def detectar_clusters(trades_por_mercado, ventana_min=VENTANA_CLUSTER_MIN):
    """Detecta cuando múltiples whales entran al mismo mercado."""
    clusters = []
    for mercado_id, entradas in trades_por_mercado.items():
        if len(entradas) >= MIN_CLUSTER_SIZE:
            monto_total = sum(e.get("monto", 0) for e in entradas)
            outcomes    = [e.get("outcome") for e in entradas]
            outcome_top = max(set(outcomes), key=outcomes.count) if outcomes else None
            coincidencia = outcomes.count(outcome_top) / len(outcomes) if outcomes else 0

            if coincidencia >= 0.70:
                clusters.append({
                    "mercado_id":    mercado_id,
                    "num_whales":    len(entradas),
                    "monto_total":   monto_total,
                    "outcome":       outcome_top,
                    "coincidencia":  round(coincidencia, 2),
                    "score":         len(entradas) * monto_total,
                })

    clusters.sort(key=lambda x: x["score"], reverse=True)
    return clusters


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
