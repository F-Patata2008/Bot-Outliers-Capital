"""Bot para el CIPC Trading Challenge.

Mantiene la conexion privada viva, lee market data por WebSocket y opera con
ordenes limite usando una estimacion simple de valor justo. No borres los
os.environ.get: el staff inyecta host y credenciales por ahi.
"""
import math
import os
import json
import time
from dataclasses import dataclass
from pathlib import Path

from cipc import CipcError, MarketDataConnection, TradingConnection

try:
    import torch

    torch.set_num_threads(1)
    TORCH_AVAILABLE = True
except Exception:
    torch = None
    TORCH_AVAILABLE = False


# El staff inyecta estos valores en la ronda quant.
HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ.get("CIPC_USER", "TU_USUARIO")
PASSWORD = os.environ.get("CIPC_PASS", "TU_PASSWORD")


# Parametros de estrategia. Ajustables sin modificar codigo.
ORDER_QTY = int(os.environ.get("CIPC_ORDER_QTY", "1"))
MIN_EDGE = int(os.environ.get("CIPC_MIN_EDGE", "90"))
TAKE_PROFIT = int(os.environ.get("CIPC_TAKE_PROFIT", "140"))
MAX_POSITION = int(os.environ.get("CIPC_MAX_POSITION", "1"))
MAX_OPEN_ORDERS = int(os.environ.get("CIPC_MAX_OPEN_ORDERS", "1"))
BOOK_DEPTH = int(os.environ.get("CIPC_BOOK_DEPTH", "3"))
TREND_WEIGHT = float(os.environ.get("CIPC_TREND_WEIGHT", "8.0"))
IMBALANCE_WEIGHT = float(os.environ.get("CIPC_IMBALANCE_WEIGHT", "0.35"))
FLOW_WEIGHT = float(os.environ.get("CIPC_FLOW_WEIGHT", "0.20"))
VOL_EDGE_MULT = float(os.environ.get("CIPC_VOL_EDGE_MULT", "1.2"))
INVENTORY_SKEW = float(os.environ.get("CIPC_INVENTORY_SKEW", "0.9"))
TORCH_WEIGHT = float(os.environ.get("CIPC_TORCH_WEIGHT", "0.45"))
TORCH_MAX_ADJUST = float(os.environ.get("CIPC_TORCH_MAX_ADJUST", "45"))
POSITION_EDGE_STEP = float(os.environ.get("CIPC_POSITION_EDGE_STEP", "1.5"))
MIN_REPRICE = int(os.environ.get("CIPC_MIN_REPRICE", "80"))
STALE_EDGE_RATIO = float(os.environ.get("CIPC_STALE_EDGE_RATIO", "0.65"))
MIN_PROFIT = int(os.environ.get("CIPC_MIN_PROFIT", "18"))
EXIT_TAKE_PROFIT = int(os.environ.get("CIPC_EXIT_TAKE_PROFIT", "35"))
STOP_LOSS = int(os.environ.get("CIPC_STOP_LOSS", "260"))
MIN_EQUITY_STOP = float(os.environ.get("CIPC_MIN_EQUITY_STOP", "89500"))
MAX_LOSS_STOP = float(os.environ.get("CIPC_MAX_LOSS_STOP", "11000"))
MAX_SPREAD_ENTER = int(os.environ.get("CIPC_MAX_SPREAD_ENTER", "90"))
MAX_VOLATILITY_ENTER = float(os.environ.get("CIPC_MAX_VOLATILITY_ENTER", "120"))
AGGRESSION_MODE = os.environ.get("CIPC_AGGRESSION_MODE", "competitivo")
MOMENTUM_MODE = os.environ.get("CIPC_MOMENTUM_MODE", "auto")
MOMENTUM_TREND_ENTER = float(os.environ.get("CIPC_MOMENTUM_TREND_ENTER", "6"))
MOMENTUM_EDGE_DISCOUNT = int(os.environ.get("CIPC_MOMENTUM_EDGE_DISCOUNT", "25"))
MOMENTUM_PRICE_STEP = int(os.environ.get("CIPC_MOMENTUM_PRICE_STEP", "18"))
DOWNTREND_EDGE_EXTRA = int(os.environ.get("CIPC_DOWNTREND_EDGE_EXTRA", "45"))
# Control operativo leido en caliente desde risk_config.json.
# PAUSE_TRADING debe mantener la conexion privada viva para evitar el
# cancel-on-disconnect del exchange, pero no debe crear ni reemplazar ordenes.
PAUSE_TRADING = os.environ.get("CIPC_PAUSE_TRADING", "0") == "1"
STOP_BOT = os.environ.get("CIPC_STOP_BOT", "0") == "1"
ALLOW_SHORT = os.environ.get("CIPC_ALLOW_SHORT", "0") == "1"
ALLOW_BUY_TAKE = os.environ.get("CIPC_ALLOW_BUY_TAKE", "0") == "1"
BUY_TAKE_MAX_PREMIUM = float(os.environ.get("CIPC_BUY_TAKE_MAX_PREMIUM", "25"))
FAIR_VALUE_OVERRIDE = os.environ.get("CIPC_FAIR_VALUE")
RISK_CONFIG_PATH = Path(os.environ.get("CIPC_RISK_CONFIG", "risk_config.json"))
RISK_CONFIG_MTIME = 0.0
HISTORY_PATH = Path(os.environ.get("CIPC_HISTORY_PATH", "trade_history.jsonl"))


