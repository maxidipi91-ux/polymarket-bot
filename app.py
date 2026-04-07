"""
app.py — Dashboard web de Claudio v0.2
Integra la arquitectura de agentes modulares.
"""

from flask import Flask, jsonify, render_template_string
import threading
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.estado import estado, addlog, get_mercados, get_operaciones
from core.database import init_db, obtener_estadisticas, get_operaciones_db, calcular_estado_financiero
import claudio as orquestador

app = Flask(__name__)

# ─── API ─────────────────────────────────────────────────────────

@app.route("/api/estado")
def api_estado():
    from config_loader import CONFIG
    stats   = obtener_estadisticas()
    mercs   = get_mercados()
    ops     = get_operaciones_db()  # siempre desde DB
    saldo, pnl = calcular_estado_financiero(CONFIG["saldo_inicial"])
    total   = stats["total"]
    ganadas = stats["ganadas"]
    return jsonify({
        "corriendo":   estado["corriendo"],
        "modo":        estado["modo"],
        "saldo":       saldo,
        "pnl":         pnl,
        "riesgo":      estado["riesgo_por_op"],
        "total_ops":   total,
        "ganadas":     ganadas,
        "winrate":     stats["winrate"],
        "ciclo_num":   estado["ciclo_num"],
        "groq":        True,  # Groq siempre activo si hay key
        "telegram":    estado["telegram_activo"],
        "mercados":    mercs[:10],
        "operaciones": ops[:10],
        "log":         estado["log"][:20],
        "stats_db":    stats,
    })

@app.route("/api/iniciar")
def api_iniciar():
    if not estado["corriendo"]:
        t = threading.Thread(target=orquestador.iniciar, daemon=True)
        t.start()
    return jsonify({"ok": True})

@app.route("/api/detener")
def api_detener():
    orquestador.detener()
    return jsonify({"ok": True})

@app.route("/api/riesgo/<valor>")
def api_riesgo(valor):
    try:
        v = float(valor)
        estado["riesgo_por_op"] = v
        addlog(f"Riesgo por operación → ${v}")
    except:
        pass
    return jsonify({"ok": True})

@app.route("/api/modo/<string:modo>")
def api_modo(modo):
    if modo in ("simulacion", "real"):
        estado["modo"] = modo
        addlog(f"Modo cambiado a: {modo}", "win" if modo == "real" else "info")
    return jsonify({"ok": True, "modo": estado["modo"]})

# ─── Dashboard ───────────────────────────────────────────────────

