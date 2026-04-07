"""
agentes/debugger.py — Agente Debugger
Revisa los logs cada 10 minutos buscando errores repetidos.
Si detecta algo crítico, avisa por Telegram con diagnóstico.
También verifica que Ollama y la VPN estén funcionando.
"""

import time
from collections import Counter
from datetime import datetime, timedelta
from core.estado import estado, addlog

INTERVALO = 600  # Cada 10 minutos
UMBRAL_ERROR = 3  # Si el mismo error aparece 3+ veces → alerta


def analizar_logs():
    """Busca patrones de error en los logs recientes."""
    logs = estado.get("log", [])
    if not logs:
        return []

    # Filtrar solo errores de los últimos 10 minutos
    errores = [l for l in logs if l.get("tipo") == "error"]

    if not errores:
        return []

    # Contar errores repetidos
    mensajes = [e["msg"][:60] for e in errores]
    contador = Counter(mensajes)

    alertas = []
    for msg, count in contador.most_common():
        if count >= UMBRAL_ERROR:
            alertas.append({"msg": msg, "count": count})

    return alertas


def verificar_ollama():
    """Verifica que Ollama esté respondiendo."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except:
        return False


def verificar_polymarket():
    """Verifica que Polymarket sea accesible (VPN activa)."""
    try:
        import requests
        r = requests.get("https://gamma-api.polymarket.com/markets?limit=1", timeout=8)
        return r.status_code == 200
    except:
        return False


def enviar_alerta(msg):
    """Manda alerta por Telegram."""
    try:
        from agentes.telegram_bot import enviar_mensaje
        enviar_mensaje(f"🔧 <b>Debugger</b>\n{msg}")
    except:
        pass


def correr():
    addlog("[Debugger] Iniciado — monitoreando errores cada 10 min", "info")
    time.sleep(120)  # Esperar que el sistema esté estable

    ollama_ok_anterior    = True
    polymarket_ok_anterior = True

    while estado["corriendo"]:
        try:
            problemas = []

            # 1. Errores repetidos en logs
            alertas = analizar_logs()
            for alerta in alertas:
                problemas.append(f"⚠️ Error repetido x{alerta['count']}: {alerta['msg']}")

            # 2. Ollama
            ollama_ok = verificar_ollama()
            if not ollama_ok and ollama_ok_anterior:
                problemas.append("❌ Ollama no responde — análisis degradado a modo básico")
            elif ollama_ok and not ollama_ok_anterior:
                problemas.append("✅ Ollama recuperado")
            ollama_ok_anterior = ollama_ok
            estado["ollama_disponible"] = ollama_ok

            # 3. Polymarket / VPN
            polymarket_ok = verificar_polymarket()
            if not polymarket_ok and polymarket_ok_anterior:
                problemas.append("❌ Polymarket inaccesible — verificar VPN")
            elif polymarket_ok and not polymarket_ok_anterior:
                problemas.append("✅ Polymarket accesible nuevamente")
            polymarket_ok_anterior = polymarket_ok

            # 4. Agentes caídos
            ciclo_actual = estado.get("ciclo_num", 0)
            if ciclo_actual > 5 and len(estado.get("mercados", [])) == 0:
                problemas.append("⚠️ Monitor sin mercados después de 5+ ciclos")

            if problemas:
                msg = "\n".join(problemas)
                addlog(f"[Debugger] {len(problemas)} problema(s) detectado(s)", "error")
                enviar_alerta(msg)
            else:
                addlog(f"[Debugger] Todo OK — Ollama: {'✅' if ollama_ok else '❌'} | Polymarket: {'✅' if polymarket_ok else '❌'}")

        except Exception as e:
            addlog(f"[Debugger] Error interno: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
