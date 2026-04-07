"""
agentes/clima.py — Agente Clima
Estrategia: comparar pronóstico meteorológico oficial vs precio de Polymarket.
La más predecible y menos competida de las estrategias.
Referencia: bot que hizo $300 → $101K en 2 meses con esta estrategia.

Fuentes: Open-Meteo (gratis, sin API key), WeatherAPI
"""

import time
import requests
import json
from datetime import datetime, timedelta
from core.estado import estado, addlog, insertar_mercado

GAMMA_URL       = "https://gamma-api.polymarket.com"
OPENMETEO_URL   = "https://api.open-meteo.com/v1/forecast"
INTERVALO       = 600  # Revisa cada 10 minutos

# Keywords para detectar mercados de clima en Polymarket
CLIMA_KEYWORDS  = ["temperature", "rain", "snow", "storm", "hurricane", "flood",
                   "weather", "celsius", "fahrenheit", "precipitation",
                   "tornado", "wildfire", "drought", "heat wave"]

# Ciudades principales con coordenadas para Open-Meteo
CIUDADES = {
    "new york":    (40.71, -74.01),
    "los angeles": (34.05, -118.24),
    "chicago":     (41.88, -87.63),
    "miami":       (25.77, -80.19),
    "london":      (51.51, -0.13),
    "paris":       (48.85, 2.35),
    "tokyo":       (35.68, 139.69),
    "sydney":      (-33.87, 151.21),
    "dubai":       (25.20, 55.27),
    "texas":       (31.97, -99.90),
    "florida":     (27.99, -81.76),
    "california":  (36.78, -119.42),
}


def obtener_pronostico(lat, lon, dias=7):
    """
    Obtiene pronóstico de Open-Meteo (gratis, sin API key).
    Retorna temperatura máx, mín, precipitación y código de clima.
    """
    try:
        params = {
            "latitude":   lat,
            "longitude":  lon,
            "daily":      "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "timezone":   "auto",
            "forecast_days": dias
        }
        r = requests.get(OPENMETEO_URL, params=params, timeout=10)
        data = r.json()
        daily = data.get("daily", {})
        return {
            "fechas":       daily.get("time", []),
            "temp_max":     daily.get("temperature_2m_max", []),
            "temp_min":     daily.get("temperature_2m_min", []),
            "precipitacion": daily.get("precipitation_sum", []),
            "weathercode":  daily.get("weathercode", []),
        }
    except Exception as e:
        addlog(f"[Clima] Error Open-Meteo: {e}", "error")
        return None


def obtener_mercados_clima():
    """Obtiene mercados de clima de Polymarket."""
    try:
        params = {"active": "true", "closed": "false", "limit": 500}
        r = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=15)
        mercados = r.json()
        clima = []
        for m in mercados:
            pregunta = m.get("question", "").lower()
            liquidez = float(m.get("liquidity", 0) or 0)
            if any(k in pregunta for k in CLIMA_KEYWORDS) and liquidez > 1000:
                clima.append(m)
        return clima
    except Exception as e:
        addlog(f"[Clima] Error obteniendo mercados: {e}", "error")
        return []


def detectar_ciudad(pregunta):
    """Detecta qué ciudad menciona la pregunta."""
    pregunta = pregunta.lower()
    for ciudad, coords in CIUDADES.items():
        if ciudad in pregunta:
            return ciudad, coords
    return None, None


