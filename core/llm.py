"""
core/llm.py — Cliente LLM via Groq (Qwen)
Analiza mercados usando noticias recientes para decidir si apostar.
Fallback silencioso si Groq no está disponible.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from core.estado import addlog

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3-32b"


def _get_groq_key():
    try:
        from config_loader import CONFIG
        return CONFIG.get("groq_api_key", "")
    except:
        return ""


def buscar_noticias(pregunta, max_noticias=5):
    """
    Busca noticias recientes via Google News RSS.
    Retorna lista de titulares relevantes.
    """
    try:
        keywords = " ".join(pregunta.split()[:6])
        query    = urllib.parse.quote(keywords)
        url      = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            contenido = resp.read().decode("utf-8")

        # Extraer títulos del RSS sin dependencias externas
        titulos = []
        import re
        items = re.findall(r"<item>(.*?)</item>", contenido, re.DOTALL)
        for item in items[:max_noticias]:
            titulo = re.search(r"<title>(.*?)</title>", item)
            if titulo:
                t = titulo.group(1)
                t = re.sub(r"<[^>]+>", "", t)  # strip HTML
                t = t.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                titulos.append(t.strip())

        return titulos
    except Exception as e:
        addlog(f"[LLM] Error buscando noticias: {e}", "error")
        return []


def evaluar_mercado(pregunta, precio, noticias):
    """
    Llama a Qwen via Groq para evaluar si vale apostar.
    Retorna dict: {"decision": "APOSTAR"|"SKIP"|"ESPERAR", "razon": str}
    o None si Groq no está disponible.
    """
    api_key = _get_groq_key()
    if not api_key:
        return None

    noticias_txt = "\n".join(f"- {n}" for n in noticias) if noticias else "Sin noticias recientes encontradas."

    prompt = f"""Eres un analista de mercados de predicción. Evalúa si vale la pena apostar en este mercado.

MERCADO: {pregunta}
PRECIO ACTUAL: {round(precio * 100, 1)}% (mercado dice que hay {round(precio * 100, 1)}% de chance de YES)

NOTICIAS RECIENTES:
{noticias_txt}

Responde SOLO con un JSON válido con este formato exacto:
{{"decision": "APOSTAR", "razon": "explicacion breve"}}

Las opciones para decision son:
- APOSTAR: el precio parece incorrecto dado las noticias, hay edge real
- SKIP: el precio parece correcto o las noticias confirman que no hay edge
- ESPERAR: no hay información suficiente para decidir

Sé conciso. Solo el JSON, nada más."""

    try:
        body = json.dumps({
            "model":       GROQ_MODEL,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens":  200,
        }).encode("utf-8")

        req = urllib.request.Request(
            GROQ_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
                "User-Agent":    "Mozilla/5.0",
            }
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data     = json.loads(resp.read().decode("utf-8"))
            contenido = data["choices"][0]["message"]["content"].strip()

        # Extraer JSON de la respuesta (Qwen a veces agrega texto extra)
        import re
        match = re.search(r'\{.*?\}', contenido, re.DOTALL)
        if match:
            resultado = json.loads(match.group())
            decision  = resultado.get("decision", "ESPERAR").upper()
            if decision not in ("APOSTAR", "SKIP", "ESPERAR"):
                decision = "ESPERAR"
            return {"decision": decision, "razon": resultado.get("razon", "")}

    except Exception as e:
        addlog(f"[LLM] Error llamando Groq: {e}", "error")

    return None


def analizar_nicho(pregunta, precio):
    """
    Función principal: busca noticias + evalúa con Qwen.
    Retorna (decision, razon, noticias).
    decision puede ser "APOSTAR", "SKIP", "ESPERAR", o "FALLBACK" si Groq no responde.
    """
    noticias = buscar_noticias(pregunta)
    resultado = evaluar_mercado(pregunta, precio, noticias)

    if resultado is None:
        return "FALLBACK", "Groq no disponible — usando lógica base", noticias

    return resultado["decision"], resultado["razon"], noticias
