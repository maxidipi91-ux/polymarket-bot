"""
agentes/odds.py — Arbitraje de odds: bookmakers vs Polymarket

Lógica:
  1. Obtiene odds de Pinnacle/Betfair (los bookmakers más eficientes del mundo)
     para los deportes activos via The Odds API.
  2. Convierte odds decimales a probabilidad implícita (eliminando el margen).
  3. Busca mercados de Polymarket del mismo partido.
  4. Si la diferencia entre la prob del bookmaker y el precio de Polymarket
     es mayor que EDGE_MIN → señal de apuesta.

Por qué funciona:
  Pinnacle y Betfair tienen los mercados más eficientes del mundo.
  Polymarket lo pricean traders de retail. La brecha es el edge.

Sin LLM. Sin noticias. Solo matemática de probabilidades.
"""

import time
import re
import json
import requests
from datetime import datetime, timezone, timedelta

from core.estado import estado, addlog
from core.database import guardar_mercado, guardar_analisis
from config_loader import CONFIG

ODDS_API_URL = "https://api.the-odds-api.com/v4"
GAMMA_URL    = "https://gamma-api.polymarket.com"

ODDS_API_KEY  = CONFIG["odds_api_key"]
INTERVALO_SEG = 86400  # 24 horas — odds de outrights no cambian tanto, conserva créditos (500/mes ~83 días)
EDGE_MIN      = 0.08  # 8% de diferencia mínima
LIQUIDEZ_MIN  = 5000  # Mínimo $5K en Polymarket para que valga
MAX_DIAS      = 7     # Solo partidos en los próximos 7 días

# Deportes a monitorear — solo los que tienen mercados activos en Polymarket
# Verificado: NFL/MLB/NCAAF/NCAAB/UEFA Euro = 0 mercados activos en Polymarket ahora
# Presupuesto: 8 deportes × 30 días = 240 créditos/mes (límite: 500)
DEPORTES = [
    # Basketball — 75 mercados, $13.6M liquidez en Polymarket
    "basketball_nba_championship_winner",
    # Hockey — 27 mercados, $3.3M liquidez
    "icehockey_nhl_championship_winner",
    # Golf — 85 mercados, $11.2M liquidez (4 majors activos)
    "golf_masters_tournament_winner",
    "golf_pga_championship_winner",
    "golf_us_open_winner",
    "golf_the_open_championship_winner",
    # Soccer — FIFA World Cup 2026: 48 mercados, $84.6M liquidez 🔥
    "soccer_fifa_world_cup_winner",
]

# Bookmakers preferidos: Pinnacle y Betfair son los más sharp del mundo
BOOKMAKERS = "pinnacle,betfair_ex_eu"


# ─── The Odds API ─────────────────────────────────────────────────────────���───

def obtener_odds(sport_key):
    """
    Obtiene odds outright de un deporte desde The Odds API.
    No filtramos por bookmaker en la query (causa 422 en outrights).
    Filtramos Pinnacle/Betfair en prob_sharp().
    """
    try:
        r = requests.get(
            f"{ODDS_API_URL}/sports/{sport_key}/odds/",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    "outrights",
                "oddsFormat": "decimal",
            },
            timeout=10
        )
        restantes = r.headers.get("x-requests-remaining", "?")
        if r.status_code == 200:
            return r.json(), restantes
        else:
            addlog(f"[Odds] Error API {sport_key}: {r.status_code}", "error")
            return [], restantes
    except Exception as e:
        addlog(f"[Odds] Excepcion {sport_key}: {e}", "error")
        return [], "?"


def prob_desde_odds(odds_decimal):
    """Convierte odds decimal a probabilidad implícita."""
    if odds_decimal <= 1:
        return 0
    return round(1 / odds_decimal, 4)


def prob_sharp(evento):
    """
    Calcula la probabilidad 'sharp' promediando Pinnacle y Betfair,
    eliminando el margen del bookmaker (overround).

    Devuelve dict: {team_name: prob_ajustada}
    """
    # Juntar todas las outcomes de todos los bookmakers disponibles
    acumulado = {}
    conteos   = {}

    for bk in evento.get("bookmakers", []):
        for market in bk.get("markets", []):
            if market.get("key") not in ("h2h", "outrights"):
                continue
            outcomes = market.get("outcomes", [])
            # Calcular overround para normalizar
            suma_probs = sum(prob_desde_odds(o["price"]) for o in outcomes)
            if suma_probs <= 0:
                continue
            for o in outcomes:
                nombre = o["name"]
                prob   = prob_desde_odds(o["price"]) / suma_probs  # normalizada
                if nombre not in acumulado:
                    acumulado[nombre] = 0
                    conteos[nombre]   = 0
                acumulado[nombre] += prob
                conteos[nombre]   += 1

    if not acumulado:
        return {}

    return {
        nombre: round(acumulado[nombre] / conteos[nombre], 4)
        for nombre in acumulado
    }


