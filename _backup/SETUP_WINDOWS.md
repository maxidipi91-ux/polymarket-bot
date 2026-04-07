# Claudio — Guía de instalación y prueba (Windows)

## 1. Estructura esperada

Descomprimí el ZIP. Deberías tener:

```
C:\polymarket-bot\
├── app.py
├── claudio.py
├── config_loader.py
├── config.json          ← sin credenciales reales
├── .env                 ← VOS creás este archivo (ver paso 2)
├── .env.example         ← plantilla
├── .gitignore
├── agentes\
│   ├── arbitraje.py
│   ├── autodream.py
│   ├── clima.py
│   ├── cripto.py        ← desconectado, no corre
│   ├── debugger.py
│   ├── investigador.py
│   ├── monitor.py
│   ├── salida.py
│   ├── telegram_bot.py
│   ├── trader.py
│   └── whale.py         ← desconectado, no corre
└── core\
    ├── database.py
    └── estado.py
```

---

## 2. Crear el archivo .env con tus credenciales

En `C:\polymarket-bot\` creá un archivo llamado exactamente `.env`
(sin nombre antes del punto — en Windows Explorer activá "extensiones de archivo" si no lo ves).

Contenido:

```
TELEGRAM_TOKEN=tu_token_de_botfather
TELEGRAM_CHAT_ID=tu_chat_id
NEWS_API_KEY=tu_key_de_newsapi
FOOTBALL_DATA_TOKEN=tu_token_football_data
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
RIESGO_POR_OP=10.0
SALDO_INICIAL=1000.0
MODO=simulacion
```

Para crear el archivo desde PowerShell:
```powershell
cd C:\polymarket-bot
notepad .env
```

> Si no tenés las API keys, podés dejar NEWS_API_KEY y FOOTBALL_DATA_TOKEN vacíos.
> El bot funciona en modo degradado usando solo Google News RSS y GDELT (ambos gratis).

---

## 3. Instalar Python y dependencias

### Verificar Python (necesitás 3.10+)
```powershell
python --version
```

### Instalar dependencias
```powershell
cd C:\polymarket-bot
pip install flask requests
```

Eso es todo. El bot no usa pandas, numpy ni nada pesado.

---

## 4. Verificar que Ollama y Mistral estén corriendo

```powershell
# Verificar que Ollama responde
curl http://localhost:11434/api/tags

# Si no está corriendo, iniciarlo
ollama serve

# En otra terminal, verificar que Mistral está descargado
ollama list
```

Deberías ver `mistral` en la lista. Si no:
```powershell
ollama pull mistral
```

---

## 5. Test de smoke antes de correr todo

Abrí PowerShell en `C:\polymarket-bot\` y corré:

```powershell
# Test 1: config_loader carga bien
python -c "from config_loader import CONFIG; print('Ollama URL:', CONFIG['ollama_url']); print('Modo:', CONFIG['modo'])"

# Test 2: estado y funciones thread-safe
python -c "from core.estado import estado, addlog, set_mercados, get_mercados; addlog('test'); print('Estado OK')"

# Test 3: base de datos
python -c "from core.database import init_db; init_db(); print('DB OK')"

# Test 4: conectividad a Polymarket
python -c "
import requests
r = requests.get('https://gamma-api.polymarket.com/markets?limit=3', timeout=10)
print(f'Polymarket: {r.status_code} — {len(r.json())} mercados')
"

# Test 5: Ollama responde
python -c "
import requests
r = requests.get('http://localhost:11434/api/tags', timeout=5)
modelos = [m['name'] for m in r.json().get('models', [])]
print('Modelos disponibles:', modelos)
tiene_mistral = any('mistral' in m for m in modelos)
print('Mistral OK' if tiene_mistral else 'ERROR: Mistral no encontrado')
"
```

Los 5 tests tienen que pasar antes de continuar.

---

## 6. Correr el bot

### Opción A — Solo el dashboard web (recomendado para empezar)
```powershell
cd C:\polymarket-bot
python app.py
```

Abrí el browser en `http://localhost:5000`

Desde ahí podés:
- Ver el dashboard
- Hacer clic en **Iniciar** para arrancar todos los agentes
- Cambiar el riesgo por operación con el slider
- Ver el log en tiempo real

### Opción B — Solo el orquestador sin web
```powershell
python claudio.py
```

---

