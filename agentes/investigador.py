"""
agentes/investigador.py — Agente Investigador v2
Mejoras v2:
  - Prompt de Mistral reescrito: realista, calibrado, no agresivo
  - Caché de 2 horas: no re-analiza mercados recientes
  - GDELT profundo como fuente principal de noticias
  - Progressive context loading: solo analiza mercados que pasaron Nivel 1
  - Prioriza mercados urgentes (triggers del Monitor)
"""

import time
import requests
import json
from datetime import datetime, timedelta
from core.estado import estado, addlog, get_mercados
from core.database import guardar_mercado, guardar_analisis, guardar_memoria
from config_loader import CONFIG

NEWS_API_KEY     = CONFIG["news_api_key"]
OLLAMA_URL       = CONFIG["ollama_url"]
GDELT_URL        = "https://api.gdeltproject.org/api/v2/doc/doc"
FOOTBALL_API_URL = "https://api.football-data.org/v4"
INTERVALO_SEG    = 60
CACHE_HORAS      = 2
MAX_POR_CICLO    = 5

FOOTBALL_TOKEN = CONFIG["football_data_token"]

# Keywords por tipo de mercado
KEYWORDS_FUTBOL   = ["win", "champion", "relegated", "qualify", "finish", "league",
                     "premier", "laliga", "bundesliga", "serie a", "ligue 1", "champions",
                     "europa", "cup", "soccer", "football", "fc ", " fc", "united", "city"]
KEYWORDS_TENIS    = ["wimbledon", "us open", "french open", "australian open", "atp", "wta",
                     "grand slam", "tennis", "masters"]
KEYWORDS_GOLF     = ["masters", "pga", "open championship", "us open golf", "ryder cup",
                     "golf", "scheffler", "mcilroy"]
KEYWORDS_POLITICA = ["president", "election", "senator", "governor", "primary", "vote",
                     "congress", "parliament", "minister", "mayor"]
KEYWORDS_JUDICIAL = ["sentence", "verdict", "trial", "convicted", "acquitted", "prison",
                     "court", "judge", "guilty", "charges", "weinstein", "case"]
KEYWORDS_CRIPTO   = ["bitcoin", "btc", "ethereum", "eth", "crypto", "price above", "price below"]


def detectar_tipo_mercado(pregunta):
    """Detecta el tipo de mercado para buscar datos específicos."""
    p = pregunta.lower()
    if any(k in p for k in KEYWORDS_FUTBOL):   return "futbol"
    if any(k in p for k in KEYWORDS_GOLF):      return "golf"
    if any(k in p for k in KEYWORDS_TENIS):     return "tenis"
    if any(k in p for k in KEYWORDS_POLITICA):  return "politica"
    if any(k in p for k in KEYWORDS_JUDICIAL):  return "judicial"
    if any(k in p for k in KEYWORDS_CRIPTO):    return "cripto"
    return "general"


def verificar_ollama():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            modelos = [m["name"] for m in r.json().get("models", [])]
            tiene   = any("mistral" in m for m in modelos)
            estado["ollama_disponible"] = tiene
            if tiene:
                addlog("[Investigador] Ollama + Mistral ✓", "win")
            else:
                addlog(f"[Investigador] Ollama sin Mistral. Modelos: {modelos}", "error")
            return tiene
    except:
        estado["ollama_disponible"] = False
        addlog("[Investigador] Ollama no disponible — análisis básico", "info")
    return False


# ─── Caché ───────────────────────────────────────────────────────────────────

def necesita_reanalisis(mercado):
    """True si el mercado nunca fue analizado o fue hace más de CACHE_HORAS."""
    ultima = mercado.get("ultima_vez_analizado")
    if not ultima:
        return True
    hace = datetime.now() - ultima
    return hace > timedelta(hours=CACHE_HORAS)


# ─── Fuentes de noticias ─────────────────────────────────────────────────────

def buscar_gdelt_profundo(query, max_resultados=5):
    """GDELT completo con más resultados para análisis profundo."""
    try:
        params = {
            "query":      str(query)[:80],
            "mode":       "artlist",
            "maxrecords": max_resultados,
            "format":     "json",
            "timespan":   "48h",
            "sort":       "datedesc"
        }
        r = requests.get(GDELT_URL, params=params, timeout=8)
        data = r.json()
        if not isinstance(data, dict):
            return []
        articulos = data.get("articles", [])
        if not isinstance(articulos, list):
            return []
        resultado = []
        for a in articulos:
            if not isinstance(a, dict):
                continue
            resultado.append({
                "titulo":      str(a.get("title", "") or ""),
                "fuente":      str(a.get("domain", "") or ""),
                "descripcion": str(a.get("title", "") or ""),
                "fecha":       str(a.get("seendate", "") or "")
            })
        return resultado
    except:
        return []


