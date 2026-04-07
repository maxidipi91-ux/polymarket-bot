"""
agentes/arbitraje.py — Agente Arbitraje v2 (agente principal)
Estrategia: encontrar ineficiencias de precio y explotarlas en minutos.

Tres tipos de arbitraje, en orden de prioridad:

TIPO 1 — Spread garantizado (mejor):
  YES + NO < $0.98 → comprar ambos lados → ganancia garantizada sin importar el resultado
  Ejemplo: YES=0.45, NO=0.52 → suma=0.97 → comprar ambos → garantiza $0.03 por $1 apostado
  Ganancia: ~3% garantizada, sin riesgo

TIPO 2 — Inconsistencia lógica:
  "Trump gana" al 60% pero "Republicano gana" al 45% → imposible matemáticamente
  El evento A implica el evento B, pero B tiene menor precio que A

TIPO 3 — Mercados nicho con pricing stale:
  Mercados con poca liquidez (<$5K) donde el precio no se actualizó
  con información reciente → mayor probabilidad de ineficiencia

Ciclo: 60 segundos (no 10 minutos)
Cuando encuentra oportunidad: ejecuta INMEDIATAMENTE
"""

import time
import requests
import json
from datetime import datetime, timedelta
from core.estado import estado, addlog, insertar_mercado

GAMMA_URL  = "https://gamma-api.polymarket.com"
INTERVALO  = 60   # Ciclo rápido de 60 segundos

# Umbrales
# Polymarket cobra ~1% de fee por lado → 2% ida+vuelta.
# El spread mínimo debe cubrir esos fees con margen real.
# Con SPREAD_MIN=0.02 el arbitraje puede ser negativo neto — subimos a 0.05.
SPREAD_MIN          = 0.05   # Mínimo 5% de ganancia garantizada para Tipo 1 (neto de fees ~3%)
EDGE_LOGICO_MIN     = 0.08   # Mínimo 8% de inconsistencia lógica para Tipo 2
LIQUIDEZ_NICHO_MAX  = 5000   # Mercados nicho: menos de $5K liquidez
LIQUIDEZ_ARBI_MIN   = 1000   # Mínimo $1K para que valga ejecutar arbitraje


def parsear_mercado(m):
    """Extrae datos relevantes de un mercado de forma segura."""
    try:
        pregunta  = m.get("question", "")
        liquidez  = float(m.get("liquidity", 0) or 0)
        volumen   = float(m.get("volume", 0) or 0)
        fecha_fin = m.get("endDate", "")[:10] if m.get("endDate") else "N/A"

        precios  = m.get("outcomePrices", "[]")
        outcomes = m.get("outcomes", "[]")
        if isinstance(precios, str):  precios  = json.loads(precios)
        if isinstance(outcomes, str): outcomes = json.loads(outcomes)

        precio_yes = precio_no = None
        for o, p in zip(outcomes, precios):
            try:
                if o == "Yes":  precio_yes = float(p)
                elif o == "No": precio_no  = float(p)
            except:
                continue

        return {
            "id":         m.get("id", ""),
            "conditionId": m.get("conditionId", ""),
            "pregunta":   pregunta,
            "precio_yes": precio_yes,
            "precio_no":  precio_no,
            "liquidez":   liquidez,
            "volumen":    volumen,
            "fecha_fin":  fecha_fin,
        }
    except:
        return None


def obtener_mercados():
    """Obtiene todos los mercados activos."""
    try:
        params = {"active": "true", "closed": "false", "limit": 500}
        r = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=15)
        return r.json()
    except Exception as e:
        addlog(f"[Arbitraje] Error obteniendo mercados: {e}", "error")
        return []


# ─── TIPO 1: Spread garantizado ───────────────────────────────────────────────

