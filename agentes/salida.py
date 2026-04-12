"""
agentes/salida.py — Agente de Salida de Posiciones v3

Dos modos de salida según el tipo de mercado:

1. Resolución instantánea (deportes, esports, eventos 1-day):
   - Esperar precio >= 95% → GANADA (redimir tokens automáticamente)
   - Esperar precio <= 5%  → PERDIDA (corte duro, no hay reversión)
   - Safety net: 48h para cierre forzado

2. Mercados continuos (BTC/ETH precios, elecciones largas, etc.):
   - Take profit: +15% desde entrada
   - Stop loss:   -10% desde entrada
   - Time exit:   48h con ganancia mínima 3%
"""

import time
import threading
import requests
import json
from datetime import datetime, timedelta
from core.estado import estado, addlog, actualizar_saldo, actualizar_pnl, get_operaciones
from core.database import cerrar_operacion

GAMMA_URL   = "https://gamma-api.polymarket.com"
INTERVALO   = 60   # Monitorea cada 60 segundos

# ─── Parámetros — resolución instantánea ─────────────────────────────────────
UMBRAL_GANADA  = 0.95   # Precio >= 95% → resolucion_ganada
UMBRAL_PERDIDA = 0.05   # Precio <= 5%  → resolucion_perdida

# ─── Parámetros — mercados continuos ─────────────────────────────────────────
TAKE_PROFIT          = 0.15   # +15% desde entrada
STOP_LOSS            = 0.10   # -10% desde entrada
MAX_HORAS            = 48     # Forzar salida tras 48h
MIN_PROFIT_TIME_EXIT = 0.03   # Time exit solo si ganancia >= 3%


# ─── Caché de mercados ────────────────────────────────────────────────────────

_mercados_cache = []
_cache_ts = None
_CACHE_TTL_SEG = 90


def _obtener_mercados_cached():
    global _mercados_cache, _cache_ts
    ahora = datetime.now()
    if _cache_ts and (ahora - _cache_ts).total_seconds() < _CACHE_TTL_SEG:
        return _mercados_cache
    try:
        resultado = []
        for offset in [0, 500]:
            params = {"active": "true", "closed": "false", "limit": 500, "offset": offset,
                      "order": "volume24hr", "ascending": "false"}
            r = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=10)
            batch = r.json()
            resultado.extend(batch)
            if len(batch) < 500:
                break
        _mercados_cache = resultado
        _cache_ts = ahora
    except Exception as e:
        addlog(f"[Salida] Error actualizando cache de mercados: {e}", "error")
    return _mercados_cache


def _extraer_polymarket_id(pregunta):
    """Extrae el ID real de Polymarket de un ID sintético (mom_<id>_Yes, arb_<id>_Yes)."""
    for prefijo in ("mom_", "arb_"):
        if pregunta.startswith(prefijo):
            resto  = pregunta[len(prefijo):]
            partes = resto.rsplit("_", 1)
            if len(partes) == 2:
                return partes[0]
    return None


def _es_resolucion_instantanea(pregunta: str) -> bool:
    """
    Detecta si el mercado es de resolución instantánea (deportes, esports, eventos 1-day).
    En estos mercados NO aplicamos stop-loss durante el partido — esperamos 95%/5%.
    """
    p = pregunta.lower()
    if " vs " in p or " vs. " in p:           return True
    if "win on " in p or "win the " in p:     return True
    if "end in " in p or "end in a " in p:    return True
    if "up or down" in p or "higher or lower" in p: return True
    if any(x in p for x in ["lpl", "lck", " bo3", " bo5", "esports", "dota", "valorant", "league of legends"]):
        return True
    return False


