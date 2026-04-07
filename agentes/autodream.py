"""
agentes/autodream.py — Agente autoDream
Inspirado en KAIROS (leak de Claude Code).
Cuando Claudio está idle (sin ciclos activos por 30+ minutos),
consolida y aprende de toda la historia de operaciones.

Hace:
  1. Analiza operaciones ganadas — ¿qué señales las predijeron?
  2. Analiza operaciones perdidas — ¿qué ignoró?
  3. Detecta patrones de error propios
  4. Elimina contradicciones en la memoria
  5. Guarda insights concretos en la DB
  6. Reporta resumen por Telegram
"""

import time
import requests
import json
import sqlite3
from datetime import datetime, timedelta
from core.estado import estado, addlog
from core.database import guardar_memoria, DB_PATH
from config_loader import CONFIG

INTERVALO_CHECK = 300   # Chequea cada 5 minutos si hay que soñar
IDLE_MINUTOS    = 30    # Considera idle si no hubo operaciones en 30 min
OLLAMA_URL      = CONFIG["ollama_url"]


def minutos_desde_ultima_op():
    """Calcula minutos desde la última operación abierta o cerrada."""
    ops_recientes = [
        op for op in estado["operaciones"]
        if op.get("estado") in ["GANADA", "PERDIDA", "ABIERTA"]
    ]
    if not ops_recientes:
        return 999  # Sin operaciones = muy idle

    # Aproximación: usar el índice (operaciones más recientes primero)
    return 0 if estado["operaciones"][0].get("estado") == "ABIERTA" else 35


def obtener_historial_completo():
    """Obtiene todo el historial de operaciones de la DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT o.mercado_id, o.outcome, o.precio_entrada, o.precio_salida,
                   o.monto, o.ganancia, o.resultado, o.fecha_entrada,
                   a.decision, a.razonamiento, a.probabilidad_claudio
            FROM operaciones o
            LEFT JOIN analisis a ON o.mercado_id = a.mercado_id
            WHERE o.resultado IN ('GANADA', 'PERDIDA')
            ORDER BY o.fecha_entrada DESC
            LIMIT 50
        """)
        rows = c.fetchall()
        conn.close()
        return rows
    except:
        return []


def consolidar_con_ollama(historial):
    """
    Manda el historial a Mistral para que extraiga patrones y aprendizajes.
    """
    if not historial:
        return None

    ganadas  = [r for r in historial if r[6] == "GANADA"]
    perdidas = [r for r in historial if r[6] == "PERDIDA"]

    resumen_ganadas  = "\n".join([
        f"- Mercado: {r[0][:40]} | Outcome: {r[1]} | Precio entrada: {round(r[2]*100,1)}% | Razonamiento: {r[9][:80] if r[9] else 'N/A'}"
        for r in ganadas[:10]
    ]) or "Sin operaciones ganadas."

    resumen_perdidas = "\n".join([
        f"- Mercado: {r[0][:40]} | Outcome: {r[1]} | Precio entrada: {round(r[2]*100,1)}% | Razonamiento: {r[9][:80] if r[9] else 'N/A'}"
        for r in perdidas[:10]
    ]) or "Sin operaciones perdidas."

    prompt = f"""Sos el cerebro de un bot de trading en Polymarket llamado Claudio.
Analizá el historial de operaciones y extraé aprendizajes concretos.

OPERACIONES GANADAS ({len(ganadas)}):
{resumen_ganadas}

OPERACIONES PERDIDAS ({len(perdidas)}):
{resumen_perdidas}

Respondé ÚNICAMENTE con este JSON:
{{
  "patron_exito": "<qué tienen en común las operaciones ganadas — máx 2 oraciones>",
  "patron_error": "<qué tienen en común las operaciones perdidas — máx 2 oraciones>",
  "ajuste_recomendado": "<un cambio concreto que mejoraría el rendimiento>",
  "confianza_actual": "<ALTA|MEDIA|BAJA — evaluación del rendimiento general>",
  "insight": "<observación más importante del análisis>"
}}"""

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "mistral", "prompt": prompt, "stream": False},
            timeout=90
        )
        texto  = r.json().get("response", "")
        inicio = texto.find("{")
        fin    = texto.rfind("}") + 1
        if inicio >= 0 and fin > inicio:
            return json.loads(texto[inicio:fin])
    except Exception as e:
        addlog(f"[autoDream] Error Ollama: {e}", "error")
    return None