def analizar_mercado_clima(mercado, pronosticos_cache):
    """
    Compara el pronóstico oficial con el precio del mercado.
    Si el mercado dice 30% de lluvia pero el pronóstico dice 80%... oportunidad.
    """
    pregunta = mercado.get("question", "")
    ciudad, coords = detectar_ciudad(pregunta)
    if not ciudad:
        return None

    # Obtener pronóstico (con cache)
    if ciudad not in pronosticos_cache:
        pronostico = obtener_pronostico(*coords)
        if pronostico:
            pronosticos_cache[ciudad] = pronostico
        else:
            return None
    else:
        pronostico = pronosticos_cache[ciudad]

    # Analizar el tipo de pregunta
    pregunta_lower = pregunta.lower()
    prob_real = None

    # Temperatura por encima de X grados
    if "above" in pregunta_lower or "exceed" in pregunta_lower or "over" in pregunta_lower:
        import re
        numeros = re.findall(r'(\d+(?:\.\d+)?)\s*(?:°|degrees|celsius|fahrenheit|°f|°c)', pregunta_lower)
        if numeros and pronostico["temp_max"]:
            temp_objetivo = float(numeros[0])
            # Convertir F a C si necesario
            if "fahrenheit" in pregunta_lower or "°f" in pregunta_lower:
                temp_objetivo = (temp_objetivo - 32) * 5/9
            # Días que superan la temperatura objetivo
            dias_sobre = sum(1 for t in pronostico["temp_max"][:7] if t and t > temp_objetivo)
            prob_real = dias_sobre / min(7, len(pronostico["temp_max"]))

    # Precipitación / lluvia
    elif any(k in pregunta_lower for k in ["rain", "precipitation", "snow"]):
        if pronostico["precipitacion"]:
            dias_lluvia = sum(1 for p in pronostico["precipitacion"][:7] if p and p > 1)
            prob_real = dias_lluvia / min(7, len(pronostico["precipitacion"]))

    if prob_real is None:
        return None

    # Obtener precio del mercado para YES
    precios_poly = mercado.get("outcomePrices", "[]")
    outcomes_poly = mercado.get("outcomes", "[]")
    if isinstance(precios_poly, str):
        precios_poly = json.loads(precios_poly)
    if isinstance(outcomes_poly, str):
        outcomes_poly = json.loads(outcomes_poly)

    precio_yes = None
    for o, p in zip(outcomes_poly, precios_poly):
        if o == "Yes":
            precio_yes = float(p)
            break

    if not precio_yes:
        return None

    edge = prob_real - precio_yes

    return {
        "pregunta":       pregunta,
        "ciudad":         ciudad,
        "prob_real":      round(prob_real, 3),
        "precio_poly":    round(precio_yes, 3),
        "edge":           round(edge, 3),
        "liquidez":       float(mercado.get("liquidity", 0) or 0),
        "fecha_fin":      mercado.get("endDate", "")[:10],
        "pronostico":     f"temp_max_7d: {pronostico['temp_max'][:3]}, precip: {pronostico['precipitacion'][:3]}",
    }


def correr():
    """Loop principal del agente Clima."""
    addlog("[Clima] Iniciado — Open-Meteo vs Polymarket cada 10 min", "info")
    time.sleep(45)
    pronosticos_cache = {}
    ultimo_reset_cache = datetime.now()

    while estado["corriendo"]:
        try:
            # Resetear cache cada 3 horas (pronósticos cambian)
            if (datetime.now() - ultimo_reset_cache).seconds > 10800:
                pronosticos_cache = {}
                ultimo_reset_cache = datetime.now()

            mercados_clima = obtener_mercados_clima()
            if not mercados_clima:
                addlog("[Clima] Sin mercados de clima activos", "info")
            else:
                addlog(f"[Clima] Analizando {len(mercados_clima)} mercados de clima...")
                oportunidades = []

                for m in mercados_clima:
                    resultado = analizar_mercado_clima(m, pronosticos_cache)
                    if resultado and abs(resultado["edge"]) > 0.10:
                        oportunidades.append(resultado)

                oportunidades.sort(key=lambda x: abs(x["edge"]), reverse=True)

                if oportunidades:
                    for op in oportunidades[:3]:
                        addlog(
                            f"[Clima] 🌦️ {op['ciudad'].title()}: "
                            f"prob_real={round(op['prob_real']*100,0)}% vs "
                            f"poly={round(op['precio_poly']*100,0)}% | "
                            f"edge={round(op['edge']*100,1)}%",
                            "win"
                        )
                        # Agregar al estado para que el Trader lo ejecute
                        mercado_formato = {
                            "id":                   f"clima_{op['pregunta'][:30]}_Yes",
                            "pregunta":             op["pregunta"],
                            "outcome":              "Yes",
                            "precio":               op["precio_poly"],
                            "precio_pct":           round(op["precio_poly"] * 100, 1),
                            "retorno_pct":          round((1 - op["precio_poly"]) / op["precio_poly"] * 100, 0),
                            "liquidez":             op["liquidez"],
                            "volumen":              0,
                            "fecha_fin":            op["fecha_fin"],
                            "margen":               abs(op["precio_poly"] - 0.5),
                            "score":                abs(op["edge"]),
                            "biases":               ["weather_model_lag"],
                            "bias_score":           0.25,
                            "tiene_noticias_gdelt": False,
                            "noticias_gdelt":       [],
                            "decision":             "OPORTUNIDAD",
                            "analizado":            True,
                            "urgente":              abs(op["edge"]) > 0.20,
                            "ultima_vez_analizado": datetime.now(),
                            "probabilidad_claudio":  op["prob_real"],
                            "decision_investigador": "APOSTAR",
                            "confianza":            "ALTA" if abs(op["edge"]) > 0.20 else "MEDIA",
                            "razonamiento":         f"Pronóstico oficial: {round(op['prob_real']*100,0)}% vs mercado: {round(op['precio_poly']*100,0)}%. {op['pronostico']}",
                            "edge_calculado":       op["edge"],
                            "metodo_analisis":      "Open-Meteo/Clima",
                        }
                        insertar_mercado(mercado_formato)
                else:
                    addlog("[Clima] Sin oportunidades de clima detectadas")

        except Exception as e:
            addlog(f"[Clima] Error: {e}", "error")

        for _ in range(INTERVALO):
            if not estado["corriendo"]: return
            time.sleep(1)