def buscar_newsapi(query, max_resultados=3):
    """NewsAPI como fuente complementaria (solo inglés)."""
    try:
        params = {
            "q":        str(query)[:60],
            "apiKey":   NEWS_API_KEY,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": max_resultados
        }
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        data = r.json()
        if not isinstance(data, dict) or data.get("status") != "ok":
            return []
        articulos = data.get("articles", [])
        if not isinstance(articulos, list):
            return []
        resultado = []
        for a in articulos:
            if not isinstance(a, dict):
                continue
            fuente = a.get("source", {})
            resultado.append({
                "titulo":      str(a.get("title", "") or ""),
                "fuente":      str(fuente.get("name", "") if isinstance(fuente, dict) else ""),
                "descripcion": str(a.get("description", "") or "")
            })
        return resultado
    except:
        return []


def obtener_noticias(pregunta):
    """Combina Google News + GDELT + NewsAPI. Garantiza lista de dicts."""
    try:
        google = buscar_google_news(pregunta)
        gdelt  = buscar_gdelt_profundo(pregunta)
        newsapi = buscar_newsapi(pregunta)

        if not isinstance(google,  list): google  = []
        if not isinstance(gdelt,   list): gdelt   = []
        if not isinstance(newsapi, list): newsapi = []

        def es_valida(n):
            return isinstance(n, dict) and isinstance(n.get("titulo"), str) and n.get("titulo")

        google  = [n for n in google  if es_valida(n)]
        gdelt   = [n for n in gdelt   if es_valida(n)]
        newsapi = [n for n in newsapi if es_valida(n)]

        # Google News primero (más fresco), luego GDELT, luego NewsAPI
        titulos_vistos = set()
        resultado = []
        for n in google + gdelt + newsapi:
            if n["titulo"] not in titulos_vistos:
                titulos_vistos.add(n["titulo"])
                resultado.append(n)

        return resultado[:8]
    except:
        return []


def titulos_noticias(noticias):
    """Extrae titulos de forma 100% segura."""
    if not isinstance(noticias, list):
        return []
    return [str(n.get("titulo", "")) for n in noticias
            if isinstance(n, dict) and n.get("titulo")]


# ─── Google News RSS (sin API key, tiempo real) ──────────────────────────────

def buscar_google_news(query, max_resultados=5):
    """
    Google News RSS — gratis, sin API key, tiempo real.
    Más fresco que NewsAPI y sin límites de requests.
    """
    try:
        import urllib.parse
        query_encoded = urllib.parse.quote(query[:80])
        url = f"https://news.google.com/rss/search?q={query_encoded}&hl=en&gl=US&ceid=US:en"
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        # Parsear XML simple sin librerías externas
        import re
        items = re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL)
        resultado = []
        for item in items[:max_resultados]:
            titulo_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
            if not titulo_match:
                titulo_match = re.search(r'<title>(.*?)</title>', item)
            titulo = titulo_match.group(1).strip() if titulo_match else ""
            if titulo:
                resultado.append({
                    "titulo":      titulo,
                    "fuente":      "Google News",
                    "descripcion": titulo
                })
        return resultado
    except:
        return []


# ─── Football Data API (tabla de posiciones, resultados) ─────────────────────

def obtener_contexto_futbol(pregunta):
    """
    Busca datos reales de fútbol para dar contexto concreto a Mistral.
    Usa football-data.org (plan gratuito, sin API key para datos básicos).
    """
    try:
        p = pregunta.lower()

        # Detectar competición
        competition_map = {
            "champions league": "CL",
            "premier league":   "PL",
            "la liga":          "PD",
            "bundesliga":       "BL1",
            "serie a":          "SA",
            "ligue 1":          "FL1",
        }

        competition_id = None
        for nombre, code in competition_map.items():
            if nombre in p:
                competition_id = code
                break

        if not competition_id:
            competition_id = "CL"  # Default Champions League

        # Obtener tabla de posiciones
        headers = {"X-Auth-Token": FOOTBALL_TOKEN}
        url = f"{FOOTBALL_API_URL}/competitions/{competition_id}/standings"
        r = requests.get(url, headers=headers, timeout=8)

        if r.status_code != 200:
            return ""

        data = r.json()
        standings = data.get("standings", [{}])[0].get("table", [])[:10]

        if not standings:
            return ""

        tabla = f"Tabla actual {competition_id}:\n"
        for s in standings[:8]:
            team = s.get("team", {}).get("name", "")
            pos  = s.get("position", "")
            pts  = s.get("points", "")
            tabla += f"  {pos}. {team} — {pts} pts\n"

        return tabla

    except:
        return ""


