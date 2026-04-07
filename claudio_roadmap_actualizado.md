# Claudio — Roadmap completo

## Técnico — arquitectura e inteligencia

### 1. Ollama + arquitectura modular de agentes ✅ EN PROGRESO
Instalar Mistral local y construir Claudio como un sistema de agentes modulares donde agregar uno nuevo es tan simple como crear un archivo y registrarlo, sin tocar el código central.

**Agentes core (primera fase):**
- Monitor — detecta oportunidades 24/7
- Investigador — analiza noticias con Ollama
- Trader — ejecuta decisiones
- Telegram — comunicación bidireccional con el usuario

**Agentes de mantenimiento (segunda fase):**
- Debugger — revisa logs diarios, detecta errores y los reporta
- Healthcheck — verifica que todos los agentes estén corriendo
- Backup — respalda la base de datos automáticamente

**Agentes de inteligencia (tercera fase):**
- Clima — especialista en mercados meteorológicos
- Copy trader — sigue a los mejores wallets de Polymarket
- Arbitraje — detecta inconsistencias entre mercados correlacionados
- Sentimiento — analiza Twitter/X en tiempo real
- Trigger — reacciona a eventos en tiempo real (ver punto 28)

**Agentes de aprendizaje (cuarta fase):**
- Evaluador — analiza qué decisiones fueron buenas y cuáles malas
- Entrenador — reentrena el modelo cada semana con datos nuevos
- Estratega — sugiere ajustes a la estrategia según rendimiento

Cada agente es independiente con su propio archivo y memoria. Se comunican a través de la base de datos compartida.

### 2. Telegram bidireccional ✅ EN PROGRESO
Claudio manda alertas y el usuario le manda comandos. Comunicación real en tiempo real desde el celular. Ejemplos:
- "Claudio, ¿qué estás analizando ahora?"
- "Claudio, pausá las apuestas por hoy"
- "Claudio, subí el riesgo a $20 por operación"
- "Claudio, mostrá el resumen de la semana"

### 3. Whale tracking y copy trading inteligente
Claudio escanea TODAS las wallets públicas de Polymarket continuamente y las puntúa con un sistema multidimensional:
- Rentabilidad histórica (30%)
- Timing de entrada (20%)
- Bajo slippage (15%)
- Consistencia (15%)
- Selección de mercados (10%)
- Recencia (10%)

**Detección de clusters coordinados:** Si varias wallets grandes mueven el mismo mercado al mismo tiempo, Claudio lo detecta como señal fuerte y entra con más confianza.

**Regime-adaptive scoring:** El sistema ajusta los puntajes de las wallets según las condiciones actuales del mercado — una wallet que ganó mucho en elecciones puede no ser buena en mercados del clima.

**Copy trading con desviación inteligente:** Copia a los mejores pero aprende cuándo desviarse basándose en su propio análisis. Con el tiempo Claudio sabe cuándo el whale se equivoca.

### 4. Mercados del clima
Comparar pronóstico oficial vs precio del mercado. La estrategia más predecible y menos competida.
Fuentes: WeatherAPI, ECMWF, HRRR, METAR, Weather Underground.
Bot de referencia: $300 → $101K en 2 meses operando mercados de clima en Polymarket (validado).

### 5. Kelly Criterion ✅ IMPLEMENTADO
Apostar más cuando hay más confianza, menos cuando hay dudas. Maximizar ganancias y proteger el capital automáticamente. Implementado en el Agente Trader con Kelly fraccionado (25%) para mayor conservadurismo.

### 6. Memoria con vector database
Que Claudio recuerde cada decisión forever y pueda buscar patrones en su propio historial. Ningún bot comprado tiene esto.

### 7. Auto-reentrenamiento semanal
Cada semana entrena su modelo con sus propias experiencias. Se vuelve único e irreplicable con el tiempo.

### 8. Deploy en VPS
Servidor en la nube 24/7, sin VPN, accesible desde cualquier dispositivo. Digital Ocean o AWS, ~$10/mes.

### 9. Seguridad de Claudio
Que nadie pueda copiarlo, acceder al código, ni usarlo sin autorización:
- Código ofuscado y encriptado
- Autenticación para acceder al dashboard
- Base de datos y modelos entrenados protegidos localmente
- Sin acceso público al servidor — solo el usuario puede conectarse
- Logs de acceso para detectar intrusiones
- Experiencia acumulada guardada en formato privado no exportable