def buscar_spread_garantizado(mercados):
    """
    Busca mercados donde YES + NO < 0.98.
    Ganancia garantizada = 1 - (YES + NO).
    """
    oportunidades = []
    for m in mercados:
        if not m or not m["precio_yes"] or not m["precio_no"]:
            continue
        if m["liquidez"] < LIQUIDEZ_ARBI_MIN:
            continue

        suma = m["precio_yes"] + m["precio_no"]
        spread = 1 - suma

        if spread >= SPREAD_MIN:
            oportunidades.append({
                "tipo":     "spread_garantizado",
                "mercado":  m,
                "suma":     round(suma, 4),
                "spread":   round(spread, 4),
                "ganancia_pct": round(spread * 100, 2),
                "prioridad": spread,  # Más spread = más prioritario
            })

    oportunidades.sort(key=lambda x: x["prioridad"], reverse=True)
    return oportunidades


# ─── TIPO 2: Inconsistencia lógica ───────────────────────────────────────────

def buscar_inconsistencias_logicas(mercados):
    """
    Busca pares de mercados donde los precios son lógicamente inconsistentes.
    Ejemplo: si A implica B, entonces P(A) <= P(B).
    Si P(A) > P(B) + umbral, hay una oportunidad.
    """
    import re
    oportunidades = []

    # Agrupar mercados por tema (primeras 3 palabras de la pregunta)
    grupos = {}
    for m in mercados:
        if not m or not m["precio_yes"]: continue
        palabras = m["pregunta"].lower().split()[:4]
        clave = " ".join(palabras[:3])
        if clave not in grupos:
            grupos[clave] = []
        grupos[clave].append(m)

    for clave, grupo in grupos.items():
        if len(grupo) < 2: continue

        for i, m1 in enumerate(grupo):
            for m2 in grupo[i+1:]:
                try:
                    p1 = m1["precio_yes"]
                    p2 = m2["precio_yes"]
                    if not p1 or not p2: continue

                    # Extraer números de las preguntas (umbrales)
                    nums1 = [float(n.replace(",","")) for n in re.findall(r'[\d,]+(?:\.\d+)?', m1["pregunta"]) if float(n.replace(",","")) > 10]
                    nums2 = [float(n.replace(",","")) for n in re.findall(r'[\d,]+(?:\.\d+)?', m2["pregunta"]) if float(n.replace(",","")) > 10]

                    if nums1 and nums2:
                        n1, n2 = nums1[0], nums2[0]
                        # Si m1 tiene umbral más bajo que m2 y ambos son "above",
                        # entonces P(m1) >= P(m2) — si no, inconsistencia
                        if ("above" in m1["pregunta"].lower() and
                            "above" in m2["pregunta"].lower() and
                            n1 < n2 and p1 < p2 - EDGE_LOGICO_MIN):

                            edge = p2 - p1
                            oportunidades.append({
                                "tipo":     "inconsistencia_logica",
                                "mercado":  m1,  # El que debería tener precio más alto
                                "mercado2": m2,
                                "edge":     round(edge, 4),
                                "ganancia_pct": round(edge * 100, 2),
                                "prioridad": edge,
                                "explicacion": f"Umbral {n1} < {n2} pero precio {round(p1*100,1)}% < {round(p2*100,1)}%"
                            })
                except:
                    continue

    oportunidades.sort(key=lambda x: x["prioridad"], reverse=True)
    return oportunidades


# ─── TIPO 3: Mercados nicho con precio stale ──────────────────────────────────

def buscar_nichos_stale(mercados):
    """
    Mercados con poca liquidez donde el precio probablemente no se actualizó.
    Son los más ineficientes — menos bots los miran.
    """
    nichos = []
    for m in mercados:
        if not m or not m["precio_yes"]: continue
        if m["liquidez"] > LIQUIDEZ_NICHO_MAX: continue
        if m["liquidez"] < 500: continue

        precio = m["precio_yes"]

        # Filtro de precio — igual que el Trader (15%-85%)
        if precio < 0.15 or precio > 0.85:
            continue

        margen = abs(precio - 0.5)
        if margen > 0.10:
            nichos.append({
                "tipo":        "nicho_stale",
                "mercado":     m,
                "margen":      round(margen, 4),
                "ganancia_pct": round(margen * 100, 2),
                "prioridad":   margen / (m["liquidez"] / 1000),
            })

    nichos.sort(key=lambda x: x["prioridad"], reverse=True)
    return nichos[:5]


