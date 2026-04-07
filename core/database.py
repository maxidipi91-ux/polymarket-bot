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
        modo TEXT DEFAULT "simulacion"
    )''')

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

def guardar_operacion(mercado_id, outcome, precio_entrada, monto, modo="simulacion"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO operaciones
                 (mercado_id, fecha_entrada, outcome, precio_entrada, monto, resultado, modo)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (mercado_id, datetime.now().isoformat(), outcome,
               precio_entrada, monto, "ABIERTA", modo))
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
