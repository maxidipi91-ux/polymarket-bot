"""
Claudio — Orquestador principal de agentes
Arranca todos los agentes y los mantiene vivos.
"""

import time
import threading
import importlib
from datetime import datetime
from core.estado import estado, addlog
from core.database import init_db
from config_loader import CONFIG

AGENTES_ACTIVOS = [
    # Señales (sin LLM, sin noticias)
    "agentes.odds",            # Bookmakers vs Polymarket en deportes (24h)
    "agentes.binance",         # BTC/ETH fair value vs Polymarket (15s)
    "agentes.arbitraje",       # Nichos stale e inconsistencias lógicas (60s)
    "agentes.near_resolution", # Mercados 95%+ cerca de resolución (5min)
    # Ejecución
    "agentes.trader",
    "agentes.salida",
    # Infraestructura
    "agentes.telegram_bot",
    "agentes.debugger",
    # DESACTIVADOS — estrategia basada en noticias/LLM (sin edge verificado):
    # "agentes.monitor",       # Reemplazado por Binance
    # "agentes.investigador",  # Depende de Ollama/Mistral
    # "agentes.autodream",     # Depende de Ollama
    # "agentes.clima",
    # "agentes.whale",
]

hilos = {}


def cargar_agente(modulo_path):
    """Carga un agente dinámicamente y lo corre en su propio hilo."""
    try:
        modulo = importlib.import_module(modulo_path)
        nombre = modulo_path.split(".")[-1]
        t = threading.Thread(target=modulo.correr, daemon=True, name=nombre)
        t.start()
        hilos[nombre] = t
        addlog(f"Agente '{nombre}' iniciado", "win")
    except Exception as e:
        addlog(f"Error cargando agente '{modulo_path}': {e}", "error")


def watchdog():
    """Revisa cada 60s que todos los agentes estén vivos. Si no, los relanza."""
    while estado["corriendo"]:
        for modulo_path in AGENTES_ACTIVOS:
            nombre = modulo_path.split(".")[-1]
            hilo = hilos.get(nombre)
            if hilo and not hilo.is_alive():
                addlog(f"Agente '{nombre}' caído — relanzando...", "error")
                cargar_agente(modulo_path)
        time.sleep(60)


def iniciar():
    init_db()

    # Aplicar configuración desde .env al estado global
    estado["riesgo_por_op"] = CONFIG["riesgo_por_op"]
    estado["modo"]          = CONFIG["modo"]
    estado["corriendo"]     = True

    # Restaurar saldo y PnL desde DB (sobrevive reinicios)
    from core.database import calcular_estado_financiero, get_operaciones_db
    saldo_actual, pnl_actual = calcular_estado_financiero(CONFIG["saldo_inicial"])
    estado["saldo"] = saldo_actual
    estado["pnl"]   = pnl_actual

    # Cargar operaciones históricas en memoria
    from core.estado import _lock
    ops_db = get_operaciones_db()
    with _lock:
        estado["operaciones"] = ops_db

    addlog(f"Claudio iniciando — {datetime.now().strftime('%Y-%m-%d %H:%M')}", "win")
    addlog(f"Modo: {estado['modo']} | Saldo: ${estado['saldo']} | Riesgo: ${estado['riesgo_por_op']}", "info")

    for agente in AGENTES_ACTIVOS:
        cargar_agente(agente)

    t_watchdog = threading.Thread(target=watchdog, daemon=True, name="watchdog")
    t_watchdog.start()

    addlog("Todos los agentes activos. Claudio operativo.", "win")


def detener():
    estado["corriendo"] = False
    addlog("Claudio detenido por el usuario.")


if __name__ == "__main__":
    iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        detener()
