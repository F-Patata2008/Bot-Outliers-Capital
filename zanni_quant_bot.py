"""Bot para el CIPC Trading Challenge.

Mantiene la conexion privada viva, lee market data por WebSocket y opera con
ordenes limite usando una estimacion simple de valor justo. No borres los
os.environ.get: el staff inyecta host y credenciales por ahi.
"""
import math
import os
import time
from dataclasses import dataclass

from cipc import CipcError, MarketDataConnection, TradingConnection


# El staff inyecta estos valores en la ronda quant.
HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ.get("CIPC_USER", "TU_USUARIO")
PASSWORD = os.environ.get("CIPC_PASS", "TU_PASSWORD")


# Parametros de estrategia. Ajustables sin modificar codigo.
ORDER_QTY = int(os.environ.get("CIPC_ORDER_QTY", "4"))
MIN_EDGE = int(os.environ.get("CIPC_MIN_EDGE", "35"))
TAKE_PROFIT = int(os.environ.get("CIPC_TAKE_PROFIT", "80"))
MAX_POSITION = int(os.environ.get("CIPC_MAX_POSITION", "40"))
MAX_OPEN_ORDERS = int(os.environ.get("CIPC_MAX_OPEN_ORDERS", "6"))
FAIR_VALUE_OVERRIDE = os.environ.get("CIPC_FAIR_VALUE")


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class SignalState:
    fair_value: float | None = None
    previous_price: float | None = None
    trend: float = 0.0
    news_bias: float = 0.0
    last_news_ts: float = 0.0


SIGNAL = SignalState()


class MyMarketData(MarketDataConnection):
    def on_news(self, news):
        headline = news.get("headline", "")
        print("NOTICIA:", headline)
        SIGNAL.news_bias += score_news(headline)
        SIGNAL.news_bias = clamp(SIGNAL.news_bias, -180.0, 180.0)
        SIGNAL.last_news_ts = time.time()

    def on_trade(self, trade):
        price = trade.get("price")
        if price is None:
            return
        update_trend(float(price))

    def on_book(self, book):
        mid = self.mid()
        if mid is not None:
            update_trend(float(mid))


class MyTrading(TradingConnection):
    def on_fill(self, report):
        print(
            f"FILL: {report['side']} {report['qty']} @ {report['price']} "
            f"(orden #{report['order_id']}, quedan {report['remaining']})"
        )

    def on_cancelled(self, report):
        print(f"CANCELADA: orden #{report['order_id']} ({report['reason']})")

    def on_settled(self, report):
        print(f"LIQUIDACION a {report['price']} - PnL final: {report['pnl']}")

    def on_pnl(self, report):
        print(
            "PNL:",
            f"total={report.get('pnl')}",
            f"realized={report.get('realized')}",
            f"unrealized={report.get('unrealized')}",
            f"pos={report.get('position')}",
            f"equity={report.get('equity')}",
        )

    def on_busted(self, report):
        print("BUSTED:", report)


def score_news(headline):
    text = headline.lower()
    positive = (
        "compra",
        "comprar",
        "sube",
        "alza",
        "arrasa",
        "demanda",
        "record",
        "récord",
        "bull",
        "positivo",
    )
    negative = (
        "vende",
        "vender",
        "cae",
        "baja",
        "crash",
        "fraude",
        "miedo",
        "bear",
        "negativo",
    )
    bias = 0
    if any(word in text for word in positive):
        bias += 70
    if any(word in text for word in negative):
        bias -= 70
    return bias


def update_trend(price):
    if SIGNAL.previous_price is None:
        SIGNAL.previous_price = price
        SIGNAL.fair_value = price
        return

    delta = price - SIGNAL.previous_price
    SIGNAL.trend = 0.85 * SIGNAL.trend + 0.15 * delta
    SIGNAL.previous_price = price
    if SIGNAL.fair_value is None:
        SIGNAL.fair_value = price
    else:
        SIGNAL.fair_value = 0.92 * SIGNAL.fair_value + 0.08 * price


def estimate_fair_value(md):
    if FAIR_VALUE_OVERRIDE:
        return float(FAIR_VALUE_OVERRIDE)

    mid = md.mid()
    mark = md.last_price
    anchor = mid if mid is not None else mark
    if anchor is None:
        return None

    if SIGNAL.fair_value is None:
        SIGNAL.fair_value = float(anchor)

    # La noticia se va apagando; si de verdad movio el fundamental, el precio la
    # confirmara y la EMA la incorporara.
    age = time.time() - SIGNAL.last_news_ts if SIGNAL.last_news_ts else 9999
    news_decay = math.exp(-age / 180.0)
    fair = SIGNAL.fair_value + 10.0 * SIGNAL.trend + SIGNAL.news_bias * news_decay
    return float(fair)