def obtener_contexto_politica(pregunta):
    """Wikipedia API para contexto político — elecciones, candidatos, encuestas."""
    try:
        import urllib.parse
        # Extraer término clave de la pregunta
        palabras = [w for w in pregunta.split() if len(w) > 4 and w[0].isupper()]
        if not palabras:
            return ""
        termino = " ".join(palabras[:3])
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(termino)}"
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            extracto = data.get("extract", "")[:400]
            if extracto:
                return f"Wikipedia: {extracto}"
    except:
        pass
    return ""


def obtener_contexto_judicial(pregunta):
    """Google News específico para casos judiciales."""
    try:
        # Extraer nombre del caso de la pregunta
        import re
        terminos = re.findall(r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*', pregunta)
        query = " ".join(terminos[:3]) + " trial verdict sentence" if terminos else pregunta[:50]
        noticias = buscar_google_news(query, max_resultados=5)
        if noticias:
            return "Noticias judiciales:\n" + "\n".join(
                f"- {n['titulo']}" for n in noticias[:4]
            )
    except:
        pass
    return ""


def obtener_contexto_golf(pregunta):
    """ESPN RSS para torneos de golf."""
    try:
        r = requests.get(
            "https://www.espn.com/espn/rss/golf/news",
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code != 200:
            return ""
        import re
        items = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
        if items:
            return "Noticias golf recientes:\n" + "\n".join(f"- {t}" for t in items[1:5])
    except:
        pass
    # Fallback: Google News
    noticias = buscar_google_news(pregunta[:60] + " golf tournament", max_resultados=4)
    if noticias:
        return "Noticias golf:\n" + "\n".join(f"- {n['titulo']}" for n in noticias)
    return ""


def obtener_contexto_tenis(pregunta):
    """Google News para torneos de tenis."""
    try:
        noticias = buscar_google_news(pregunta[:60] + " tennis", max_resultados=4)
        if noticias:
            return "Noticias tenis:\n" + "\n".join(f"- {n['titulo']}" for n in noticias)
    except:
        pass
    return ""


def obtener_contexto_por_tipo(pregunta, tipo):
    """Obtiene contexto específico según el tipo de mercado."""
    if tipo == "futbol":
        return obtener_contexto_futbol(pregunta)
    elif tipo == "politica":
        return obtener_contexto_politica(pregunta)
    elif tipo == "judicial":
        return obtener_contexto_judicial(pregunta)
    elif tipo == "golf":
        return obtener_contexto_golf(pregunta)
    elif tipo == "tenis":
        return obtener_contexto_tenis(pregunta)
    return ""


# ─── Prompt de Mistral (calibrado) ──────────────────────────────────────────

def analizar_con_ollama(mercado, noticias, contexto_estructurado=""):
    """
    Prompt calibrado con contexto real.
    Si no hay noticias ni contexto → ESPERAR automáticamente.
    """
    noticias_texto = "\n".join([
        f"- {n['titulo']} ({n.get('fuente', '')})"
        for n in noticias[:6]
        if isinstance(n, dict) and n.get("titulo")
    ]) or ""

    # Sin información real → no adivinar
    if not noticias_texto and not contexto_estructurado:
        addlog(f"[Investigador] Sin datos reales — ESPERAR automático", "info")
        return {
            "probabilidad_estimada": mercado["precio"],
            "decision":   "ESPERAR",
            "confianza":  "BAJA",
            "edge":       0,
            "razonamiento": "Sin noticias recientes ni datos estructurados. Insuficiente para evaluar."
        }

    precio     = mercado["precio"]
    precio_pct = mercado["precio_pct"]
    biases     = mercado.get("biases", [])
    bias_texto = f"Biases: {', '.join(str(b) for b in biases)}" if biases else ""

    # Construir sección de datos disponibles
    datos_disponibles = ""
    if contexto_estructurado:
        datos_disponibles += f"\nDATOS ESTRUCTURADOS:\n{contexto_estructurado}"
    if noticias_texto:
        datos_disponibles += f"\nNOTICIAS RECIENTES:\n{noticias_texto}"

    prompt = f"""Sos un analista de prediction markets con acceso a datos reales.

MERCADO:
- Pregunta: {mercado['pregunta']}
- Outcome: {mercado['outcome']}
- Precio actual: {precio_pct}% de probabilidad implícita
- Retorno potencial: +{mercado['retorno_pct']}%
- Liquidez: ${mercado['liquidez']:,}
- Vence: {mercado['fecha_fin']}
{bias_texto}
{datos_disponibles}

REGLAS ESTRICTAS:
1. Usá SOLO los datos proporcionados arriba — no inventes ni uses conocimiento general
2. Si los datos no son suficientes para evaluar → decidí ESPERAR
3. APOSTAR solo si hay evidencia concreta de que el precio está mal
4. Tu probabilidad estimada debe basarse en los datos, no en intuición
5. Si el precio actual parece razonable dado los datos → ESPERAR

Respondé SOLO con este JSON:
{{
  "probabilidad_estimada": <número entre 0.10 y 0.90>,
  "decision": "<APOSTAR|ESPERAR|EVITAR>",
  "confianza": "<ALTA|MEDIA|BAJA>",
  "razonamiento": "<2 oraciones basadas SOLO en los datos proporcionados>"
}}"""

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "mistral", "prompt": prompt, "stream": False},
            timeout=60
        )
        texto = r.json().get("response", "")
        inicio = texto.find("{")
        fin    = texto.rfind("}") + 1
        if inicio >= 0 and fin > inicio:
            json_str = texto[inicio:fin]
            # Fix comunes: comillas simples → dobles, trailing commas
            json_str = json_str.replace("'", '"')
            json_str = json_str.replace(",\n}", "\n}").replace(",\n  }", "\n  }")
            try:
                resultado = json.loads(json_str)
            except:
                # Último intento: extraer solo los campos que nos importan con regex
                import re
                prob_match = re.search(r'"probabilidad_estimada"\s*:\s*([\d.]+)', json_str)
                dec_match  = re.search(r'"decision"\s*:\s*"(\w+)"', json_str)
                conf_match = re.search(r'"confianza"\s*:\s*"(\w+)"', json_str)
                razon_match = re.search(r'"razonamiento"\s*:\s*"([^"]+)"', json_str)
                if prob_match and dec_match:
                    resultado = {
                        "probabilidad_estimada": float(prob_match.group(1)),
                        "decision":   dec_match.group(1),
                        "confianza":  conf_match.group(1) if conf_match else "BAJA",
                        "edge":       0,
                        "razonamiento": razon_match.group(1) if razon_match else ""
                    }
                else:
                    return None
            # Sanity check
            prob = resultado.get("probabilidad_estimada", precio)
            resultado["probabilidad_estimada"] = max(0.10, min(0.90, float(prob)))
            return resultado
    except Exception as e:
        addlog(f"[Investigador] Error Ollama: {e}", "error")
    return None