# ─── Agregar al estado para que el Trader ejecute ────────────────────────────

def registrar_oportunidad(op):
    """Convierte una oportunidad de arbitraje en formato mercado para el Trader."""
    m = op["mercado"]

    # Para spread garantizado, registrar ambos lados
    if op["tipo"] == "spread_garantizado":
        for outcome, precio in [("Yes", m["precio_yes"]), ("No", m["precio_no"])]:
            mercado_fmt = {
                "id":                   f"arb_{op['tipo']}_{m['id'][:20]}_{outcome}",
                "pregunta":             m["pregunta"],
                "outcome":              outcome,
                "precio":               precio,
                "precio_pct":           round(precio * 100, 1),
                "retorno_pct":          round((1 - precio) / precio * 100, 0),
                "liquidez":             m["liquidez"],
                "volumen":              m["volumen"],
                "fecha_fin":            m["fecha_fin"],
                "margen":               abs(precio - 0.5),
                "score":                op["prioridad"],
                "biases":               [op["tipo"]],
                "bias_score":           0.5,
                "tiene_noticias_gdelt": False,
                "noticias_gdelt":       [],
                "decision":             "OPORTUNIDAD",
                "analizado":            True,
                "urgente":              op["spread"] > 0.03,
                "ultima_vez_analizado": datetime.now(),
                "probabilidad_claudio": 0.99,  # Spread garantizado = certeza
                "decision_investigador": "APOSTAR",
                "confianza":            "ALTA",
                "razonamiento":         f"Spread garantizado: YES+NO={round(m['precio_yes']+m['precio_no'],3)}. Ganancia: {op['ganancia_pct']}%",
                "edge_calculado":       op["spread"] / 2,
                "metodo_analisis":      "Arbitraje/Spread",
            }
            insertar_mercado(mercado_fmt)

    elif op["tipo"] in ["inconsistencia_logica", "nicho_stale"]:
        precio = m["precio_yes"]
        mercado_fmt = {
            "id":                   f"arb_{op['tipo']}_{m['id'][:20]}_Yes",
            "pregunta":             m["pregunta"],
            "outcome":              "Yes",
            "precio":               precio,
            "precio_pct":           round(precio * 100, 1),
            "retorno_pct":          round((1 - precio) / precio * 100, 0),
            "liquidez":             m["liquidez"],
            "volumen":              m["volumen"],
            "fecha_fin":            m["fecha_fin"],
            "margen":               abs(precio - 0.5),
            "score":                op["prioridad"],
            "biases":               [op["tipo"]],
            "bias_score":           0.4,
            "tiene_noticias_gdelt": False,
            "noticias_gdelt":       [],
            "decision":             "OPORTUNIDAD",
            "analizado":            True,
            "urgente":              op.get("edge", op.get("margen", 0)) > 0.15,
            "ultima_vez_analizado": datetime.now(),
            "probabilidad_claudio": min(0.85, precio + op.get("edge", op.get("margen", 0.1))),
            "decision_investigador": "APOSTAR",
            "confianza":            "ALTA" if op["ganancia_pct"] > 15 else "MEDIA",
            "razonamiento":         op.get("explicacion", f"Mercado nicho: margen={op['ganancia_pct']}%"),
            "edge_calculado":       op.get("edge", op.get("margen", 0)),
            "metodo_analisis":      f"Arbitraje/{op['tipo']}",
        }
        insertar_mercado(mercado_fmt)


