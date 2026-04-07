"""
agentes/telegram_bot.py — Agente Telegram
Comunicación bidireccional con Claudio desde el celular.
Manda alertas automáticas y recibe comandos del usuario.

SETUP:
1. Crear bot en @BotFather → obtener TELEGRAM_TOKEN
2. Mandar un mensaje al bot → obtener TELEGRAM_CHAT_ID
3. Poner ambos en config.json o variables de entorno
"""

import time
import requests
import json
import os
from datetime import datetime
from core.estado import estado, addlog, get_operaciones
from core.database import obtener_estadisticas
from config_loader import CONFIG

# ─── Configuración ───────────────────────────────────────────────
TELEGRAM_TOKEN   = CONFIG["telegram_token"]
TELEGRAM_CHAT_ID = CONFIG["telegram_chat_id"]
TELEGRAM_URL     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ─── Envío de mensajes ───────────────────────────────────────────

def enviar_mensaje(texto):
    """Manda un mensaje al usuario vía Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_URL}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML"},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        addlog(f"[Telegram] Error enviando mensaje: {e}", "error")
        return False

def notificar_apuesta(mercado, monto, ganancia_potencial):
    texto = (
        f"🎯 <b>Nueva apuesta</b>\n"
        f"📌 {mercado['pregunta'][:60]}\n"
        f"✅ Outcome: {mercado['outcome']}\n"
        f"💰 Precio: {mercado['precio_pct']}%\n"
        f"💵 Monto: ${monto}\n"
        f"🚀 Potencial: +${ganancia_potencial}\n"
        f"🔍 Confianza: {mercado.get('confianza', '?')}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    enviar_mensaje(texto)

def notificar_resultado(pregunta, resultado, ganancia):
    emoji = "✅" if "GANADA" in resultado else "❌"
    texto = (
        f"{emoji} <b>Resultado</b>\n"
        f"📌 {pregunta[:50]}\n"
        f"{'💵' if ganancia > 0 else '📉'} {resultado}: "
        f"{'+'if ganancia > 0 else ''}{ganancia:.2f}\n"
        f"💼 Saldo: ${estado['saldo']:.2f} | P&L: ${estado['pnl']:.2f}"
    )
    enviar_mensaje(texto)

# ─── Recepción de comandos ───────────────────────────────────────

ultimo_update_id = 0

def obtener_updates():
    global ultimo_update_id
    try:
        r = requests.get(
            f"{TELEGRAM_URL}/getUpdates",
            params={"offset": ultimo_update_id + 1, "timeout": 10},
            timeout=15
        )
        updates = r.json().get("result", [])
        if updates:
            ultimo_update_id = updates[-1]["update_id"]
        return updates
    except:
        return []

def procesar_comando(texto, chat_id):
    """Procesa un comando recibido y responde."""
    texto = texto.strip().lower()
    stats = obtener_estadisticas()
    ops_snap = get_operaciones()  # snapshot thread-safe

    if "/estado" in texto or "estado" in texto:
        ops     = len(ops_snap)
        ganadas = len([o for o in ops_snap if o["estado"] == "GANADA"])
        abiertas = [o for o in ops_snap if o["estado"] == "ABIERTA"]
        lineas_abiertas = ""
        for o in abiertas[:3]:
            precio_actual = o.get("precio_salida", o["precio"])
            cambio = round(precio_actual - o["precio"], 1)
            lineas_abiertas += f"\n  • {o['pregunta'][:30]}... {'+' if cambio >= 0 else ''}{cambio}%"
        respuesta = (
            f"📊 <b>Estado de Claudio</b>\n"
            f"🔄 {'Corriendo' if estado['corriendo'] else 'Detenido'}\n"
            f"💼 Saldo: ${estado['saldo']:.2f}\n"
            f"📈 P&L: ${estado['pnl']:.2f}\n"
            f"🎯 Ops: {ops} ({ganadas} ganadas)\n"
            f"🔓 Abiertas: {len(abiertas)}{lineas_abiertas}\n"
            f"🔢 Ciclo: #{estado['ciclo_num']}\n"
            f"🤖 Ollama: {'✅' if estado['ollama_disponible'] else '❌'}"
        )

    elif "/pausa" in texto or "pausá" in texto or "pausa" in texto:
        estado["corriendo"] = False
        respuesta = "⏸ Claudio pausado."

    elif "/resumir" in texto or "/resumen" in texto:
        respuesta = (
            f"📋 <b>Resumen</b>\n"
            f"Total ops: {stats['total']}\n"
            f"Ganadas: {stats['ganadas']}\n"
            f"Winrate: {stats['winrate']}%\n"
            f"Ganancia total: ${stats['ganancia_total']:.2f}"
        )

    elif "/mercados" in texto:
        ops = estado["mercados"][:5]
        if ops:
            lines = "\n".join([
                f"• {m['pregunta'][:40]}... → {m.get('decision_investigador', m['decision'])}"
                for m in ops
            ])
            respuesta = f"🔍 <b>Top mercados</b>\n{lines}"
        else:
            respuesta = "Sin mercados detectados aún."

    elif "/riesgo" in texto:
        partes = texto.split()
        numeros = [p for p in partes if p.replace("$", "").isdigit()]
        if numeros:
            nuevo_riesgo = float(numeros[0].replace("$", ""))
            estado["riesgo_por_op"] = nuevo_riesgo
            respuesta = f"✅ Riesgo por operación actualizado a ${nuevo_riesgo}"
        else:
            respuesta = f"Riesgo actual: ${estado['riesgo_por_op']}. Usá: /riesgo 20"

    elif "/ayuda" in texto or "/help" in texto or "/start" in texto:
        respuesta = (
            "🤖 <b>Comandos de Claudio</b>\n\n"
            "/estado — saldo, P&L, operaciones\n"
            "/resumen — estadísticas totales\n"
            "/mercados — top oportunidades actuales\n"
            "/riesgo 20 — cambiar riesgo por op\n"
            "/pausa — detener Claudio\n"
            "/ayuda — este menú"
        )
    else:
        respuesta = "No entendí ese comando. Mandá /ayuda para ver las opciones."

    try:
        requests.post(
            f"{TELEGRAM_URL}/sendMessage",
            json={"chat_id": chat_id, "text": respuesta, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass


def correr():
    """Loop principal del agente Telegram."""
    if not TELEGRAM_TOKEN:
        addlog("[Telegram] Sin token configurado — agente desactivado. Ver config.json", "error")
        estado["telegram_activo"] = False
        return

    addlog("[Telegram] Iniciado — escuchando comandos", "win")
    estado["telegram_activo"] = True
    enviar_mensaje(
        f"🤖 <b>Claudio iniciado</b>\n"
        f"Modo: {estado['modo']}\n"
        f"Saldo: ${estado['saldo']:.2f}\n"
        f"Mandá /ayuda para ver los comandos."
    )

    while estado["corriendo"]:
        try:
            updates = obtener_updates()
            for update in updates:
                msg = update.get("message", {})
                texto = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if texto and chat_id:
                    addlog(f"[Telegram] Comando recibido: {texto}")
                    procesar_comando(texto, chat_id)
        except Exception as e:
            addlog(f"[Telegram] Error: {e}", "error")

        time.sleep(3)  # Polling cada 3 segundos