def obtener_precio_real(pregunta, outcome):
    """
    Obtiene el precio real de Polymarket usando la cache compartida del ciclo.
    Soporta IDs sintéticos (mom_, arb_) y matching por texto.
    """
    try:
        mercados = _obtener_mercados_cached()

        pm_id = _extraer_polymarket_id(pregunta)
        if pm_id:
            for m in mercados:
                if m.get("id", "") == pm_id or str(m.get("id", "")).startswith(pm_id[:20]):
                    precios  = m.get("outcomePrices", "[]")
                    outcomes = m.get("outcomes", "[]")
                    if isinstance(precios, str):  precios  = json.loads(precios)
                    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                    for o, p in zip(outcomes, precios):
                        if o.lower() == outcome.lower():
                            return float(p)

        buscar = pregunta[:25].lower()
        for m in mercados:
            if buscar in m.get("question", "").lower():
                precios  = m.get("outcomePrices", "[]")
                outcomes = m.get("outcomes", "[]")
                if isinstance(precios, str):  precios  = json.loads(precios)
                if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                for o, p in zip(outcomes, precios):
                    if o.lower() == outcome.lower():
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
    Evalúa si hay que salir.
    Retorna (salir, motivo, ganancia_pct)

    Para mercados de resolución instantánea (deportes):
      - Sale solo a >=95% o <=5% (no durante el partido)
      - Safety net a 48h

    Para mercados continuos:
      - Take profit +15% / Stop loss -10% / Time exit 48h
    """
    precio_entrada = op["precio"] / 100
    if not precio_actual or precio_entrada <= 0:
        return False, "", 0

    cambio = (precio_actual - precio_entrada) / precio_entrada
    horas  = calcular_horas_abierta(op)

    pregunta = op.get("pregunta", "")
    es_instantaneo = _es_resolucion_instantanea(pregunta)

    if es_instantaneo:
        # Resolución instantánea — esperar resolución real
        if precio_actual >= UMBRAL_GANADA:
            return True, "resolucion_ganada", cambio
        if precio_actual <= UMBRAL_PERDIDA:
            return True, "resolucion_perdida", cambio
        # Safety net: si lleva 48h y no resolvió, forzar con lo que haya
        if horas >= MAX_HORAS:
            if cambio >= 0:
                return True, f"time_exit +{round(cambio*100,1)}%", cambio
            else:
                return True, f"time_exit_loss {round(cambio*100,1)}%", cambio
    else:
        # Mercados continuos — take/stop normal
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

    actualizar_saldo(monto + ganancia)
    actualizar_pnl(ganancia)

    gano = ganancia > 0
    op["estado"]        = "GANADA" if gano else "PERDIDA"
    op["resultado"]     = f"{'+'if gano else ''}${ganancia}"
    op["precio_salida"] = precio_salida
    op["motivo_salida"] = motivo

    db_id = op.get("db_id")
    if db_id:
        cerrar_operacion(db_id, precio_actual, ganancia, op["estado"])

    # Cancelar órdenes CLOB abiertas para este mercado
    if estado.get("modo") == "real":
        try:
            from agentes.clob import cancelar_ordenes_abiertas
            cancelar_ordenes_abiertas()
        except Exception as e:
            addlog(f"[Salida] Error cancelando ordenes CLOB: {e}", "error")

    # Auto-redimir tokens ganadores en on-chain
    if motivo == "resolucion_ganada" and estado.get("modo") == "real":
        def _redimir():
            try:
                from agentes.clob import buscar_y_redimir
                pm_id = _extraer_polymarket_id(op.get("id", "")) or op.get("id", "")
                buscar_y_redimir(pm_id, op.get("outcome", "Yes"))
            except Exception as e:
                addlog(f"[Salida] Error auto-redimiendo: {e}", "error")
        threading.Thread(target=_redimir, daemon=True).start()

    # Anti-martingale
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
    """
    abiertas = [op for op in get_operaciones() if op.get("estado") == "ABIERTA"]
    if not abiertas:
        return

    addlog(f"[Salida] Monitoreando {len(abiertas)} posiciones con precios reales...")
    _obtener_mercados_cached()

    for op in abiertas:
        try:
            precio_actual = obtener_precio_real(op.get("id", op["pregunta"]), op["outcome"])

            if precio_actual is None:
                addlog(f"[Salida] No se pudo obtener precio real para {op['pregunta'][:30]}...", "error")
                continue

            precio_entrada = op["precio"] / 100
            cambio_pct     = round((precio_actual - precio_entrada) / precio_entrada * 100, 1)
            horas          = round(calcular_horas_abierta(op), 1)
            es_inst        = _es_resolucion_instantanea(op.get("pregunta", ""))
            tipo_str       = "⚡" if es_inst else "📈"

            addlog(
                f"[Salida] {tipo_str} {op['pregunta'][:35]}... | "
                f"entrada {op['precio']}% -> actual {round(precio_actual*100,1)}% | "
                f"cambio {'+' if cambio_pct >= 0 else ''}{cambio_pct}% | "
                f"{horas}h",
                "win" if cambio_pct > 0 else "loss" if cambio_pct < -3 else ""
            )

            salir, motivo, ganancia_pct = evaluar_salida(op, precio_actual)
            if salir:
                cerrar_posicion(op, precio_actual, motivo, ganancia_pct)

        except Exception as e:
            addlog(f"[Salida] Error: {e}", "error")


def correr():
    addlog("[Salida] v3 iniciado — resolución instantánea (95%/5%) + continuos (TP15%/SL10%)", "info")
    time.sleep(20)

    while estado["corriendo"]:
        try:
            monitorear_posiciones()
        except Exception as e:
            addlog(f"[Salida] Error general: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
