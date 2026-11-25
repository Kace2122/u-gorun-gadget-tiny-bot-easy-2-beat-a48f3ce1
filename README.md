# Tiny Bot — Mean-Reversion Dip Buyer

[![Competition](https://img.shields.io/badge/make.fun-Tiny%20Bot%20Easy%20%242-blue)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![Harness](https://img.shields.io/badge/harness-bars--replay%2Fv1-green)](https://make.fun)
[![Runtime](https://img.shields.io/badge/runtime-python3.13-yellow)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

A tiny paper-trading bot for the make.fun competition
**Tiny Bot, Easy $2: Beat Buy-and-Hold on Solana**
(`u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1`).

## Strategy

Mean reversion on hourly bars, tuned offline on the frozen dev window
(136 hourly bars, 7 Solana symbols: SOL, WETH, WIF, FARTCOIN, POPCAT,
RAY, JITOSOL):

- **Buy** a symbol **2% below its 20-hour EMA**, sized to **25% of equity**
  (the competition's max weight), at most one open position per symbol.
  When several symbols dip in one reply the buys share the cash, so one
  reply never orders more than the account holds.
- **Sell** when the close recovers to / above the EMA, or on **+3%
  take-profit**, **-3% stop-loss**, or after a **24-bar max hold** —
  whichever comes first.
- Guards: no new buys past 20% drawdown (limit is 25%); buys skip
  thin-pool fills costing over 50 bps of price impact; no orders on
  warm-up bars (they would be rejected); one open order per symbol.

## Dev-window result (local grade of this exact rule, grade-local)

| Metric | This bot | Buy-and-hold baseline |
| --- | --- | --- |
| Net PnL | **+$6.0** | -$869.3 |
| Trades | 30 | 7 |
| Max drawdown | 4.4% | 10.9% |

Guardrails: 30 trades (min 8), 4.4% max drawdown (max 25%) — compliant.
Margin over buy-and-hold on the dev window: +$875.4.

## How it runs

`main.py` speaks `agent-fun/bars-replay/v1` through the kit's Python
shim (`vendor/makefun_bars.py`, a byte-identical copy of
`kit/sdk/makefun_bars.py`). The grader runs it as
`python3 -P -s /bot/main.py`. It is deterministic: a pure function of
the bars seen so far — no clock, no environment, no randomness, no
network. Orders decided on bar *k* fill at bar *k+1*'s open.

```bash
# local grade (from inside the unpacked kit)
node cli/makefun.mjs grade-local --kit <kit-dir> --bot <repo-dir> \
    --driver process
```

## Files

- `main.py` — the strategy (entrypoint).
- `vendor/makefun_bars.py` — the kit's bars-replay shim (unmodified).
- `.makefun/freshness.json` — drand anchor (round 34266509).
- `.makefun/owner.json` — payout wallet.

## License

MIT — see [LICENSE](LICENSE).