RISK_KEYS = {
    "ORDER_QTY": int,
    "MIN_EDGE": int,
    "TAKE_PROFIT": int,
    "MAX_POSITION": int,
    "MAX_OPEN_ORDERS": int,
    "BOOK_DEPTH": int,
    "TREND_WEIGHT": float,
    "IMBALANCE_WEIGHT": float,
    "FLOW_WEIGHT": float,
    "VOL_EDGE_MULT": float,
    "INVENTORY_SKEW": float,
    "TORCH_WEIGHT": float,
    "TORCH_MAX_ADJUST": float,
    "POSITION_EDGE_STEP": float,
    "MIN_REPRICE": int,
    "STALE_EDGE_RATIO": float,
    "MIN_PROFIT": int,
    "EXIT_TAKE_PROFIT": int,
    "STOP_LOSS": int,
    "MIN_EQUITY_STOP": float,
    "MAX_LOSS_STOP": float,
    "MAX_SPREAD_ENTER": int,
    "MAX_VOLATILITY_ENTER": float,
    "AGGRESSION_MODE": str,
    "MOMENTUM_MODE": str,
    "MOMENTUM_TREND_ENTER": float,
    "MOMENTUM_EDGE_DISCOUNT": int,
    "MOMENTUM_PRICE_STEP": int,
    "DOWNTREND_EDGE_EXTRA": int,
    "PAUSE_TRADING": bool,
    "STOP_BOT": bool,
    "ALLOW_SHORT": bool,
    "ALLOW_BUY_TAKE": bool,
    "BUY_TAKE_MAX_PREMIUM": float,
    "FAIR_VALUE_OVERRIDE": str,
}


