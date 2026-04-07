"""
core/llm.py — Cliente LLM con cascada de proveedores y cache

Cascada (en orden):
  1. Groq       — llama-3.3-70b  (primario, rápido)
  2. Cerebras   — llama-3.3-70b  (fallback #1, 1M tokens/día gratis)
  3. Mistral    — mistral-small   (fallback #2, 1B tokens/mes gratis)

Cache:
  - 6 horas por pregunta de mercado
  - Evita re-analizar el mismo nicho cada 60 segundos
  - Reduce llamadas de ~1,440/día a ~20/día

Noticias:
  - NewsData.io como fuente primaria (2,000 artículos/día gratis)
  - Google News RSS como fallback (gratis, sin límite)
"""

import json
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import re
from core.estado import addlog

# ─── Proveedores LLM ──────────────────────────────────────────────────────────

PROVEEDORES = [
    {
        "nombre":  "Groq",
        "url":     "https://api.groq.com/openai/v1/chat/completions",
        "modelo":  "llama-3.3-70b-versatile",
        "key_cfg": "groq_api_key",
    },
    {
        "nombre":  "Cerebras",
        "url":     "https://api.cerebras.ai/v1/chat/completions",
        "modelo":  "llama3.3-70b",
        "key_cfg": "cerebras_api_key",
    },
    {
        "nombre":  "Mistral",
        "url":     "https://api.mistral.ai/v1/chat/completions",
        "modelo":  "mistral-small-latest",
        "key_cfg": "mistral_api_key",
    },
]

# ─── Cache ────────────────────────────────────────────────────────────────────

_cache: dict = {}          # {hash: {"ts": float, "result": dict}}
CACHE_TTL    = 6 * 3600    # 6 horas


def _cache_key(pregunta: str) -> str:
    return hashlib.md5(pregunta.lower().strip().encode()).hexdigest()


def _get_cache(pregunta: str):
    k = _cache_key(pregunta)
    entry = _cache.get(k)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["result"]
    return None


def _set_cache(pregunta: str, result: dict):
    _cache[_cache_key(pregunta)] = {"ts": time.time(), "result": result}


# ─── Llamada genérica a cualquier proveedor OpenAI-compatible ─────────────────

