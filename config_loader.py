"""
config_loader.py — Carga de configuración segura.

Orden de prioridad:
  1. Variables de entorno (producción / VPS)
  2. Archivo .env (desarrollo local)
  3. config.json (legacy — solo como último recurso)

NUNCA pongas credenciales reales en config.json ni lo subas a git.
Usá .env (está en .gitignore).
"""

import os
import json


def _cargar_env_file(path=".env"):
    """Lee un archivo .env y carga las variables en os.environ (sin pisar las ya definidas)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            if clave and clave not in os.environ:
                os.environ[clave] = valor


def _cargar_config_json(path="config.json"):
    """Carga config.json como fallback legacy."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def cargar():
    """
    Devuelve el diccionario de configuración completo.
    Llamar una sola vez al inicio del proceso.
    """
    _cargar_env_file()
    legacy = _cargar_config_json()

    def get(env_key, json_key, default=""):
        return os.environ.get(env_key) or legacy.get(json_key, default)

    return {
        "telegram_token":       get("TELEGRAM_TOKEN",       "telegram_token",       ""),
        "telegram_chat_id":     get("TELEGRAM_CHAT_ID",     "telegram_chat_id",     ""),
        "news_api_key":         get("NEWS_API_KEY",         "news_api_key",         ""),
        "football_data_token":  get("FOOTBALL_DATA_TOKEN",  "football_data_token",  ""),
        "odds_api_key":         get("ODDS_API_KEY",         "odds_api_key",         ""),
        "groq_api_key":         get("GROQ_API_KEY",         "groq_api_key",         ""),
        "kalshi_api_key":       get("KALSHI_API_KEY",       "kalshi_api_key",       ""),
        "ollama_url":           get("OLLAMA_URL",           "ollama_url",           "http://localhost:11434"),
        "ollama_model":         get("OLLAMA_MODEL",         "ollama_model",         "mistral"),
        "riesgo_por_op":        float(get("RIESGO_POR_OP", "riesgo_por_op",        10.0)),
        "saldo_inicial":        float(get("SALDO_INICIAL",  "saldo_inicial",        1000.0)),
        "modo":                 get("MODO",                 "modo",                 "simulacion"),
    }


# Instancia global — se inicializa una vez al importar
CONFIG = cargar()