DASHBOARD = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claudio v0.2</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:system-ui,sans-serif; background:#f5f5f0; color:#1a1a18; font-size:13px; }
header { background:#fff; border-bottom:1px solid #e8e6e0; padding:10px 20px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.logo { font-size:16px; font-weight:700; }
.version { font-size:11px; color:#aaa; margin-right:8px; }
.pill { display:flex; gap:3px; background:#f0ede8; border-radius:20px; padding:3px; }
.pill-btn { padding:4px 12px; border-radius:16px; font-size:11px; cursor:pointer; border:none; background:transparent; color:#666; transition:.15s; }
.pill-btn.active-sim { background:#EF9F27; color:#412402; font-weight:600; }
.pill-btn.active-real { background:#c0392b; color:#fff; font-weight:600; }
.status-group { display:flex; gap:10px; align-items:center; margin-left:auto; flex-wrap:wrap; }
.status-item { display:flex; align-items:center; gap:5px; font-size:11px; color:#888; }
.dot { width:7px; height:7px; border-radius:50%; }
.dot.on { background:#1D9E75; } .dot.off { background:#bbb; }
.dot.warn { background:#EF9F27; }
main { padding:14px 18px; display:flex; flex-direction:column; gap:12px; max-width:1200px; margin:0 auto; }
.metrics { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; }
@media(max-width:700px){ .metrics{grid-template-columns:repeat(2,1fr);} .panels{grid-template-columns:1fr!important;} }
.metric { background:#fff; border:1px solid #e8e6e0; border-radius:10px; padding:12px 14px; }
.metric-label { font-size:10px; color:#999; text-transform:uppercase; letter-spacing:.04em; margin-bottom:4px; }
.metric-value { font-size:20px; font-weight:700; }
.green { color:#0F6E56; } .red { color:#A32D2D; } .amber { color:#854F0B; } .blue { color:#1a5fa8; }
.panels { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.panel { background:#fff; border:1px solid #e8e6e0; border-radius:10px; padding:14px; }
.panel-title { font-size:10px; font-weight:700; color:#999; text-transform:uppercase; letter-spacing:.06em; margin-bottom:10px; display:flex; justify-content:space-between; }
.mrow { padding:7px 0; border-bottom:1px solid #f5f5f0; display:flex; gap:8px; align-items:flex-start; }
.mrow:last-child { border-bottom:none; }
.mname { flex:1; font-size:12px; line-height:1.4; }
.mname small { color:#aaa; font-size:10px; }
.badge { font-size:10px; padding:2px 8px; border-radius:10px; white-space:nowrap; font-weight:500; }
.badge.op { background:#EAF3DE; color:#27500A; }
.badge.wait { background:#f5f5f0; color:#aaa; }
.badge.alta { background:#d4edda; color:#155724; }
.badge.media { background:#fff3cd; color:#856404; }
.badge.baja { background:#f5f5f0; color:#888; }
.lrow { display:flex; gap:8px; font-size:11px; padding:4px 0; border-bottom:1px solid #fafaf8; }
.lrow:last-child { border-bottom:none; }
.ltime { color:#ccc; min-width:50px; flex-shrink:0; }
.win { color:#0F6E56; } .loss { color:#A32D2D; } .error { color:#c0392b; } .info { color:#1a5fa8; }
.controls { background:#fff; border:1px solid #e8e6e0; border-radius:10px; padding:12px 16px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.btn { padding:7px 16px; border-radius:8px; font-size:12px; font-weight:600; cursor:pointer; border:1px solid; transition:.15s; }
.btn-start { background:#1D9E75; color:#fff; border-color:#0F6E56; }
.btn-stop { background:#FCEBEB; color:#A32D2D; border-color:#F09595; }
.btn:disabled { opacity:.5; cursor:default; }
.slider-wrap { display:flex; align-items:center; gap:8px; }
.ops-table { width:100%; border-collapse:collapse; font-size:11px; }
.ops-table th { text-align:left; color:#999; font-weight:600; padding:5px 4px; border-bottom:1px solid #e8e6e0; font-size:10px; text-transform:uppercase; }
.ops-table td { padding:6px 4px; border-bottom:1px solid #fafaf8; }
.tag { font-size:10px; padding:2px 7px; border-radius:8px; font-weight:500; }
.tag.abierta { background:#EAF3DE; color:#27500A; }
.tag.ganada { background:#d4edda; color:#155724; }
.tag.perdida { background:#FCEBEB; color:#A32D2D; }
.razon { font-size:10px; color:#888; font-style:italic; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
</head>
<body>
<header>
  <span class="logo">Claudio</span><span class="version">v0.2</span>
  <div class="pill">
    <button class="pill-btn" id="btn-sim" onclick="setModo('simulacion')">Simulación</button>
    <button class="pill-btn" id="btn-real" onclick="setModo('real')">Real</button>
  </div>
  <div class="status-group">
    <div class="status-item"><div class="dot off" id="dot-main"></div><span id="txt-main">Detenido</span></div>
    <div class="status-item"><div class="dot off" id="dot-groq"></div><span>LLM</span></div>
    <div class="status-item"><div class="dot off" id="dot-telegram"></div><span>Telegram</span></div>
  </div>
</header>
<main>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Saldo virtual</div><div class="metric-value" id="saldo">$1,000.00</div></div>
    <div class="metric"><div class="metric-label">P&L total</div><div class="metric-value" id="pnl">$0.00</div></div>
    <div class="metric"><div class="metric-label">Operaciones</div><div class="metric-value amber" id="total_ops">0</div></div>
    <div class="metric"><div class="metric-label">Tasa acierto</div><div class="metric-value" id="winrate">—</div></div>
    <div class="metric"><div class="metric-label">Ciclo</div><div class="metric-value blue" id="ciclo">#0</div></div>
  </div>

  <div class="panels">
    <div class="panel">
      <div class="panel-title">Mercados <span id="cnt-mercados" style="font-weight:400;color:#ccc">0</span></div>
      <div id="mercados"><div style="color:#ccc;padding:8px 0;font-size:12px">Iniciá Claudio...</div></div>
    </div>
    <div class="panel">
      <div class="panel-title">Log en tiempo real</div>
      <div id="log"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">Operaciones</div>
    <div id="ops-container"><div style="color:#ccc;font-size:12px">Sin operaciones aún</div></div>
  </div>

  <div class="controls">
    <button class="btn btn-start" id="btn-iniciar" onclick="iniciar()">▶ Iniciar</button>
    <button class="btn btn-stop" onclick="detener()">⏸ Detener</button>
    <div class="slider-wrap">
      <span style="color:#888;font-size:12px">Riesgo:</span>
      <input type="range" min="1" max="100" value="10" id="slider-riesgo" oninput="updateRiesgo(this.value)">
      <span id="val-riesgo" style="font-weight:700;min-width:36px">$10</span>
    </div>
  </div>
</main>

<script>
let modoActual = 'simulacion';

async function iniciar() {
  await fetch('/api/iniciar');
  document.getElementById('btn-iniciar').disabled = true;
  document.getElementById('btn-iniciar').textContent = 'Iniciando...';
}
async function detener() {
  await fetch('/api/detener');
  document.getElementById('btn-iniciar').disabled = false;
  document.getElementById('btn-iniciar').textContent = '▶ Iniciar';
}
async function setModo(modo) {
  await fetch('/api/modo/' + modo);
  modoActual = modo;
  document.getElementById('btn-sim').className = 'pill-btn' + (modo==='simulacion'?' active-sim':'');
  document.getElementById('btn-real').className = 'pill-btn' + (modo==='real'?' active-real':'');
}
async function updateRiesgo(v) {
  document.getElementById('val-riesgo').textContent = '$' + v;
  await fetch('/api/riesgo/' + v);
}

function fmt(n) { return (n >= 0 ? '+' : '') + '$' + Math.abs(n).toFixed(2); }

async function actualizar() {
  try {
    const r = await fetch('/api/estado');
    const d = await r.json();

    // Status dots
    document.getElementById('dot-main').className = 'dot ' + (d.corriendo ? 'on' : 'off');
    document.getElementById('txt-main').textContent = d.corriendo ? 'Corriendo' : 'Detenido';
    document.getElementById('dot-groq').className = 'dot ' + (d.groq ? 'on' : 'warn');
    document.getElementById('dot-telegram').className = 'dot ' + (d.telegram ? 'on' : 'off');

    // Métricas
    document.getElementById('saldo').textContent = '$' + d.saldo.toFixed(2);
    const pnlEl = document.getElementById('pnl');
    pnlEl.textContent = fmt(d.pnl);
    pnlEl.className = 'metric-value ' + (d.pnl >= 0 ? 'green' : 'red');
    document.getElementById('total_ops').textContent = d.total_ops;
    document.getElementById('winrate').textContent = d.total_ops > 0 ? d.winrate + '%' : '—';
    document.getElementById('ciclo').textContent = '#' + d.ciclo_num;

    // Modo botones
    document.getElementById('btn-sim').className = 'pill-btn' + (d.modo==='simulacion'?' active-sim':'');
    document.getElementById('btn-real').className = 'pill-btn' + (d.modo==='real'?' active-real':'');

    // Botón iniciar
    if (d.corriendo) {
      document.getElementById('btn-iniciar').disabled = true;
      document.getElementById('btn-iniciar').textContent = 'Corriendo...';
    }

    // Mercados
    document.getElementById('cnt-mercados').textContent = d.mercados.length;
    if (d.mercados.length > 0) {
      document.getElementById('mercados').innerHTML = d.mercados.slice(0,8).map(m => `
        <div class="mrow">
          <div class="mname">
            ${m.pregunta.substring(0,55)}${m.pregunta.length>55?'…':''}
            <br><small>${m.outcome} · ${m.fecha_fin} · $${m.liquidez.toLocaleString()}</small>
            ${m.razonamiento ? `<br><span class="razon">💬 ${String(m.razonamiento).substring(0,120)}${m.razonamiento.length>120?"…":""}</span>` : ""}${m.biases && m.biases.length ? `<br><span style="font-size:10px;color:#EF9F27">⚡ ${m.biases.join(", ")}</span>` : ""}
          </div>
          <div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end">
            <span class="badge ${m.decision_investigador==='APOSTAR'?'op':m.decision==='OPORTUNIDAD'?'wait':'wait'}">
              ${m.decision_investigador || m.decision}
            </span>
            ${m.confianza ? `<span class="badge ${m.confianza.toLowerCase()}">${m.confianza}</span>` : ''}
          </div>
        </div>`).join('');
    }

    // Log
    document.getElementById('log').innerHTML = d.log.map(l =>
      `<div class="lrow"><span class="ltime">${l.time}</span><span class="${l.tipo||''}">${l.msg}</span></div>`
    ).join('');

    // Operaciones
    if (d.operaciones.length > 0) {
      document.getElementById('ops-container').innerHTML = `
        <table class="ops-table">
          <tr><th>Mercado</th><th>Outcome</th><th>Precio</th><th>Monto</th><th>Potencial</th><th>Kelly</th><th>Estado</th></tr>
          ${d.operaciones.map(o => `
            <tr>
              <td>${o.pregunta.substring(0,40)}…</td>
              <td>${o.outcome}</td>
              <td>${o.precio}%</td>
              <td>$${o.monto}</td>
              <td class="green">+$${o.ganancia_potencial}</td>
              <td>${o.kelly_usado ? (o.kelly_usado*100).toFixed(1)+'%' : '—'}</td>
              <td><span class="tag ${o.estado.toLowerCase()}">${o.estado}</span></td>
            </tr>`).join('')}
        </table>`;
    }
  } catch(e) { console.error(e); }
}

setInterval(actualizar, 3000);
actualizar();
setModo('simulacion');
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD)


def _startup():
    """Inicialización de Claudio — corre tanto con gunicorn como con python directo."""
    init_db()
    estado["modo"] = "simulacion"
    t = threading.Thread(target=orquestador.iniciar, daemon=True)
    t.start()


# Arranca al importar el módulo (gunicorn) y también al correr directo
_startup()

if __name__ == "__main__":
    print("=" * 50)
    print("Claudio v0.2 — http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", debug=False, port=5000, use_reloader=False)