def analizar_basico(mercado, noticias):
    """Fallback sin Ollama."""
    margen = mercado["margen"]
    biases = mercado.get("biases", [])

    if margen > 0.20 and len(noticias) > 0 and biases:
        decision, confianza = "APOSTAR", "MEDIA"
    elif margen > 0.15 and len(noticias) > 0:
        decision, confianza = "ESPERAR", "BAJA"
    else:
        decision, confianza = "EVITAR", "BAJA"

    return {
        "probabilidad_estimada": mercado["precio"],
        "decision":              decision,
        "confianza":             confianza,
        "edge":                  0,
        "razonamiento":          f"Análisis básico. Margen: {round(margen*100,1)}%. Noticias: {len(noticias)}."
    }


# ─── Investigar un mercado ────────────────────────────────────────────────────

def investigar(mercado):
    pregunta   = mercado["pregunta"]
    mercado_id = mercado["id"]

    # Detectar tipo de mercado
    tipo = detectar_tipo_mercado(pregunta)
    addlog(f"[Investigador] Tipo detectado: {tipo} | {pregunta[:40]}...", "info")

    # Obtener noticias (Google News + GDELT + NewsAPI)
    noticias = obtener_noticias(pregunta)

    # Obtener contexto estructurado según el tipo
    contexto = obtener_contexto_por_tipo(pregunta, tipo)
    if contexto:
        addlog(f"[Investigador] Contexto estructurado obtenido para {tipo}", "info")

    if estado["ollama_disponible"]:
        resultado = analizar_con_ollama(mercado, noticias, contexto)
        if not resultado:
            resultado = analizar_basico(mercado, noticias)
        metodo = "Ollama/Mistral"
    else:
        resultado = analizar_basico(mercado, noticias)
        metodo = "básico"

    prob       = resultado.get("probabilidad_estimada", mercado["precio"])
    decision   = resultado.get("decision", "ESPERAR")
    razon      = resultado.get("razonamiento", "")
    confianza  = resultado.get("confianza", "BAJA")

    # Normalizar tipos — Mistral a veces devuelve lista en vez de string
    if isinstance(razon, list):    razon     = " ".join(str(r) for r in razon)
    if isinstance(decision, list): decision  = decision[0] if decision else "ESPERAR"
    if isinstance(confianza, list): confianza = confianza[0] if confianza else "BAJA"
    razon     = str(razon or "")
    decision  = str(decision or "ESPERAR").upper()
    confianza = str(confianza or "BAJA").upper()
    try: prob = float(prob)
    except: prob = mercado["precio"]
    prob = max(0.10, min(0.90, prob))

    # Edge siempre calculado internamente — ignorar el de Mistral (puede ser absurdo)
    edge = round(prob - mercado["precio"], 4)

    # Actualizar mercado
    mercado["analizado"]             = True
    mercado["ultima_vez_analizado"]  = datetime.now()
    mercado["probabilidad_claudio"]  = round(prob, 4)
    mercado["decision_investigador"] = decision
    mercado["confianza"]             = confianza
    mercado["razonamiento"]          = razon
    mercado["edge_calculado"]        = round(edge, 4)
    mercado["metodo_analisis"]       = metodo

    # Guardar en DB — conversión defensiva de todos los tipos
    guardar_mercado(mercado_id, pregunta, mercado["fecha_fin"])
    biases_raw = mercado.get("biases", [])
    biases_str = ", ".join(str(b) for b in biases_raw) if isinstance(biases_raw, list) else str(biases_raw or "")
    # razon puede llegar como lista si Mistral mal-formatea el JSON
    if isinstance(razon, list):
        razon = " ".join(str(r) for r in razon)
    razon_safe = str(razon or "")[:500]
    suffix = f" | biases: {biases_str}" if biases_str else ""
    guardar_analisis(mercado_id, mercado["precio"], prob,
                     mercado["margen"], titulos_noticias(noticias),
                     decision, razon_safe + suffix)

    emoji = "✅" if decision == "APOSTAR" else "⏳" if decision == "ESPERAR" else "❌"
    addlog(f"[Investigador] {emoji} {decision}: {pregunta[:40]}... "
           f"edge={round(edge*100,1)}% ({confianza}) [{metodo}]",
           "win" if decision == "APOSTAR" else "")

    if decision == "APOSTAR":
        guardar_memoria("oportunidad", f"{pregunta} | edge={round(edge*100,1)}% | {razon}", mercado_id)

    return resultado


