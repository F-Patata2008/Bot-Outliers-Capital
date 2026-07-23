import argparse


LOW = 620.0
HIGH = 880.0
SPAN = HIGH - LOW
COINS = 10_000


def expected_profit_normalized(t):
    """
    Expected profit divided by SPAN for normalized bids t.

    If reserve r has CDF F(t)=t^2 on [0, 1], bid t_i earns (1 - t_i)
    whenever r is in (t_{i-1}, t_i].
    """
    total = 0.0
    prev = 0.0
    for bid in t:
        total += (1.0 - bid) * (bid * bid - prev * prev)
        prev = bid
    return total


def build_stationary_points(first_bid, num_bids):
    points = [first_bid]
    prev = 0.0
    cur = first_bid

    for _ in range(1, num_bids):
        nxt = (3.0 * cur * cur - prev * prev) / (2.0 * cur)
        points.append(nxt)
        prev, cur = cur, nxt

    return points


def terminal_condition(first_bid, num_bids):
    points = build_stationary_points(first_bid, num_bids)

    if num_bids == 1:
        last = points[-1]
        return 2.0 * last - 3.0 * last * last

    before_last = points[-2]
    last = points[-1]
    return before_last * before_last + 2.0 * last - 3.0 * last * last


def optimal_normalized_bids(num_bids):
    if num_bids < 1:
        raise ValueError("num_bids debe ser al menos 1")

    lo = 0.0
    hi = 1.0

    for _ in range(100):
        mid = (lo + hi) / 2.0
        if terminal_condition(mid, num_bids) > 0.0:
            lo = mid
        else:
            hi = mid

    return build_stationary_points((lo + hi) / 2.0, num_bids)


def optimize_phase(num_bids, steps=None, restarts=None, lr=None, seed=None):
    best_t = optimal_normalized_bids(num_bids)
    best_profit = expected_profit_normalized(best_t)

    bids = [LOW + SPAN * t for t in best_t]
    profit_per_coin = SPAN * best_profit
    total_profit = COINS * profit_per_coin

    return bids, profit_per_coin, total_profit


def main():
    parser = argparse.ArgumentParser(
        description="Optimiza ofertas para el problema Zanni de Oro sin librerias externas."
    )
    parser.add_argument(
        "--max-bids",
        type=int,
        default=3,
        help="Cantidad maxima de ofertas/fases a resolver.",
    )
    parser.add_argument("--steps", type=int, default=4000, help=argparse.SUPPRESS)
    parser.add_argument("--restarts", type=int, default=40, help=argparse.SUPPRESS)
    parser.add_argument("--lr", type=float, default=0.05, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args()

    for num_bids in range(1, args.max_bids + 1):
        bids, profit_per_coin, total_profit = optimize_phase(
            num_bids=num_bids,
            steps=args.steps,
            restarts=args.restarts,
            lr=args.lr,
            seed=args.seed + num_bids,
        )

        bids_text = ", ".join(f"{bid:.6f}" for bid in bids)
        print(f"Fase {num_bids}: {bids_text}")
        print(f"  Ganancia esperada por moneda: {profit_per_coin:.6f} Lucas")
        print(f"  Ganancia esperada total:      {total_profit:.2f} Lucas")


if __name__ == "__main__":
    main()