## 7. Qué mirar en el log los primeros 5 minutos

El orden normal de inicio es:

```
[HH:MM:SS] Claudio iniciando — 2026-04-06 HH:MM
[HH:MM:SS] Modo: simulacion | Saldo inicial: $1000.0 | Riesgo: $10.0
[HH:MM:SS] Agente 'monitor' iniciado
[HH:MM:SS] Agente 'investigador' iniciado
[HH:MM:SS] Agente 'trader' iniciado
[HH:MM:SS] Agente 'salida' iniciado
[HH:MM:SS] Agente 'telegram_bot' iniciado
[HH:MM:SS] Agente 'arbitraje' iniciado
[HH:MM:SS] Agente 'clima' iniciado
[HH:MM:SS] Agente 'autodream' iniciado
[HH:MM:SS] Agente 'debugger' iniciado
[HH:MM:SS] Todos los agentes activos. Claudio operativo.
[HH:MM:SS] [Investigador] Ollama + Mistral ✓         ← importante
[HH:MM:SS] [Monitor] Consultando Polymarket...
[HH:MM:SS] [Monitor] XX mercados · Y con GDELT · Z con biases · ciclo #1
[HH:MM:SS] [Arbitraje] Escaneando ineficiencias...
[HH:MM:SS] [Clima] Analizando X mercados de clima...
```

### Señales de alerta a vigilar

| Log | Qué significa | Solución |
|-----|--------------|----------|
| `[Investigador] Ollama no disponible` | Mistral no responde | Correr `ollama serve` |
| `[Monitor] Error conectando a Polymarket` | Sin acceso a la API | Verificar conexión/VPN |
| `[Telegram] Sin token configurado` | Falta token en .env | Completar .env |
| `[Trader] Saldo insuficiente` | Bug en saldo | Reiniciar el bot |
| `[Arbitraje] X spreads garantizados!` | Oportunidad detectada | Normal, es lo que querés ver |

---

## 8. Primer ciclo completo — qué esperar

**Minuto 0-1:** Todos los agentes arrancan. Monitor hace la primera consulta.

**Minuto 1-5:** Investigador empieza a analizar mercados con Mistral. Cada análisis tarda 10-30 segundos (depende de tu GPU/CPU).

**Minuto 5-10:** Si Mistral encuentra edge real (>8%), el Trader abre la primera posición simulada.

**Hora 1+:** autoDream se activa cuando el bot lleva 30+ min idle.

**Día 1+:** El Agente de Salida empieza a cerrar posiciones por TP/SL con precios reales.

---

## 9. Comandos Telegram para controlar desde el celular

Una vez que el bot arranca, podés controlarlo desde Telegram:

```
/estado    → saldo, P&L, operaciones abiertas
/resumen   → estadísticas totales
/mercados  → top 5 oportunidades actuales
/riesgo 20 → cambiar riesgo por operación a $20
/pausa     → detener el bot
/ayuda     → ver todos los comandos
```

---

## 10. Checklist antes de poner dinero real

No mover a modo real hasta que se cumplan TODAS:

- [ ] 50+ operaciones en simulación
- [ ] Winrate sostenido >55% por al menos 2 semanas
- [ ] El Agente de Salida cierra posiciones correctamente con precios reales
- [ ] Telegram funciona (recibís alertas en el celular)
- [ ] El bot corrió 24h sin caerse (watchdog funciona)
- [ ] Revisaste los logs buscando errores repetidos
- [ ] Wallet Polygon configurada con USDC (máx $100 para empezar)

---

## Problemas frecuentes en Windows

**`ModuleNotFoundError: No module named 'flask'`**
```powershell
pip install flask requests
```

**`FileNotFoundError: config.json`**
Asegurate de correr Python desde `C:\polymarket-bot\`, no desde otro directorio.
```powershell
cd C:\polymarket-bot
python app.py   # no: python C:\polymarket-bot\app.py desde otro lado
```

**`.env` no se carga**
Windows a veces crea el archivo como `.env.txt`. Verificar:
```powershell
dir /a C:\polymarket-bot\.env
```
Si aparece como `.env.txt`, renombrarlo:
```powershell
ren C:\polymarket-bot\.env.txt .env
```

**El puerto 5000 ya está en uso**
```powershell
# Ver qué usa el 5000
netstat -ano | findstr :5000
# Cambiar el puerto en app.py (última línea): port=5001
```
