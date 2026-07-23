"""Muestra estado actual de cuenta y libro CIPC."""
import os

from cipc import TradingConnection


HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ.get("CIPC_USER", "TU_USUARIO")
PASSWORD = os.environ.get("CIPC_PASS", "TU_PASSWORD")


def main() -> None:
    trading = TradingConnection(HOST, PORT)
    trading.login(USER, PASSWORD)
    account = trading.account()
    book = trading.book(depth=5)
    print("ACCOUNT", account)
    print("BOOK", book)


if __name__ == "__main__":
    main()