def clamp(value, low, high):
    return max(low, min(high, value))


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def load_risk_config():
    global RISK_CONFIG_MTIME
    global ORDER_QTY, MIN_EDGE, TAKE_PROFIT, MAX_POSITION, MAX_OPEN_ORDERS
    global BOOK_DEPTH, TREND_WEIGHT, IMBALANCE_WEIGHT, FLOW_WEIGHT, VOL_EDGE_MULT
    global INVENTORY_SKEW, TORCH_WEIGHT, TORCH_MAX_ADJUST, POSITION_EDGE_STEP
    global MIN_REPRICE, STALE_EDGE_RATIO, MIN_PROFIT, EXIT_TAKE_PROFIT
    global STOP_LOSS, MIN_EQUITY_STOP, MAX_LOSS_STOP
    global MAX_SPREAD_ENTER, MAX_VOLATILITY_ENTER
    global AGGRESSION_MODE, MOMENTUM_MODE, MOMENTUM_TREND_ENTER
    global MOMENTUM_EDGE_DISCOUNT, MOMENTUM_PRICE_STEP, DOWNTREND_EDGE_EXTRA
    global PAUSE_TRADING, STOP_BOT
    global ALLOW_SHORT, ALLOW_BUY_TAKE, BUY_TAKE_MAX_PREMIUM, FAIR_VALUE_OVERRIDE

    try:
        stat = RISK_CONFIG_PATH.stat()
    except FileNotFoundError:
        return
    except OSError as exc:
        print("risk config stat error:", exc)
        return

    if stat.st_mtime <= RISK_CONFIG_MTIME:
        return

    try:
        data = json.loads(RISK_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print("risk config read error:", exc)
        return

    for key, caster in RISK_KEYS.items():
        if key not in data:
            continue
        try:
            if caster is bool:
                value = parse_bool(data[key])
            elif key == "FAIR_VALUE_OVERRIDE" and str(data[key]).strip() == "":
                value = None
            else:
                value = caster(data[key])
        except (TypeError, ValueError) as exc:
            print(f"risk config invalid {key}: {exc}")
            continue
        globals()[key] = value

    RISK_CONFIG_MTIME = stat.st_mtime
    print(f"risk config loaded: {RISK_CONFIG_PATH}", flush=True)


@dataclass
class SignalState:
    fair_value: float | None = None
    previous_price: float | None = None
    trend: float = 0.0
    volatility: float = 0.0
    trade_flow: float = 0.0
    book_imbalance: float = 0.0
    news_bias: float = 0.0
    last_news_ts: float = 0.0


SIGNAL = SignalState()


class TorchSignalModel:
    def __init__(self):
        self.model = torch.nn.Sequential(
            torch.nn.Linear(6, 8),
            torch.nn.Tanh(),
            torch.nn.Linear(8, 1),
        )
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.015)
        self.loss_fn = torch.nn.SmoothL1Loss()
        self.last_features = None
        self.last_price = None
        self.samples = 0

    def features(self, spread):
        return torch.tensor(
            [
                clamp(SIGNAL.trend / 80.0, -3.0, 3.0),
                clamp(SIGNAL.volatility / 80.0, 0.0, 3.0),
                SIGNAL.book_imbalance,
                SIGNAL.trade_flow,
                clamp(spread / 150.0, 0.0, 3.0),
                clamp(SIGNAL.news_bias / 180.0, -1.0, 1.0),
            ],
            dtype=torch.float32,
        )

    def update_and_predict(self, price, spread):
        x = self.features(spread)

        if self.last_features is not None and self.last_price is not None:
            target_delta = clamp((price - self.last_price) / 100.0, -2.0, 2.0)
            y = torch.tensor([target_delta], dtype=torch.float32)
            pred = self.model(self.last_features)
            loss = self.loss_fn(pred, y)
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
            self.samples += 1

        with torch.no_grad():
            predicted_delta = float(self.model(x).item()) * 100.0

        self.last_features = x.detach()
        self.last_price = price

        if self.samples < 8:
            return 0.0
        return clamp(predicted_delta, -TORCH_MAX_ADJUST, TORCH_MAX_ADJUST)


TORCH_MODEL = TorchSignalModel() if TORCH_AVAILABLE else None


class MyMarketData(MarketDataConnection):
    def on_news(self, news):
        headline = news.get("headline", "")
        print("NOTICIA:", headline)
        SIGNAL.news_bias += score_news(headline)
        SIGNAL.news_bias = clamp(SIGNAL.news_bias, -180.0, 180.0)
        SIGNAL.last_news_ts = time.time()

    def on_trade(self, trade):
        price = trade.get("price")
        update_trade_flow(trade)
        if price is None:
            return
        update_trend(float(price))

    def on_book(self, book):
        SIGNAL.book_imbalance = calculate_book_imbalance(book)
        mid = self.mid()
        if mid is not None:
            update_trend(float(mid))


class MyTrading(TradingConnection):
    def log_event(self, event, payload):
        row = {"ts": time.time(), "event": event, **payload}
        try:
            with HISTORY_PATH.open("a", encoding="utf-8") as file:
                file.write(json.dumps(row, sort_keys=True) + "\n")
        except OSError as exc:
            print("history log error:", exc)

    def on_execution_report(self, report):
        self.log_event("execution", report)

    def on_fill(self, report):
        self.log_event("fill", report)
        print(
            f"FILL: {report['side']} {report['qty']} @ {report['price']} "
            f"(orden #{report['order_id']}, quedan {report['remaining']})"
        )

    def on_cancelled(self, report):
        self.log_event("cancelled", report)
        print(f"CANCELADA: orden #{report['order_id']} ({report['reason']})")

    def on_settled(self, report):
        self.log_event("settled", report)
        print(f"LIQUIDACION a {report['price']} - PnL final: {report['pnl']}")

    def on_pnl(self, report):
        self.log_event("pnl", report)
        print(
            "PNL:",
            f"total={report.get('pnl')}",
            f"realized={report.get('realized')}",
            f"unrealized={report.get('unrealized')}",
            f"pos={report.get('position')}",
            f"equity={report.get('equity')}",
        )

    def on_busted(self, report):
        self.log_event("busted", report)
        print("BUSTED:", report)