### 10. Wallet real conectada
Cuando la simulación muestre resultados consistentes, conectar USDC real con montos pequeños para empezar.

### 11. Dashboard móvil optimizado
La web actual no está optimizada para celular. Claudio tiene que verse bien y ser controlable desde iPhone/Android.

### 12. Sistema de backup automático
La memoria y base de datos de Claudio tienen que respaldarse automáticamente. Si se rompe el disco, no puede perder meses de aprendizaje.

### 13. Modo papel trading extendido
Antes de poner plata real, correr Claudio en simulación durante al menos 2-3 semanas con registro detallado para validar que la estrategia funciona.

### 14. Arbitraje entre mercados correlacionados
Detectar inconsistencias lógicas — si "Trump gana" está al 60% pero "Republicano gana" está al 45%, hay una oportunidad matemática garantizada.

### 15. Integración con datos de X/Twitter
Monitorear tweets relevantes en tiempo real para reaccionar antes que el mercado a noticias importantes.

### 16. Sistema de alertas de riesgo
Si Claudio pierde más de X% en un día, se detiene automáticamente y avisa. Protección contra situaciones inesperadas.

### 17. Historial de rendimiento exportable
Poder exportar el historial completo de operaciones en Excel o PDF para analizar el rendimiento.

### 18. Soporte multi-wallet
Poder operar con más de una wallet para distribuir el riesgo.

### 28. GDELT como fuente de noticias multilingüe
Integrar GDELT (Global Database of Events, Language and Tone) como fuente primaria de noticias para el Agente Investigador.

**Por qué es clave:**
- Gratuito, sin límites de requests
- Cubre noticias en 65+ idiomas en tiempo real
- Fuentes en árabe, farsi, chino y ruso anticipan noticias geopolíticas 2-4 horas antes que los medios en inglés
- Esto le da a Claudio una ventana de tiempo real antes de que el mercado reaccione

**Implementación:**
- GDELT API v2 — busca eventos por keyword y categoría
- Complementa NewsAPI (que solo cubre inglés)
- El Investigador consulta ambas fuentes y prioriza la más reciente
- Especialmente útil para mercados de política internacional y geopolítica

### 29. Behavioral biases en el Monitor
El Monitor no solo mira margen de precio — detecta patrones de comportamiento del crowd que generan ineficiencias predecibles.

**Bias a detectar:**
- **Round number clustering** — precios cerca de 50%, 25%, 75% suelen estar mal priceados porque la gente ancla en números redondos. Si un mercado está exactamente en 50%, hay que investigar.
- **Stale market blindness** — mercados sin actividad reciente donde el precio no se actualizó con info nueva. Alta oportunidad si hay noticias recientes.
- **Weekend gaps** — volumen bajo los fines de semana genera ineficiencias que se corrigen el lunes. Claudio puede anticipar la corrección.
- **Anchoring bias** — el crowd ancla al precio histórico aunque la realidad cambió.
- **Cascade overshoot** — cuando el mercado sobrereacciona a una noticia y el precio va demasiado lejos en una dirección.

**Cómo funciona:** El Monitor asigna un bonus de score a mercados donde detecta estos patrones, subiéndolos en la lista de prioridades para el Investigador.

### 30. Progressive context loading — análisis en dos niveles
No todos los mercados necesitan análisis profundo con Ollama. El sistema opera en capas para mantener velocidad y eficiencia.

**Nivel 1 — filtro rápido (Monitor):**
- Liquidez mínima
- Precio en rango válido
- Spread disponible
- Behavioral biases detectados
- Costo: milisegundos, sin IA

**Nivel 2 — análisis profundo (Investigador con Ollama):**
- Solo mercados que pasaron el Nivel 1
- Consulta GDELT + NewsAPI
- Análisis de sentimiento con Mistral
- Probabilidad bayesiana estimada
- Decisión final con razonamiento
- Costo: 20-30 segundos, usa Ollama

**Resultado:** Ollama solo trabaja en el 10-20% de mercados que realmente valen. El sistema es más rápido y el análisis más profundo donde importa.

### 31. Trigger system — reacción a eventos, no solo a tiempo
El Monitor no solo corre cada 5 minutos — también reacciona a eventos específicos que pueden generar oportunidades inmediatas.

**Triggers implementados:**
- **Price dislocation** — un mercado cambia más de 5% en menos de 10 minutos → análisis inmediato
- **Breaking news** — GDELT detecta noticia relacionada a un mercado activo → investigar ahora
- **Whale activity** — una wallet top entra en un mercado → evaluar si seguir
- **New listing** — mercado nuevo con pricing inicial potencialmente ineficiente
- **Volume spike** — volumen inusual en mercado de bajo tráfico → posible información privilegiada (ver punto 24)

