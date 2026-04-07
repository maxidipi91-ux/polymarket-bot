"""
agentes/momentum.py — Volume Spike + PredictIt Comparison

Estrategia 1 — Volume Spike:
  Detecta mercados donde el volumen subió >50% en la última hora sin
  que el precio se moviera. Señal de traders informados acumulando
  posición antes de que el precio se ajuste.

Estrategia 2 — PredictIt vs Polymarket:
  Compara precios de los mismos eventos políticos en ambas plataformas.
  PredictIt es dinero real. Diferencias >10% = arbitraje entre mercados.
  API pública sin auth: predictit.org/api/marketdata/all/

Señal combinada: spike + diferencia PredictIt = confianza ALTA.
"""

import time
import json
import requests
from datetime import datetime
from core.estado import estado, addlog, insertar_mercado
from core.database import guardar_mercado

GAMMA_URL      = "https://gamma-api.polymarket.com"
PREDICTIT_URL  = "https://www.predictit.org/api/marketdata/all/"
INTERVALO      = 300    # 5 minutos

SPIKE_RATIO    = 1.50   # Volumen actual > 1.5x el de hace 1 hora
SPIKE_MIN_VOL  = 500    # Al menos $500 de volumen nuevo
PI_EDGE        = 0.10   # Diferencia mínima con PredictIt (10%)
LIQUIDEZ_MIN   = 1000   # Liquidez mínima en Polymarket

_vol_history   = {}     # mercado_id → [(timestamp, volumen), ...]
_pi_cache      = {"data": None, "ts": 0}
PI_CACHE_TTL   = 300    # Cachear PredictIt 5 min (misma frecuencia que el ciclo)


def parsear_lista(valor):
    if isinstance(valor, list): return valor
    if isinstance(valor, str):
        try: return json.loads(valor)
        except: return []
    return []


# ─── Volume Spike ─────────────────────────────────────────────────────────────

def registrar_volumen(mercados):
    """Guarda snapshot del volumen actual de cada mercado."""
    ahora = time.time()
    ids_activos = {m.get("id", "") for m in mercados}

    # Limpiar keys de mercados que ya no están activos
    for mid in list(_vol_history.keys()):
        if mid not in ids_activos:
            del _vol_history[mid]

    for m in mercados:
        mid = m.get("id", "")
        vol = float(m.get("volume", 0) or 0)
        if mid not in _vol_history:
            _vol_history[mid] = []
        _vol_history[mid].append((ahora, vol))
        _vol_history[mid] = _vol_history[mid][-15:]


def detectar_spikes(mercados):
    """Detecta mercados con volume spike en la última hora."""
    ahora   = time.time()
    hace_1h = ahora - 3600
    spikes  = []

    for m in mercados:
        mid      = m.get("id", "")
        vol_now  = float(m.get("volume", 0) or 0)
        liquidez = float(m.get("liquidity", 0) or 0)

        if liquidez < LIQUIDEZ_MIN:
            continue

        historial    = _vol_history.get(mid, [])
        vol_anterior = None
        for ts, vol in historial:
            if ts <= hace_1h:
                vol_anterior = vol

        if vol_anterior is None or vol_anterior <= 0:
            continue

        ratio     = vol_now / vol_anterior
        vol_nuevo = vol_now - vol_anterior

        if ratio >= SPIKE_RATIO and vol_nuevo >= SPIKE_MIN_VOL:
            spikes.append({
                "mercado":   m,
                "ratio":     round(ratio, 2),
                "vol_nuevo": round(vol_nuevo, 0),
            })

    spikes.sort(key=lambda x: x["ratio"], reverse=True)
    return spikes[:5]


# ─── PredictIt Comparison ─────────────────────────────────────────────────────

