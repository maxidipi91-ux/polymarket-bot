# Claudio — Pendientes (actualizado 06/04/2026)

## ✅ Completado hoy

### Arquitectura
- Arquitectura modular de 10 agentes funcionando
- Monitor v2 — filtro 15% precio, liquidez $5K, máx 60 días, biases, GDELT, triggers
- Investigador v2 — Ollama/Mistral, caché 2h, GDELT+NewsAPI, prompt calibrado
- Trader v2 — Kelly corregido (cap 20%), edge mínimo 8%, sin confianza BAJA
- Agente Salida — take profit 15%, stop loss 10%, max 48h
- Agente Cripto — BTC/ETH/SOL vs Binance/CoinGecko cada 60s
- Agente Clima — Open-Meteo vs Polymarket cada 10 min
- Agente Whale — escanea top wallets, detecta clusters
- Agente Arbitraje — spread YES+NO < 100%, inconsistencias lógicas
- Agente autoDream — consolida memoria con Mistral cuando está idle
- Telegram bidireccional — comandos + alertas desde el celular
- Behavioral biases — round numbers, stale market, weekend gap, cascade overshoot
- Progressive context loading — Nivel 1 rápido, Nivel 2 Mistral solo cuando vale
- Trigger system — price dislocation y volume spike
- Kelly Criterion con validaciones estrictas
- Caché de análisis 2 horas

---

## 🔴 Prioritario — antes de dinero real

### 1. Corregir edge de Mistral
El edge que reporta Mistral es absurdo (-2550%, 150%). Hay que ignorarlo completamente
y usar solo el cálculo interno del Trader (probabilidad_claudio - precio).
Fix: en investigador.py, calcular edge siempre como `prob - precio_mercado`, ignorar
el campo "edge" que devuelve Mistral.

### 2. Validación en simulación 2-3 semanas
Mínimo 50-100 operaciones con winrate >55% sostenido antes de conectar dinero real.
Actualmente: 2 operaciones, winrate 100% (muy temprano para concluir nada).

### 3. Estrategia de salida real vía CLOB API
El Agente de Salida simula las salidas pero no ejecuta ventas reales.
Necesita conectar con py-clob-client para vender tokens YES/NO antes del vencimiento.
Requiere wallet conectada con private key.

### 4. Wallet real conectada
Conectar USDC real con montos pequeños ($50-100) una vez validada la simulación.
Necesita: private key de wallet Polygon, fondos en USDC, allowances configurados.

---

## 🟡 Importante — próximas sesiones

### 5. Deploy en VPS
Digital Ocean droplet $6/mes — servidor en EEUU, sin VPN, 24/7.
El código ya está listo. Solo falta configurar el servidor y hacer deploy.
Pasos: crear droplet, instalar Python + Ollama, copiar código, configurar systemd.

### 6. Claude Code en Windows
Instalar Claude Code para modificar el proyecto directamente desde la terminal.
Requiere: Git para Windows + plan Pro ($20/mes — ya incluido).
```
Invoke-WebRequest -Uri "https://claude.ai/install.ps1" -UseBasicParsing | Invoke-Expression
```

### 7. CLAUDE.md — contexto permanente
Crear archivo CLAUDE.md en C:\polymarket-bot con arquitectura completa de Claudio.
Así Claude Code ya sabe todo al arrancar sin explicar nada.

### 8. claude-mem — memoria persistente entre sesiones
Plugin que captura todo lo que hace Claude Code y lo inyecta en sesiones futuras.
```
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem
```

### 9. Fix edge de Mistral
El campo "edge" que devuelve Mistral es inútil — a veces -2550%, a veces 150%.
Eliminarlo del prompt y calcularlo siempre internamente.

### 10. Agente Debugger
Revisa logs diarios, detecta errores repetidos y los reporta por Telegram.
Especialmente útil para detectar cuando Ollama se cuelga o la VPN se cae.

### 11. Agente Healthcheck
Verifica que todos los agentes estén corriendo cada 5 minutos.
El watchdog actual relanza agentes caídos pero no notifica por Telegram.

### 12. Agente Backup
Respalda la DB automáticamente cada 24 horas.
Si se rompe el disco, Claudio no pierde meses de aprendizaje.

### 13. Sistema de alertas de riesgo
Si Claudio pierde más de X% en un día, se detiene y avisa por Telegram.
Actualmente no hay límite de pérdida diaria.

### 14. Respuestas de Telegram con IA
Que Mistral genere las respuestas en primera persona con personalidad.
En vez de templates fijos, Claudio responde como si fuera él hablando.

---

## 🟢 A futuro — cuando haya resultados

### 15. Agente Evaluador (quality gate PASS/REVISE/REJECT)
Evalúa estrategias con 8 criterios antes de escalar a dinero real:
edge plausibility, overfitting risk, sample adequacy, regime dependency,
exit calibration, risk concentration, execution realism, invalidation quality.

### 16. Agente Entrenador
Reentrena el modelo cada semana con datos reales de Claudio.

### 17. Agente Estratega
Sugiere ajustes a la estrategia según rendimiento histórico.

### 18. Memoria con vector database
ChromaDB o FAISS para que Claudio busque patrones en su propio historial.
Actualmente usa SQLite que no permite búsqueda semántica.

### 19. Dashboard móvil optimizado
La web actual no está optimizada para celular.
Claudio tiene que verse bien y controlarse desde iPhone.

### 20. Historial de rendimiento exportable
Exportar todas las operaciones a Excel/PDF para análisis externo.

### 21. Multi-wallet
Operar con más de una wallet para distribuir riesgo.

### 22. Estrategias paralelas con capital independiente
Clima, copy trading, arbitraje y momentum cada una con su propio capital.
Si una falla no afecta a las otras.

### 23. Integración X/Twitter via MCP
Monitorear tweets en tiempo real usando cuenta existente, sin pagar API.

### 24. GDELT funcional
GDELT está bloqueado en el entorno actual (403 Forbidden).
En el VPS debería funcionar sin restricciones — testear al hacer deploy.

### 25. Superpowers plugin (Claude Code)
Fuerza a Claude Code a pensar antes de codear — TDD, brainstorming, debugging estructurado.
```
/plugin marketplace add obra/superpowers
/plugin install superpowers
```

### 26. Compound Engineering plugin (Claude Code)
Planificación antes de todo — genera plan.md antes de tocar código.
```
/plugin marketplace add EveryInc/compound-engineering-plugin
/plugin install compound-engineering
```

---

## Stack actual (06/04/2026)
- Python 3.12
- Flask (dashboard)
- SQLite (base de datos)
- Ollama + Mistral 7B (análisis local)
- NewsAPI (noticias en inglés)
- Open-Meteo (pronósticos clima, gratis)
- CoinGecko/Binance (precios cripto)
- Telegram Bot API (comunicación)
- Windscribe VPN (acceso desde Argentina)

## Stack próximo
- VPS Digital Ocean $6/mes (producción 24/7)
- GDELT API v2 (noticias 65 idiomas — pendiente testear en VPS)
- py-clob-client con wallet real (ventas reales)
- ChromaDB (memoria semántica)
- Claude Code + plugins (desarrollo más eficiente)
