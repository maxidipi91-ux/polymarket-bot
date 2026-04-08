"""
agentes/trader.py — Agente Trader v3
- Kelly cap 20%, edge mín 8%, sin confianza BAJA
- Límite 2 apuestas por tema (anti-concentración)
- Anti-martingale: sube riesgo en racha ganadora, baja en perdedora
- Nunca para completamente
"""

import time
import threading
from datetime import datetime
from core.estado import (estado, addlog, insertar_operacion,
                         actualizar_saldo, actualizar_pnl, get_mercados,
                         get_operaciones, incrementar_ciclo)
from core.database import guardar_operacion, get_mercados_apostados, guardar_memoria

INTERVALO_SEGUNDOS  = 90
apostados           = set()
_mult_lock          = threading.Lock()

# ─── Parámetros de riesgo ────────────────────────────────────────────────────
EDGE_MINIMO         = 0.08
KELLY_FACTOR        = 0.25
KELLY_MAX           = 0.20
MAX_PCT_SALDO       = 0.10
PRECIO_MIN_APOSTAR  = 0.15
PRECIO_MAX_APOSTAR  = 0.85
MAX_OPS_POR_TEMA    = 2

# ─── Anti-martingale ─────────────────────────────────────────────────────────
MULTIPLICADOR_MAX   = 2.0
MULTIPLICADOR_MIN   = 0.25
PASO_SUBIDA         = 0.25
PASO_BAJADA         = 0.25
UMBRAL_NOTIFICAR    = 0.50

multiplicador_actual = 1.0
racha_actual         = 0


def kelly_fraction(prob_estimada, precio_mercado):
    """Kelly Criterion con validaciones estrictas."""
    if not (0 < precio_mercado < 1): return 0
    if not (0 < prob_estimada < 1):  return 0

    b = (1 / precio_mercado) - 1
    p = prob_estimada
    q = 1 - p
    kelly_puro = (b * p - q) / b

    if kelly_puro <= 0:
        return 0

    if kelly_puro > 1.0:
        addlog(f"[Trader] ⚠️ Kelly puro={round(kelly_puro*100,0)}% — datos sospechosos, usando cap", "error")
        return 0.02

    kelly = kelly_puro * KELLY_FACTOR
    kelly = min(kelly, KELLY_MAX)
    return round(kelly, 4)


def contar_ops_por_tema(pregunta):
    """Cuenta operaciones recientes sobre el mismo tema (usa snapshot thread-safe)."""
    palabras_clave = set(pregunta.lower().split()[:6])
    count = 0
    for op in get_operaciones():
        if op.get("estado") in ["ABIERTA", "GANADA", "PERDIDA"]:
            palabras_op = set(op.get("pregunta", "").lower().split()[:6])
            if len(palabras_clave & palabras_op) >= 3:
                count += 1
    return count


def ajustar_multiplicador(gano):
    """Anti-martingale: ajusta el multiplicador según el resultado."""
    global multiplicador_actual, racha_actual

    with _mult_lock:
        mult_anterior = multiplicador_actual

        if gano:
            racha_actual = max(0, racha_actual) + 1
            multiplicador_actual = min(MULTIPLICADOR_MAX, multiplicador_actual + PASO_SUBIDA)
            if racha_actual >= 3:
                addlog(f"[Trader] 🔥 Racha ganadora x{racha_actual} — riesgo subió a {round(multiplicador_actual,2)}x", "win")
        else:
            racha_actual = min(0, racha_actual) - 1
            multiplicador_actual = max(MULTIPLICADOR_MIN, multiplicador_actual - PASO_BAJADA)
            if racha_actual <= -3:
                addlog(f"[Trader] ❄️ Racha perdedora x{abs(racha_actual)} — riesgo bajó a {round(multiplicador_actual,2)}x", "error")

        cambio      = abs(multiplicador_actual - mult_anterior)
        mult_actual = multiplicador_actual
        racha       = racha_actual

    # Persistir en DB para sobrevivir reinicios
    guardar_memoria("multiplicador", f"{mult_actual},{racha}")

    if cambio >= UMBRAL_NOTIFICAR:
        try:
            from agentes.telegram_bot import enviar_mensaje
            emoji = "📈" if gano else "📉"
            enviar_mensaje(
                f"{emoji} <b>Riesgo ajustado</b>\n"
                f"Multiplicador: {round(mult_anterior,2)}x → {round(mult_actual,2)}x\n"
                f"Racha: {racha:+d} operaciones\n"
                f"Riesgo por op: ${round(estado['riesgo_por_op'] * mult_actual, 2)}"
            )
        except:
            pass


def calcular_monto(mercado):
    """Calcula el monto a apostar con Kelly y anti-martingale."""
    precio = mercado["precio"]
    prob   = mercado.get("probabilidad_claudio", precio)

    with _mult_lock:
        mult = multiplicador_actual

    saldo  = estado["saldo"]
    riesgo = estado["riesgo_por_op"] * mult

    # Near-resolution: rango extendido hasta 99%, edge mínimo 1%
    # Odds outrights: rango extendido hacia abajo hasta 5% (campeonatos con muchos candidatos)
    es_near_res = mercado.get("metodo_analisis") == "NearResolution"
    es_odds     = str(mercado.get("metodo_analisis", "")).startswith("Odds/")
    precio_min  = 0.05 if es_odds else PRECIO_MIN_APOSTAR
    precio_max  = 0.99 if es_near_res else PRECIO_MAX_APOSTAR
    edge_min    = 0.01 if es_near_res else EDGE_MINIMO

    if precio < precio_min or precio > precio_max:
        addlog(f"[Trader] Precio {round(precio*100,1)}% fuera de rango — skip", "info")
        return 0

    edge = prob - precio
    if edge < edge_min:
        addlog(f"[Trader] Edge {round(edge*100,1)}% < mínimo — skip", "info")
        return 0

    if mercado.get("confianza") == "BAJA":
        addlog(f"[Trader] Confianza BAJA — skip", "info")
        return 0

    ops_mismo_tema = contar_ops_por_tema(mercado["pregunta"])
    if ops_mismo_tema >= MAX_OPS_POR_TEMA:
        addlog(f"[Trader] Exposición máxima ({MAX_OPS_POR_TEMA}) para este tema — skip", "info")
        return 0

    fraccion = kelly_fraction(prob, precio)
    if fraccion <= 0:
        return 0

    monto = min(saldo * fraccion, riesgo, saldo * MAX_PCT_SALDO)
    return round(max(monto, 1.0), 2)


