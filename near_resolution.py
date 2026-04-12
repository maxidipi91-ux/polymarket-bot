"""
agentes/near_resolution.py — Yield en mercados casi resueltos

Estrategia: comprar mercados donde el precio ya esta en 90-97%
(el evento casi seguramente ya ocurrio) y redimir al 100%.
Retorno: 3-11% por operacion en pocas horas.

Diferente al copytrader — no requiere seguir wallets ni predecir.
Es mas parecido a arbitraje: el oracle confirma lo que ya todos saben.

Criterios para entrar:
- precio >= 0.92 y <= 0.97 (debajo de 92% hay riesgo real; encima de 97% poco margen)
- endDate ya paso O es en las proximas 4 horas (evento casi seguro que termino)
- volumen > $500 (mercado activo, no basura)
- NO tener ya una posicion en ese conditionId
- Max 3 posiciones near-resolution simultaneas
- Monto fijo pequeno: $3 por posicion (yield mecanico, no apostamos fuerte)
"""

import time
import json
import requests
from datetime import datetime, timezone, timedelta
from core.estado import estado, addlog, insertar_mercado, actualizar_saldo, actualizar_pnl, get_operaciones
from core.database import guardar_mercado, guardar_operacion, cerrar_operacion, get_operaciones_db

GAMMA_API  = "https://gamma-api.polymarket.com"
DATA_API   = "https://data-api.polymarket.com"
INTERVALO  = 300   # Escanear cada 5 minutos

PRECIO_MIN    = 0.92   # Solo entrar si probabilidad >= 92%
PRECIO_MAX    = 0.97   # Si ya esta en 98%+ hay poco margen
VOLUMEN_MIN   = 500    # Mercado activo
MONTO_POR_OP  = 15.0   # $15 por posicion
MAX_NR_ABIERTAS = 3    # Max posiciones near-resolution simultaneas

_nr_apostados = set()  # conditionIds ya procesados en esta sesion

# ── ESPN live game detection ──────────────────────────────────────────────────
ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

ESPN_ENDPOINTS = [
    ("basketball", "nba"),
    ("hockey",     "nhl"),
    ("baseball",   "mlb"),
    ("soccer",     "eng.1"),
    ("soccer",     "esp.1"),
    ("soccer",     "ger.1"),
    ("soccer",     "ita.1"),
    ("soccer",     "fra.1"),
    ("soccer",     "usa.1"),
]

# Thresholds to qualify a live game as a "safe blowout"
BLOWOUT_THRESHOLDS = {
    "nba":    {"margin": 15, "period": 4,  "clock_max_sec": 300},  # 4th Q, <5 min
    "nhl":    {"margin": 2,  "period": 3,  "clock_max_sec": 300},  # 3rd P, <5 min
    "mlb":    {"margin": 5,  "inning": 8},                          # 8th inn or later
    "soccer": {"margin": 2,  "minute": 75},                         # 75th min or later
}

_espn_cache: list = []       # cached live games
_espn_cache_ts: float = 0.0  # timestamp of last fetch