def side_orders(account, side):
    return [order for order in account["open_orders"] if order["side"] == side]


def cancel_excess_orders(trading, account):
    open_orders = account["open_orders"]
    if len(open_orders) <= MAX_OPEN_ORDERS:
        return 0

    cancelled = 0
    for order in sorted(open_orders, key=lambda item: item.get("id", 0))[: len(open_orders) - MAX_OPEN_ORDERS]:
        trading.cancel_order(order["id"])
        cancelled += 1
        if cancelled >= 2:
            break
    return cancelled


def replace_or_create(trading, existing, side, price, qty):
    if existing:
        order = existing[0]
        if order["price"] != price or order["remaining"] != qty:
            trading.replace_order(order["id"], price=price, qty=qty)
            return "replace"
        return "keep"
    trading.new_order(side=side, price=price, qty=qty)
    return "new"


def clamp_to_price_band(price, mark):
    if mark is None:
        return max(1, int(price))
    low = int(math.ceil(mark * 0.80))
    high = int(math.floor(mark * 1.20))
    return int(clamp(int(price), low, high))


def strategy(md: MyMarketData, trading: MyTrading) -> None:
    account = trading.account()
    position = int(account["position"])
    fair = estimate_fair_value(md)
    bid = md.best_bid()
    ask = md.best_ask()
    mark = md.last_price
    fair_text = f"{fair:.1f}" if fair is not None else "None"

    print(
        f"mark={mark} bid={bid} ask={ask} fair={fair_text} "
        f"pos={position} pnl={account.get('pnl')} open={len(account['open_orders'])}"
    )

    if fair is None or bid is None or ask is None:
        return
    if account.get("busted"):
        return

    if cancel_excess_orders(trading, account):
        return

    spread = max(1, ask - bid)
    position_skew = position * 0.7
    buy_price = clamp_to_price_band(
        min(ask, fair - MIN_EDGE - spread * 0.15 - position_skew),
        mark,
    )
    sell_price = clamp_to_price_band(
        max(bid, fair + MIN_EDGE + spread * 0.15 - position_skew),
        mark,
    )

    buy_edge = fair - buy_price
    sell_edge = sell_price - fair
    open_buys = side_orders(account, "buy")
    open_sells = side_orders(account, "sell")

    max_position = min(MAX_POSITION, int(md.status.get("pos_limit", 100)))
    max_qty = min(ORDER_QTY, int(md.status.get("max_order_qty", 50)))
    buy_capacity = max(0, max_position - position)
    sell_capacity = max(0, max_position + position)

    # Si hay ganancia clara contra el libro, toma liquidez con una orden limite
    # al mejor precio disponible. Si no, deja quotes pasivas con edge.
    if buy_capacity > 0 and fair - ask >= TAKE_PROFIT:
        qty = min(max_qty, buy_capacity)
        trading.new_order("buy", ask, qty)
        print(f"BUY TAKE qty={qty} price={ask} edge={fair - ask:.1f}")
        return

    if sell_capacity > 0 and bid - fair >= TAKE_PROFIT:
        qty = min(max_qty, sell_capacity)
        trading.new_order("sell", bid, qty)
        print(f"SELL TAKE qty={qty} price={bid} edge={bid - fair:.1f}")
        return

    if buy_capacity > 0 and buy_edge >= MIN_EDGE:
        qty = min(max_qty, buy_capacity)
        action = replace_or_create(trading, open_buys, "buy", buy_price, qty)
        print(f"BUY {action} qty={qty} price={buy_price} edge={buy_edge:.1f}")
        return

    if sell_capacity > 0 and sell_edge >= MIN_EDGE:
        qty = min(max_qty, sell_capacity)
        action = replace_or_create(trading, open_sells, "sell", sell_price, qty)
        print(f"SELL {action} qty={qty} price={sell_price} edge={sell_edge:.1f}")


def main() -> None:
    md = MyMarketData(HOST, PORT)
    trading = MyTrading(HOST, PORT)

    trading.login(USER, PASSWORD)
    trading.connect()
    md.connect()
    md.wait_ready()
    print("Conectado. Estado del mercado:", md.status.get("state"))

    while True:
        time.sleep(1)
        if not md.market_open():
            continue
        try:
            strategy(md, trading)
        except CipcError as exc:
            print("orden rechazada:", exc)
        except Exception as exc:
            print("error estrategia:", exc)


if __name__ == "__main__":
    main()
