import requests
import json
from datetime import datetime

GAMMA_URL = "https://gamma-api.polymarket.com"

def obtener_mercados(limit=500):
    try:
        params = {"active": "true", "closed": "false", "limit": limit}
        response = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error obteniendo mercados: {e}")
        return []

def parsear_lista(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except:
            return []
    return []

def analizar_oportunidades(mercados):
    resultado = []
    for m in mercados:
        try:
            pregunta = m.get("question", "")
            fecha_fin = m.get("endDate", "")
            volumen = float(m.get("volume", 0) or 0)
            liquidez = float(m.get("liquidity", 0) or 0)
            precios_raw = parsear_lista(m.get("outcomePrices"))
            outcomes_raw = parsear_lista(m.get("outcomes"))

            if not pregunta or not precios_raw or not outcomes_raw:
                continue

            for outcome, precio_str in zip(outcomes_raw, precios_raw):
                precio = float(precio_str)
                if precio <= 0.01 or precio >= 0.99:
                    continue
                resultado.append({
                    "pregunta": pregunta,
                    "outcome": outcome,
                    "precio": precio,
                    "retorno": round((1 - precio) / precio, 2),
                    "volumen": volumen,
                    "liquidez": liquidez,
                    "fecha_fin": fecha_fin[:10] if fecha_fin else "N/A"
                })
        except Exception:
            continue

    resultado.sort(key=lambda x: x["liquidez"])
    return resultado

if __name__ == "__main__":
    print("Conectando con Polymarket...")
    mercados = obtener_mercados()
    print(f"Mercados obtenidos: {len(mercados)}")
    ops = analizar_oportunidades(mercados)
    print(f"Oportunidades encontradas: {len(ops)}")
    for op in ops[:10]:
        print(f"\n{op['pregunta']}")
        print(f"  {op['outcome']} | Precio: {round(op['precio']*100,1)}% | Retorno: +{round(op['retorno']*100,0)}%")
        print(f"  Liquidez: ${op['liquidez']:,.0f} | Vence: {op['fecha_fin']}")