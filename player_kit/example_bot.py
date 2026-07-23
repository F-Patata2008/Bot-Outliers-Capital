"""Template de bot para el CIPC Trading Challenge.

1. pip install requests websocket-client
2. Completa HOST, USER y PASSWORD.
3. Implementa tus reacciones en MyTrading / MyMarketData y tu estrategia en strategy().
4. python example_bot.py
"""
import os
import time

from cipc import CipcError, MarketDataConnection, TradingConnection

# NO borres los os.environ.get: en la ronda quant el staff corre tu bot
# inyectando host/puerto/credenciales de tu instancia por variables de entorno.
HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ.get("CIPC_USER", "TU_USUARIO")
PASSWORD = os.environ.get("CIPC_PASS", "TU_PASSWORD")


class MyMarketData(MarketDataConnection):
    """Sobreescribe los eventos de mercado que te interesen."""

    def on_news(self, news):
        print("NOTICIA:", news["headline"])

    def on_trade(self, trade):
        # Cada trade del mercado (de cualquier participante).
        pass

    def on_book(self, book):
        # Snapshot completo del libro cada vez que cambia (también al conectar).
        pass


class MyTrading(TradingConnection):
    """Sobreescribe tus execution reports."""

    def on_fill(self, report):
        print(f"FILL: {report['side']} {report['qty']} @ {report['price']} "
              f"(orden #{report['order_id']}, quedan {report['remaining']})")

    def on_cancelled(self, report):
        print(f"CANCELADA: orden #{report['order_id']} ({report['reason']})")

    def on_settled(self, report):
        print(f"LIQUIDACIÓN a {report['price']} — PnL final: {report['pnl']}")

    def on_pnl(self, report):
        # Cada ~2s: {'pnl', 'realized', 'unrealized', 'position', 'equity'}
        pass


def strategy(md: MyMarketData, trading: MyTrading) -> None:
    """Se llama una vez por segundo mientras el mercado está abierto.

    ================= TU ESTRATEGIA AQUÍ =================
    Ejemplo tonto: si no tengo órdenes abiertas, cotizo a ambos lados del mid.
    """
    mid = md.mid()
    account = trading.account()
    print(f"bid={md.best_bid()} ask={md.best_ask()} pos={account['position']} pnl={account['pnl']}")

    if mid is not None and not account["open_orders"]:
        trading.new_order(side="buy", price=int(mid) - 40, qty=2)
        trading.new_order(side="sell", price=int(mid) + 40, qty=2)


def main() -> None:
    md = MyMarketData(HOST, PORT)
    trading = MyTrading(HOST, PORT)

    trading.login(USER, PASSWORD)
    trading.connect()   # execution reports en tiempo real (¡mantenla viva!)
    md.connect()
    md.wait_ready()
    print("Conectado. Estado del mercado:", md.status.get("state"))

    while True:
        time.sleep(1)
        if not md.market_open():
            continue
        try:
            strategy(md, trading)
        except CipcError as e:
            print("orden rechazada:", e)


if __name__ == "__main__":
    main()