class RiskStop(Exception):
    pass


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
    SIGNAL.volatility = 0.90 * SIGNAL.volatility + 0.10 * abs(delta)
    SIGNAL.previous_price = price
    if SIGNAL.fair_value is None:
        SIGNAL.fair_value = price
    else:
        SIGNAL.fair_value = 0.92 * SIGNAL.fair_value + 0.08 * price


def update_trade_flow(trade):
    aggressor = str(trade.get("aggressor", "")).lower()
    qty = max(1.0, float(trade.get("qty") or 1))
    direction = 0
    if "buy" in aggressor or "compra" in aggressor:
        direction = 1
    elif "sell" in aggressor or "venta" in aggressor:
        direction = -1

    flow = direction * min(1.0, qty / 10.0)
    SIGNAL.trade_flow = 0.85 * SIGNAL.trade_flow + 0.15 * flow


def calculate_book_imbalance(book):
    bids = book.get("bids", [])[:BOOK_DEPTH]
    asks = book.get("asks", [])[:BOOK_DEPTH]
    bid_qty = sum(float(level[1]) for level in bids)
    ask_qty = sum(float(level[1]) for level in asks)
    total = bid_qty + ask_qty
    if total <= 0:
        return 0.0
    return clamp((bid_qty - ask_qty) / total, -1.0, 1.0)


def microprice(md):
    bids = md.book.get("bids", [])
    asks = md.book.get("asks", [])
    if not bids or not asks:
        return md.mid()

    bid_price, bid_qty = bids[0][0], max(1.0, float(bids[0][1]))
    ask_price, ask_qty = asks[0][0], max(1.0, float(asks[0][1]))
    return (ask_price * bid_qty + bid_price * ask_qty) / (bid_qty + ask_qty)


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
    book_price = microprice(md)
    if book_price is None:
        book_price = float(anchor)

    bid = md.best_bid()
    ask = md.best_ask()
    spread = max(1.0, float(ask - bid)) if bid is not None and ask is not None else 1.0
    base = 0.65 * SIGNAL.fair_value + 0.35 * float(book_price)
    fair = (
        base
        + TREND_WEIGHT * SIGNAL.trend
        + IMBALANCE_WEIGHT * spread * SIGNAL.book_imbalance
        + FLOW_WEIGHT * spread * SIGNAL.trade_flow
        + SIGNAL.news_bias * news_decay
    )
    if TORCH_MODEL is not None:
        torch_adjust = TORCH_MODEL.update_and_predict(float(anchor), spread)
        if torch_adjust:
            print(f"TORCH adjust={torch_adjust:.1f}")
        fair += TORCH_WEIGHT * torch_adjust
    return float(fair)


def side_orders(account, side):
    return [order for order in account["open_orders"] if order["side"] == side]


def cancel_side_orders(trading, account, side):
    cancelled = 0
    for order in side_orders(account, side):
        trading.cancel_order(order["id"])
        cancelled += 1
    return cancelled


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


def preferred_order(orders, side):
    if not orders:
        return None
    reverse = side == "buy"
    return sorted(orders, key=lambda item: (item["price"], -item.get("id", 0)), reverse=reverse)[0]


def cancel_duplicate_side_orders(trading, orders, side):
    if len(orders) <= 1:
        return 0

    keep = preferred_order(orders, side)
    if keep is None:
        return 0

    cancelled = 0
    for order in orders:
        if order["id"] == keep["id"]:
            continue
        trading.cancel_order(order["id"])
        cancelled += 1
        if cancelled >= 2:
            break
    return cancelled


def replace_or_create(trading, existing, side, price, qty):
    if existing:
        order = preferred_order(existing, side)
        current_price = int(order["price"])
        remaining = int(order["remaining"])
        if abs(current_price - price) >= MIN_REPRICE:
            trading.replace_order(order["id"], price=price, qty=qty)
            return "replace"
        if side == "buy" and current_price >= price:
            return "keep"
        if side == "sell" and current_price <= price:
            return "keep"
        if remaining > qty:
            trading.replace_order(order["id"], qty=qty)
            return "resize"
        return "keep"
    trading.new_order(side=side, price=price, qty=qty)
    return "new"


def clamp_to_price_band(price, mark):
    if mark is None:
        return max(1, int(price))
    low = int(math.ceil(mark * 0.80))
    high = int(math.floor(mark * 1.20))
    return int(clamp(int(price), low, high))


