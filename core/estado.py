"""
core/estado.py — Estado global compartido entre todos los agentes.
Cada agente lee y escribe acá para comunicarse.

Thread-safety: todas las mutaciones de listas y campos críticos
usan _lock para evitar race conditions entre hilos.
"""

from datetime import datetime
import threading
from config_loader import CONFIG

_lock = threading.Lock()

estado = {
    "corriendo":        False,
    "modo":             CONFIG.get("modo", "simulacion"),
    "saldo":            CONFIG.get("saldo_inicial", 1000.0),
    "pnl":              0.0,
    "riesgo_por_op":    CONFIG.get("riesgo_por_op", 10.0),
    "operaciones":      [],
    "mercados":         [],
    "log":              [],
    "telegram_activo":  False,
    "ciclo_num":        0,
    "señales_cripto":   {},             # publicado por agentes/binance.py
}


def addlog(msg, tipo=""):
    """Agrega una línea al log. tipo: '' | 'win' | 'loss' | 'error' | 'info'"""
    with _lock:
        now = datetime.now().strftime("%H:%M:%S")
        estado["log"].insert(0, {"time": now, "msg": msg, "tipo": tipo})
        if len(estado["log"]) > 100:
            estado["log"].pop()
    print(f"[{now}] {msg}")


# ─── Operaciones thread-safe sobre listas ────────────────────────────────────

def set_mercados(nueva_lista):
    """Reemplaza la lista de mercados de forma atómica."""
    with _lock:
        estado["mercados"] = nueva_lista


def insertar_mercado(mercado):
    """Inserta un mercado al frente si su id no existe ya."""
    with _lock:
        ids = {m["id"] for m in estado["mercados"]}
        if mercado["id"] not in ids:
            estado["mercados"].insert(0, mercado)


def get_mercados():
    """Devuelve una copia snapshot de la lista de mercados."""
    with _lock:
        return list(estado["mercados"])


def insertar_operacion(op):
    """Inserta una operación al frente de la lista."""
    with _lock:
        estado["operaciones"].insert(0, op)


def get_operaciones():
    """Devuelve una copia snapshot de las operaciones."""
    with _lock:
        return list(estado["operaciones"])


def actualizar_saldo(delta):
    """Suma delta al saldo de forma atómica. Usar delta negativo para restar."""
    with _lock:
        estado["saldo"] = round(estado["saldo"] + delta, 2)


def actualizar_pnl(delta):
    """Suma delta al PnL de forma atómica."""
    with _lock:
        estado["pnl"] = round(estado["pnl"] + delta, 2)


def incrementar_ciclo():
    with _lock:
        estado["ciclo_num"] += 1
        return estado["ciclo_num"]