def ejecutar_apuesta(mercado):
    """Simula o ejecuta una apuesta usando helpers thread-safe."""
    monto = calcular_monto(mercado)
    if monto <= 0:
        return

    if estado["saldo"] < monto:
        addlog("[Trader] Saldo insuficiente", "error")
        return

    precio             = mercado["precio"]
    prob               = mercado.get("probabilidad_claudio", precio)
    edge               = prob - precio
    ganancia_potencial = round(monto / precio - monto, 2)
    kelly_usado        = kelly_fraction(prob, precio)

    # Descontar saldo de forma atómica
    actualizar_saldo(-monto)

    op = {
        "id":                   mercado["id"],
        "pregunta":             mercado["pregunta"][:60],
        "outcome":              mercado["outcome"],
        "precio":               mercado["precio_pct"],
        "monto":                monto,
        "ganancia_potencial":   ganancia_potencial,
        "estado":               "ABIERTA",
        "fecha":                datetime.now().strftime("%H:%M:%S"),
        "fecha_completa":       datetime.now().isoformat(),
        "confianza":            mercado.get("confianza", "BAJA"),
        "kelly_usado":          kelly_usado,
        "edge":                 round(edge, 4),
        "probabilidad_claudio": prob,
    }

    insertar_operacion(op)

    modo  = estado["modo"]
    op_id = guardar_operacion(mercado["id"], mercado["outcome"], precio, monto, modo)
    op["db_id"] = op_id

    # Ejecución real en Polymarket CLOB
    if modo == "real":
        try:
            from agentes.clob import ejecutar_orden, obtener_token_id
            from agentes.salida import _extraer_polymarket_id
            pm_id = _extraer_polymarket_id(mercado["id"])
            if pm_id:
                resultado = ejecutar_orden(pm_id, mercado["outcome"], precio, monto)
                if not resultado:
                    addlog("[Trader] ⚠️ Orden CLOB falló — posición registrada pero NO ejecutada en cadena", "error")
            else:
                addlog(f"[Trader] ⚠️ No se pudo extraer polymarket_id de {mercado['id']}", "error")
        except Exception as e:
            addlog(f"[Trader] Error en ejecución real: {e}", "error")

    with _mult_lock:
        mult = multiplicador_actual

    addlog(
        f"[Trader] {'SIM' if modo == 'simulacion' else '🔴 REAL'} "
        f"${monto} (x{round(mult,2)}) → {mercado['pregunta'][:30]}... "
        f"({mercado['outcome']}) @ {mercado['precio_pct']}% | "
        f"edge={round(edge*100,1)}% | potencial +${ganancia_potencial}",
        "win"
    )
    addlog("[Trader] Posición abierta — Agente de Salida monitoreando precio real de Polymarket", "info")


def correr():
    global multiplicador_actual, racha_actual
    addlog("[Trader] v3 iniciado — anti-martingale, límite por tema, edge 8%", "info")
    time.sleep(15)

    # Restaurar apostados desde DB para sobrevivir reinicios
    apostados.update(get_mercados_apostados())
    addlog(f"[Trader] {len(apostados)} mercados ya apostados cargados desde DB", "info")

    # Restaurar multiplicador y racha desde DB
    try:
        import sqlite3
        from core.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT contenido FROM memoria WHERE tipo='multiplicador' ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row:
            partes = row[0].split(",")
            with _mult_lock:
                multiplicador_actual = float(partes[0])
                racha_actual = int(partes[1])
            addlog(f"[Trader] Multiplicador restaurado: {multiplicador_actual}x | racha: {racha_actual:+d}", "info")
    except:
        pass

    while estado["corriendo"]:
        try:
            incrementar_ciclo()
            with _mult_lock:
                mult = multiplicador_actual
            addlog(f"[Trader] Multiplicador: {round(mult,2)}x | Riesgo efectivo: ${round(estado['riesgo_por_op'] * mult,2)}", "info")

            # Usar snapshot thread-safe de mercados
            candidatos = [
                m for m in get_mercados()
                if m.get("analizado")
                and m.get("decision_investigador") == "APOSTAR"
                and m.get("confianza") in ["ALTA", "MEDIA"]
                and m["id"] not in apostados
            ]

            if candidatos:
                addlog(f"[Trader] {len(candidatos)} candidatos para apostar")
                for mercado in candidatos[:2]:
                    if not estado["corriendo"]: return
                    ejecutar_apuesta(mercado)
                    apostados.add(mercado["id"])
                    time.sleep(3)

        except Exception as e:
            addlog(f"[Trader] Error: {e}", "error")

        for _ in range(INTERVALO_SEGUNDOS):
            if not estado["corriendo"]: return
            time.sleep(1)
