"""Analiza historial local del bot para ajustar riesgo y edge."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path


HISTORY_PATH = Path("trade_history.jsonl")


def load_rows(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def pair_round_trips(fills):
    inventory = []
    trades = []
    for fill in fills:
        side = fill.get("side")
        qty = int(fill.get("qty") or 0)
        price = float(fill.get("price") or 0)
        ts = float(fill.get("ts") or 0)
        if qty <= 0 or price <= 0:
            continue

        if side == "buy":
            for _ in range(qty):
                inventory.append((price, ts))
            continue

        if side == "sell":
            for _ in range(qty):
                if not inventory:
                    continue
                buy_price, buy_ts = inventory.pop(0)
                trades.append(
                    {
                        "buy_price": buy_price,
                        "sell_price": price,
                        "profit": price - buy_price,
                        "hold_seconds": max(0.0, ts - buy_ts),
                    }
                )
    return trades, inventory


def summarize(values):
    if not values:
        return "n/a"
    avg = sum(values) / len(values)
    win_rate = sum(1 for value in values if value > 0) / len(values)
    return (
        f"n={len(values)} avg={avg:.2f} min={min(values):.2f} "
        f"max={max(values):.2f} win_rate={win_rate:.1%}"
    )


def main():
    rows = load_rows(HISTORY_PATH)
    print(f"rows={len(rows)} path={HISTORY_PATH}")
    if not rows:
        print("No hay historial local todavia. Deja correr el bot con logging para medir fills reales.")
        return

    counts = Counter(row.get("event") for row in rows)
    print("events:", dict(counts))

    fills = [row for row in rows if row.get("event") == "fill"]
    round_trips, open_inventory = pair_round_trips(fills)
    profits = [trade["profit"] for trade in round_trips]
    holds = [trade["hold_seconds"] for trade in round_trips if math.isfinite(trade["hold_seconds"])]
    print("round_trips:", summarize(profits))
    print("hold_seconds:", summarize(holds))
    print(f"open_inventory_units={len(open_inventory)}")

    snapshots = [row for row in rows if row.get("event") == "snapshot"]
    if snapshots:
        last = snapshots[-1]
        print(
            "last_snapshot:",
            f"pnl={last.get('pnl')}",
            f"equity={last.get('equity')}",
            f"pos={last.get('position')}",
            f"bid={last.get('bid')}",
            f"ask={last.get('ask')}",
            f"fair={last.get('fair')}",
        )

    if profits:
        avg = sum(profits) / len(profits)
        if avg < 0:
            print("suggestion: subir MIN_EDGE y bajar STOP_LOSS; las vueltas cerradas pierden en promedio.")
        elif len(open_inventory) > 0:
            print("suggestion: mantener MAX_POSITION=1 y usar salida mas rapida; hay inventario abierto.")
        else:
            print("suggestion: edge actual funciona en las vueltas cerradas; aumentar tamano seria prematuro hasta n>=20.")


if __name__ == "__main__":
    main()