def obtener_predictit():
    """
    Descarga todos los mercados de PredictIt (API pública, sin auth).
    Retorna lista de contratos con precios. Cache 5 min.
    """
    ahora = time.time()
    if _pi_cache["data"] and ahora - _pi_cache["ts"] < PI_CACHE_TTL:
        return _pi_cache["data"]
    try:
        r = requests.get(PREDICTIT_URL, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        markets = r.json().get("markets", [])

        # Aplanar: un contrato por fila con su precio
        contratos = []
        for m in markets:
            nombre = m.get("name", "").lower()
            for c in m.get("contracts", []):
                last = c.get("lastTradePrice")
                best_yes = c.get("bestYesBid")
                precio = last or best_yes
                if precio and float(precio) > 0:
                    contratos.append({
                        "nombre":    nombre,
                        "contrato":  c.get("name", "").lower(),
                        "precio":    float(precio),
                        "ticker":    c.get("id"),
                    })

        _pi_cache["data"] = contratos
        _pi_cache["ts"]   = ahora
        addlog(f"[Momentum] PredictIt: {len(contratos)} contratos cargados", "info")
        return contratos
    except Exception as e:
        addlog(f"[Momentum] Error cargando PredictIt: {e}", "error")
        return []


def buscar_en_predictit(pregunta, contratos_pi):
    """
    Busca el contrato más relevante en PredictIt para una pregunta de Polymarket.
    Matching por palabras clave compartidas.
    Retorna precio (0-1) o None si no hay match suficiente.
    """
    palabras = set(pregunta.lower().split())
    # Filtrar stopwords
    stopwords = {"will", "the", "a", "an", "be", "by", "in", "on",
                 "to", "of", "for", "is", "at", "or", "and", "win",
                 "2024", "2025", "2026", "?"}
    palabras -= stopwords

    if len(palabras) < 2:
        return None, None

    mejor_score  = 0
    mejor_precio = None
    mejor_nombre = None

    for c in contratos_pi:
        texto = c["nombre"] + " " + c["contrato"]
        palabras_pi = set(texto.split()) - stopwords
        comunes = len(palabras & palabras_pi)
        score   = comunes / max(len(palabras), 1)

        if score > mejor_score and score >= 0.35:  # al menos 35% de palabras en común
            mejor_score  = score
            mejor_precio = c["precio"]
            mejor_nombre = c["contrato"]

    return mejor_precio, mejor_nombre


# ─── Crear oportunidad para el Trader ────────────────────────────────────────

def crear_op(m_raw, spike=None, pi_precio=None, pi_nombre=None):
    """Convierte señales de momentum en formato para el Trader."""
    pregunta  = m_raw.get("question", "")
    fecha_fin = (m_raw.get("endDate") or "")[:10] or "N/A"
    liquidez  = float(m_raw.get("liquidity", 0) or 0)
    volumen   = float(m_raw.get("volume", 0) or 0)

    outcomes = parsear_lista(m_raw.get("outcomes", []))
    precios  = parsear_lista(m_raw.get("outcomePrices", []))
    precio_yes = None
    for o, p in zip(outcomes, precios):
        if "yes" in o.lower():
            try: precio_yes = float(p)
            except: pass

    if not precio_yes or precio_yes < 0.10 or precio_yes > 0.90:
        return None

    # Calcular edge
    pi_edge = None
    if pi_precio:
        pi_edge = pi_precio - precio_yes

    tiene_spike  = spike is not None
    tiene_pi     = pi_edge and pi_edge > PI_EDGE

    # Necesita al menos una señal fuerte
    if not tiene_spike and not tiene_pi:
        return None

    # Fair value
    if tiene_pi:
        prob = pi_precio
    else:
        prob = min(0.90, precio_yes + 0.08)

    edge = prob - precio_yes
    if edge < 0.05:
        return None

    confianza = "ALTA" if (tiene_spike and tiene_pi) else "MEDIA"

    señales = []
    if tiene_spike:
        señales.append(f"spike x{spike['ratio']} (+${spike['vol_nuevo']:,.0f})")
    if tiene_pi:
        señales.append(
            f"PredictIt {round(pi_precio*100,1)}% vs PM {round(precio_yes*100,1)}%"
            + (f" ({pi_nombre[:30]})" if pi_nombre else "")
        )

    return {
        "id":                    f"mom_{m_raw.get('id','')[:25]}_Yes",
        "pregunta":              pregunta,
        "outcome":               "Yes",
        "precio":                round(precio_yes, 4),
        "precio_pct":            round(precio_yes * 100, 1),
        "retorno_pct":           round((1 - precio_yes) / precio_yes * 100, 1),
        "liquidez":              round(liquidez, 0),
        "volumen":               round(volumen, 0),
        "fecha_fin":             fecha_fin,
        "margen":                round(abs(precio_yes - 0.5), 4),
        "score":                 round(edge, 4),
        "biases":                ["momentum"],
        "bias_score":            0.6,
        "tiene_noticias_gdelt":  False,
        "noticias_gdelt":        [],
        "decision":              "OPORTUNIDAD",
        "analizado":             True,
        "urgente":               edge > 0.15,
        "ultima_vez_analizado":  datetime.now(),
        "decision_investigador": "APOSTAR",
        "confianza":             confianza,
        "probabilidad_claudio":  round(prob, 4),
        "edge_calculado":        round(edge, 4),
        "metodo_analisis":       "Momentum",
        "razonamiento":          " | ".join(señales),
    }


# ─── Loop principal ───────────────────────────────────────────────────────────

def correr():
    addlog("[Momentum] Iniciado — Volume Spike + PredictIt comparison | ciclo 5min", "info")
    time.sleep(60)  # Primer ciclo: solo registrar snapshot base

    while estado["corriendo"]:
        try:
            # Obtener mercados de Polymarket — 2 páginas = hasta 1,000 mercados
            mercados_raw = []
            for offset in [0, 500]:
                r = requests.get(f"{GAMMA_URL}/markets", params={
                    "active": "true", "closed": "false",
                    "limit": 500, "offset": offset, "order": "volume24hr", "ascending": "false"
                }, timeout=15)
                batch = r.json()
                mercados_raw.extend(batch)
                if len(batch) < 500:
                    break  # No hay más páginas

            registrar_volumen(mercados_raw)
            spikes      = detectar_spikes(mercados_raw)
            contratos_pi = obtener_predictit()
            encontrados  = set()
            total_ops    = []

            # Señal 1: Volume spike (+ PredictIt si hay match)
            for spike in spikes:
                m   = spike["mercado"]
                mid = m.get("id", "")
                encontrados.add(mid)

                pi_precio, pi_nombre = buscar_en_predictit(
                    m.get("question", ""), contratos_pi
                )
                op = crear_op(m, spike=spike, pi_precio=pi_precio, pi_nombre=pi_nombre)
                if op:
                    total_ops.append(op)
                    insertar_mercado(op)
                    guardar_mercado(op["id"], op["pregunta"], op["fecha_fin"])
                    tipo = "SPIKE+PREDICTIT" if (pi_precio and pi_precio - float(
                        next((p for o, p in zip(
                            parsear_lista(m.get("outcomes", [])),
                            parsear_lista(m.get("outcomePrices", []))
                        ) if "yes" in o.lower()), 0.5)) > PI_EDGE) else "SPIKE"
                    addlog(
                        f"[Momentum] {tipo}: {m.get('question','')[:45]}... "
                        f"| {op['razonamiento']} | {op['confianza']}",
                        "win"
                    )

            # Señal 2: Solo PredictIt (sin spike necesario) — todos los mercados
            if contratos_pi:
                for m in mercados_raw:
                    mid = m.get("id", "")
                    if mid in encontrados: continue
                    if float(m.get("liquidity", 0) or 0) < LIQUIDEZ_MIN: continue

                    pi_precio, pi_nombre = buscar_en_predictit(
                        m.get("question", ""), contratos_pi
                    )
                    if not pi_precio: continue

                    op = crear_op(m, spike=None, pi_precio=pi_precio, pi_nombre=pi_nombre)
                    if op:
                        total_ops.append(op)
                        insertar_mercado(op)
                        guardar_mercado(op["id"], op["pregunta"], op["fecha_fin"])
                        addlog(
                            f"[Momentum] PREDICTIT: {m.get('question','')[:45]}... "
                            f"| {op['razonamiento']}",
                            "win"
                        )

            if total_ops:
                addlog(
                    f"[Momentum] {len(total_ops)} oportunidades | "
                    f"mejor edge: {round(max(o['edge_calculado'] for o in total_ops)*100,1)}%",
                    "win"
                )
            else:
                n = len(spikes)
                pi_txt = f"{len(contratos_pi)} contratos PI" if contratos_pi else "PI sin datos"
                addlog(f"[Momentum] {n} spikes | {pi_txt} | sin señales suficientes")

        except Exception as e:
            addlog(f"[Momentum] Error: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