def _llamar_proveedor(proveedor: dict, prompt: str) -> str | None:
    """
    Hace la llamada HTTP al proveedor.
    Retorna el texto de la respuesta, o None si falla.
    """
    from config_loader import CONFIG
    api_key = CONFIG.get(proveedor["key_cfg"], "")
    if not api_key:
        return None

    body = json.dumps({
        "model":       proveedor["modelo"],
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens":  200,
    }).encode("utf-8")

    req = urllib.request.Request(
        proveedor["url"],
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "User-Agent":    "Mozilla/5.0",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            addlog(f"[LLM] {proveedor['nombre']} rate limit (429) — probando siguiente proveedor", "info")
        else:
            addlog(f"[LLM] {proveedor['nombre']} error {e.code}", "error")
        return None
    except Exception as e:
        addlog(f"[LLM] {proveedor['nombre']} excepción: {e}", "error")
        return None


def _parsear_decision(contenido: str) -> dict | None:
    """Extrae el JSON de decision/razon del texto del LLM."""
    # Limpiar tags <think> de modelos que los usan (Qwen, etc.)
    contenido = re.sub(r"<think>.*?</think>", "", contenido, flags=re.DOTALL).strip()

    matches = re.findall(r"\{[^{}]*\}", contenido)
    for raw in reversed(matches):
        try:
            resultado = json.loads(raw)
            if "decision" in resultado:
                decision = resultado["decision"].upper()
                if decision not in ("APOSTAR", "SKIP", "ESPERAR"):
                    decision = "ESPERAR"
                return {"decision": decision, "razon": resultado.get("razon", "")}
        except Exception:
            continue
    return None


# ─── Evaluación principal con cascada ────────────────────────────────────────

def evaluar_mercado(pregunta: str, precio: float, noticias: list) -> dict | None:
    """
    Evalúa si vale la pena apostar usando la cascada de LLMs.
    Retorna {"decision": "APOSTAR"|"SKIP"|"ESPERAR", "razon": str}
    o None si todos los proveedores fallan.
    """
    # Cache hit
    cached = _get_cache(pregunta)
    if cached:
        addlog(f"[LLM] Cache hit: {pregunta[:40]}... → {cached['decision']}", "info")
        return cached

    noticias_txt = (
        "\n".join(f"- {n}" for n in noticias)
        if noticias else "Sin noticias recientes."
    )

    prompt = f"""Eres un analista de mercados de predicción. Evalúa si vale la pena apostar.

MERCADO: {pregunta}
PRECIO ACTUAL: {round(precio * 100, 1)}% (probabilidad implícita de YES)

NOTICIAS RECIENTES:
{noticias_txt}

Responde SOLO con JSON válido:
{{"decision": "APOSTAR", "razon": "explicacion breve"}}

Opciones para decision:
- APOSTAR: precio incorrecto dado las noticias, hay edge real
- SKIP: precio correcto o noticias confirman que no hay edge
- ESPERAR: información insuficiente

Solo el JSON, nada más."""

    for proveedor in PROVEEDORES:
        contenido = _llamar_proveedor(proveedor, prompt)
        if contenido is None:
            continue

        resultado = _parsear_decision(contenido)
        if resultado:
            addlog(
                f"[LLM] {proveedor['nombre']} → {resultado['decision']} "
                f"({pregunta[:35]}...)",
                "info"
            )
            _set_cache(pregunta, resultado)
            return resultado

        addlog(f"[LLM] {proveedor['nombre']} respuesta inválida — probando siguiente", "info")

    addlog("[LLM] Todos los proveedores fallaron", "error")
    return None


# ─── Noticias ─────────────────────────────────────────────────────────────────

def _buscar_newsdata(pregunta: str, max_noticias: int = 5) -> list:
    """Busca noticias via NewsData.io (primario). 200 créditos/día gratis."""
    from config_loader import CONFIG
    api_key = CONFIG.get("newsdata_api_key", "")
    if not api_key:
        return []

    try:
        keywords = " ".join(pregunta.split()[:6])
        params   = urllib.parse.urlencode({
            "apikey":   api_key,
            "q":        keywords,
            "language": "en",
            "size":     max_noticias,
        })
        url = f"https://newsdata.io/api/1/news?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        with urllib.request.urlopen(req, timeout=8) as resp:
            data     = json.loads(resp.read().decode("utf-8"))
            articulos = data.get("results", [])
            return [a.get("title", "") for a in articulos if a.get("title")]

    except Exception as e:
        addlog(f"[LLM] NewsData.io error: {e}", "error")
        return []


def _buscar_google_rss(pregunta: str, max_noticias: int = 5) -> list:
    """Busca noticias via Google News RSS (fallback, gratis y sin límite)."""
    try:
        keywords = " ".join(pregunta.split()[:6])
        query    = urllib.parse.quote(keywords)
        url      = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            contenido = resp.read().decode("utf-8")

        titulos = []
        items   = re.findall(r"<item>(.*?)</item>", contenido, re.DOTALL)
        for item in items[:max_noticias]:
            titulo = re.search(r"<title>(.*?)</title>", item)
            if titulo:
                t = titulo.group(1)
                t = re.sub(r"<[^>]+>", "", t)
                t = t.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                titulos.append(t.strip())

        return titulos

    except Exception as e:
        addlog(f"[LLM] Google RSS error: {e}", "error")
        return []


def buscar_noticias(pregunta: str, max_noticias: int = 5) -> list:
    """
    Busca noticias con fallback automático:
    1. NewsData.io (si hay API key configurada)
    2. Google News RSS (siempre disponible)
    """
    noticias = _buscar_newsdata(pregunta, max_noticias)
    if noticias:
        return noticias
    return _buscar_google_rss(pregunta, max_noticias)


# ─── Función principal ────────────────────────────────────────────────────────

def analizar_nicho(pregunta: str, precio: float) -> tuple:
    """
    Busca noticias y evalúa con la cascada de LLMs.
    Retorna (decision, razon, noticias).
    decision: "APOSTAR" | "SKIP" | "ESPERAR" | "FALLBACK"
    FALLBACK solo si todos los LLMs fallan Y no hay cache.
    """
    noticias  = buscar_noticias(pregunta)
    resultado = evaluar_mercado(pregunta, precio, noticias)

    if resultado is None:
        return "FALLBACK", "Todos los LLMs no disponibles", noticias

    return resultado["decision"], resultado["razon"], noticias
