"""
Canonical grid trading bot script (ScriptStrategy).

Upper/lower bounds may be updated at runtime by TradingExecutor via grid_runtime
(adaptive bounds + waterfall protection). Read bounds with ctx.param() each bar.
"""
from __future__ import annotations

GRID_BOT_SCRIPT = r'''
def on_init(ctx):
    ctx.param("upperPrice", 0)
    ctx.param("lowerPrice", 0)
    ctx.param("gridCount", 10)
    ctx.param("amountPerGrid", 0)
    ctx.param("gridMode", "arithmetic")
    ctx.param("gridDirection", "neutral")
    ctx.param("adaptiveBounds", True)
    ctx.param("waterfallProtection", True)
    ctx.param("prev_price", 0.0)
    ctx.param("long_exposure", 0.0)
    ctx.param("short_exposure", 0.0)
    ctx.param("waterfall_pause", False)
    ctx.log("grid bot init")


def _grid_levels(lo, hi, n, mode):
    n = max(2, int(n or 2))
    if str(mode or "").lower() == "geometric" and lo > 0 and hi > lo:
        ratio = (hi / lo) ** (1.0 / (n - 1))
        return [lo * (ratio ** i) for i in range(n)]
    step = (hi - lo) / float(n - 1)
    return [lo + step * i for i in range(n)]


def on_bar(ctx, bar):
    price = float(bar.close or 0)
    if price <= 0:
        return

    if ctx.param("waterfall_pause", False):
        ctx.log("grid paused: waterfall protection")
        return

    upper = float(ctx.param("upperPrice", 0) or 0)
    lower = float(ctx.param("lowerPrice", 0) or 0)
    if upper <= lower:
        return

    grid_count = int(ctx.param("gridCount", 10) or 10)
    amt = float(ctx.param("amountPerGrid", 0) or 0)
    if amt <= 0:
        return

    mode = ctx.param("gridMode", "arithmetic")
    direction = str(ctx.param("gridDirection", "neutral") or "neutral").lower()
    levels = _grid_levels(lower, upper, grid_count, mode)

    prev = float(ctx.param("prev_price", 0) or 0)
    if prev <= 0:
        ctx._params["prev_price"] = price
        return

    long_exp = float(ctx.param("long_exposure", 0) or 0)
    short_exp = float(ctx.param("short_exposure", 0) or 0)
    budget = float(ctx.balance or ctx.equity or 0)
    if budget <= 0:
        budget = amt * grid_count * 2

    crossed_down = prev > price
    crossed_up = prev < price

    for lv in levels:
        if prev >= lv > price and crossed_down:
            if direction in ("long", "neutral"):
                if short_exp > 0:
                    use = min(amt, short_exp)
                    ctx.buy(price=price, amount=use)
                    short_exp -= use
                    if use < amt and long_exp + (amt - use) <= budget:
                        ctx.buy(price=price, amount=amt - use)
                        long_exp += amt - use
                elif long_exp + amt <= budget:
                    ctx.buy(price=price, amount=amt)
                    long_exp += amt
            elif direction == "short" and short_exp + amt <= budget:
                ctx.sell(price=price, amount=amt)
                short_exp += amt
        elif prev <= lv < price and crossed_up:
            if direction in ("short", "neutral"):
                if long_exp > 0:
                    use = min(amt, long_exp)
                    ctx.sell(price=price, amount=use)
                    long_exp -= use
                    if use < amt and short_exp + (amt - use) <= budget:
                        ctx.sell(price=price, amount=amt - use)
                        short_exp += amt - use
                elif short_exp + amt <= budget:
                    ctx.sell(price=price, amount=amt)
                    short_exp += amt
            elif direction == "long" and long_exp > 0:
                use = min(amt, long_exp)
                ctx.sell(price=price, amount=use)
                long_exp -= use

    ctx._params["prev_price"] = price
    ctx._params["long_exposure"] = long_exp
    ctx._params["short_exposure"] = short_exp
'''


def build_grid_bot_script() -> str:
    return GRID_BOT_SCRIPT.strip() + "\n"
