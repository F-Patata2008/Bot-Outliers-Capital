"""SDK del CIPC Trading Challenge.

Dos clases, dos conexiones. Hereda de ellas y sobreescribe los métodos on_*
para reaccionar a los eventos:

    class MyTrading(TradingConnection):
        def on_fill(self, report):
            print("fill!", report["qty"], "@", report["price"])

    md = MarketDataConnection(host, port)      # market data pública (WebSocket)
    trading = MyTrading(host, port)            # órdenes + execution reports

    trading.login("mi_usuario", "mi_password")
    trading.connect()                          # execution reports en tiempo real
    md.connect()
    md.wait_ready()

    trading.new_order(side="buy", price=md.best_bid(), qty=5)

IMPORTANTE — cancel-on-disconnect: si pierdes todas tus conexiones privadas
(trading.connect()) por más de ~5 segundos, el exchange cancela automáticamente
todas tus órdenes abiertas.

Requiere:  pip install requests websocket-client
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

import requests
import websocket  # paquete: websocket-client


class CipcError(Exception):
    """Orden rechazada o request inválido (el mensaje explica el motivo)."""


class _ReconnectingWS:
    """WebSocket en un hilo de fondo que se reconecta solo."""

    def __init__(self, url: str, handler):
        self._url = url
        self._handler = handler
        self._stop = False
        self._app: websocket.WebSocketApp | None = None
        self.connected = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop = True
        try:
            if self._app is not None:
                self._app.close()
        except Exception:
            pass

    def _run(self) -> None:
        while not self._stop:
            try:
                self._app = websocket.WebSocketApp(
                    self._url,
                    on_open=lambda ws: setattr(self, "connected", True),
                    on_message=lambda ws, raw: self._dispatch(raw),
                    on_close=lambda ws, *a: setattr(self, "connected", False),
                    on_error=lambda ws, e: None,
                )
                self._app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            self.connected = False
            if not self._stop:
                time.sleep(2)

    def _dispatch(self, raw: str) -> None:
        try:
            self._handler(json.loads(raw))
        except Exception:
            pass  # un error en tu callback no debe tumbar la conexión


class MarketDataConnection:
    """Market data pública en tiempo real.

    Mantiene el estado siempre actualizado (atributos como .book y .last_price).
    Para reaccionar a eventos, hereda y sobreescribe los métodos on_*:

        class MyMarketData(MarketDataConnection):
            def on_news(self, news):
                print("NOTICIA:", news["headline"])

            def on_trade(self, trade):
                print("trade", trade["price"], trade["qty"])
    """

    def __init__(self, host: str, port: int = 443):
        ws_scheme = "wss" if port == 443 else "ws"
        self._url = f"{ws_scheme}://{host}:{port}/ws/market"
        self._ws: _ReconnectingWS | None = None
        self._got_snapshot = threading.Event()

        # Estado (se actualiza solo):
        self.book: dict = {"bids": [], "asks": []}
        self.last_price: int | None = None
        self.status: dict = {}
        self.news: list[dict] = []
        self.trades: deque = deque(maxlen=200)
        self.prices: deque = deque(maxlen=2000)

    # ------------------------------------------------- eventos (sobreescribe)

    def on_book(self, book: dict) -> None:
        """El libro cambió. Siempre es un SNAPSHOT completo del top 10 por nivel
        (nunca deltas): {'bids': [[precio, qty], ...], 'asks': [...]}.
        Cada mensaje reemplaza al anterior — no necesitas mantener estado.
        También se llama al conectar (y reconectar) con el libro inicial."""

    def on_trade(self, trade: dict) -> None:
        """Cada trade del mercado: {'price', 'qty', 'aggressor', 'ts'}."""

    def on_news(self, news: dict) -> None:
        """Noticia nueva: {'headline', 'ts'}."""

    # ------------------------------------------------------------- conexión

    def connect(self) -> "MarketDataConnection":
        self._ws = _ReconnectingWS(self._url, self._handle)
        self._ws.start()
        return self

    def disconnect(self) -> None:
        if self._ws:
            self._ws.stop()

    @property
    def connected(self) -> bool:
        return bool(self._ws and self._ws.connected)

    def wait_ready(self, timeout: float = 10) -> bool:
        """Bloquea hasta recibir el estado inicial del mercado."""
        return self._got_snapshot.wait(timeout)

    # ------------------------------------------------------------- helpers

    def best_bid(self) -> int | None:
        return self.book["bids"][0][0] if self.book["bids"] else None

    def best_ask(self) -> int | None:
        return self.book["asks"][0][0] if self.book["asks"] else None

    def mid(self) -> float | None:
        bid, ask = self.best_bid(), self.best_ask()
        return (bid + ask) / 2 if bid is not None and ask is not None else self.last_price

    def market_open(self) -> bool:
        return self.status.get("state") == "running"

    # ------------------------------------------------------------- interno

    def _handle(self, m: dict) -> None:
        kind = m.get("type")
        if kind == "snapshot":
            # Estado inicial: se guarda todo y al player se le entrega como on_book.
            self.book = m["book"]
            self.status = m["status"]
            self.news = list(reversed(m["news"]))
            self.trades.extend(m["trades"])
            self.prices.extend(m["prices"])
            self.last_price = self.status.get("mark")
            self._got_snapshot.set()
            self.on_book(self.book)
        elif kind == "trade":
            self.last_price = m["price"]
            self.trades.append(m)
            self.prices.append({"t": m["ts"], "p": m["price"]})
            self.on_trade(m)
        elif kind == "book":
            self.book = {"bids": m["bids"], "asks": m["asks"]}
            self.on_book(self.book)
        elif kind == "tick":
            self.prices.append({"t": m["t"], "p": m["p"]})
        elif kind == "news":
            self.news.insert(0, m)
            self.on_news(m)
        elif kind == "status":
            self.status = m
            self.last_price = m.get("mark", self.last_price)


class TradingConnection:
    """Órdenes (place / cancel / replace), cuenta y execution reports.

    Hereda y sobreescribe los métodos on_* para recibir tus execution reports
    (llegan después de connect(), y son solo los tuyos):

        class MyTrading(TradingConnection):
            def on_fill(self, report):
                print("fill", report["qty"], "@", report["price"])

            def on_cancelled(self, report):
                print("cancelada", report["order_id"], report["reason"])
    """

    def __init__(self, host: str, port: int = 443):
        secure = port == 443
        self._base = f"{'https' if secure else 'http'}://{host}:{port}"
        self._ws_base = f"{'wss' if secure else 'ws'}://{host}:{port}"
        self._session = requests.Session()
        self._ws: _ReconnectingWS | None = None
        self.token: str | None = None

    # ------------------------------------------------- eventos (sobreescribe)

    def on_execution_report(self, report: dict) -> None:
        """Genérico: se llama para TODOS los reports, antes del método específico."""

    def on_fill(self, report: dict) -> None:
        """Ejecución: {'order_id', 'side', 'price', 'qty', 'remaining', 'order_status'}."""

    def on_cancelled(self, report: dict) -> None:
        """Orden cancelada:
        {'order_id', 'reason': 'user' | 'replaced' | 'settle' | 'disconnect' | 'bust'}."""

    def on_settled(self, report: dict) -> None:
        """Fin de la ronda: {'price', 'pnl'}."""

    def on_pnl(self, report: dict) -> None:
        """Tu PnL actual, cada ~2 segundos:
        {'pnl', 'realized', 'unrealized', 'position', 'equity', 'ts'}.
        pnl = realized + unrealized. realized es lo ya asegurado con cierres;
        unrealized marca tu posición abierta contra el último precio."""

    def on_busted(self, report: dict) -> None:
        """Tu equity llegó a 0: el exchange cerró tus posiciones y no puedes
        seguir enviando órdenes esta ronda. {'equity', 'realized', 'ts'}."""

    # ------------------------------------------------------------- sesión

    def login(self, username: str, password: str) -> dict:
        data = self._request("POST", "/api/login",
                             json={"username": username, "password": password})
        self.token = data["token"]
        self._session.headers["Authorization"] = f"Bearer {self.token}"
        return data["user"]

    def connect(self) -> "TradingConnection":
        """Conecta el canal privado de execution reports (requiere login previo)."""
        if not self.token:
            raise CipcError("Haz login() antes de connect()")
        self._ws = _ReconnectingWS(f"{self._ws_base}/ws/private?token={self.token}", self._handle)
        self._ws.start()
        return self

    def disconnect(self) -> None:
        if self._ws:
            self._ws.stop()

    # ------------------------------------------------------------- órdenes

    def new_order(self, side: str, price: int, qty: int) -> dict:
        """Orden límite DAY. side: 'buy' | 'sell'. Devuelve {'order': ..., 'trades': [...]}."""
        return self._request("POST", "/api/c2/orders",
                             json={"side": side, "price": int(price), "qty": int(qty)})

    def cancel_order(self, order_id: int) -> dict:
        return self._request("DELETE", f"/api/c2/orders/{order_id}")

    def replace_order(self, order_id: int, price: int | None = None, qty: int | None = None) -> dict:
        """Bajar qty al mismo precio conserva prioridad; cambiar precio o subir qty
        es cancel-replace: la orden va al final de la cola y cambia de id
        (el id nuevo viene en la respuesta)."""
        body = {k: int(v) for k, v in (("price", price), ("qty", qty)) if v is not None}
        return self._request("PATCH", f"/api/c2/orders/{order_id}", json=body)

    def cancel_all(self) -> dict:
        return self._request("DELETE", "/api/c2/orders")

    # ------------------------------------------------------------- consultas

    def account(self) -> dict:
        """Cash, posición, PnL y órdenes abiertas."""
        return self._request("GET", "/api/c2/account")

    def open_orders(self) -> list[dict]:
        return self.account()["open_orders"]

    def status(self) -> dict:
        return self._request("GET", "/api/c2/status")

    def book(self, depth: int = 10) -> dict:
        return self._request("GET", f"/api/c2/book?depth={depth}")

    # ------------------------------------------------------------- interno

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._session.request(method, self._base + path, timeout=10, **kwargs)
        except requests.RequestException as e:
            raise CipcError(f"No se pudo conectar al servidor: {e}") from e
        data = response.json()
        if not response.ok:
            raise CipcError(data.get("detail", str(data)))
        return data

    def _handle(self, m: dict) -> None:
        kind = m.get("type")
        if kind in ("hello", "error"):
            return
        if kind == "pnl":
            self.on_pnl(m)
            return
        self.on_execution_report(m)
        handler = {"fill": self.on_fill, "cancelled": self.on_cancelled,
                   "settled": self.on_settled, "busted": self.on_busted}.get(kind)
        if handler:
            handler(m)
