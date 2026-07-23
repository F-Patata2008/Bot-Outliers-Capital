"""Panel HTTP local para cambiar parametros de riesgo del bot CIPC."""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("RISK_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("RISK_SERVER_PORT", "8765"))
CONFIG_PATH = Path(os.environ.get("CIPC_RISK_CONFIG", "risk_config.json"))
BOT_SCRIPT = Path(os.environ.get("CIPC_BOT_SCRIPT", "zanni_quant_bot.py"))
BOT_PID_PATH = Path(os.environ.get("CIPC_BOT_PID", "zanni_quant_bot.pid"))
BOT_LOG_PATH = Path(os.environ.get("CIPC_BOT_LOG", "zanni_quant_bot.log"))
ENV_PATH = Path(os.environ.get("CIPC_ENV_FILE", ".env"))
HISTORY_PATH = Path(os.environ.get("CIPC_HISTORY_PATH", "trade_history.jsonl"))


FIELDS = [
    ("PAUSE_TRADING", "bool", "Pausar trading"),
    ("STOP_BOT", "bool", "Detener bot"),
    ("ORDER_QTY", "int", "Cantidad por orden"),
    ("MAX_POSITION", "int", "Posicion maxima"),
    ("MAX_OPEN_ORDERS", "int", "Ordenes abiertas max"),
    ("MIN_EDGE", "int", "Edge minimo entrada"),
    ("TAKE_PROFIT", "int", "Take profit agresivo"),
    ("MIN_PROFIT", "int", "Ganancia minima salida"),
    ("EXIT_TAKE_PROFIT", "int", "Cerrar al bid si gana"),
    ("STOP_LOSS", "int", "Stop-loss por unidad"),
    ("MIN_EQUITY_STOP", "float", "Equity minimo antes de apagar"),
    ("MAX_LOSS_STOP", "float", "Perdida maxima antes de apagar"),
    ("MAX_SPREAD_ENTER", "int", "Spread maximo para entrar"),
    ("MAX_VOLATILITY_ENTER", "float", "Volatilidad maxima para entrar"),
    ("AGGRESSION_MODE", "str", "Modo agresividad"),
    ("MOMENTUM_MODE", "str", "Modo momentum"),
    ("MOMENTUM_TREND_ENTER", "float", "Umbral tendencia momentum"),
    ("MOMENTUM_EDGE_DISCOUNT", "int", "Descuento edge en subida"),
    ("MOMENTUM_PRICE_STEP", "int", "Paso precio en subida"),
    ("DOWNTREND_EDGE_EXTRA", "int", "Edge extra en baja"),
    ("MIN_REPRICE", "int", "Ticks antes de reemplazar"),
    ("STALE_EDGE_RATIO", "float", "Cancelar si edge cae bajo ratio"),
    ("VOL_EDGE_MULT", "float", "Spread extra por volatilidad"),
    ("INVENTORY_SKEW", "float", "Skew por inventario"),
    ("POSITION_EDGE_STEP", "float", "Penalizacion por inventario"),
    ("BOOK_DEPTH", "int", "Profundidad libro"),
    ("IMBALANCE_WEIGHT", "float", "Peso imbalance libro"),
    ("FLOW_WEIGHT", "float", "Peso flujo trades"),
    ("TREND_WEIGHT", "float", "Peso tendencia"),
    ("TORCH_WEIGHT", "float", "Peso modelo online"),
    ("TORCH_MAX_ADJUST", "float", "Ajuste max modelo"),
    ("ALLOW_SHORT", "bool", "Permitir short"),
    ("ALLOW_BUY_TAKE", "bool", "Comprar agresivo"),
    ("BUY_TAKE_MAX_PREMIUM", "float", "Sobreprecio max compra actual"),
    ("FAIR_VALUE_OVERRIDE", "str", "Fair value manual"),
]


DEFAULTS = {
    "PAUSE_TRADING": False,
    "STOP_BOT": False,
    "ORDER_QTY": 1,
    "MAX_POSITION": 2,
    "MAX_OPEN_ORDERS": 1,
    "MIN_EDGE": 115,
    "TAKE_PROFIT": 160,
    "MIN_PROFIT": 24,
    "EXIT_TAKE_PROFIT": 42,
    "STOP_LOSS": 210,
    "MIN_EQUITY_STOP": 90000,
    "MAX_LOSS_STOP": 10000,
    "MAX_SPREAD_ENTER": 90,
    "MAX_VOLATILITY_ENTER": 120,
    "AGGRESSION_MODE": "competitivo_20p",
    "MOMENTUM_MODE": "auto",
    "MOMENTUM_TREND_ENTER": 6.0,
    "MOMENTUM_EDGE_DISCOUNT": 25,
    "MOMENTUM_PRICE_STEP": 18,
    "DOWNTREND_EDGE_EXTRA": 45,
    "MIN_REPRICE": 95,
    "STALE_EDGE_RATIO": 0.65,
    "VOL_EDGE_MULT": 1.5,
    "INVENTORY_SKEW": 1.2,
    "POSITION_EDGE_STEP": 8.0,
    "BOOK_DEPTH": 3,
    "IMBALANCE_WEIGHT": 0.35,
    "FLOW_WEIGHT": 0.20,
    "TREND_WEIGHT": 8.0,
    "TORCH_WEIGHT": 0.35,
    "TORCH_MAX_ADJUST": 35,
    "ALLOW_SHORT": False,
    "ALLOW_BUY_TAKE": False,
    "BUY_TAKE_MAX_PREMIUM": 25.0,
    "FAIR_VALUE_OVERRIDE": "",
}


PRESETS = {
    "supervivencia": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 1,
        "MAX_POSITION": 1,
        "MIN_EDGE": 180,
        "TAKE_PROFIT": 220,
        "MIN_PROFIT": 30,
        "EXIT_TAKE_PROFIT": 55,
        "STOP_LOSS": 150,
        "MIN_EQUITY_STOP": 94000,
        "MAX_LOSS_STOP": 6000,
        "MAX_SPREAD_ENTER": 55,
        "MAX_VOLATILITY_ENTER": 70,
        "AGGRESSION_MODE": "supervivencia",
        "MOMENTUM_MODE": "auto",
        "MOMENTUM_TREND_ENTER": 8.0,
        "MOMENTUM_EDGE_DISCOUNT": 8,
        "MOMENTUM_PRICE_STEP": 5,
        "DOWNTREND_EDGE_EXTRA": 80,
        "MIN_REPRICE": 120,
        "VOL_EDGE_MULT": 2.0,
        "TORCH_WEIGHT": 0.25,
        "TORCH_MAX_ADJUST": 25,
    },
    "competitivo_20p": DEFAULTS,
    "recuperacion_controlada": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 1,
        "MAX_POSITION": 3,
        "MIN_EDGE": 95,
        "TAKE_PROFIT": 135,
        "MIN_PROFIT": 22,
        "EXIT_TAKE_PROFIT": 38,
        "STOP_LOSS": 190,
        "MIN_EQUITY_STOP": 90000,
        "MAX_LOSS_STOP": 10000,
        "MAX_SPREAD_ENTER": 110,
        "MAX_VOLATILITY_ENTER": 150,
        "AGGRESSION_MODE": "recuperacion_controlada",
        "MOMENTUM_MODE": "auto",
        "MOMENTUM_TREND_ENTER": 6.0,
        "MOMENTUM_EDGE_DISCOUNT": 30,
        "MOMENTUM_PRICE_STEP": 22,
        "DOWNTREND_EDGE_EXTRA": 50,
        "MIN_REPRICE": 85,
        "VOL_EDGE_MULT": 1.2,
        "TORCH_WEIGHT": 0.40,
        "TORCH_MAX_ADJUST": 40,
    },
    "sprint_final": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 1,
        "MAX_POSITION": 4,
        "MIN_EDGE": 75,
        "TAKE_PROFIT": 115,
        "MIN_PROFIT": 20,
        "EXIT_TAKE_PROFIT": 32,
        "STOP_LOSS": 170,
        "MIN_EQUITY_STOP": 91000,
        "MAX_LOSS_STOP": 9000,
        "MAX_SPREAD_ENTER": 140,
        "MAX_VOLATILITY_ENTER": 190,
        "AGGRESSION_MODE": "sprint_final",
        "MOMENTUM_MODE": "alcista",
        "MOMENTUM_TREND_ENTER": 5.0,
        "MOMENTUM_EDGE_DISCOUNT": 40,
        "MOMENTUM_PRICE_STEP": 35,
        "DOWNTREND_EDGE_EXTRA": 35,
        "MIN_REPRICE": 75,
        "VOL_EDGE_MULT": 1.0,
        "TORCH_WEIGHT": 0.45,
        "TORCH_MAX_ADJUST": 45,
    },
    "momentum_alcista": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 1,
        "MAX_POSITION": 3,
        "MIN_EDGE": 85,
        "TAKE_PROFIT": 125,
        "MIN_PROFIT": 20,
        "EXIT_TAKE_PROFIT": 34,
        "STOP_LOSS": 180,
        "MIN_EQUITY_STOP": 91000,
        "MAX_LOSS_STOP": 9000,
        "MAX_SPREAD_ENTER": 120,
        "MAX_VOLATILITY_ENTER": 160,
        "AGGRESSION_MODE": "momentum_alcista",
        "MOMENTUM_MODE": "alcista",
        "MOMENTUM_TREND_ENTER": 5.0,
        "MOMENTUM_EDGE_DISCOUNT": 35,
        "MOMENTUM_PRICE_STEP": 30,
        "DOWNTREND_EDGE_EXTRA": 55,
        "MIN_REPRICE": 80,
        "VOL_EDGE_MULT": 1.15,
        "TORCH_WEIGHT": 0.42,
        "TORCH_MAX_ADJUST": 42,
    },
    "comprador_actual": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 6,
        "MAX_POSITION": 18,
        "MAX_OPEN_ORDERS": 2,
        "MIN_EDGE": 22,
        "TAKE_PROFIT": 70,
        "MIN_PROFIT": 500,
        "EXIT_TAKE_PROFIT": 500,
        "STOP_LOSS": 160,
        "MIN_EQUITY_STOP": 80000,
        "MAX_LOSS_STOP": 25000,
        "MAX_SPREAD_ENTER": 130,
        "MAX_VOLATILITY_ENTER": 160,
        "AGGRESSION_MODE": "comprador_actual",
        "MOMENTUM_MODE": "auto",
        "MOMENTUM_TREND_ENTER": 6.0,
        "MOMENTUM_EDGE_DISCOUNT": 18,
        "MOMENTUM_PRICE_STEP": 18,
        "DOWNTREND_EDGE_EXTRA": 55,
        "MIN_REPRICE": 25,
        "VOL_EDGE_MULT": 1.5,
        "ALLOW_BUY_TAKE": True,
        "BUY_TAKE_MAX_PREMIUM": 35.0,
        "TORCH_WEIGHT": 0.35,
        "TORCH_MAX_ADJUST": 35,
    },
    "bajista_defensivo": {
        **DEFAULTS,
        "PAUSE_TRADING": False,
        "STOP_BOT": False,
        "ORDER_QTY": 1,
        "MAX_POSITION": 0,
        "MIN_EDGE": 240,
        "TAKE_PROFIT": 260,
        "MIN_PROFIT": 18,
        "EXIT_TAKE_PROFIT": 26,
        "STOP_LOSS": 130,
        "MIN_EQUITY_STOP": 94000,
        "MAX_LOSS_STOP": 6000,
        "MAX_SPREAD_ENTER": 45,
        "MAX_VOLATILITY_ENTER": 60,
        "AGGRESSION_MODE": "bajista_defensivo",
        "MOMENTUM_MODE": "bajista",
        "MOMENTUM_TREND_ENTER": 5.0,
        "MOMENTUM_EDGE_DISCOUNT": 0,
        "MOMENTUM_PRICE_STEP": 0,
        "DOWNTREND_EDGE_EXTRA": 120,
        "MIN_REPRICE": 130,
        "VOL_EDGE_MULT": 2.2,
        "TORCH_WEIGHT": 0.20,
        "TORCH_MAX_ADJUST": 20,
    },
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    config = dict(DEFAULTS)
    config.update({k: v for k, v in data.items() if k in DEFAULTS})
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: config.get(key, DEFAULTS[key]) for key in DEFAULTS}
    fd, tmp_path = tempfile.mkstemp(prefix=".risk_config.", suffix=".json", dir=str(CONFIG_PATH.parent or "."))
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(clean, file, indent=2, sort_keys=True)
        file.write("\n")
    os.replace(tmp_path, CONFIG_PATH)