# ─── Loop principal ──────────────────────────────────────────────────────────

def correr():
    addlog("[Investigador] v2 iniciado — caché 2h, GDELT+NewsAPI, prompt calibrado", "info")
    time.sleep(10)
    verificar_ollama()

    while estado["corriendo"]:
        try:
            # Snapshot thread-safe de mercados para este ciclo
            mercados_snap = get_mercados()

            # Priorizar urgentes primero
            urgentes = [m for m in mercados_snap
                        if m.get("urgente") and not m.get("analizado")]

            # Analizar cualquier mercado que necesite análisis:
            # - los del Monitor (decision == "OPORTUNIDAD")
            # - los del Arbitraje (metodo_analisis empieza con "Arbitraje")
            sin_cache = [m for m in mercados_snap
                         if not m.get("urgente") and necesita_reanalisis(m)
                         and (m.get("decision") == "OPORTUNIDAD"
                              or m.get("metodo_analisis", "").startswith("Arbitraje"))]

            cola = urgentes[:2] + sin_cache[:MAX_POR_CICLO - len(urgentes[:2])]

            if cola:
                addlog(f"[Investigador] Analizando {len(cola)} mercados "
                       f"({len(urgentes)} urgentes)...")
                for mercado in cola:
                    if not estado["corriendo"]: return
                    investigar(mercado)
                    mercado["urgente"] = False
                    time.sleep(2)
            else:
                verificar_ollama()

        except Exception as e:
            import traceback
            addlog(f"[Investigador] Error: {e} | {traceback.format_exc()[-200:]}", "error")

        for _ in range(INTERVALO_SEG):
            if not estado["corriendo"]: return
            time.sleep(1)
