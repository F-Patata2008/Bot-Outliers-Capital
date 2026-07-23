"""Reduce posicion larga del CIPC bot inmediatamente."""
import os
import time

from cipc import CipcError, TradingConnection


HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ.get("CIPC_USER", "TU_USUARIO")
PASSWORD = os.environ.get("CIPC_PASS", "TU_PASSWORD")


def main() -> None:
    trading = TradingConnection(HOST, PORT)
    trading.login(USER, PASSWORD)

    try:
        trading.cancel_all()
        print("Ordenes abiertas canceladas.")
    except CipcError as exc:
        print("No se pudo cancelar todo:", exc)

    for step in range(12):
        account = trading.account()
        position = int(account.get("position", 0))
        print(
            f"step={step} pos={position} pnl={account.get('pnl')} "
            f"equity={account.get('equity')} open={len(account.get('open_orders', []))}"
        )

        if position <= 0:
            print("Posicion larga cerrada o no positiva.")
            return

        book = trading.book(depth=1)
        bids = book.get("bids", [])
        if not bids:
            print("Sin bids disponibles; no vendo sin contraparte.")
            return

        bid_price = int(bids[0][0])
        qty = min(position, 50)
        try:
            trading.new_order("sell", bid_price, qty)
            print(f"SELL emergency qty={qty} price={bid_price}")
        except CipcError as exc:
            print("Venta rechazada:", exc)
            return

        time.sleep(1.2)

    account = trading.account()
    print(
        f"Final pos={account.get('position')} pnl={account.get('pnl')} "
        f"equity={account.get('equity')} open={len(account.get('open_orders', []))}"
    )


if __name__ == "__main__":
    main()