**Cómo funciona:** El Monitor corre su ciclo normal cada 5 minutos PERO también escucha estos eventos y puede despertar al Investigador fuera de ciclo si detecta algo urgente.

---

## Estratégico

### 19. Definir nichos específicos de Claudio
Decidir en qué categorías se va a especializar — clima, deportes, política, etc. Un bot especializado gana más que uno generalista.

### 20. Plan de escalado
Empezar con $50-100 reales, validar, y escalar gradualmente. Definir cuándo y cuánto escalar según rendimiento.

### 21. Estrategia de salida de posiciones
No solo saber cuándo entrar sino cuándo salir antes del vencimiento si el precio se mueve a favor.

## Legal

### 22. Legalidad en Argentina — ACTUALIZADO 05/04/2026
El 17 de marzo de 2026 un tribunal de Buenos Aires ordenó el bloqueo nacional de Polymarket. La medida instruye a ENACOM a bloquear el acceso vía ISPs, y a Google y Apple a eliminar las apps. Argentina es el primer país de América Latina en tomar esta medida.

**Importante:** La restricción apunta a la plataforma, no criminaliza a usuarios individuales. El riesgo legal personal es bajo.

**Estrategia adoptada para Claudio:**
- Claudio corre en un VPS en EEUU — la conexión nunca pasa por Argentina
- El usuario solo accede al dashboard de Claudio (que es propio, no Polymarket)
- Misma lógica que usar VPN, pero más limpio porque el servidor está físicamente en EEUU
- Monitorear si la regulación evoluciona hacia los usuarios individuales

### 23. Estrategias paralelas con capital independiente
Cada estrategia de Claudio corre con su propio capital asignado, límites de riesgo y modo paper/real independiente:
- Estrategia clima — capital conservador, alta confianza
- Estrategia copy trading — capital moderado
- Estrategia arbitraje lógico — capital agresivo solo cuando hay certeza matemática
- Estrategia momentum — reacciona a noticias en tiempo real

Así si una estrategia falla no afecta a las otras.

### 24. Detección de información privilegiada
Monitorear volumen inusual en mercados específicos — si de repente hay $50,000 en un mercado de bajo volumen, algo está pasando. Claudio lo detecta y decide si seguir esa señal o evitarla. Inspirado en el caso de la inflación argentina donde Polymarket anticipó el dato oficial.

### 25. Principio de validación — anti-hype
Inspirado en bl888m: si algo realmente funcionara, nadie lo publicaría gratis. Claudio tiene que desarrollar sus propias ventajas, no copiar tutoriales públicos.

**Reglas de oro de Claudio:**
- Si no gana en simulación consistentemente 2-3 semanas, no opera con plata real
- Nunca escalar capital antes de validar la estrategia
- Desconfiar de estrategias públicas masivamente difundidas — si todos la usan, el edge desapareció
- La ventaja real está en su memoria acumulada propia, no en estrategias conocidas
- Cada estrategia nueva entra primero en paper trading aislado antes de integrarse al sistema
- Filtrar siempre los posts virales: separar lo que es real y técnico de lo que es marketing con link de Telegram al final

### 26. Motor de aprendizaje autónomo
Claudio tiene que poder aprender solo y volverse el mejor en sus nichos:
- Aprende de cada ganancia — ¿qué señales predijeron el éxito?
- Aprende de cada pérdida — ¿qué ignoró o malinterpretó?
- Detecta sus propios patrones de error y los corrige
- Genera sus propias hipótesis sobre nuevas estrategias y las testea en simulación
- Con suficiente historia, puede sugerir mejoras a su propio código vía Telegram

### 27. Conexión a redes sociales via MCP
Usar Model Context Protocol (MCP) para conectar Claudio a las redes sociales del usuario sin scraping ni APIs de pago.

**Redes a conectar con tu cuenta:**
- X/Twitter — servidor MCP de Twitter, lee tweets en tiempo real sobre mercados activos
- Reddit — r/Polymarket, r/news, r/worldnews
- Telegram — grupos de trading y predicción markets
- Instagram — cuentas de noticias y figuras públicas

**Cómo funciona:**
Claudio llama al servidor MCP → busca posts sobre el mercado que está analizando → recibe resultados → los manda a Ollama para analizar sentimiento → decide si apostar.

