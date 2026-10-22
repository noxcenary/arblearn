
Learning-only cross-exchange arbitrage monitor
(NO real trading, NO API keys).

Features:
- Fetches public Binance and OKX order books
- Calculates arbitrage in both directions
- Chooses the more profitable direction
- Simulates ONLY the best profitable trade
- Tracks simulated capital
- Shows current capital
- Live capital graph
- Stops when capital reaches 0
- Stops after 75 consecutive no-trade cycles
- Logs simulated trades to CSV

Install:
    pip install requests matplotlib

Run:
    python arb_monitor.py
"""

import csv
import os
import time
from datetime import datetime, timezone

import requests
import matplotlib.pyplot as plt


# ================================================================
# CONFIG
# ================================================================

BINANCE_SYMBOL = "GRAMUSDT"
OKX_INST_ID = "GRAM-USDT"

DEPTH = 100

# Simulated trade size
TRADE_SIZE = 50000.0

# 0.1% fee per leg
FEE_RATE = 0.001

# Seconds between order-book checks
POLL_SECONDS = 1.0

# CSV log
LOG_FILE = "opportunities.csv"

# Starting simulated capital
STARTING_CAPITAL = 10000.0

# Stop after this many consecutive cycles without a trade
MAX_NO_TRADE_CYCLES = 75


# ================================================================
# BINANCE
# ================================================================

def fetch_binance():

    r = requests.get(
        "https://api.binance.com/api/v3/depth",
        params={
            "symbol": BINANCE_SYMBOL,
            "limit": DEPTH
        },
        timeout=5,
    )

    r.raise_for_status()

    d = r.json()

    if "bids" not in d:

        raise RuntimeError(
            f"Binance returned: {d}"
        )

    bids = [
        (float(p), float(q))
        for p, q in d["bids"]
    ]

    asks = [
        (float(p), float(q))
        for p, q in d["asks"]
    ]

    return bids, asks


# ================================================================
# OKX
# ================================================================

def fetch_okx():

    r = requests.get(
        "https://www.okx.com/api/v5/market/books",
        params={
            "instId": OKX_INST_ID,
            "sz": DEPTH
        },
        timeout=5,
    )

    r.raise_for_status()

    payload = r.json()

    if (
        payload.get("code") != "0"
        or not payload.get("data")
    ):

        raise RuntimeError(
            f"OKX returned: {payload}"
        )

    d = payload["data"][0]

    bids = [
        (float(x[0]), float(x[1]))
        for x in d["bids"]
    ]

    asks = [
        (float(x[0]), float(x[1]))
        for x in d["asks"]
    ]

    return bids, asks


# ================================================================
# ORDER BOOK WALKING
# ================================================================

def avg_fill_price(levels, size):

    """
    Walk through the order book.

    Returns:

        average_fill_price
        filled_quantity
    """

    remaining = size
    cost = 0.0

    for price, qty in levels:

        take = min(
            remaining,
            qty
        )

        cost += take * price

        remaining -= take

        if remaining <= 1e-12:

            break

    filled = size - remaining

    if filled == 0:

        return 0.0, 0.0

    average_price = cost / filled

    return average_price, filled


# ================================================================
# ARBITRAGE CALCULATION
# ================================================================

def evaluate(
    buy_asks,
    sell_bids,
    size
):

    """
    Simulate:

        BUY on one exchange
        SELL on the other exchange
    """

    buy_px, buy_filled = avg_fill_price(
        buy_asks,
        size
    )

    sell_px, sell_filled = avg_fill_price(
        sell_bids,
        size
    )

    qty = min(
        buy_filled,
        sell_filled
    )

    if qty == 0:

        return None

    # ------------------------------------------------------------
    # BUY
    # ------------------------------------------------------------

    buy_cost = (
        buy_px
        * qty
    )

    buy_fee = (
        buy_cost
        * FEE_RATE
    )

    total_cost = (
        buy_cost
        + buy_fee
    )

    # ------------------------------------------------------------
    # SELL
    # ------------------------------------------------------------

    sell_revenue = (
        sell_px
        * qty
    )

    sell_fee = (
        sell_revenue
        * FEE_RATE
    )

    total_revenue = (
        sell_revenue
        - sell_fee
    )

    # ------------------------------------------------------------
    # PROFIT
    # ------------------------------------------------------------

    profit = (
        total_revenue
        - total_cost
    )

    net_percentage = (
        profit
        / total_cost
        * 100
    )

    return {

        "qty":
            qty,

        "buy_px":
            buy_px,

        "sell_px":
            sell_px,

        "buy_cost":
            buy_cost,

        "buy_fee":
            buy_fee,

        "sell_revenue":
            sell_revenue,

        "sell_fee":
            sell_fee,

        "net_profit_usdt":
            profit,

        "net_pct":
            net_percentage,
    }


# ================================================================
# CSV LOGGING
# ================================================================

def log_row(row):

    new_file = not os.path.exists(
        LOG_FILE
    )

    with open(
        LOG_FILE,
        "a",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=row.keys()
        )

        if new_file:

            writer.writeheader()

        writer.writerow(row)


# ================================================================
# MAIN
# ================================================================

def main():

    # ============================================================
    # CAPITAL
    # ============================================================

    total_capital = STARTING_CAPITAL

    # Number of actual simulated trades
    trade_number = 0

    # Number of consecutive cycles with NO trade
    no_trade_cycles = 0

    # ============================================================
    # GRAPH DATA
    # ============================================================

    trade_history = [0]

    capital_history = [
        total_capital
    ]

    # ============================================================
    # GRAPH
    # ============================================================

    plt.ion()

    fig, ax = plt.subplots()

    # No marker="o"
    # Therefore there are no dots.

    line, = ax.plot(
        trade_history,
        capital_history
    )

    ax.set_title(
        "Simulated Arbitrage Capital"
    )

    ax.set_xlabel(
        "Trade Number"
    )

    ax.set_ylabel(
        "Capital (USDT)"
    )

    ax.grid(True)

    # ============================================================
    # START MESSAGE
    # ============================================================

    print()
    print("=" * 80)

    print(
        f"Monitoring "
        f"{BINANCE_SYMBOL} / {OKX_INST_ID}"
    )

    print(
        f"Trade size: "
        f"{TRADE_SIZE} GRAM"
    )

    print(
        f"Fee per leg: "
        f"{FEE_RATE * 100:.3f}%"
    )

    print(
        f"Starting capital: "
        f"{STARTING_CAPITAL:.2f} USDT"
    )

    print(
        f"Maximum consecutive no-trade cycles: "
        f"{MAX_NO_TRADE_CYCLES}"
    )

    print("=" * 80)

    # ============================================================
    # MAIN LOOP
    # ============================================================

    while True:

        # ========================================================
        # CAPITAL CHECK
        # ========================================================

        if total_capital <= 0:

            total_capital = 0.0

            print()
            print("=" * 80)
            print("CAPITAL DEPLETED")
            print(
                "Current capital: "
                "0.00 USDT"
            )
            print(
                "Monitor stopped automatically."
            )
            print("=" * 80)

            break

        # ========================================================
        # FETCH ORDER BOOKS
        # ========================================================

        try:

            b_bids, b_asks = fetch_binance()

            o_bids, o_asks = fetch_okx()

        except Exception as e:

            print(
                f"FETCH ERROR | "
                f"Capital: {total_capital:.2f} USDT | "
                f"{e}"
            )

            time.sleep(
                POLL_SECONDS
            )

            continue

        # ========================================================
        # TIMESTAMP
        # ========================================================

        ts = datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )

        # ========================================================
        # CALCULATE BOTH DIRECTIONS
        # ========================================================

        binance_to_okx = evaluate(
            b_asks,
            o_bids,
            TRADE_SIZE
        )

        okx_to_binance = evaluate(
            o_asks,
            b_bids,
            TRADE_SIZE
        )

        # ========================================================
        # STORE VALID ROUTES
        # ========================================================

        routes = {}

        if binance_to_okx is not None:

            routes[
                "buy_binance_sell_okx"
            ] = binance_to_okx

        if okx_to_binance is not None:

            routes[
                "buy_okx_sell_binance"
            ] = okx_to_binance

        # ========================================================
        # NO VALID ROUTES
        # ========================================================

        if not routes:

            no_trade_cycles += 1

            print(
                f"{ts} | "
                f"NO ROUTE | "
                f"Capital: "
                f"{total_capital:.2f} USDT | "
                f"No-trade cycles: "
                f"{no_trade_cycles}/"
                f"{MAX_NO_TRADE_CYCLES}"
            )

            # Check stop condition
            if (
                no_trade_cycles
                >= MAX_NO_TRADE_CYCLES
            ):

                print()
                print("=" * 80)
                print(
                    "75 CONSECUTIVE NO-TRADE CYCLES"
                )
                print(
                    f"Final capital: "
                    f"{total_capital:.2f} USDT"
                )
                print(
                    "Monitor stopped automatically."
                )
                print("=" * 80)

                break

            time.sleep(
                POLL_SECONDS
            )

            continue

        # ========================================================
        # FIND BEST ROUTE
        # ========================================================

        best_route, best_result = max(
            routes.items(),
            key=lambda x:
                x[1]["net_profit_usdt"]
        )

        # ========================================================
        # EXTRACT RESULT
        # ========================================================

        profit = best_result[
            "net_profit_usdt"
        ]

        percentage = best_result[
            "net_pct"
        ]

        qty = best_result[
            "qty"
        ]

        # ========================================================
        # NO PROFITABLE TRADE
        # ========================================================

        if profit <= 0:

            no_trade_cycles += 1

            print(
                f"{ts} | "
                f"BEST: {best_route:24s} | "
                f"net={percentage:+.4f}% | "
                f"P&L={profit:+.4f} USDT | "
                f"NO TRADE | "
                f"Capital: "
                f"{total_capital:.2f} USDT | "
                f"No-trade cycles: "
                f"{no_trade_cycles}/"
                f"{MAX_NO_TRADE_CYCLES}"
            )

            # Check stop condition
            if (
                no_trade_cycles
                >= MAX_NO_TRADE_CYCLES
            ):

                print()
                print("=" * 80)
                print(
                    "75 CONSECUTIVE NO-TRADE CYCLES"
                )
                print(
                    f"Final capital: "
                    f"{total_capital:.2f} USDT"
                )
                print(
                    "Monitor stopped automatically."
                )
                print("=" * 80)

                break

            time.sleep(
                POLL_SECONDS
            )

            continue

        # ========================================================
        # PROFITABLE TRADE
        # ========================================================

        # A trade happened, therefore reset counter.
        no_trade_cycles = 0

        # Update simulated capital
        total_capital += profit

        # Safety
        if total_capital < 0:

            total_capital = 0.0

        trade_number += 1

        # ========================================================
        # SAVE GRAPH DATA
        # ========================================================

        trade_history.append(
            trade_number
        )

        capital_history.append(
            total_capital
        )

        # ========================================================
        # PRINT TRADE
        # ========================================================

        print()
        print("-" * 80)

        print(
            f"{ts} | "
            f"TRADE #{trade_number}"
        )

        print(
            f"Route:          "
            f"{best_route}"
        )

        print(
            f"Quantity:       "
            f"{qty:.4f} GRAM"
        )

        print(
            f"Buy price:      "
            f"{best_result['buy_px']:.6f}"
        )

        print(
            f"Sell price:     "
            f"{best_result['sell_px']:.6f}"
        )

        print(
            f"Net spread:     "
            f"{percentage:+.4f}%"
        )

        print(
            f"Trade P&L:      "
            f"{profit:+.6f} USDT"
        )

        print(
            f"CURRENT CAPITAL: "
            f"{total_capital:.6f} USDT"
        )

        print(
            f"No-trade cycles: "
            f"{no_trade_cycles}/"
            f"{MAX_NO_TRADE_CYCLES}"
        )

        print("-" * 80)

        # ========================================================
        # UPDATE GRAPH
        # ========================================================

        line.set_xdata(
            trade_history
        )

        line.set_ydata(
            capital_history
        )

        ax.relim()

        ax.autoscale_view()

        fig.canvas.draw()

        fig.canvas.flush_events()

        # ========================================================
        # LOG TRADE
        # ========================================================

        log_row({

            "timestamp":
                ts,

            "trade_number":
                trade_number,

            "route":
                best_route,

            "qty":
                round(
                    qty,
                    4
                ),

            "buy_px":
                round(
                    best_result["buy_px"],
                    6
                ),

            "sell_px":
                round(
                    best_result["sell_px"],
                    6
                ),

            "net_profit_usdt":
                round(
                    profit,
                    6
                ),

            "net_pct":
                round(
                    percentage,
                    6
                ),

            "simulated_total_capital":
                round(
                    total_capital,
                    6
                ),

        })

        # ========================================================
        # CAPITAL DEPLETED
        # ========================================================

        if total_capital <= 0:

            print()
            print("=" * 80)

            print(
                "CAPITAL DEPLETED"
            )

            print(
                "Current capital: "
                "0.00 USDT"
            )

            print(
                "Monitor stopped automatically."
            )

            print("=" * 80)

            plt.ioff()

            plt.show()

            return

        # ========================================================
        # WAIT
        # ========================================================

        time.sleep(
            POLL_SECONDS
        )


# ================================================================
# PROGRAM START
# ================================================================

if __name__ == "__main__":

    main()