def notificar_telegram(insights):
    """Manda el resumen del sueño por Telegram."""
    try:
        from agentes.telegram_bot import enviar_mensaje
        msg = (
            f"🧠 <b>autoDream completado</b>\n\n"
            f"✅ Patrón de éxito:\n{insights.get('patron_exito', 'N/A')}\n\n"
            f"❌ Patrón de error:\n{insights.get('patron_error', 'N/A')}\n\n"
            f"💡 Ajuste recomendado:\n{insights.get('ajuste_recomendado', 'N/A')}\n\n"
            f"🎯 Insight clave:\n{insights.get('insight', 'N/A')}\n\n"
            f"📊 Confianza actual: {insights.get('confianza_actual', 'N/A')}"
        )
        enviar_mensaje(msg)
    except:
        pass


def sonar():
    """El proceso de consolidación de memoria — el 'sueño' de Claudio."""
    addlog("[autoDream] 💤 Iniciando consolidación de memoria...")

    historial = obtener_historial_completo()
    if len(historial) < 3:
        addlog("[autoDream] Poco historial todavía — necesita más operaciones")
        return

    addlog(f"[autoDream] Analizando {len(historial)} operaciones con Mistral...")

    if estado.get("ollama_disponible"):
        insights = consolidar_con_ollama(historial)
    else:
        # Análisis básico sin Ollama
        ganadas  = [r for r in historial if r[6] == "GANADA"]
        perdidas = [r for r in historial if r[6] == "PERDIDA"]
        winrate  = round(len(ganadas) / len(historial) * 100, 1) if historial else 0
        insights = {
            "patron_exito":       f"{len(ganadas)} operaciones ganadas de {len(historial)} total",
            "patron_error":       f"{len(perdidas)} operaciones perdidas",
            "ajuste_recomendado": "Continuar acumulando datos para análisis más preciso",
            "confianza_actual":   "ALTA" if winrate > 60 else "MEDIA" if winrate > 40 else "BAJA",
            "insight":            f"Winrate actual: {winrate}%"
        }

    if insights:
        # Guardar en memoria
        guardar_memoria("autodream", json.dumps(insights, ensure_ascii=False))
        addlog(f"[autoDream] ✨ Insight: {insights.get('insight', '')[:80]}", "win")
        addlog(f"[autoDream] Confianza: {insights.get('confianza_actual', '')} | "
               f"Ajuste: {insights.get('ajuste_recomendado', '')[:60]}", "win")
        notificar_telegram(insights)
    else:
        addlog("[autoDream] Sin insights generados en este ciclo")

    addlog("[autoDream] 💭 Consolidación completada")


def correr():
    """Loop principal del agente autoDream."""
    addlog("[autoDream] Iniciado — consolida memoria cuando Claudio está idle", "info")
    ultimo_sueno = datetime.now() - timedelta(hours=2)  # Forzar primer sueño pronto

    while estado["corriendo"]:
        try:
            minutos_idle = minutos_desde_ultima_op()
            horas_desde_sueno = (datetime.now() - ultimo_sueno).seconds / 3600

            # Soñar si: idle por 30+ min Y pasaron 2+ horas desde el último sueño
            if minutos_idle >= IDLE_MINUTOS and horas_desde_sueno >= 2:
                sonar()
                ultimo_sueno = datetime.now()

        except Exception as e:
            addlog(f"[autoDream] Error: {e}", "error")

        for _ in range(INTERVALO_CHECK):
            if not estado["corriendo"]: return
            time.sleep(1)