**Ventajas sobre scraping:**
- Usa tu cuenta existente, sin riesgo de bloqueo
- Gratis, sin pagar API oficial de X ($100/mes)
- Más confiable — si X cambia su estructura, el MCP se actualiza solo
- Un solo call hace búsqueda + análisis + recomendación

**Fuentes adicionales sin cuenta:**
- Google News RSS — noticias de cualquier tema en tiempo real
- Portales especializados — LegalInsider para casos judiciales, Weather Underground para clima
- YouTube — transcripciones de videos de análisis

---

## Estado actual (al 05/04/2026)

### Completado
- Python instalado y configurado
- Librerías instaladas (py-clob-client, flask, pandas, scikit-learn, etc.)
- Conexión con Polymarket API funcionando
- Detección de mercados nicho con baja liquidez
- Base de datos SQLite inicializada (mercados, análisis, operaciones, noticias, memoria)
- Sistema de noticias con NewsAPI funcionando
- Dashboard web con Flask corriendo en localhost:5000
- Apuestas virtuales en modo simulación
- Log de actividad en tiempo real
- P&L virtual tracking
- Arquitectura modular de agentes (Monitor, Investigador, Trader, Telegram)
- Kelly Criterion implementado en el Trader
- Watchdog — relanza agentes caídos automáticamente

### En progreso
- Instalación de Ollama + Mistral

### Próxima sesión
- Confirmar que Ollama + Mistral funcionan
- Integrar GDELT al Investigador
- Implementar behavioral biases en el Monitor
- Implementar progressive context loading (2 niveles)
- Implementar trigger system por eventos

---

## Hardware disponible
- PC principal: Ryzen 5 8600G, 32GB RAM, NPU integrada — ideal para Ollama
- PC vieja: por definir specs — para correr Claudio 24/7
- Posible VPS: Digital Ocean o AWS para producción

## Stack tecnológico actual
- Python 3.12
- Flask (servidor web)
- SQLite (base de datos)
- py-clob-client (Polymarket API)
- NewsAPI (noticias)
- Ollama + Mistral 7B (análisis con IA local) — en instalación
- Windscribe VPN (acceso a Polymarket desde Argentina)

## Stack tecnológico próximo
- GDELT API v2 (noticias multilingüe, gratis)
- ChromaDB o FAISS (vector database para memoria)
- Telegram Bot API (comunicación bidireccional)

---

## Entorno de desarrollo — Claude Code

### 32. Claude Code en Windows
Instalar Claude Code para modificar el proyecto directamente desde la terminal, sin copiar y pegar código.

**Instalación:**
1. Instalar Git para Windows desde git-scm.com (con "Add to PATH" marcado)
2. Abrir PowerShell y correr: `Invoke-WebRequest -Uri "https://claude.ai/install.ps1" -UseBasicParsing | Invoke-Expression`
3. Correr `claude` y autenticarse con la cuenta Pro ($20/mes — ya incluido, sin costo extra)
4. Entrar a `C:\polymarket-bot` y correr `claude`

**Uso:** hablarle en español directamente en la terminal. "Claudio tiene un bug en el investigador, arreglalo." Claude Code lee los archivos, encuentra el problema y lo corrige solo.

### 33. CLAUDE.md — contexto permanente del proyecto
Crear un archivo `CLAUDE.md` en `C:\polymarket-bot` con el contexto completo de Claudio.

**Qué incluir:**
- Arquitectura de agentes y cómo se comunican
- Stack tecnológico (Python 3.12, Flask, SQLite, Ollama/Mistral)
- Reglas de oro (nunca operar real sin validar simulación, anti-hype, etc.)
- Estructura de carpetas del proyecto
- Comandos para correr y testear

**Resultado:** cada vez que abras Claude Code ya sabe todo sobre Claudio sin que tengas que explicar nada. Sesiones más rápidas y eficientes.

### 34. Everything Claude Code — plugin de optimización
Instalar el plugin `everything-claude-code` (128K estrellas, ganador del hackathon de Anthropic) para potenciar Claude Code con el proyecto.

**Lo que suma a Claudio específicamente:**

**Continuous Learning v2** — cada sesión de trabajo extrae patrones automáticamente y los guarda como "instincts". Con el tiempo Claude Code conoce los patrones específicos de Claudio y trabaja más rápido sin repetir explicaciones.

