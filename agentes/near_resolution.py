"""
agentes/near_resolution.py — Estrategia High-Probability Near-Resolution

Lógica:
  1. Cada 5 minutos escanea todos los mercados activos de Polymarket.
  2. Filtra mercados donde YES o NO >= 95% de probabilidad.
  3. Filtra mercados que vencen en las próximas 24 horas.
  4. Calcula el retorno anualizado: 5% en 2 horas = 21,900% anual.
  5. Prioriza por: (prob - 0.95) / horas_restantes — mayor urgencia primero.

Por qué funciona:
  Los mercados al 95%+ son casi seguros. Comprando YES a $0.96 que resuelve
  en 3 horas ganás 4% en 3 horas (~120% anualizado). Con compounding diario
  los retornos son exponenciales. El riesgo es el "black swan" — el 5%.

Ejemplos reales documentados:
  - Fed rate cut 95% priced in → comprar YES 72h antes → +5%
  - Trader "Sharky6999" construyó fortuna solo con esta estrategia
"""

import time
import json
import requests
from datetime import datetime, timezone

from core.estado import estado, addlog
from core.database import guardar_mercado, guardar_analisis

GAMMA_URL       = "https://gamma-api.polymarket.com"
INTERVALO_SEG   = 300    # 5 minutos
PROB_MIN        = 0.95   # Mínimo 95% de probabilidad
HORAS_MAX       = 24     # Solo mercados que vencen en las próximas 24 horas
HORAS_MIN       = 0.5    # Descartar si quedan menos de 30 minutos (riesgo ejecución)
LIQUIDEZ_MIN    = 2000   # Mínimo $2K de liquidez


def parsear_lista(valor):
    if isinstance(valor, list): return valor
    if isinstance(valor, str):
        try: return json.loads(valor)
        except: return []
    return []


def horas_restantes(fecha_fin_str):
    try:
        ahora = datetime.now(timezone.utc)
        s = fecha_fin_str.rstrip("Z")
        if "+" in s:
            venc = datetime.fromisoformat(fecha_fin_str)
        else:
            venc = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return (venc - ahora).total_seconds() / 3600
    except:
        return None


def analizar(m_raw):
    """Analiza un mercado y retorna oportunidad near-resolution o None."""
    pregunta  = m_raw.get("question", "")
    fecha_fin = m_raw.get("endDate", "")
    liquidez  = float(m_raw.get("liquidity", 0) or 0)
    volumen   = float(m_raw.get("volume", 0) or 0)

    if liquidez < LIQUIDEZ_MIN:
        return None

    horas = horas_restantes(fecha_fin)
    if horas is None or horas < HORAS_MIN or horas > HORAS_MAX:
        return None

    outcomes = parsear_lista(m_raw.get("outcomes"))
    precios  = parsear_lista(m_raw.get("outcomePrices"))
    if not outcomes or not precios:
        return None

    mejor_prob    = 0.0
    mejor_outcome = None

    for outcome, precio_str in zip(outcomes, precios):
        try:
            prob = float(precio_str)
            if prob >= PROB_MIN and prob > mejor_prob:
                mejor_prob    = prob
                mejor_outcome = outcome
        except:
            continue

    if mejor_prob < PROB_MIN:
        return None

    precio_op      = mejor_prob
    retorno_pct    = round((1 - precio_op) / precio_op * 100, 2)
    retorno_anual  = round(retorno_pct / horas * 8760, 0)  # anualizado
    urgencia       = (mejor_prob - 0.95) / max(horas, 0.1)  # score de prioridad
    confianza      = "ALTA" if mejor_prob >= 0.97 else "MEDIA"
    mercado_id     = f"nr_{pregunta[:30].replace(' ','_')}_{mejor_outcome}"

    return {
        "id":                    mercado_id,
        "pregunta":              pregunta,
        "outcome":               mejor_outcome,
        "precio":                round(precio_op, 4),
        "precio_pct":            round(precio_op * 100, 1),
        "retorno_pct":           retorno_pct,
        "liquidez":              round(liquidez, 0),
        "volumen":               round(volumen, 0),
        "fecha_fin":             fecha_fin[:16] if fecha_fin else "N/A",
        "horas_restantes":       round(horas, 1),
        "retorno_anualizado":    retorno_anual,
        "margen":                round(abs(precio_op - 0.5), 4),
        "score":                 round(urgencia, 6),
        "biases":                ["near_resolution"],
        "bias_score":            0.8,
        "tiene_noticias_gdelt":  False,
        "noticias_gdelt":        [],
        "decision":              "OPORTUNIDAD",
        "analizado":             True,
        "urgente":               horas < 6,
        "ultima_vez_analizado":  datetime.now(),
        "decision_investigador": "APOSTAR",
        "confianza":             confianza,
        "probabilidad_claudio":  1.0,   # Mercado cerca de resolver YES — fair value = 100%
        "edge_calculado":        round(1.0 - precio_op, 4),
        "metodo_analisis":       "NearResolution",
        "razonamiento": (
            f"{mejor_outcome} {round(mejor_prob*100,1)}% | "
            f"{round(horas,1)}h restantes | "
            f"retorno {retorno_pct}% ({retorno_anual:,.0f}% anual)"
        ),
    }


def correr():
    addlog("[NearRes] Agente iniciado — mercados 95%+ cerca de resolución | ciclo 5min", "info")
    time.sleep(20)  # Dejar que otros agentes arranquen primero

    while estado["corriendo"]:
        try:
            addlog("[NearRes] Escaneando mercados near-resolution...")

            mercados_raw = []
            for offset in [0, 500]:
                r = requests.get(f"{GAMMA_URL}/markets", params={
                    "active": "true", "closed": "false", "limit": 500, "offset": offset, "order": "volume24hr", "ascending": "false"
                }, timeout=15)
                batch = r.json()
                mercados_raw.extend(batch)
                if len(batch) < 500:
                    break

            encontrados = []
            for m in mercados_raw:
                resultado = analizar(m)
                if resultado:
                    encontrados.append(resultado)

            # Actualizar estado — reemplazar los mercados nr_ anteriores
            import core.estado as _estado_mod
            from core.estado import _lock
            with _lock:
                otros = [m for m in _estado_mod.estado["mercados"]
                         if not m["id"].startswith("nr_")]
                _estado_mod.estado["mercados"] = otros + encontrados

            # Guardar en DB
            for o in encontrados:
                guardar_mercado(o["id"], o["pregunta"], o["fecha_fin"])
                guardar_analisis(
                    o["id"], o["precio"], o["probabilidad_claudio"],
                    o["margen"], [], o["decision_investigador"], o["razonamiento"]
                )

            if encontrados:
                # Ordenar por urgencia
                top = sorted(encontrados, key=lambda x: x["score"], reverse=True)[:3]
                addlog(
                    f"[NearRes] {len(encontrados)} oportunidades | "
                    f"mejor: {round(max(o['probabilidad_claudio'] for o in encontrados)*100,1)}%",
                    "win"
                )
                for o in top:
                    addlog(
                        f"[NearRes] {o['pregunta'][:50]}... "
                        f"| {o['outcome']} {o['precio_pct']}% "
                        f"| {o['horas_restantes']}h | +{o['retorno_pct']}%",
                        "win"
                    )
            else:
                addlog("[NearRes] Sin mercados near-resolution en este ciclo")

        except Exception as e:
            addlog(f"[NearRes] Error: {e}", "error")

        for _ in range(INTERVALO_SEG):
            if not estado["corriendo"]:
                return
            time.sleep(1)