def cancel_stale_orders(trading, open_buys, open_sells, fair, buy_min_edge, sell_min_edge, buy_capacity, sell_capacity):
    candidates = []
    for order in open_buys:
        edge = fair - int(order["price"])
        if buy_capacity <= 0 or edge < buy_min_edge * STALE_EDGE_RATIO:
            candidates.append((edge, order, "buy"))

    for order in open_sells:
        edge = int(order["price"]) - fair
        if sell_capacity <= 0 or edge < sell_min_edge * STALE_EDGE_RATIO:
            candidates.append((edge, order, "sell"))

    if not candidates:
        return 0

    edge, order, side = sorted(candidates, key=lambda item: item[0])[0]
    trading.cancel_order(order["id"])
    print(f"CANCEL STALE {side} #{order['id']} price={order['price']} edge={edge:.1f}")
    return 1


def log_history(event, **payload):
    row = {"ts": time.time(), "event": event, **payload}
    try:
        with HISTORY_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        print("history log error:", exc)


def momentum_flags():
    up_votes = 0
    down_votes = 0

    if SIGNAL.trend >= MOMENTUM_TREND_ENTER:
        up_votes += 1
    elif SIGNAL.trend <= -MOMENTUM_TREND_ENTER:
        down_votes += 1

    if SIGNAL.book_imbalance >= 0.22:
        up_votes += 1
    elif SIGNAL.book_imbalance <= -0.22:
        down_votes += 1

    if SIGNAL.trade_flow >= 0.18:
        up_votes += 1
    elif SIGNAL.trade_flow <= -0.18:
        down_votes += 1

    return up_votes >= 2, down_votes >= 2


def normalized_momentum_mode():
    return str(MOMENTUM_MODE or "auto").strip().lower()


def is_up_mode(mode):
    return mode in ("alcista", "up", "bull", "sprint", "momentum_alcista")


def is_down_mode(mode):
    return mode in ("bajista", "down", "bear", "defensivo_bajista")


def uses_momentum(mode):
    return mode not in ("neutral", "off", "apagado")