**Hooks para Python** — automatizaciones que se disparan al editar archivos. Ejemplo: cada vez que modificás un agente de Claudio, el hook verifica automáticamente que no rompiste la sintaxis ni las importaciones.

**Token optimization** — configuración para usar Sonnet (no Opus) por defecto y limitar thinking tokens. Reduce costo de Claude Code sin perder calidad para las modificaciones rutinarias de Claudio.

**AgentShield** — escanea vulnerabilidades en la configuración. Relevante porque Claudio tiene tokens de API sensibles (Telegram, NewsAPI) en `config.json`.

**Instalación dentro de Claude Code:**
```
/plugin marketplace add affaan-m/everything-claude-code
/plugin install everything-claude-code@everything-claude-code
```

**Configuración de token optimization** — agregar a `~/.claude/settings.json`:
```json
{
  "model": "sonnet",
  "env": {
    "MAX_THINKING_TOKENS": "10000",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50"
  }
}
```

**Lo que NO instalar:** skills de TypeScript, React, Java, Django — no aplican a Claudio que es Python puro.

---

## Inteligencia avanzada — inspirado en GitHub top repos

### 35. Sistema de evaluación de estrategias — PASS/REVISE/REJECT
Inspirado en `claude-trading-skills` (tradermonty). Antes de que una estrategia opere con plata real, pasa por un quality gate con 8 criterios:

1. **Edge plausibility** — ¿el edge tiene sentido lógico o es ruido?
2. **Overfitting risk** — ¿la estrategia fue optimizada sobre los mismos datos que se testean?
3. **Sample adequacy** — ¿hay suficientes operaciones para que los resultados sean estadísticamente válidos?
4. **Regime dependency** — ¿la estrategia solo funciona en cierto tipo de mercado?
5. **Exit calibration** — ¿las salidas están bien definidas o son arbitrarias?
6. **Risk concentration** — ¿demasiado capital en un solo tipo de mercado?
7. **Execution realism** — ¿los resultados asumen slippage y fees realistas?
8. **Invalidation quality** — ¿está claro cuándo la estrategia dejó de funcionar?

**Veredictos:** PASS (puede escalar a real), REVISE (volver a paper trading con ajustes concretos), REJECT (abandonar la estrategia).

**Quién lo implementa:** el Agente Evaluador (cuarta fase). Corre automáticamente cada semana y reporta por Telegram.

### 36. autoDream — consolidación de memoria en background
Inspirado en KAIROS, el modo daemon autónomo filtrado del leak de Claude Code.

Cuando Claudio está idle (sin apuestas activas, sin análisis en curso), un proceso background:
- Revisa todas las operaciones de las últimas 24 horas
- Identifica patrones: ¿qué señales predijeron los aciertos? ¿qué ignoró antes de las pérdidas?
- Elimina contradicciones en la memoria acumulada
- Convierte observaciones vagas en hechos concretos
- Guarda los insights en la tabla `memoria` de la DB

**Cuándo corre:** automáticamente cuando el Monitor detecta que no hay ciclos activos por más de 30 minutos.

**Resultado:** Claudio aprende continuamente sin intervención manual. Cada semana su modelo interno mejora con sus propias experiencias.

### 37. Migración al Agent SDK oficial de Python
Cuando incorporemos Claude API como cerebro (en lugar de o además de Mistral), usar el SDK oficial de Anthropic para agentes.

**Ventaja principal:** cada agente pasa a ser una clase Python con herramientas MCP integradas en el mismo proceso, sin procesos separados. La arquitectura actual de archivos independientes se mantiene, pero la comunicación entre agentes es más limpia y eficiente.

**Cuándo hacerlo:** después de validar resultados en simulación y antes de conectar plata real. El Agent SDK facilita el logging y trazabilidad de cada decisión, clave para auditar el comportamiento de Claudio en producción.

### 38. root-cause-tracing en el Agente Debugger
Cuando el Agente Debugger detecta un error, en vez de solo reportar el log, traza hacia atrás hasta encontrar el trigger original.

**Ejemplo:** Claudio pierde 3 apuestas seguidas → Debugger no solo dice "perdió", sino que traza: ¿qué mercado? ¿qué señal lo llevó ahí? ¿qué noticia o dato estaba disponible y fue ignorado? ¿en qué punto del pipeline falló el razonamiento?

**Resultado:** cada pérdida genera un informe de causa raíz que alimenta directamente al autoDream (punto 36).

---

## Plugins para Claude Code — instalación prioritaria

