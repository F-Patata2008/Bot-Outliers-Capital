import json
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk
from urllib.parse import urlencode, urljoin, urlparse

import requests

try:
    import websocket
except ImportError:
    websocket = None


BASE_URL = "https://outliers.progcomp.cl"


@dataclass
class MarketState:
    book: dict = field(default_factory=lambda: {"bids": [], "asks": []})
    trades: list = field(default_factory=list)
    prices: list = field(default_factory=list)
    news: list = field(default_factory=list)
    status: dict = field(
        default_factory=lambda: {
            "instrument": "KUKI",
            "state": "idle",
            "mark": 0,
            "settle_price": None,
            "pos_limit": 100,
            "max_order_qty": 50,
        }
    )
    connected: bool = False


class OutliersClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token = None

    def set_token(self, token):
        self.token = token.strip() or None

    def request(self, path, method=None, body=None, timeout=10):
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        method = method or ("POST" if body is not None else "GET")
        response = self.session.request(method, url, headers=headers, json=body, timeout=timeout)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise RuntimeError(detail if isinstance(detail, str) else f"HTTP {response.status_code}")
        return data

    def login(self, username, password):
        data = self.request("/api/login", body={"username": username, "password": password})
        self.token = data["token"]
        return data.get("user", {})

    def me(self):
        return self.request("/api/me")

    def account(self):
        return self.request("/api/c2/account")

    def leaderboard(self):
        return self.request("/api/c2/leaderboard")

    def market_ws_url(self, private=False):
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = "/ws/private" if private else "/ws/market"
        query = ""
        if private:
            query = "?" + urlencode({"token": self.token or ""})
        return f"{scheme}://{parsed.netloc}{path}{query}"


def apply_market_message(state, message):
    kind = message.get("type")
    if kind == "snapshot":
        state.book = message.get("book", state.book)
        state.trades = list(reversed(message.get("trades", [])))
        state.prices = message.get("prices", state.prices)
        state.news = list(reversed(message.get("news", [])))
        state.status = message.get("status", state.status)
    elif kind == "trade":
        state.trades = [message, *state.trades][:60]
        state.prices = [*state.prices, {"t": message.get("ts"), "p": message.get("price")}][-1500:]
        state.status = {**state.status, "mark": message.get("price", state.status.get("mark", 0))}
    elif kind == "tick":
        state.prices = [*state.prices, {"t": message.get("t"), "p": message.get("p")}][-1500:]
    elif kind == "book":
        state.book = {"bids": message.get("bids", []), "asks": message.get("asks", [])}
    elif kind == "news":
        state.news = [{"ts": message.get("ts"), "headline": message.get("headline")}, *state.news][:30]
    elif kind == "status":
        state.status = message


class OutliersApiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Outliers API Assistant")
        self.geometry("1120x760")
        self.minsize(980, 650)

        self.client = OutliersClient()
        self.market = MarketState()
        self.account_data = None
        self.event_queue = queue.Queue()
        self.ws_app = None
        self.ws_thread = None
        self.poll_job = None

        self.base_url_var = tk.StringVar(value=BASE_URL)
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Sin conectar.")
        self.target_var = tk.StringVar(value="13000")
        self.qty_var = tk.StringVar(value="1")
        self.min_gain_var = tk.StringVar(value="100")
        self.manual_price_var = tk.StringVar()
        self.side_var = tk.StringVar(value="buy")
        self.signal_var = tk.StringVar(value="SIN DATOS")

        self._build_ui()
        self.after(150, self._drain_events)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(top, text="Usuario").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.username_var, width=16).grid(row=0, column=3, padx=(6, 10))
        ttk.Label(top, text="Clave").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.password_var, show="*", width=16).grid(row=0, column=5, padx=(6, 10))
        ttk.Button(top, text="Login", command=self.login).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(top, text="Conectar feed", command=self.connect_market).grid(row=0, column=7)

        token_row = ttk.Frame(self, padding=(12, 0, 12, 8))
        token_row.grid(row=1, column=0, sticky="ew")
        token_row.columnconfigure(1, weight=1)
        ttk.Label(token_row, text="Token").grid(row=0, column=0, sticky="w")
        ttk.Entry(token_row, textvariable=self.token_var, show="*", width=60).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Button(token_row, text="Usar token", command=self.use_token).grid(row=0, column=2)

        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.rowconfigure(2, weight=1)

        self.dashboard = ttk.Frame(notebook, padding=12)
        self.dashboard.columnconfigure(0, weight=1)
        self.dashboard.columnconfigure(1, weight=1)
        self.dashboard.rowconfigure(1, weight=1)
        notebook.add(self.dashboard, text="Trading")

        calc = ttk.LabelFrame(self.dashboard, text="Ganancia objetivo", padding=12)
        calc.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        calc.columnconfigure(1, weight=1)

        ttk.Label(calc, text="Precio objetivo").grid(row=0, column=0, sticky="w")
        ttk.Entry(calc, textvariable=self.target_var, width=12).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(calc, text="Cantidad").grid(row=0, column=2, sticky="w")
        ttk.Entry(calc, textvariable=self.qty_var, width=8).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(calc, text="Ganancia min/u").grid(row=0, column=4, sticky="w")
        ttk.Entry(calc, textvariable=self.min_gain_var, width=10).grid(row=0, column=5, sticky="w", padx=(8, 0))

        ttk.Label(calc, text="Precio manual").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(calc, textvariable=self.manual_price_var, width=12).grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(8, 0))
        ttk.Radiobutton(calc, text="Comprar", variable=self.side_var, value="buy", command=self.update_profit).grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Radiobutton(calc, text="Vender", variable=self.side_var, value="sell", command=self.update_profit).grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Button(calc, text="Calcular", command=self.update_profit).grid(row=1, column=5, sticky="e", pady=(8, 0))

        signal = ttk.LabelFrame(self.dashboard, text="Senal", padding=12)
        signal.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 10))
        signal.columnconfigure(0, weight=1)
        ttk.Label(signal, textvariable=self.signal_var, font=("TkDefaultFont", 18, "bold"), anchor="center").grid(row=0, column=0, sticky="ew")

        self.market_text = tk.Text(self.dashboard, height=20, wrap="word", padx=8, pady=8)
        self.market_text.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.account_text = tk.Text(self.dashboard, height=20, wrap="word", padx=8, pady=8)
        self.account_text.grid(row=1, column=1, sticky="nsew", padx=(8, 0))

        buttons = ttk.Frame(self.dashboard)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Refrescar cuenta", command=self.refresh_account).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Leaderboard", command=self.refresh_leaderboard).pack(side=tk.LEFT, padx=(8, 0))

        self.log_text = tk.Text(notebook, height=10, wrap="word", padx=8, pady=8)
        notebook.add(self.log_text, text="Log")

        footer = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 6))
        footer.grid(row=3, column=0, sticky="ew")

    def configure_client(self):
        self.client = OutliersClient(self.base_url_var.get())
        if self.token_var.get().strip():
            self.client.set_token(self.token_var.get())

    def login(self):
        self.configure_client()
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            messagebox.showerror("Outliers API", "Ingresa usuario y clave.")
            return
        self._run("login", lambda: self._login_worker(username, password))

    def _login_worker(self, username, password):
        user = self.client.login(username, password)
        self.event_queue.put(("token", self.client.token or ""))
        self.event_queue.put(("log", f"Login OK: {user.get('username', username)}"))
        self.event_queue.put(("status", "Autenticado."))
        self.event_queue.put(("account", self.client.account()))

    def use_token(self):
        self.configure_client()
        self._run("me", self._me_worker)

    def _me_worker(self):
        user = self.client.me()
        self.event_queue.put(("log", f"Token OK: {user.get('username', 'usuario')}"))
        self.event_queue.put(("status", "Token activo."))
        self.event_queue.put(("account", self.client.account()))

    def connect_market(self):
        self.configure_client()
        if websocket is None:
            messagebox.showerror(
                "Outliers API",
                "Falta websocket-client. Instala con: python3 -m pip install -r requirements.txt",
            )
            return
        if self.ws_app:
            self.ws_app.close()
            self.ws_app = None
            self.status_var.set("Feed desconectado.")
            return

        url = self.client.market_ws_url(private=False)
        self.ws_app = websocket.WebSocketApp(
            url,
            on_open=lambda _ws: self.event_queue.put(("market_connected", None)),
            on_message=lambda _ws, msg: self.event_queue.put(("market_message", msg)),
            on_error=lambda _ws, err: self.event_queue.put(("log", f"WS error: {err}")),
            on_close=lambda _ws, _code, _reason: self.event_queue.put(("market_closed", None)),
        )
        self.ws_thread = threading.Thread(target=self.ws_app.run_forever, daemon=True)
        self.ws_thread.start()
        self.status_var.set("Conectando feed de mercado...")
        if self.poll_job is None:
            self.poll_job = self.after(2000, self._poll_account_loop)

    def refresh_account(self):
        self._run("account", self._account_worker)

    def _account_worker(self):
        account = self.client.account()
        self.event_queue.put(("account", account))
        self.event_queue.put(("status", "Cuenta actualizada."))

    def refresh_leaderboard(self):
        self._run("leaderboard", self._leaderboard_worker)

    def _leaderboard_worker(self):
        data = self.client.leaderboard()
        entries = data.get("entries", [])
        lines = ["Leaderboard trading:"]
        for entry in entries[:15]:
            name = entry.get("name") or entry.get("team") or entry.get("username") or "-"
            lines.append(f"{name}: PnL {entry.get('pnl', 0)} · pos {entry.get('position', 0)}")
        self.event_queue.put(("log", "\n".join(lines)))

    def _poll_account_loop(self):
        if self.client.token:
            self.refresh_account()
        self.poll_job = self.after(2000, self._poll_account_loop)

    def _run(self, label, fn):
        def runner():
            try:
                fn()
            except Exception as exc:
                self.event_queue.put(("log", f"{label}: {exc}"))
                self.event_queue.put(("status", f"Error en {label}."))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_events(self):
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "market_connected":
                self.market.connected = True
                self.status_var.set("Feed de mercado conectado.")
                self.log("Feed de mercado conectado.")
            elif kind == "market_closed":
                self.market.connected = False
                self.status_var.set("Feed de mercado cerrado.")
                self.log("Feed de mercado cerrado.")
                self.ws_app = None
            elif kind == "market_message":
                try:
                    apply_market_message(self.market, json.loads(payload))
                    self.render_market()
                    self.update_profit()
                except Exception as exc:
                    self.log(f"Mensaje mercado invalido: {exc}")
            elif kind == "account":
                self.account_data = payload
                self.render_account()
                self.update_profit()
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "log":
                self.log(payload)
            elif kind == "token":
                self.token_var.set(payload)

        self.after(150, self._drain_events)

    def render_market(self):
        bids = self.market.book.get("bids", [])
        asks = self.market.book.get("asks", [])
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        status = self.market.status
        trades = self.market.trades[:10]
        lines = [
            "Mercado",
            f"Instrumento: {status.get('instrument', 'KUKI')}",
            f"Estado: {status.get('state', '-')}",
            f"Ultimo/mark: {status.get('mark', 0)}",
            f"Best bid: {best_bid}",
            f"Best ask: {best_ask}",
            f"Limite posicion: ±{status.get('pos_limit', '-')}",
            f"Max orden: {status.get('max_order_qty', '-')}",
            "",
            "Ultimos trades:",
        ]
        for trade in trades:
            lines.append(f"{trade.get('qty')} @ {trade.get('price')} · {trade.get('aggressor', '-')}")
        self.replace_text(self.market_text, "\n".join(lines))

    def render_account(self):
        account = self.account_data or {}
        open_orders = account.get("open_orders", [])
        lines = [
            "Mi cuenta",
            f"Posicion: {account.get('position', 0)}",
            f"Precio promedio: {account.get('avg_price', 0)}",
            f"Cash: {account.get('cash', 0)}",
            f"PnL realizado: {account.get('realized', 0)}",
            f"PnL no realizado: {account.get('unrealized', 0)}",
            f"Busted: {account.get('busted', False)}",
            "",
            "Ordenes abiertas:",
        ]
        if not open_orders:
            lines.append("Sin ordenes abiertas")
        for order in open_orders:
            lines.append(
                f"#{order.get('id')} {order.get('side')} "
                f"{order.get('remaining')}/{order.get('qty')} @ {order.get('price')}"
            )
        self.replace_text(self.account_text, "\n".join(lines))

    def update_profit(self):
        try:
            target = float(self.target_var.get())
            qty = float(self.qty_var.get())
            min_gain = float(self.min_gain_var.get())
        except ValueError:
            self.signal_var.set("DATOS INVALIDOS")
            return

        bids = self.market.book.get("bids", [])
        asks = self.market.book.get("asks", [])
        side = self.side_var.get()
        manual_price = self.parse_optional_float(self.manual_price_var.get())
        market_price = asks[0][0] if side == "buy" and asks else bids[0][0] if side == "sell" and bids else None
        entry_price = manual_price if manual_price is not None else market_price

        if entry_price is None:
            self.signal_var.set("ESPERAR · SIN PRECIO")
            return

        if side == "buy":
            gain_per_unit = target - entry_price
            action = "COMPRAR" if gain_per_unit >= min_gain else "ESPERAR"
        else:
            gain_per_unit = entry_price - target
            action = "VENDER" if gain_per_unit >= min_gain else "ESPERAR"

        planned_gain = gain_per_unit * qty
        realized = float((self.account_data or {}).get("realized", 0) or 0)
        unrealized = float((self.account_data or {}).get("unrealized", 0) or 0)
        projected_total = realized + unrealized + planned_gain
        self.signal_var.set(f"{action} · {planned_gain:,.0f}")
        self.log_profit(entry_price, gain_per_unit, planned_gain, projected_total)

    def log_profit(self, entry_price, gain_per_unit, planned_gain, projected_total):
        account = self.account_data or {}
        text = (
            f"Precio entrada: {entry_price:,.0f}\n"
            f"Ganancia por unidad: {gain_per_unit:,.0f}\n"
            f"Ganancia planificada: {planned_gain:,.0f}\n"
            f"PnL total proyectado: {projected_total:,.0f}\n"
            f"Posicion actual: {account.get('position', 0)} @ {account.get('avg_price', 0)}\n"
            f"Actualizado: {time.strftime('%H:%M:%S')}"
        )
        current = self.account_text.get("1.0", tk.END).strip()
        marker = "\n\nCalculo de ganancia\n"
        base = current.split(marker)[0]
        self.replace_text(self.account_text, base + marker + text)

    def log(self, message):
        self.log_text.insert(tk.END, message.rstrip() + "\n")
        self.log_text.see(tk.END)

    @staticmethod
    def parse_optional_float(value):
        value = value.strip()
        if not value:
            return None
        return float(value)

    @staticmethod
    def replace_text(widget, text):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)


def main():
    app = OutliersApiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