def cast_value(raw: str, kind: str):
    if kind == "bool":
        return raw.lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return raw.strip()


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid_file() -> int | None:
    try:
        pid = int(BOT_PID_PATH.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    if pid_is_running(pid):
        return pid
    try:
        BOT_PID_PATH.unlink()
    except OSError:
        pass
    return None


def find_bot_pid() -> int | None:
    pid = read_pid_file()
    if pid:
        return pid

    proc_root = Path("/proc")
    if not proc_root.exists():
        return None
    current_pid = os.getpid()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid_value = int(entry.name)
        if pid_value == current_pid:
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except OSError:
            continue
        if "zanni_quant_bot.py" in cmdline:
            return pid_value
    return None


def start_bot() -> int | None:
    existing = find_bot_pid()
    if existing:
        return existing

    env = os.environ.copy()
    env.update(load_env_file())
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("CIPC_RISK_CONFIG", str(CONFIG_PATH))
    env.setdefault("CIPC_HISTORY_PATH", "trade_history.jsonl")

    with BOT_LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(BOT_SCRIPT)],
            cwd=str(Path.cwd()),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    BOT_PID_PATH.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def load_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values = {}
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def history_metrics() -> str:
    if not HISTORY_PATH.exists():
        return "Historial: sin datos todavia."

    fills = []
    last_snapshot = None
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "Historial: no se pudo leer."

    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "fill":
            fills.append(row)
        elif row.get("event") == "snapshot":
            last_snapshot = row

    inventory = []
    profits = []
    for fill in fills:
        side = fill.get("side")
        qty = int(fill.get("qty") or 0)
        price = float(fill.get("price") or 0)
        if qty <= 0 or price <= 0:
            continue
        if side == "buy":
            inventory.extend([price] * qty)
        elif side == "sell":
            for _ in range(qty):
                if not inventory:
                    continue
                profits.append(price - inventory.pop(0))

    if profits:
        avg = sum(profits) / len(profits)
        wins = sum(1 for profit in profits if profit > 0)
        metrics = (
            f"Historial: vueltas={len(profits)} avg/accion={avg:.1f} "
            f"win_rate={wins / len(profits):.0%} min={min(profits):.1f} max={max(profits):.1f}"
        )
    else:
        metrics = f"Historial: fills={len(fills)} sin vueltas cerradas."

    if last_snapshot:
        metrics += (
            f" | ultimo pnl={last_snapshot.get('pnl')} "
            f"equity={last_snapshot.get('equity')} pos={last_snapshot.get('position')}"
        )
    if inventory:
        metrics += f" | inventario medido={len(inventory)}"
    return metrics


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/action":
            name = parse_qs(parsed.query).get("name", [""])[0]
            self.apply_action(name)
            self.redirect("/")
            return
        if parsed.path == "/preset":
            name = parse_qs(parsed.query).get("name", [""])[0]
            if name in PRESETS:
                save_config(PRESETS[name])
                self.redirect("/")
                return
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        self.render()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        action = form.get("action", [""])[0]
        if action:
            self.apply_action(action)
            self.redirect("/")
            return

        config = load_config()
        for key, kind, _label in FIELDS:
            if kind == "bool":
                config[key] = key in form
                continue
            value = form.get(key, [""])[0]
            try:
                config[key] = cast_value(value, kind)
            except ValueError:
                pass
        save_config(config)
        self.redirect("/")

    def apply_action(self, name):
        config = load_config()
        if name == "start":
            config["PAUSE_TRADING"] = False
            config["STOP_BOT"] = False
            save_config(config)
            start_bot()
            return
        if name == "pause":
            config["PAUSE_TRADING"] = True
            config["STOP_BOT"] = False
        elif name == "resume":
            config["PAUSE_TRADING"] = False
            config["STOP_BOT"] = False
        elif name == "stop":
            config["PAUSE_TRADING"] = True
            config["STOP_BOT"] = True
        save_config(config)

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def render(self):
        config = load_config()
        bot_pid = find_bot_pid()
        bot_state = f"vivo PID {bot_pid}" if bot_pid else "no ejecutandose"
        status = (
            "DETENIDO"
            if config.get("STOP_BOT")
            else "LISTO"
            if not bot_pid
            else "PAUSADO"
            if config.get("PAUSE_TRADING")
            else "OPERANDO"
        )
        status_class = (
            "danger"
            if config.get("STOP_BOT")
            else "warn"
            if not bot_pid or config.get("PAUSE_TRADING")
            else "ok"
        )
        status_help = (
            "Proceso apagado al siguiente ciclo; reinicia el bot para volver a operar."
            if config.get("STOP_BOT")
            else "El bot no esta corriendo; usa Iniciar bot para arrancarlo con esta configuracion."
            if not bot_pid
            else "Conexion viva, ordenes abiertas canceladas y sin ordenes nuevas."
            if config.get("PAUSE_TRADING")
            else "El bot puede enviar, reemplazar y cancelar ordenes segun la estrategia."
        )
        rows = []
        for key, kind, label in FIELDS:
            value = config.get(key, DEFAULTS[key])
            if kind == "bool":
                checked = "checked" if value else ""
                field = f'<input type="checkbox" name="{key}" {checked}>'
            elif key == "MOMENTUM_MODE":
                options = ("auto", "alcista", "bajista", "neutral")
                field = '<select name="MOMENTUM_MODE">' + "".join(
                    f'<option value="{html.escape(option)}" {"selected" if str(value) == option else ""}>'
                    f"{html.escape(option)}</option>"
                    for option in options
                ) + "</select>"
            elif key == "AGGRESSION_MODE":
                options = tuple(PRESETS.keys())
                field = '<select name="AGGRESSION_MODE">' + "".join(
                    f'<option value="{html.escape(option)}" {"selected" if str(value) == option else ""}>'
                    f"{html.escape(option)}</option>"
                    for option in options
                ) + "</select>"
            else:
                safe = html.escape(str(value))
                step = "1" if kind == "int" else "0.01"
                input_type = "number" if kind in ("int", "float") else "text"
                field = f'<input type="{input_type}" step="{step}" name="{key}" value="{safe}">'
            rows.append(f"<label><span>{html.escape(label)}</span>{field}</label>")

        preset_links = " ".join(
            f'<a class="preset" href="/preset?name={html.escape(name)}">{html.escape(name)}</a>'
            for name in PRESETS
        )
        history_text = history_metrics()
        body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="10">
  <title>CIPC Risk Control</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #10141b; color: #e8edf4; }}
    main {{ max-width: 860px; margin: auto; }}
    h1 {{ font-size: 24px; }}
    form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    label {{ display: grid; gap: 6px; padding: 10px; background: #171d26; border: 1px solid #2a3443; border-radius: 8px; }}
    span {{ color: #aab5c4; font-size: 13px; }}
    input {{ font: inherit; padding: 8px; border-radius: 6px; border: 1px solid #384455; background: #0d1117; color: #e8edf4; }}
    select {{ font: inherit; padding: 8px; border-radius: 6px; border: 1px solid #384455; background: #0d1117; color: #e8edf4; }}
    input[type=checkbox] {{ width: 24px; height: 24px; }}
    button, .preset {{ display: inline-block; margin: 14px 8px 14px 0; padding: 10px 12px; border-radius: 7px; border: 0; background: #2f80ed; color: white; text-decoration: none; font-weight: 700; }}
    .preset {{ background: #293548; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0; }}
    .actions form {{ display: inline; }}
    .actions button {{ margin: 0; min-width: 132px; }}
    .start {{ background: #2563eb; }}
    .pause {{ background: #d69e2e; }}
    .resume {{ background: #2f855a; }}
    .stop {{ background: #c53030; }}
    .status {{ display: inline-block; padding: 8px 10px; border-radius: 7px; font-weight: 800; }}
    .ok {{ background: #11391f; color: #7ee099; }}
    .warn {{ background: #3b2b10; color: #ffd37a; }}
    .danger {{ background: #421818; color: #ff9a9a; }}
    .note {{ color: #9aa7b8; line-height: 1.45; }}
    .metrics {{ padding: 10px; background: #171d26; border: 1px solid #2a3443; border-radius: 8px; color: #d4dbe7; }}
    .hotkeys {{ color: #9aa7b8; font-size: 13px; margin-top: -4px; }}
  </style>
  <script>
    function submitAction(action) {{
      const form = document.querySelector(`form[data-action="${{action}}"]`);
      if (form) form.submit();
    }}
    window.addEventListener("keydown", (event) => {{
      if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
      const key = event.key.toLowerCase();
      if (key === "i") submitAction("start");
      if (key === "p") submitAction("pause");
      if (key === "r") submitAction("resume");
      if (key === "s") submitAction("stop");
    }});
  </script>
</head>
<body>
  <main>
    <h1>CIPC Risk Control</h1>
    <p>Estado: <span class="status {status_class}">{status}</span></p>
    <p>Proceso bot: <strong>{html.escape(bot_state)}</strong></p>
    <p class="note">{html.escape(status_help)}</p>
    <div class="actions">
      <form data-action="start" method="post"><input type="hidden" name="action" value="start"><button class="start" type="submit">Iniciar bot</button></form>
      <form data-action="pause" method="post"><input type="hidden" name="action" value="pause"><button class="pause" type="submit">Pausar bot</button></form>
      <form data-action="resume" method="post"><input type="hidden" name="action" value="resume"><button class="resume" type="submit">Reanudar</button></form>
      <form data-action="stop" method="post"><input type="hidden" name="action" value="stop"><button class="stop" type="submit">Detener bot</button></form>
    </div>
    <p class="hotkeys">Atajos: I iniciar, P pausar, R reanudar, S detener. Guardar cambios tambien se toma en el siguiente ciclo del bot.</p>
    <p class="note">Pausar cancela ordenes abiertas y mantiene el proceso vivo sin operar. Detener cancela ordenes y apaga el bot.</p>
    <p class="note">Momentum: auto evita comprar si detecta baja; alcista exige subida confirmada y entra mas cerca del ask; bajista bloquea compras y sale antes si ya hay ganancia; neutral ignora momentum.</p>
    <p class="metrics">{html.escape(history_text)}</p>
    <p>{preset_links}</p>
    <form method="post">
      {''.join(rows)}
      <button type="submit">Guardar cambios</button>
    </form>
  </main>
</body>
</html>"""
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[risk-server] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    save_config(load_config())
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Risk control server: http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