def _fetch_espn_live_games() -> list:
    """Fetches all in-progress games from ESPN unofficial API. Cached for 60s."""
    global _espn_cache, _espn_cache_ts
    now = time.time()
    if now - _espn_cache_ts < 60:
        return _espn_cache

    games = []
    for sport, league in ESPN_ENDPOINTS:
        try:
            url = ESPN_BASE.format(sport=sport, league=league)
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                continue
            for event in r.json().get("events", []):
                state = event.get("status", {}).get("type", {}).get("state", "")
                if state != "in":
                    continue
                comp = (event.get("competitions") or [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                # Extract scores and team names
                teams = {}
                for c in competitors:
                    side = "home" if c.get("homeAway") == "home" else "away"
                    teams[side] = {
                        "name": c.get("team", {}).get("displayName", ""),
                        "score": int(c.get("score", 0) or 0),
                    }

                home_score = teams["home"]["score"]
                away_score = teams["away"]["score"]
                margin = abs(home_score - away_score)
                leading_side = "home" if home_score >= away_score else "away"
                trailing_side = "away" if leading_side == "home" else "home"

                status = event.get("status", {})
                period = status.get("period", 0)
                clock_str = status.get("displayClock", "0:00")
                # Parse clock to seconds
                try:
                    parts = clock_str.split(":")
                    clock_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
                except Exception:
                    clock_sec = 999

                # Soccer: period=2 means 2nd half, use elapsed minutes
                minute = 0
                if sport == "soccer":
                    # ESPN reports time remaining in clock; in soccer period=1 → 1st half (45min), period=2 → 2nd half
                    # displayClock shows elapsed time for soccer
                    try:
                        minute = int(parts[0]) if len(parts) >= 1 else 0
                        if period == 2:
                            minute += 45
                    except Exception:
                        minute = 0

                game_key = "soccer" if sport == "soccer" else league
                thr = BLOWOUT_THRESHOLDS.get(game_key, {})
                is_blowout = _check_blowout(sport, league, margin, period, clock_sec, minute, thr)

                games.append({
                    "name":          event.get("name", ""),
                    "short_name":    event.get("shortName", ""),
                    "sport":         sport,
                    "league":        league,
                    "home":          teams["home"]["name"],
                    "away":          teams["away"]["name"],
                    "home_score":    home_score,
                    "away_score":    away_score,
                    "margin":        margin,
                    "leading_team":  teams[leading_side]["name"],
                    "trailing_team": teams[trailing_side]["name"],
                    "period":        period,
                    "clock_sec":     clock_sec,
                    "minute":        minute,
                    "is_blowout":    is_blowout,
                })
        except Exception as e:
            addlog(f"[NearRes/ESPN] Error {sport}/{league}: {e}", "error")

    _espn_cache = games
    _espn_cache_ts = now
    return games


def _check_blowout(sport, league, margin, period, clock_sec, minute, thr) -> bool:
    """Returns True if a live game meets blowout criteria."""
    if not thr:
        return False
    if sport == "soccer":
        return margin >= thr.get("margin", 99) and minute >= thr.get("minute", 99)
    if league == "mlb":
        return margin >= thr.get("margin", 99) and period >= thr.get("inning", 99)
    # nba / nhl: check period and clock
    return (
        margin >= thr.get("margin", 99)
        and period >= thr.get("period", 99)
        and clock_sec <= thr.get("clock_max_sec", 0)
    )


def _match_espn_game(title: str, outcome: str) -> dict | None:
    """
    Tries to match a Polymarket market title to a live ESPN game.
    Returns the game dict if matched AND it's a blowout for the given outcome.
    """
    title_lower = title.lower()
    # Extract meaningful words (length > 3)
    words = [w.strip("?.,'\"") for w in title_lower.split() if len(w.strip("?.,'\"")) > 3]

    best_game = None
    best_matches = 0

    for game in _fetch_espn_live_games():
        game_str = (game["home"] + " " + game["away"] + " " + game["name"]).lower()
        matches = sum(1 for w in words if w in game_str)
        if matches >= 2 and matches > best_matches:
            best_matches = matches
            best_game = game

    if not best_game:
        return None

    if not best_game["is_blowout"]:
        return None

    # Check that the outcome matches the leading team
    outcome_lower = outcome.lower()
    leading_lower = best_game["leading_team"].lower()
    # "yes" outcomes in sport markets usually mean the home/favorite wins
    # We accept if: outcome contains the leading team name OR outcome is "yes" and we have a blowout
    leading_words = [w for w in leading_lower.split() if len(w) > 3]
    outcome_matches_leader = any(w in outcome_lower for w in leading_words)
    outcome_is_yes = outcome_lower in ("yes", "si")

    if outcome_matches_leader or outcome_is_yes:
        return best_game
    return None


def _get_mercados_candidatos() -> list:
    """
    Descarga mercados activos y filtra candidatos near-resolution.

    Dos fuentes de candidatos:
    1. endDate ya paso hace >1h — evento terminado, oracle pendiente (principal)
    2. endDate en las proximas 3h + ESPN confirma blowout en vivo (secundario)
    """
    candidatos = []
    try:
        ahora = datetime.now(timezone.utc)
        corte_pasado = ahora - timedelta(hours=1)    # terminados hace al menos 1h
        corte_futuro = ahora + timedelta(hours=3)    # proximas 3h para live blowouts

        for offset in [0, 500]:
            r = requests.get(f"{GAMMA_API}/markets", params={
                "active": "true", "closed": "false",
                "limit": 500, "offset": offset,
                "order": "volume24hr", "ascending": "false"
            }, timeout=12)
            if r.status_code != 200:
                break
            mercados = r.json()
            for m in mercados:
                try:
                    outcomes = m.get("outcomes", "[]")
                    prices   = m.get("outcomePrices", "[]")
                    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                    if isinstance(prices, str):   prices   = json.loads(prices)
                    if not outcomes or not prices:
                        continue

                    for outcome, precio_str in zip(outcomes, prices):
                        precio = float(precio_str)
                        if not (PRECIO_MIN <= precio <= PRECIO_MAX):
                            continue

                        vol = float(m.get("volume", 0) or 0)
                        if vol < VOLUMEN_MIN:
                            continue

                        end_date_str = m.get("endDate") or m.get("end_date_iso") or ""
                        if not end_date_str:
                            continue
                        try:
                            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                        except Exception:
                            continue

                        title = m.get("question", m.get("title", ""))[:60]

                        # Fuente 1: evento ya termino hace >1h (principal, near-zero risk)
                        if end_dt <= corte_pasado:
                            candidatos.append({
                                "conditionId": m.get("conditionId", ""),
                                "title": title,
                                "outcome": outcome,
                                "precio": precio,
                                "volumen": vol,
                                "endDate": end_date_str,
                                "clobTokenIds": m.get("clobTokenIds", "[]"),
                                "fuente": "pasado",
                            })
                            continue

                        # Fuente 2: evento en las proximas 3h — solo si ESPN confirma blowout
                        if ahora < end_dt <= corte_futuro:
                            game = _match_espn_game(title, outcome)
                            if game:
                                addlog(
                                    f"[NearRes/ESPN] Blowout detectado: {game['leading_team']} "
                                    f"+{game['margin']} | {title[:40]}",
                                    "info"
                                )
                                candidatos.append({
                                    "conditionId": m.get("conditionId", ""),
                                    "title": title,
                                    "outcome": outcome,
                                    "precio": precio,
                                    "volumen": vol,
                                    "endDate": end_date_str,
                                    "clobTokenIds": m.get("clobTokenIds", "[]"),
                                    "fuente": "espn_blowout",
                                })
                except Exception:
                    continue
            if len(mercados) < 500:
                break
    except Exception as e:
        addlog(f"[NearRes] Error descargando mercados: {e}", "error")
    return candidatos


def _ya_tenemos_posicion(cond_id: str) -> bool:
    """Verifica si ya tenemos una posicion abierta en este conditionId."""
    cond_key = cond_id[:20]
    if cond_key in _nr_apostados:
        return True
    from core.database import get_mercados_apostados
    if any(cond_key in m for m in get_mercados_apostados()):
        return True
    return False


def _contar_nr_abiertas() -> int:
    """Cuenta posiciones near-resolution actualmente abiertas."""
    return sum(
        1 for op in get_operaciones_db()
        if op.get("resultado") == "ABIERTA"
        and str(op.get("mercado_id", "")).startswith("nr_")
    )


def _ejecutar_entrada(candidato: dict):
    """Entra en un mercado near-resolution."""
    cond_id  = candidato["conditionId"]
    outcome  = candidato["outcome"]
    precio   = candidato["precio"]
    title    = candidato["title"]
    cond_key = cond_id[:20]

    if estado["saldo"] < MONTO_POR_OP:
        addlog("[NearRes] Saldo insuficiente para entrar", "error")
        return

    mercado_id = f"nr_{cond_key}_{outcome[:3]}"

    # Extraer clob_token_id para el outcome
    clob_token_id = ""
    try:
        clobids = candidato.get("clobTokenIds", "[]")
        if isinstance(clobids, str):
            clobids = json.loads(clobids)
        # No tenemos los outcomes originales aqui, usamos el primer token por defecto
        if clobids:
            clob_token_id = clobids[0] if outcome.lower() in ("yes", "si", "over") else (clobids[1] if len(clobids) > 1 else clobids[0])
    except:
        pass

    ganancia_potencial = round(MONTO_POR_OP / precio - MONTO_POR_OP, 2)

    mercado_obj = {
        "id":                    mercado_id,
        "pregunta":              title,
        "outcome":               outcome,
        "precio":                precio,
        "precio_pct":            round(precio * 100, 1),
        "probabilidad_claudio":  round(min(precio + 0.03, 0.99), 4),
        "liquidez":              candidato["volumen"],
        "fecha_fin":             candidato["endDate"][:10],
        "confianza":             "ALTA",
        "decision":              "APOSTAR",
        "decision_investigador": "APOSTAR",
        "analizado":             True,
        "metodo_analisis":       "NearResolution",
        "condition_id":          cond_id,
        "clob_token_id":         clob_token_id,
        "razonamiento":          (
            f"Near-resolution: {outcome} @ {round(precio*100,1)}% "
            f"endDate={candidato['endDate'][:10]} vol=${round(candidato['volumen'])}"
        ),
    }

    actualizar_saldo(-MONTO_POR_OP)
    guardar_mercado(mercado_id, title, candidato["endDate"][:10])
    insertar_mercado(mercado_obj)

    op_id = guardar_operacion(mercado_id, outcome, precio, MONTO_POR_OP, estado.get("modo", "real"), 0)

    # Ejecutar orden CLOB en modo real
    if estado.get("modo") == "real":
        try:
            from agentes.clob import ejecutar_orden
            resultado = ejecutar_orden(cond_id, outcome, precio, MONTO_POR_OP, token_id_directo=clob_token_id or None)
            if not resultado:
                actualizar_saldo(MONTO_POR_OP)
                if op_id:
                    cerrar_operacion(op_id, precio, 0, "FALLIDA")
                addlog(f"[NearRes] Orden CLOB fallo — revertido", "error")
                return
        except Exception as e:
            addlog(f"[NearRes] Error CLOB: {e}", "error")
            actualizar_saldo(MONTO_POR_OP)
            return

    _nr_apostados.add(cond_key)
    addlog(
        f"[NearRes] ENTRADA {outcome} @ {round(precio*100,1)}% | {title[:40]} "
        f"| potencial +${ganancia_potencial} | endDate={candidato['endDate'][:10]}",
        "win"
    )


def correr():
    addlog(f"[NearRes] Iniciado — scan cada 5min | rango {round(PRECIO_MIN*100)}-{round(PRECIO_MAX*100)}% | ${MONTO_POR_OP}/op", "info")
    time.sleep(60)  # Esperar que el resto del sistema arranque

    while estado["corriendo"]:
        try:
            nr_abiertas = _contar_nr_abiertas()
            if nr_abiertas >= MAX_NR_ABIERTAS:
                addlog(f"[NearRes] Max posiciones ({nr_abiertas}/{MAX_NR_ABIERTAS}) — esperando", "info")
            else:
                candidatos = _get_mercados_candidatos()
                # Filtrar los ya apostados
                candidatos = [c for c in candidatos if not _ya_tenemos_posicion(c["conditionId"])]
                # Ordenar por precio desc (mas cerca de resolver primero)
                candidatos.sort(key=lambda x: -x["precio"])

                slots = MAX_NR_ABIERTAS - nr_abiertas
                tomados = 0
                for c in candidatos[:slots * 3]:  # revisar hasta 3x los slots disponibles
                    if tomados >= slots:
                        break
                    if estado["saldo"] < MONTO_POR_OP:
                        break
                    addlog(
                        f"[NearRes] Candidato: {c['outcome']} @ {round(c['precio']*100,1)}% "
                        f"| {c['title'][:40]} | vol=${round(c['volumen'])}",
                        "info"
                    )
                    _ejecutar_entrada(c)
                    tomados += 1
                    time.sleep(3)

                if not candidatos:
                    addlog("[NearRes] Sin candidatos en este ciclo", "info")

        except Exception as e:
            addlog(f"[NearRes] Error general: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]:
                return
            time.sleep(1)