# ─── Polymarket ───────────────────────────────────────────────────────────────

def obtener_mercados_polymarket():
    """Obtiene mercados de deportes de Polymarket."""
    try:
        mercados = []
        for offset in [0, 500]:
            r = requests.get(f"{GAMMA_URL}/markets", params={
                "active": "true", "closed": "false",
                "limit": 500, "offset": offset, "order": "volume24hr", "ascending": "false"
            }, timeout=15)
            mercados.extend(r.json())
        return mercados
    except Exception as e:
        addlog(f"[Odds] Error Polymarket: {e}", "error")
        return []


def normalizar_nombre(nombre):
    """Normaliza nombre de equipo para comparación."""
    nombre = nombre.lower().strip()
    reemplazos = {
        "manchester united":       "manchester united",
        "manchester city":         "manchester city",
        "wolverhampton wanderers": "wolverhampton wolves",
        "tottenham hotspur":       "tottenham",
        "newcastle united":        "newcastle",
        "west ham united":         "west ham",
        "nottingham forest":       "nottingham forest",
        "atletico madrid":         "atletico madrid",
        "atletico de madrid":      "atletico madrid",
        "fc barcelona":            "barcelona",
        "paris saint-germain":     "paris psg",
        "paris saint germain":     "paris psg",
        "internazionale":          "inter milan",
        "golden state warriors":   "golden state warriors",
        "los angeles lakers":      "los angeles lakers",
        "los angeles clippers":    "los angeles clippers",
        "los angeles dodgers":     "los angeles dodgers",
        "los angeles rams":        "los angeles rams",
        "new york knicks":         "new york knicks",
        "new york yankees":        "new york yankees",
        "new york mets":           "new york mets",
        "new york giants":         "new york giants",
        "new york jets":           "new york jets",
        "oklahoma city thunder":   "oklahoma city thunder",
    }
    for largo, corto in reemplazos.items():
        nombre = nombre.replace(largo, corto)
    return nombre


# Palabras genéricas que NO identifican un equipo (solo la ciudad)
# Si la pregunta solo contiene estas palabras del nombre → falso positivo
PALABRAS_GENERICAS = {
    "los", "angeles", "new", "york", "san", "golden", "state",
    "city", "united", "fc", "cf", "sc", "ac", "the"
}


def palabras_especificas(nombre):
    """Devuelve las palabras del nombre que identifican al equipo (no genéricas)."""
    stop = {"los", "the", "new", "san", "fc", "cf", "sc", "ac", "city"}
    return [p for p in nombre.lower().split() if p not in stop and len(p) >= 3]


def nombre_en_pregunta(nombre_equipo, pregunta):
    """
    True solo si las palabras específicas del equipo aparecen en la pregunta.
    Requiere al menos 2 palabras específicas, o 1 si es única (ej: 'liverpool').
    Evita falsos positivos como Lakers vs Dodgers (ambos 'Los Angeles').
    """
    palabras = palabras_especificas(nombre_equipo)
    if not palabras:
        return False

    pq_lower = pregunta.lower()

    # Si el nombre completo normalizado aparece → match directo
    norm = normalizar_nombre(nombre_equipo)
    if norm in pq_lower:
        return True

    # Para equipos de 1 palabra específica (ej: "Liverpool", "Arsenal")
    if len(palabras) == 1:
        return palabras[0] in pq_lower

    # Para equipos de 2+ palabras, requerir que AL MENOS 2 aparezcan
    matches = sum(1 for p in palabras if p in pq_lower)
    return matches >= 2


