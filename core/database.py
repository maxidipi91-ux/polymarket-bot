"""
core/database.py — Base de datos SQLite de Claudio.
Todas las tablas y operaciones de persistencia.
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "claudio.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS mercados (
        id TEXT PRIMARY KEY,
        pregunta TEXT,
        fecha_fin TEXT,
        fecha_detectado TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analisis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mercado_id TEXT,
        fecha TEXT,
        precio_mercado REAL,
        probabilidad_claudio REAL,
        margen REAL,
        noticias TEXT,
        decision TEXT,
        razonamiento TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS operaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mercado_id TEXT,
        fecha_entrada TEXT,
        fecha_salida TEXT,
        outcome TEXT,
        precio_entrada REAL,
        precio_salida REAL,
        monto REAL,
        ganancia REAL,
        resultado TEXT,
        modo TEXT DEFAULT "simulacion",
        kelly_usado REAL
    )''')
    # Migración: agregar kelly_usado si no existe en tablas ya creadas
    try:
        c.execute('ALTER TABLE operaciones ADD COLUMN kelly_usado REAL')
    except:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS noticias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mercado_id TEXT,
        fecha TEXT,
        titulo TEXT,
        fuente TEXT,
        sentimiento REAL
    )''')

    # Nueva tabla para memoria de Claudio
    c.execute('''CREATE TABLE IF NOT EXISTS memoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        tipo TEXT,
        contenido TEXT,
        mercado_id TEXT
    )''')

    conn.commit()
    conn.close()

def guardar_mercado(mercado_id, pregunta, fecha_fin):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO mercados VALUES (?, ?, ?, ?)',
              (mercado_id, pregunta, fecha_fin, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def guardar_analisis(mercado_id, precio_mercado, probabilidad_claudio,
                     margen, noticias, decision, razonamiento=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO analisis
                 (mercado_id, fecha, precio_mercado, probabilidad_claudio,
                  margen, noticias, decision, razonamiento)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (mercado_id, datetime.now().isoformat(), precio_mercado,
               probabilidad_claudio, margen, json.dumps(noticias), decision, razonamiento))
    conn.commit()
    conn.close()

def guardar_operacion(mercado_id, outcome, precio_entrada, monto, modo="simulacion", kelly_usado=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO operaciones
                 (mercado_id, fecha_entrada, outcome, precio_entrada, monto, resultado, modo, kelly_usado)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (mercado_id, datetime.now().isoformat(), outcome,
               precio_entrada, monto, "ABIERTA", modo, kelly_usado))
    op_id = c.lastrowid
    conn.commit()
    conn.close()
    return op_id

def cerrar_operacion(op_id, precio_salida, ganancia, resultado):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''UPDATE operaciones
                 SET fecha_salida=?, precio_salida=?, ganancia=?, resultado=?
                 WHERE id=?''',
              (datetime.now().isoformat(), precio_salida, ganancia, resultado, op_id))
    conn.commit()
    conn.close()

def guardar_memoria(tipo, contenido, mercado_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO memoria (fecha, tipo, contenido, mercado_id) VALUES (?, ?, ?, ?)',
              (datetime.now().isoformat(), tipo, contenido, mercado_id))
    conn.commit()
    conn.close()

def get_operaciones_db():
    """Retorna operaciones en formato compatible con estado['operaciones']."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT o.id, o.mercado_id, o.outcome, o.precio_entrada, o.monto,
               o.ganancia, o.resultado, o.fecha_entrada,
               COALESCE(m.pregunta, o.mercado_id) as pregunta,
               o.kelly_usado
        FROM operaciones o
        LEFT JOIN mercados m ON o.mercado_id = m.id
        ORDER BY o.id DESC LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    ops = []
    for row in rows:
        db_id, mercado_id, outcome, precio, monto, ganancia, resultado, fecha, pregunta, kelly = row
        ops.append({
            "id":                  mercado_id,
            "db_id":               db_id,
            "pregunta":            pregunta,
            "outcome":             outcome or "",
            "precio":              round((precio or 0) * 100, 1),
            "monto":               round(monto or 0, 2),
            "ganancia_potencial":  round((monto or 0) / max(precio or 0.5, 0.01) - (monto or 0), 2),
            "estado":              resultado or "ABIERTA",
            "fecha":               (fecha or "")[:19],
            "fecha_completa":      fecha or "",
            "confianza":           "—",
            "kelly_usado":         kelly,
            "edge":                0,
            "probabilidad_claudio": precio or 0,
            "ganancia":            round(ganancia or 0, 2),
        })
    return ops


def calcular_estado_financiero(saldo_inicial):
    """Calcula saldo actual y PnL desde la DB."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(monto) FROM operaciones WHERE resultado='ABIERTA'")
    exposure = c.fetchone()[0] or 0.0
    c.execute("SELECT SUM(ganancia) FROM operaciones WHERE ganancia IS NOT NULL")
    pnl = c.fetchone()[0] or 0.0
    conn.close()
    saldo_actual = saldo_inicial - exposure + pnl
    return round(saldo_actual, 2), round(pnl, 2)


def get_mercados_apostados():
    """Retorna set de mercado_ids que ya tienen operaciones (para sobrevivir reinicios)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT mercado_id FROM operaciones")
    ids = {row[0] for row in c.fetchall()}
    conn.close()
    return ids

def obtener_estadisticas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM operaciones")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM operaciones WHERE resultado = 'GANADA'")
    ganadas = c.fetchone()[0]
    c.execute("SELECT SUM(ganancia) FROM operaciones WHERE ganancia IS NOT NULL")
    ganancia_total = c.fetchone()[0] or 0.0
    c.execute("SELECT COUNT(*) FROM operaciones WHERE modo='simulacion'")
    sim_total = c.fetchone()[0]
    conn.close()
    return {
        "total": total,
        "ganadas": ganadas,
        "ganancia_total": round(ganancia_total, 2),
        "sim_total": sim_total,
        "winrate": round(ganadas / total * 100, 1) if total > 0 else 0
    }