### 39. claude-mem — memoria persistente entre sesiones
**github.com/thedotmack/claude-mem — 38K estrellas**

Resuelve el problema más frustrante de Claude Code: cada sesión empieza de cero. claude-mem captura todo lo que hacés durante una sesión, lo comprime con IA, y lo inyecta automáticamente en la próxima.

**Cómo funciona:**
- SessionStart → carga memorias relevantes de sesiones anteriores
- UserPromptSubmit → captura tus requests para contexto
- PostToolUse → registra cada acción y resultado
- Summary → comprime la sesión en insights clave
- SessionEnd → guarda todo para la próxima vez

Todo local en SQLite en `~/.claude-mem/claude-mem.db`. Web viewer en http://localhost:37777 para navegar el historial.

**Endless Mode (beta)** — arquitectura biomimética para sesiones largas sin degradación de contexto. Clave para sesiones largas de desarrollo de Claudio.

**Instalación:**
```
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem
```

**Complementa:** el CLAUDE.md (punto 33). Juntos garantizan que Claude Code nunca pierda contexto del proyecto.

### 40. Superpowers — Claude piensa antes de codear
**github.com/obra/superpowers**

Sin Superpowers: decís "arreglá este bug" → Claude escribe 200 líneas de código sin pensar. Con Superpowers: Claude analiza, plantea múltiples enfoques, elige el mejor, y recién entonces codea.

**Lo que activa:**
- **TDD mode** — escribe tests antes de la implementación, no después
- **Brainstorming** — explora múltiples enfoques antes de comprometerse con uno
- **Debugging estructurado** — root cause analysis en lugar de fixes al azar
- **Skill authoring** — crea skills reutilizables de los patrones que descubre

**Para Claudio:** cada vez que Claude Code toque un agente, primero analiza el impacto en el resto del sistema. Evita romper cosas que funcionaban.

**Instalación:**
```
/plugin marketplace add obra/superpowers
/plugin install superpowers
```

**Complementa:** el punto 38 (root-cause-tracing). Superpowers previene errores, root-cause-tracing los analiza cuando ocurren igual.

### 41. Compound Engineering — planificar antes de todo
**github.com/EveryInc/compound-engineering-plugin**

Filosofía: cada unidad de trabajo debe hacer el siguiente más fácil, no más difícil. Invierte la acumulación de deuda técnica.

**Comandos clave:**
- `/ce:plan` — lanza agentes en paralelo que leen el codebase, detectan patrones y gaps, y generan un `plan.md` antes de tocar código
- `/ce:brainstorm` — refina ideas a través de Q&A interactivo
- `/ce:work` — ejecuta con chequeo automático de confianza
- `/ce:review` — detecta problemas antes de que se acumulen
- `/ce:compound` — extrae patrones para uso futuro
- `/ce:ideate` — Claude proactivamente sugiere mejoras al codebase sin que se las pidas

**Regla de uso:** salvo que sea un cambio de una línea, siempre hay un plan.md primero.

**Para Claudio:** antes de agregar cualquier agente nuevo o feature importante, `/ce:plan` primero. Evita la arquitectura improvisada.

**Instalación:**
```
/plugin marketplace add EveryInc/compound-engineering-plugin
/plugin install compound-engineering
```

### 42. VoiceMode — hablarle a Claude Code
**github.com/mbailey/voicemode**

Cuando estás debuggeando con las manos en el teclado, hablarle en vez de tipear. Claude escucha, procesa y responde con voz.

**Stack local (sin enviar datos a nadie):**
- Whisper → speech-to-text
- Kokoro → text-to-speech
- ~500MB de descarga, después 100% offline

**Instalación:**
```
/plugin marketplace add mbailey/voicemode
/plugin install voicemode
/voicemode:install
```

**Cuándo usarlo:** sesiones largas de debugging de Claudio donde necesitás las manos libres.

---

## Stack completo de Claude Code para el proyecto

Una vez instalado Claude Code, el orden de instalación recomendado:

1. **claude-mem** — memoria persistente (instalar primero, siempre activo)
2. **Everything Claude Code** — sistema base de optimización (punto 34)
3. **Superpowers** — disciplina de desarrollo
4. **Compound Engineering** — filosofía de planificación
5. **VoiceMode** — opcional, para sesiones largas
6. Crear **CLAUDE.md** con contexto de Claudio (punto 33)

Con esto Claude Code pasa de: smart + olvidadizo + impulsivo + caótico
A: smart + recuerda todo + piensa antes de codear + planifica antes de todo