def buscar_mercado_polymarket(equipo, mercados_pm, partido_hora=None, es_outright=False):
    """
    Busca el mercado de Polymarket para un equipo.
    - es_outright=True: mercados de temporada/campeonato, sin filtro de tiempo estricto.
    - es_outright=False: mercados de partido individual, ventana de 48h.
    """
    for m in mercados_pm:
        pregunta = m.get("question", "")
        fecha    = m.get("endDate", "")
        liq      = float(m.get("liquidity", 0) or 0)

        if liq < LIQUIDEZ_MIN:
            continue

        # Filtro de tiempo — solo para mercados de partido individual
        if not es_outright and partido_hora and fecha:
            try:
                venc = datetime.fromisoformat(fecha.rstrip("Z")).replace(tzinfo=timezone.utc)
                diff = abs((venc - partido_hora).total_seconds() / 3600)
                if diff > 48:
                    continue
            except:
                pass

        if not nombre_en_pregunta(equipo, pregunta):
            continue

        # Extraer precio YES
        precios  = m.get("outcomePrices", "[]")
        outcomes = m.get("outcomes", "[]")
        if isinstance(precios, str):  precios  = json.loads(precios)
        if isinstance(outcomes, str): outcomes = json.loads(outcomes)

        for o, p in zip(outcomes, precios):
            if o == "Yes":
                return m, float(p)

    return None, None


# ─── Análisis de un evento ───────────────────────────────────────────────────��

def extraer_nivel_mercado(pregunta):
    """
    Detecta el nivel del mercado para evitar comparar Finals vs Conference Finals.
    Devuelve: 'finals', 'conference', 'division', 'season', 'other'
    """
    q = pregunta.lower()
    if any(x in q for x in ["nba finals", "world series", "stanley cup", "super bowl", "masters", "world cup winner"]):
        return "finals"
    if any(x in q for x in ["conference finals", "conference semi", "conference"]):
        return "conference"
    if any(x in q for x in ["division", "wild card", "playoff"]):
        return "division"
    if any(x in q for x in ["league", "premier", "season", "serie a", "bundesliga", "la liga"]):
        return "season"
    return "other"


def analizar_evento(evento, mercados_pm, sport_title):
    """
    Compara las probabilidades del bookmaker vs Polymarket para un evento outright.
    Soporta tanto YES (subvaluado) como NO (sobrevaluado).
    """
    oportunidades = []

    try:
        probs = prob_sharp(evento)
        if not probs:
            return []

        hora_str = evento.get("commence_time", "")
        hora     = datetime.fromisoformat(hora_str.rstrip("Z")).replace(tzinfo=timezone.utc) if hora_str else datetime.now(timezone.utc)

        for equipo, prob_bk in probs.items():
            if prob_bk < 0.02 or prob_bk > 0.95:
                continue

            # Buscar mercado YES en Polymarket (outright = sin filtro estricto de tiempo)
            mercado_pm, precio_yes = buscar_mercado_polymarket(equipo, mercados_pm, hora, es_outright=True)
            if not mercado_pm or not precio_yes:
                continue

            pregunta = mercado_pm.get("question", "")

            # Filtrar: solo comparar mismo nivel de mercado
            # (no mezclar "NBA Finals" con "Conference Finals")
            nivel_pm = extraer_nivel_mercado(pregunta)
            nivel_bk = extraer_nivel_mercado(sport_title + " " + (evento.get("home_team") or ""))
            # Para outrights de campeonato, solo queremos mercados de finals/season
            if nivel_pm == "conference":
                continue

            liquidez  = float(mercado_pm.get("liquidity", 0) or 0)
            fecha_fin = mercado_pm.get("endDate", "")[:16]

            # Edge en YES: bookmaker cree que es más probable que Polymarket
            edge_yes = prob_bk - precio_yes

            # Edge en NO: bookmaker cree que es menos probable (Polymarket sobrevalúa)
            precio_no  = round(1 - precio_yes, 4)
            prob_no_bk = round(1 - prob_bk, 4)
            edge_no    = prob_no_bk - precio_no  # = -(edge_yes)

            # Elegir el lado con edge positivo (prob_bookmaker > precio_polymarket)
            # Edge positivo = el mercado está subvalorado = oportunidad de compra
            if edge_yes >= EDGE_MIN:
                outcome     = "Yes"
                precio_op   = precio_yes
                prob_op     = prob_bk
                edge        = edge_yes
            elif edge_no >= EDGE_MIN:
                outcome     = "No"
                precio_op   = precio_no
                prob_op     = prob_no_bk
                edge        = edge_no
            else:
                continue

            confianza  = "ALTA" if abs(edge) >= 0.15 else "MEDIA"
            mercado_id = f"odds_{equipo[:25].replace(' ','_')}_{outcome}"

            oportunidades.append({
                "id":                    mercado_id,
                "pregunta":              pregunta,
                "outcome":               outcome,
                "precio":                round(precio_op, 4),
                "precio_pct":            round(precio_op * 100, 1),
                "retorno_pct":           round((1 - precio_op) / precio_op * 100, 0),
                "liquidez":              round(liquidez, 0),
                "volumen":               float(mercado_pm.get("volume", 0) or 0),
                "fecha_fin":             fecha_fin,
                "margen":                round(abs(precio_op - 0.5), 4),
                "score":                 round(abs(edge), 4),
                "biases":                [],
                "bias_score":            0.0,
                "tiene_noticias_gdelt":  False,
                "noticias_gdelt":        [],
                "decision":              "OPORTUNIDAD",
                "analizado":             True,
                "urgente":               abs(edge) >= 0.20,
                "ultima_vez_analizado":  datetime.now(),
                "decision_investigador": "APOSTAR",
                "confianza":             confianza,
                "probabilidad_claudio":  round(prob_op, 4),
                "edge_calculado":        round(edge, 4),
                "metodo_analisis":       f"Odds/{sport_title}",
                "razonamiento": (
                    f"{equipo} {outcome} | "
                    f"Bookmaker: {round(prob_op*100,1)}% | "
                    f"Polymarket: {round(precio_op*100,1)}% | "
                    f"Edge: {round(edge*100,1)}%"
                ),
            })

    except Exception as e:
        addlog(f"[Odds] Error analizando evento: {e}", "error")

    return oportunidades


