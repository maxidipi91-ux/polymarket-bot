"""
agentes/debugger.py — Agente Debugger
Revisa los logs cada 10 minutos buscando errores repetidos.
Si detecta algo crítico, avisa por Telegram con diagnóstico.
Verifica Polymarket, Kraken y el cascade LLM (Groq/Cerebras/Mistral).
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


def verificar_llm_cascade():
    """
    Verifica que al menos un proveedor LLM del cascade esté respondiendo.
    Retorna (ok, nombre_proveedor) o (False, None).
    """
    import requests
    try:
        from core.config_loader import cargar_config
        cfg = cargar_config()
    except:
        return False, None

    proveedores = [
        {
            "nombre": "Groq",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": cfg.get("groq_api_key", ""),
            "model": "llama-3.3-70b-versatile",
        },
        {
            "nombre": "Cerebras",
            "url": "https://api.cerebras.ai/v1/chat/completions",
            "key": cfg.get("cerebras_api_key", ""),
            "model": "llama3.3-70b",
        },
        {
            "nombre": "Mistral",
            "url": "https://api.mistral.ai/v1/chat/completions",
            "key": cfg.get("mistral_api_key", ""),
            "model": "mistral-small-latest",
        },
    ]

    for p in proveedores:
        if not p["key"]:
            continue
        try:
            r = requests.post(
                p["url"],
                headers={"Authorization": f"Bearer {p['key']}", "Content-Type": "application/json"},
                json={
                    "model": p["model"],
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
                timeout=8,
            )
            if r.status_code == 200:
                return True, p["nombre"]
        except:
            continue

    return False, None


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
    llm_ok_anterior        = True

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

            # 4. LLM cascade (Groq/Cerebras/Mistral)
            llm_ok, llm_proveedor = verificar_llm_cascade()
            if not llm_ok and llm_ok_anterior:
                problemas.append("LLM cascade caído — ningún proveedor responde (Groq/Cerebras/Mistral)")
            elif llm_ok and not llm_ok_anterior:
                enviar_alerta(f"LLM cascade OK nuevamente — activo: {llm_proveedor}")
            llm_ok_anterior = llm_ok

            # 5. Sin mercados tras arranque
            if len(estado.get("mercados", [])) == 0:
                problemas.append("Sin mercados detectados — revisar agentes Odds/Arbitraje")

            if problemas:
                msg = "\n".join(problemas)
                addlog(f"[Debugger] {len(problemas)} problema(s): {problemas[0]}", "error")
                enviar_alerta(msg)
            else:
                llm_txt = llm_proveedor if llm_ok else "DOWN"
                addlog(f"[Debugger] Todo OK — Polymarket: OK | Kraken: OK | LLM: {llm_txt}")

        except Exception as e:
            addlog(f"[Debugger] Error interno: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
