"""
agentes/monitor.py — Agente Monitor v2
Escanea Polymarket cada 5 minutos buscando oportunidades.
Mejoras v2:
  - Filtro precio mínimo 15% (evita longshots de 5% que explotan Kelly)
  - Behavioral biases: round numbers, stale markets, weekend gaps, cascade overshoot
  - GDELT como fuente de señal rápida (65+ idiomas, gratis)
  - Progressive context loading: Nivel 1 filtro rápido, Nivel 2 = Investigador
  - Triggers: price dislocation y volume spike para análisis urgente
"""

import time
import requests
import json
from datetime import datetime
from core.estado import estado, addlog, set_mercados, incrementar_ciclo

GAMMA_URL = "https://gamma-api.polymarket.com"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
INTERVALO_SEGUNDOS = 300  # 5 minutos

# ─── Filtros Nivel 1 ─────────────────────────────────────────────────────────
PRECIO_MIN   = 0.15   # Mínimo 15% — elimina los longshots de 5% que quiebran Kelly
PRECIO_MAX   = 0.85   # Máximo 85%
LIQUIDEZ_MIN = 5000   # Mínimo $5,000 — evita mover mercados chicos
MARGEN_MIN   = 0.08   # Mínimo 8% de distancia al 50%
DIAS_MAX     = 60     # Solo mercados que vencen en los próximos 60 días


def parsear_lista(valor):
    if isinstance(valor, list): return valor
    if isinstance(valor, str):
        try: return json.loads(valor)
        except: return []
    return []


def obtener_mercados():
    try:
        params = {"active": "true", "closed": "false", "limit": 500}
        r = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=15)
        return r.json()
    except Exception as e:
        addlog(f"[Monitor] Error conectando a Polymarket: {e}", "error")
        return []


# ─── Behavioral biases ───────────────────────────────────────────────────────

def detectar_biases(precio, liquidez, volumen):
    biases = []
    score  = 0.0

    # Round number clustering — ancla en 25%, 50%, 75%
    for rn in [0.25, 0.50, 0.75]:
        if abs(precio - rn) < 0.02:
            biases.append(f"round_{int(rn*100)}")
            score += 0.15

    # Stale market — liquidez muy baja vs volumen histórico
    if volumen > 0 and liquidez / max(volumen, 1) < 0.05:
        biases.append("stale_market")
        score += 0.10

    # Weekend gap
    if datetime.now().weekday() in [4, 5, 6]:
        biases.append("weekend_gap")
        score += 0.05

    # Cascade overshoot — precio muy extremo puede ser sobrereacción
    if abs(precio - 0.5) > 0.35:
        biases.append("possible_overshoot")
        score += 0.08

    return round(score, 3), biases


# ─── GDELT — señal rápida ────────────────────────────────────────────────────

def hay_noticias_gdelt(pregunta):
    """Nivel 1 rápido: ¿GDELT tiene algo sobre este mercado en las últimas 24h?"""
    try:
        palabras = " ".join(pregunta.split()[:5])
        params = {
            "query": palabras,
            "mode": "artlist",
            "maxrecords": 3,
            "format": "json",
            "timespan": "24h",
            "sort": "datedesc"
        }
        r = requests.get(GDELT_URL, params=params, timeout=6)
        data = r.json()
        articulos = data.get("articles", [])
        noticias = [{
            "titulo": a.get("title", ""),
            "fuente": a.get("domain", ""),
        } for a in articulos]
        return len(noticias) > 0, noticias
    except:
        return False, []


# ─── Análisis Nivel 1 ────────────────────────────────────────────────────────

