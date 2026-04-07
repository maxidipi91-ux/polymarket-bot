"""
agentes/salida.py — Agente de Salida de Posiciones v2
Paper trading con datos REALES de Polymarket.

No usa random() — monitorea el precio real cada 60 segundos.
Sale cuando el precio real se mueve a favor (take profit) o en contra (stop loss).

Esto convierte la simulación en paper trading real:
  - Si Liverpool estaba al 16% y sube al 18.4% → GANADA (take profit 15%)
  - Si baja al 14.4% → PERDIDA (stop loss 10%)
  - El winrate refleja si Claudio realmente detecta edge, no suerte
"""

import time
import requests
import json
from datetime import datetime, timedelta
from core.estado import estado, addlog, actualizar_saldo, actualizar_pnl, get_operaciones
from core.database import cerrar_operacion

GAMMA_URL   = "https://gamma-api.polymarket.com"
INTERVALO   = 60   # Monitorea cada 60 segundos

# ─── Parámetros de salida ─────────────────────────────────────────────────────
TAKE_PROFIT          = 0.15   # Salir si el precio subió 15% desde la entrada
STOP_LOSS            = 0.10   # Salir si el precio bajó 10% desde la entrada
MAX_HORAS            = 48     # Salir después de 48h aunque no haya movimiento
MIN_PROFIT_TIME_EXIT = 0.03   # Time exit solo si hay al menos 3% de ganancia


# ─── Caché de mercados para evitar N llamadas a la API ───────────────────────

_mercados_cache = []
_cache_ts = None
_CACHE_TTL_SEG = 90   # Refrescar cada 90s (un poco más que el ciclo del Trader)


def _obtener_mercados_cached():
    """
    Descarga los mercados UNA sola vez por ciclo de monitoreo y los reutiliza
    para todas las posiciones abiertas. Evita N llamadas a la API cuando hay N ops.
    """
    global _mercados_cache, _cache_ts
    ahora = datetime.now()
    if _cache_ts and (ahora - _cache_ts).total_seconds() < _CACHE_TTL_SEG:
        return _mercados_cache
    try:
        params = {"active": "true", "closed": "false", "limit": 500}
        r = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=10)
        _mercados_cache = r.json()
        _cache_ts = ahora
    except Exception as e:
        addlog(f"[Salida] Error actualizando cache de mercados: {e}", "error")
    return _mercados_cache


def obtener_precio_real(pregunta, outcome):
    """
    Obtiene el precio real de Polymarket usando la cache compartida del ciclo.
    Ya no descarga 500 mercados por cada posicion abierta.
    """
    try:
        mercados = _obtener_mercados_cached()
        for m in mercados:
            if pregunta[:25].lower() in m.get("question", "").lower():
                precios  = m.get("outcomePrices", "[]")
                outcomes = m.get("outcomes", "[]")
                if isinstance(precios, str):  precios  = json.loads(precios)
                if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                for o, p in zip(outcomes, precios):
                    if o == outcome:
                        return float(p)
    except:
        pass
    return None


def calcular_horas_abierta(op):
    """Calcula cuantas horas lleva abierta la operacion."""
    try:
        fecha_str = op.get("fecha_completa")
        if fecha_str:
            fecha = datetime.fromisoformat(fecha_str)
            return (datetime.now() - fecha).total_seconds() / 3600
    except:
        pass
    return 0


def evaluar_salida(op, precio_actual):
    """
    Evalua si hay que salir basandose en el precio REAL de Polymarket.
    Retorna (salir, motivo, ganancia_pct)
    """
    precio_entrada = op["precio"] / 100
    if not precio_actual or precio_entrada <= 0:
        return False, "", 0

    cambio = (precio_actual - precio_entrada) / precio_entrada
    horas  = calcular_horas_abierta(op)

    if cambio >= TAKE_PROFIT:
        return True, f"take_profit +{round(cambio*100,1)}%", cambio

    if cambio <= -STOP_LOSS:
        return True, f"stop_loss {round(cambio*100,1)}%", cambio

    if horas >= MAX_HORAS and cambio >= MIN_PROFIT_TIME_EXIT:
        return True, f"time_exit +{round(cambio*100,1)}%", cambio

    if horas >= MAX_HORAS and cambio < -0.02:
        return True, f"time_exit_loss {round(cambio*100,1)}%", cambio

    return False, "", cambio