# ─── Loop principal ──────────────────────────────────────────────────────────

def correr():
    addlog("[Arbitraje] v2 iniciado — spread garantizado + lógica + nichos | ciclo 60s", "info")
    time.sleep(30)

    while estado["corriendo"]:
        try:
            addlog("[Arbitraje] Escaneando ineficiencias...")
            mercados_raw = obtener_mercados()
            mercados     = [parsear_mercado(m) for m in mercados_raw]
            mercados     = [m for m in mercados if m]

            # TIPO 1 — Spread garantizado (prioridad máxima)
            spreads = buscar_spread_garantizado(mercados)
            if spreads:
                addlog(f"[Arbitraje] SPREAD: {len(spreads)} spreads garantizados!", "win")
                for op in spreads[:3]:
                    m = op["mercado"]
                    addlog(
                        f"[Arbitraje] SPREAD: {m['pregunta'][:45]}... | "
                        f"YES={round(m['precio_yes']*100,1)}% + NO={round(m['precio_no']*100,1)}% = "
                        f"{round(op['suma']*100,1)}% | ganancia garantizada: {op['ganancia_pct']}%",
                        "win"
                    )
                    registrar_oportunidad(op)
            else:
                addlog("[Arbitraje] Sin spreads garantizados")

            # TIPO 2 — Inconsistencias lógicas
            inconsistencias = buscar_inconsistencias_logicas(mercados)
            if inconsistencias:
                addlog(f"[Arbitraje] LOGICA: {len(inconsistencias)} inconsistencias logicas!", "win")
                for op in inconsistencias[:2]:
                    addlog(
                        f"[Arbitraje] LÓGICA: {op.get('explicacion', '')} | "
                        f"edge={op['ganancia_pct']}%",
                        "win"
                    )
                    registrar_oportunidad(op)

            # TIPO 3 — Nichos stale (con filtro LLM)
            nichos = buscar_nichos_stale(mercados)
            if nichos:
                addlog(f"[Arbitraje] NICHO: {len(nichos)} mercados nicho con precio posiblemente stale")
                from core.llm import analizar_nicho
                for op in nichos[:2]:
                    m = op["mercado"]
                    decision, razon, noticias = analizar_nicho(m["pregunta"], m["precio_yes"])

                    if decision == "SKIP":
                        addlog(
                            f"[Arbitraje] NICHO DESCARTADO por LLM: {m['pregunta'][:40]}... | {razon}",
                            "info"
                        )
                        continue

                    if decision == "ESPERAR":
                        addlog(
                            f"[Arbitraje] NICHO EN ESPERA: {m['pregunta'][:40]}... | {razon}",
                            "info"
                        )
                        continue

                    # APOSTAR o FALLBACK — pasa al Trader
                    if noticias:
                        op["razonamiento_llm"] = razon
                        op["noticias"]         = noticias
                        if decision == "APOSTAR":
                            op["confianza_llm"] = "ALTA"
                            addlog(
                                f"[Arbitraje] NICHO CONFIRMADO por LLM: {m['pregunta'][:40]}... | {razon}",
                                "win"
                            )
                        else:
                            addlog(
                                f"[Arbitraje] NICHO: {m['pregunta'][:45]}... | "
                                f"liquidez=${m['liquidez']:,.0f} | margen={op['ganancia_pct']}% (Groq no disponible)"
                            )
                    else:
                        addlog(
                            f"[Arbitraje] NICHO: {m['pregunta'][:45]}... | "
                            f"liquidez=${m['liquidez']:,.0f} | margen={op['ganancia_pct']}%"
                        )
                    registrar_oportunidad(op)

            total = len(spreads) + len(inconsistencias) + len(nichos)
            if total == 0:
                addlog("[Arbitraje] Sin ineficiencias detectadas en este ciclo")

        except Exception as e:
            addlog(f"[Arbitraje] Error: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
