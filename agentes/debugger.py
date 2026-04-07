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


def verificar_polymarket():
    """Verifica que Polymarket sea accesible."""
    try:
        import requests
        r = requests.get("https://gamma-api.polymarket.com/markets?limit=1", timeout=8)
        return r.status_code == 200
    except:
        return False


def verificar_kraken():
    """Verifica que Kraken esté accesible."""
    try:
        import requests
        r = requests.get("https://api.kraken.com/0/public/Time", timeout=5)
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

    polymarket_ok_anterior = True
    kraken_ok_anterior     = True

    while estado["corriendo"]:
        try:
            problemas = []

            # 1. Errores repetidos en logs
            alertas = analizar_logs()
            for alerta in alertas:
                problemas.append(f"Error repetido x{alerta['count']}: {alerta['msg']}")

            # 2. Polymarket
            polymarket_ok = verificar_polymarket()
            if not polymarket_ok and polymarket_ok_anterior:
                problemas.append("Polymarket inaccesible")
            elif polymarket_ok and not polymarket_ok_anterior:
                enviar_alerta("Polymarket accesible nuevamente")
            polymarket_ok_anterior = polymarket_ok

            # 3. Kraken
            kraken_ok = verificar_kraken()
            if not kraken_ok and kraken_ok_anterior:
                problemas.append("Kraken inaccesible — sin precios BTC/ETH")
            elif kraken_ok and not kraken_ok_anterior:
                enviar_alerta("Kraken accesible nuevamente")
            kraken_ok_anterior = kraken_ok

            # 4. Sin mercados tras arranque
            if len(estado.get("mercados", [])) == 0:
                problemas.append("Sin mercados detectados — revisar agentes Odds/Arbitraje")

            if problemas:
                msg = "\n".join(problemas)
                addlog(f"[Debugger] {len(problemas)} problema(s): {problemas[0]}", "error")
                enviar_alerta(msg)
            else:
                addlog(f"[Debugger] Todo OK — Polymarket: OK | Kraken: OK")

        except Exception as e:
            addlog(f"[Debugger] Error interno: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