def cerrar_posicion(op, precio_actual, motivo, ganancia_pct):
    """Cierra una posicion con el precio real de Polymarket (thread-safe)."""
    monto         = op["monto"]
    ganancia      = round(monto * ganancia_pct, 2)
    precio_salida = round(precio_actual * 100, 1)

    # Actualizar saldo y PnL de forma atomica
    actualizar_saldo(monto + ganancia)   # devolver monto + ganancia (o - perdida)
    actualizar_pnl(ganancia)

    gano = ganancia > 0
    op["estado"]        = "GANADA" if gano else "PERDIDA"
    op["resultado"]     = f"{'+'if gano else ''}${ganancia}"
    op["precio_salida"] = precio_salida
    op["motivo_salida"] = motivo

    # Guardar en DB
    db_id = op.get("db_id")
    if db_id:
        cerrar_operacion(db_id, precio_actual, ganancia, op["estado"])

    # Actualizar anti-martingale del Trader
    try:
        import agentes.trader as trader_mod
        trader_mod.ajustar_multiplicador(gano)
    except:
        pass

    emoji = "✅" if gano else "❌"
    addlog(
        f"[Salida] {emoji} {motivo.upper()} | {op['pregunta'][:35]}... | "
        f"entrada {op['precio']}% -> salida real {precio_salida}% | "
        f"{'+'if gano else ''}${ganancia}",
        "win" if gano else "loss"
    )

    # Notificar por Telegram
    try:
        from agentes.telegram_bot import enviar_mensaje
        enviar_mensaje(
            f"{emoji} <b>{motivo.upper()}</b>\n"
            f"Mercado: {op['pregunta'][:50]}\n"
            f"Entrada: {op['precio']}% -> Salida: {precio_salida}%\n"
            f"{'+'if gano else ''}${ganancia} | Saldo: ${estado['saldo']:.2f}"
        )
    except:
        pass

    return ganancia


def monitorear_posiciones():
    """
    Revisa todas las posiciones abiertas con precios reales de Polymarket.
    Usa un snapshot thread-safe de operaciones y cache de mercados.
    """
    abiertas = [op for op in get_operaciones() if op.get("estado") == "ABIERTA"]

    if not abiertas:
        return

    addlog(f"[Salida] Monitoreando {len(abiertas)} posiciones con precios reales...")

    # Refrescar cache una sola vez para todo el ciclo
    _obtener_mercados_cached()

    for op in abiertas:
        try:
            precio_actual = obtener_precio_real(op["pregunta"], op["outcome"])

            if precio_actual is None:
                addlog(f"[Salida] No se pudo obtener precio real para {op['pregunta'][:30]}...", "error")
                continue

            precio_entrada = op["precio"] / 100
            cambio_pct     = round((precio_actual - precio_entrada) / precio_entrada * 100, 1)
            horas          = round(calcular_horas_abierta(op), 1)

            addlog(
                f"[Salida] {op['pregunta'][:35]}... | "
                f"entrada {op['precio']}% -> actual {round(precio_actual*100,1)}% | "
                f"cambio {'+' if cambio_pct >= 0 else ''}{cambio_pct}% | "
                f"{horas}h abierta",
                "win" if cambio_pct > 0 else "loss" if cambio_pct < -3 else ""
            )

            salir, motivo, ganancia_pct = evaluar_salida(op, precio_actual)

            if salir:
                cerrar_posicion(op, precio_actual, motivo, ganancia_pct)

        except Exception as e:
            addlog(f"[Salida] Error: {e}", "error")


def correr():
    addlog("[Salida] v2 iniciado — paper trading con precios REALES de Polymarket", "info")
    addlog("[Salida] Take profit 15% | Stop loss 10% | Max 48h | Sin random()", "info")
    time.sleep(20)

    while estado["corriendo"]:
        try:
            monitorear_posiciones()
        except Exception as e:
            addlog(f"[Salida] Error general: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
