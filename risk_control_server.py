"""Panel HTTP local para cambiar parametros de riesgo del bot CIPC."""
from __future__ import annotations

import html
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("RISK_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("RISK_SERVER_PORT", "8765"))
CONFIG_PATH = Path(os.environ.get("CIPC_RISK_CONFIG", "risk_config.json"))


FIELDS = [
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
    ("FAIR_VALUE_OVERRIDE", "str", "Fair value manual"),
]


DEFAULTS = {
    "ORDER_QTY": 1,
    "MAX_POSITION": 6,
    "MAX_OPEN_ORDERS": 1,
    "MIN_EDGE": 90,
    "TAKE_PROFIT": 140,
    "MIN_PROFIT": 18,
    "EXIT_TAKE_PROFIT": 35,
    "STOP_LOSS": 260,
    "MIN_EQUITY_STOP": 89500,
    "MAX_LOSS_STOP": 11000,
    "MIN_REPRICE": 80,
    "STALE_EDGE_RATIO": 0.65,
    "VOL_EDGE_MULT": 1.2,
    "INVENTORY_SKEW": 0.9,
    "POSITION_EDGE_STEP": 1.5,
    "BOOK_DEPTH": 3,
    "IMBALANCE_WEIGHT": 0.35,
    "FLOW_WEIGHT": 0.20,
    "TREND_WEIGHT": 8.0,
    "TORCH_WEIGHT": 0.45,
    "TORCH_MAX_ADJUST": 45,
    "ALLOW_SHORT": False,
    "ALLOW_BUY_TAKE": False,
    "FAIR_VALUE_OVERRIDE": "",
}


PRESETS = {
    "conservador": {
        **DEFAULTS,
        "ORDER_QTY": 1,
        "MAX_POSITION": 4,
        "MIN_EDGE": 120,
        "TAKE_PROFIT": 180,
        "EXIT_TAKE_PROFIT": 45,
        "STOP_LOSS": 220,
        "MIN_EQUITY_STOP": 90000,
        "MAX_LOSS_STOP": 10500,
        "MIN_REPRICE": 100,
        "VOL_EDGE_MULT": 1.8,
    },
    "balanceado": DEFAULTS,
    "agresivo_limitado": {
        **DEFAULTS,
        "ORDER_QTY": 2,
        "MAX_POSITION": 10,
        "MIN_EDGE": 70,
        "TAKE_PROFIT": 110,
        "EXIT_TAKE_PROFIT": 30,
        "MIN_REPRICE": 55,
        "VOL_EDGE_MULT": 1.0,
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
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

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def render(self):
        config = load_config()
        rows = []
        for key, kind, label in FIELDS:
            value = config.get(key, DEFAULTS[key])
            if kind == "bool":
                checked = "checked" if value else ""
                field = f'<input type="checkbox" name="{key}" {checked}>'
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
    input[type=checkbox] {{ width: 24px; height: 24px; }}
    button, .preset {{ display: inline-block; margin: 14px 8px 14px 0; padding: 10px 12px; border-radius: 7px; border: 0; background: #2f80ed; color: white; text-decoration: none; font-weight: 700; }}
    .preset {{ background: #293548; }}
    .note {{ color: #9aa7b8; line-height: 1.45; }}
  </style>
</head>
<body>
  <main>
    <h1>CIPC Risk Control</h1>
    <p class="note">Guarda y el bot lo toma en el siguiente ciclo. Presets inspirados en inventario Avellaneda-Stoikov, imbalance/OFI y control de rotacion.</p>
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
