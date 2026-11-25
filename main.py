"""Tiny Bot — mean-reversion dip buyer for agent-fun/bars-replay/v1.

Strategy (tuned offline on the frozen dev window, 136 hourly bars):
  - Buy a symbol 2% below its 20-hour EMA, sized to 25% of equity (the
    competition's max weight), at most one open position per symbol.
  - Sell when the close recovers to / above the EMA, or on +3% take-profit,
    -3% stop-loss, or after a 24-bar max hold — whichever comes first.
  - Dev-window grade of this exact rule (grade-local, process driver):
    +$6.0 net PnL, 30 trades, 4.4% max drawdown, vs the buy-and-hold
    baseline -$869.3 on the same window.

Deterministic: pure function of the bars seen so far. No clock, no
environment, no randomness, no network. Orders decided on bar k fill at
bar k+1's open, so every signal uses only closes already delivered.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

EMA_PERIOD = 20          # hours in the EMA
DIP = 0.02               # buy when close is 2% below the EMA
TAKE_PROFIT = 0.03       # sell at +3% vs entry close
STOP_LOSS = 0.03         # sell at -3% vs entry close
MAX_HOLD_BARS = 24       # sell after 24 bars held, whatever the price
MIN_HISTORY = 20         # bars of closes before the first signal
MIN_BUY_USDC_UNITS = 100_000_000   # $100 minimum buy (quote units, 6dp)
MAX_SLIPPAGE_BPS = 10_000          # wide open, as the house baselines do
DRAWDOWN_GUARD = 0.20    # stop opening new positions past 20% drawdown
                         # (limit is 25%; the guard leaves headroom)

_EMA_K = 2.0 / (EMA_PERIOD + 1)

# Per-symbol state, built only from bars the harness has delivered.
_closes = {}    # symbol -> list[int] of closes, oldest first
_ema = {}       # symbol -> float EMA of closes
_entry = {}     # symbol -> (entry_close int, entry_seq int) of the open buy
_pending = {}   # symbol -> "buy" | "sell" order sent, awaiting its fill
_peak_equity = [0]  # highest equity seen, for the drawdown guard


def _record_bar(state):
    """Fold this batch's closes into history and EMA. Runs on warm-up
    bars too, so the EMA is warm by the first tradable batch."""
    for symbol in state.symbols:
        close = state.close(symbol)
        if close is None:
            continue
        hist = _closes.setdefault(symbol, [])
        hist.append(close)
        if symbol in _ema:
            _ema[symbol] = close * _EMA_K + _ema[symbol] * (1.0 - _EMA_K)
        else:
            _ema[symbol] = float(close)


def on_batch(state, batch):
    _record_bar(state)
    if state.warming_up:
        return []  # orders on warm-up bars are rejected; just build history

    if state.equity > _peak_equity[0]:
        _peak_equity[0] = state.equity
    drawdown = 0.0
    if _peak_equity[0] > 0:
        drawdown = (_peak_equity[0] - state.equity) / _peak_equity[0]
    may_buy = drawdown <= DRAWDOWN_GUARD

    orders = []
    # Cash left to spend in THIS reply. Each buy is sized against it and
    # spends it down, so one reply can never order more than the cash
    # (the old code sized every buy against the full cash, and a
    # market-wide dip ordered ~150% of equity: 3 of 7 buys were rejected
    # for insufficient cash). Sells in this reply do not add to it: their
    # proceeds never fund a buy of the same reply.
    cash_left = state.cash
    for symbol in state.symbols:
        close = state.close(symbol)
        if close is None or symbol not in _ema:
            continue
        holding = state.positions.get(symbol)
        pending = _pending.get(symbol)

        # Resolve last bar's pending order against the account we now see.
        # The harness fills orders at the next bar's open, so by this batch
        # the outcome is known. A buy that filled shows a holding: clear
        # the pending flag but keep the entry, so the sell rules below can
        # run. (The old code only cleared pending when the buy had NOT
        # filled, so a filled buy stayed "pending" forever, its sell rules
        # never ran, and the position sat until the end-of-data flatten.)
        # A buy with no holding was rejected: drop its entry and try again
        # later. A sell that filled leaves no holding; one that did not
        # was rejected and is retried next bar.
        if pending == "buy":
            if holding is None:
                _entry.pop(symbol, None)
            _pending.pop(symbol, None)
            pending = None
        elif pending == "sell":
            _pending.pop(symbol, None)
            pending = None

        if holding is None:
            if not may_buy:
                continue
            if len(_closes.get(symbol, ())) < MIN_HISTORY:
                continue
            if close < _ema[symbol] * (1.0 - DIP):
                room = min(state.weight_room(symbol), cash_left)
                # Skip thin-pool fills: never pay more than 50 bps of
                # constant-product price impact on a single buy. On the
                # dev window depths this never binds (a $2,500 buy costs
                # well under 1 bp); it only guards the unseen final window.
                impact = state.impact_bps(symbol, int(room))
                if impact is not None and impact > 50:
                    continue
                if room >= MIN_BUY_USDC_UNITS:
                    orders.append({
                        "side": "buy",
                        "symbol": symbol,
                        "notional_quote_units": int(room),
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    })
                    cash_left -= int(room)
                    _pending[symbol] = "buy"
                    _entry[symbol] = (close, state.seq)
        else:
            entry_close, entry_seq = _entry.get(symbol, (close, state.seq))
            gain = close / entry_close - 1.0
            if (close >= _ema[symbol]
                    or gain >= TAKE_PROFIT
                    or gain <= -STOP_LOSS
                    or state.seq - entry_seq >= MAX_HOLD_BARS):
                orders.append({
                    "side": "sell",
                    "symbol": symbol,
                    "qty": holding.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                })
                _pending[symbol] = "sell"
                _entry.pop(symbol, None)

    return orders


makefun_bars.run(on_batch)
