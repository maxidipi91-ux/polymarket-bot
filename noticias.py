import requests
from datetime import datetime

NEWS_API_KEY = "263a0bcac56a45a599a87b0f316ad81a"
NEWS_URL = "https://newsapi.org/v2/everything"

def buscar_noticias(query, max_resultados=5):
    try:
        params = {
            "q": query,
            "apiKey": NEWS_API_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_resultados
        }
        response = requests.get(NEWS_URL, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "ok":
            return []
        
        noticias = []
        for art in data.get("articles", []):
            noticias.append({
                "titulo": art.get("title"),
                "fuente": art.get("source", {}).get("name"),
                "fecha": art.get("publishedAt"),
                "descripcion": art.get("description")
            })
        return noticias
    except Exception as e:
        print(f"Error buscando noticias: {e}")
        return []

def resumir_noticias(noticias):
    if not noticias:
        return "Sin noticias recientes."
    resumen = ""
    for n in noticias:
        resumen += f"- {n['titulo']} ({n['fuente']})\n"
    return resumen

if __name__ == "__main__":
    print("Buscando noticias de prueba...")
    noticias = buscar_noticias("Harvey Weinstein sentence")
    print(resumir_noticias(noticias))