# ─── Loop principal ───────────────────────────────────────────────────────────

def correr():
    if not ODDS_API_KEY:
        addlog("[Odds] Sin ODDS_API_KEY — agente desactivado. Agregar en .env", "error")
        return

    addlog("[Odds] Agente iniciado — Bookmakers vs Polymarket | ciclo 10min", "info")
    time.sleep(20)  # Esperar que el sistema arranque

    while estado["corriendo"]:
        try:
            addlog("[Odds] Escaneando bookmakers...")

            # Obtener mercados de Polymarket una sola vez por ciclo
            mercados_pm = obtener_mercados_polymarket()
            addlog(f"[Odds] {len(mercados_pm)} mercados Polymarket cargados", "info")

            todas_oportunidades = []
            calls_usadas        = 0

            for sport_key in DEPORTES:
                if not estado["corriendo"]:
                    break

                sport_title = sport_key.split("_", 1)[-1].replace("_", " ").upper()
                eventos, restantes = obtener_odds(sport_key)
                calls_usadas += 1

                if not eventos:
                    continue

                oport_sport = []
                for evento in eventos:
                    oport = analizar_evento(evento, mercados_pm, sport_title)
                    oport_sport.extend(oport)

                if oport_sport:
                    addlog(
                        f"[Odds] {sport_title}: {len(oport_sport)} oportunidades "
                        f"| mejor edge: {round(max(abs(o['edge_calculado']) for o in oport_sport)*100,1)}%",
                        "win"
                    )
                    todas_oportunidades.extend(oport_sport)

                time.sleep(1)  # Respetar rate limit

            # Actualizar estado con todas las oportunidades encontradas
            from core.estado import _lock
            import core.estado as _estado_mod
            with _lock:
                otros = [m for m in _estado_mod.estado["mercados"]
                         if not m["id"].startswith("odds_")]
                _estado_mod.estado["mercados"] = otros + todas_oportunidades

            # Guardar en DB
            for o in todas_oportunidades:
                guardar_mercado(o["id"], o["pregunta"], o["fecha_fin"])
                guardar_analisis(
                    o["id"], o["precio"], o["probabilidad_claudio"],
                    o["margen"], [], o["decision_investigador"], o["razonamiento"]
                )

            if todas_oportunidades:
                addlog(
                    f"[Odds] Total: {len(todas_oportunidades)} oportunidades en {calls_usadas} deportes",
                    "win"
                )
                for o in sorted(todas_oportunidades, key=lambda x: abs(x["edge_calculado"]), reverse=True)[:5]:
                    addlog(
                        f"[Odds] {o['pregunta'][:50]}... "
                        f"edge={round(o['edge_calculado']*100,1)}% ({o['confianza']})",
                        "win"
                    )
            else:
                addlog(f"[Odds] Sin edge suficiente en {calls_usadas} deportes escaneados", "info")

            addlog(f"[Odds] Calls API restantes: {restantes}", "info")

        except Exception as e:
            addlog(f"[Odds] Error inesperado: {e}", "error")

        for _ in range(INTERVALO_SEG):
            if not estado["corriendo"]:
                return
            time.sleep(1)