def strategy(md: MyMarketData, trading: MyTrading) -> None:
    load_risk_config()
    account = trading.account()
    position = int(account["position"])
    fair = estimate_fair_value(md)
    bid = md.best_bid()
    ask = md.best_ask()
    mark = md.last_price
    fair_text = f"{fair:.1f}" if fair is not None else "None"
    up_momentum, down_momentum = momentum_flags()
    momentum_mode = normalized_momentum_mode()

    print(
        f"mark={mark} bid={bid} ask={ask} fair={fair_text} "
        f"pos={position} pnl={account.get('pnl')} open={len(account['open_orders'])} "
        f"mom={momentum_mode} up={int(up_momentum)} down={int(down_momentum)}"
    )
    log_history(
        "snapshot",
        mark=mark,
        bid=bid,
        ask=ask,
        fair=fair,
        position=position,
        avg_price=account.get("avg_price"),
        pnl=account.get("pnl"),
        realized=account.get("realized"),
        unrealized=account.get("unrealized"),
        equity=account.get("equity"),
        open_orders=len(account["open_orders"]),
        trend=SIGNAL.trend,
        volatility=SIGNAL.volatility,
        book_imbalance=SIGNAL.book_imbalance,
        trade_flow=SIGNAL.trade_flow,
        up_momentum=up_momentum,
        down_momentum=down_momentum,
        momentum_mode=momentum_mode,
        aggression_mode=AGGRESSION_MODE,
    )

    if fair is None or bid is None or ask is None:
        return
    if account.get("busted"):
        raise RiskStop("Cuenta busted")

    if STOP_BOT:
        trading.cancel_all()
        raise RiskStop("Detenido desde panel local")

    if PAUSE_TRADING:
        # Pausa local:
        # - cancela ordenes abiertas para dejar de tomar riesgo;
        # - conserva el proceso y WebSocket privado vivos;
        # - sale antes de cualquier decision de estrategia.
        # La siguiente IA debe mantener este bloque antes de stops/quotes para
        # que el boton Pausar sea inmediato y no dependa de la logica quant.
        if account["open_orders"]:
            trading.cancel_all()
            print(f"PAUSED: canceladas ordenes abiertas={len(account['open_orders'])}")
        else:
            print("PAUSED: conexion viva, sin ordenes nuevas")
        return

    equity = float(account.get("equity") or 0.0)
    pnl = float(account.get("pnl") or 0.0)
    if equity <= MIN_EQUITY_STOP or pnl <= -MAX_LOSS_STOP:
        trading.cancel_all()
        raise RiskStop(
            f"Corte de riesgo: equity={equity:.1f}, pnl={pnl:.1f}, "
            f"limites equity>{MIN_EQUITY_STOP:.1f} pnl>-{MAX_LOSS_STOP:.1f}"
        )

    if len(account["open_orders"]) > MAX_OPEN_ORDERS:
        trading.cancel_all()
        print(f"CANCEL ALL open={len(account['open_orders'])}")
        return

    if position > 0:
        cancelled = cancel_side_orders(trading, account, "buy")
        if cancelled:
            print(f"CANCEL BUY exposure={cancelled}")
            return

        avg_price = float(account.get("avg_price") or 0.0)
        min_exit_price = math.ceil(avg_price + MIN_PROFIT) if avg_price else ask
        if avg_price and bid <= avg_price - STOP_LOSS:
            qty = min(position, int(md.status.get("max_order_qty", 50)))
            trading.cancel_all()
            trading.new_order("sell", bid, qty)
            raise RiskStop(
                f"Stop-loss ejecutado qty={qty} price={bid} avg={avg_price:.1f} "
                f"loss={avg_price - bid:.1f}"
            )

        if avg_price and bid >= avg_price + EXIT_TAKE_PROFIT:
            qty = min(ORDER_QTY, position, int(md.status.get("max_order_qty", 50)))
            trading.cancel_all()
            trading.new_order("sell", bid, qty)
            print(f"SELL REALIZE qty={qty} price={bid} avg={avg_price:.1f} profit={bid - avg_price:.1f}")
            return

        if (
            avg_price
            and uses_momentum(momentum_mode)
            and (down_momentum or is_down_mode(momentum_mode))
            and bid >= avg_price + MIN_PROFIT
        ):
            qty = min(ORDER_QTY, position, int(md.status.get("max_order_qty", 50)))
            trading.cancel_all()
            trading.new_order("sell", bid, qty)
            print(
                f"SELL MOMENTUM EXIT qty={qty} price={bid} "
                f"avg={avg_price:.1f} profit={bid - avg_price:.1f}"
            )
            return

        target_price = ask if ask >= min_exit_price else min_exit_price
        target_price = clamp_to_price_band(target_price, mark)
        qty = min(ORDER_QTY, position, int(md.status.get("max_order_qty", 50)))
        action = replace_or_create(trading, side_orders(account, "sell"), "sell", target_price, qty)
        print(
            f"SELL TARGET {action} qty={qty} price={target_price} "
            f"avg={avg_price:.1f} min={min_exit_price}"
        )
        return

    if position == 0 and not ALLOW_SHORT:
        cancelled = cancel_side_orders(trading, account, "sell")
        if cancelled:
            print(f"CANCEL SELL no-short={cancelled}")
            return

    if position == 0 and uses_momentum(momentum_mode):
        block_reason = None
        if is_down_mode(momentum_mode):
            block_reason = "modo bajista"
        elif is_up_mode(momentum_mode) and not up_momentum:
            block_reason = "esperando momentum alcista"
        elif momentum_mode == "auto" and down_momentum:
            block_reason = "momentum bajista"

        if block_reason:
            cancelled = cancel_side_orders(trading, account, "buy")
            print(f"NO ENTRY {block_reason} cancelled_buys={cancelled}")
            return

    spread_now = ask - bid
    if position == 0 and (
        spread_now > MAX_SPREAD_ENTER or SIGNAL.volatility > MAX_VOLATILITY_ENTER
    ):
        cancelled = cancel_side_orders(trading, account, "buy")
        reason = (
            f"spread={spread_now}>{MAX_SPREAD_ENTER}"
            if spread_now > MAX_SPREAD_ENTER
            else f"vol={SIGNAL.volatility:.1f}>{MAX_VOLATILITY_ENTER:.1f}"
        )
        print(f"NO ENTRY {reason} cancelled_buys={cancelled}")
        return

    if cancel_excess_orders(trading, account):
        return

    spread = max(1, spread_now)
    risk_edge = VOL_EDGE_MULT * SIGNAL.volatility
    momentum_discount = 0
    if uses_momentum(momentum_mode) and up_momentum and (momentum_mode == "auto" or is_up_mode(momentum_mode)):
        momentum_discount = MOMENTUM_EDGE_DISCOUNT
    downtrend_extra = DOWNTREND_EDGE_EXTRA if uses_momentum(momentum_mode) and down_momentum else 0
    quote_edge = max(10.0, MIN_EDGE - momentum_discount + downtrend_extra + spread * 0.15 + risk_edge)
    position_skew = position * INVENTORY_SKEW
    buy_ceiling = bid - 1
    if uses_momentum(momentum_mode) and up_momentum and (momentum_mode == "auto" or is_up_mode(momentum_mode)):
        buy_ceiling = min(ask - 1, bid - 1 + MOMENTUM_PRICE_STEP)
        if ALLOW_BUY_TAKE:
            buy_ceiling = ask
    buy_price = clamp_to_price_band(
        math.floor(min(buy_ceiling, fair - quote_edge - position_skew)),
        mark,
    )
    sell_price = clamp_to_price_band(
        math.ceil(max(bid, fair + quote_edge - position_skew)),
        mark,
    )

    buy_edge = fair - buy_price
    sell_edge = sell_price - fair
    buy_min_edge = max(10.0, MIN_EDGE + max(position, 0) * POSITION_EDGE_STEP)
    sell_min_edge = max(10.0, MIN_EDGE + max(-position, 0) * POSITION_EDGE_STEP)
    if position > 0:
        sell_min_edge = max(10.0, MIN_EDGE - position * POSITION_EDGE_STEP)
    elif position < 0:
        buy_min_edge = max(10.0, MIN_EDGE + position * POSITION_EDGE_STEP)
    open_buys = side_orders(account, "buy")
    open_sells = side_orders(account, "sell")

    if cancel_duplicate_side_orders(trading, open_buys, "buy"):
        print("CANCEL DUP buy")
        return
    if cancel_duplicate_side_orders(trading, open_sells, "sell"):
        print("CANCEL DUP sell")
        return

    max_position = min(MAX_POSITION, int(md.status.get("pos_limit", 100)))
    max_qty = min(ORDER_QTY, int(md.status.get("max_order_qty", 50)))
    buy_capacity = max(0, max_position - position)
    sell_capacity = max(0, max_position + position) if ALLOW_SHORT else max(0, position)

    if cancel_stale_orders(
        trading,
        open_buys,
        open_sells,
        fair,
        buy_min_edge,
        sell_min_edge,
        buy_capacity,
        sell_capacity,
    ):
        return

    if ALLOW_BUY_TAKE and buy_capacity > 0 and ask - fair <= BUY_TAKE_MAX_PREMIUM:
        cancelled = cancel_side_orders(trading, account, "buy")
        if cancelled:
            print(f"CANCEL BUY before take={cancelled}")
            return
        qty = min(max_qty, buy_capacity)
        trading.new_order("buy", ask, qty)
        print(
            f"BUY TAKE qty={qty} price={ask} "
            f"premium={ask - fair:.1f}/{BUY_TAKE_MAX_PREMIUM:.1f}"
        )
        return

    if sell_capacity > 0 and bid - fair >= TAKE_PROFIT:
        qty = min(max_qty, sell_capacity)
        trading.new_order("sell", bid, qty)
        print(f"SELL TAKE qty={qty} price={bid} edge={bid - fair:.1f}")
        return

    acted = False

    if buy_capacity > 0 and buy_edge >= buy_min_edge:
        qty = min(max_qty, buy_capacity)
        action = replace_or_create(trading, open_buys, "buy", buy_price, qty)
        print(f"BUY {action} qty={qty} price={buy_price} edge={buy_edge:.1f}/{buy_min_edge:.1f}")
        acted = action != "keep"

    if sell_capacity > 0 and sell_edge >= sell_min_edge:
        qty = min(max_qty, sell_capacity)
        action = replace_or_create(trading, open_sells, "sell", sell_price, qty)
        print(f"SELL {action} qty={qty} price={sell_price} edge={sell_edge:.1f}/{sell_min_edge:.1f}")
        acted = acted or action != "keep"

    if acted:
        return


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
        except RiskStop as exc:
            print("BOT DETENIDO POR RIESGO:", exc)
            return
        except CipcError as exc:
            print("orden rechazada:", exc)
        except Exception as exc:
            print("error estrategia:", exc)


if __name__ == "__main__":
    main()