def analizar_mercados(mercados_raw):
    resultado = []
    for m in mercados_raw:
        try:
            pregunta  = m.get("question", "")
            fecha_fin = m.get("endDate", "")
            liquidez  = float(m.get("liquidity", 0) or 0)
            volumen   = float(m.get("volume", 0) or 0)
            precios   = parsear_lista(m.get("outcomePrices"))
            outcomes  = parsear_lista(m.get("outcomes"))

            if not pregunta or not precios or not outcomes: continue
            if liquidez < LIQUIDEZ_MIN: continue

            # Filtro de fecha: solo mercados que vencen en los próximos DIAS_MAX días
            if fecha_fin:
                try:
                    fecha_venc = datetime.fromisoformat(fecha_fin[:10])
                    dias_restantes = (fecha_venc - datetime.now()).days
                    if dias_restantes < 1 or dias_restantes > DIAS_MAX:
                        continue
                except:
                    pass

            for outcome, precio_str in zip(outcomes, precios):
                precio = float(precio_str)

                # Filtro duro: sin longshots ni near-certainties
                if precio < PRECIO_MIN or precio > PRECIO_MAX:
                    continue

                margen = abs(precio - 0.5)
                if margen < MARGEN_MIN:
                    continue

                bias_score, biases = detectar_biases(precio, liquidez, volumen)
                tiene_gdelt, noticias_gdelt = hay_noticias_gdelt(pregunta)

                score = (margen * 0.5
                         + min(liquidez / 50000, 1) * 0.3
                         + bias_score * 0.2)

                resultado.append({
                    "id":                   f"{pregunta[:40]}_{outcome}",
                    "pregunta":             pregunta,
                    "outcome":              outcome,
                    "precio":               round(precio, 4),
                    "precio_pct":           round(precio * 100, 1),
                    "retorno_pct":          round((1 - precio) / precio * 100, 0),
                    "liquidez":             round(liquidez, 0),
                    "volumen":              round(volumen, 0),
                    "fecha_fin":            fecha_fin[:10] if fecha_fin else "N/A",
                    "margen":               round(margen, 4),
                    "score":                round(score, 4),
                    "biases":               biases,
                    "bias_score":           bias_score,
                    "tiene_noticias_gdelt": tiene_gdelt,
                    "noticias_gdelt":       noticias_gdelt,
                    "decision":             "OPORTUNIDAD",
                    "analizado":            False,
                    "urgente":              False,
                    "ultima_vez_analizado": None,
                })
        except:
            continue

    resultado.sort(key=lambda x: x["score"], reverse=True)
    return resultado[:30]


# ─── Triggers ────────────────────────────────────────────────────────────────

def detectar_triggers(mercados_anteriores, mercados_nuevos):
    mapa = {m["id"]: m["precio"] for m in mercados_anteriores}
    urgentes = set()

    for m in mercados_nuevos:
        precio_ant = mapa.get(m["id"])
        # Price dislocation: cambio > 5% en un ciclo
        if precio_ant and abs(m["precio"] - precio_ant) > 0.05:
            urgentes.add(m["id"])
            addlog(f"[Monitor] ⚡ DISLOCATION: {m['pregunta'][:35]}... "
                   f"{round(precio_ant*100,1)}%→{m['precio_pct']}%", "win")
        # Volume spike: vol/liquidez > 5x
        if m["liquidez"] > 0 and m["volumen"] / m["liquidez"] > 5:
            urgentes.add(m["id"])
            addlog(f"[Monitor] 📈 VOL SPIKE: {m['pregunta'][:35]}...", "win")

    for m in mercados_nuevos:
        if m["id"] in urgentes:
            m["urgente"] = True


# ─── Loop principal ──────────────────────────────────────────────────────────

def correr():
    addlog("[Monitor] v2 iniciado — filtro 15%, biases, GDELT, triggers", "info")
    mercados_anteriores = []

    while estado["corriendo"]:
        try:
            addlog("[Monitor] Consultando Polymarket...")
            mercados_raw = obtener_mercados()
            mercados     = analizar_mercados(mercados_raw)

            if mercados_anteriores:
                detectar_triggers(mercados_anteriores, mercados)

            set_mercados(mercados)
            mercados_anteriores = [{"id": m["id"], "precio": m["precio"],
                                    "volumen": m["volumen"], "liquidez": m["liquidez"]}
                                   for m in mercados]
            ciclo = incrementar_ciclo()

            ops        = len(mercados)
            con_gdelt  = sum(1 for m in mercados if m["tiene_noticias_gdelt"])
            con_biases = sum(1 for m in mercados if m["biases"])
            urgentes   = sum(1 for m in mercados if m["urgente"])

            addlog(f"[Monitor] {ops} mercados · {con_gdelt} con GDELT · "
                   f"{con_biases} con biases · {urgentes} urgentes · "
                   f"ciclo #{ciclo}", "win")

            for m in mercados[:3]:
                if m["biases"]:
                    addlog(f"[Monitor] Bias: {m['pregunta'][:40]}... → {', '.join(m['biases'])}", "info")

        except Exception as e:
            addlog(f"[Monitor] Error: {e}", "error")

        for _ in range(INTERVALO_SEGUNDOS):
            if not estado["corriendo"]: return
            time.sleep(1)
