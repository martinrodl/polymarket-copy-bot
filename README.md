# Polymarket Copy Trading Bot

Basket copy-trading bot that follows top Polymarket wallets, detects consensus signals, and executes trades with quarter-Kelly position sizing.

## How it works

1. **Wallet Monitor** — polls Polymarket Data API every 60s for new trades from 5 target wallets
2. **Signal Engine** — when 2+ traders buy the same outcome on the same market → confirmed signal
3. **Position Sizer** — quarter-Kelly criterion, max $5 per trade (5% of $100 bankroll)
4. **Risk Manager** — drawdown protocol, exposure limits, daily stop-loss
5. **Executor** — paper trading (default) or live execution via CLOB API

## Target basket

| Trader | Category | Weight | Edge |
|--------|----------|--------|------|
| BAdiosB | Mispricing | 1.0 | 90.8% WR, 11.3% ROI |
| LucasMeow | Crypto | 0.8 | 94.9% WR, contrarian |
| Erasmus | Politics | 0.9 | $1.3M+ PnL, Iran/geopolitics |
| elkmonkey | Sports | 0.7 | NBA, MLB, NHL, UFC |
| gatorr | General | 0.7 | 18.6% profit/volume efficiency |

## Quick start

```bash
# 1. Configure
cp .env.example .env
# Edit .env — wallet addresses are pre-filled in .env.example

# 2. Install
pip install -e .

# 3. Paper trading (default)
python -m src.main run

# 4. Check status
python -m src.main status

# 5. Test wallet polling
python -m src.main wallets --test
```

## Requirements

- Python 3.12+
- No API keys needed for paper trading (Data API is free)
- Polymarket API keys required only for live trading

## Architecture

```
src/
├── config.py           # .env config + wallet targets
├── wallet_monitor.py   # Data API polling
├── signal_engine.py    # Consensus detection
├── position_sizer.py   # Quarter-Kelly sizing
├── risk_manager.py     # Portfolio limits + drawdown protocol
├── executor.py         # Paper + Live execution
├── db.py               # SQLite persistence
└── main.py             # CLI entry point
```

## Risk management

| Rule | Value |
|------|-------|
| Max per trade | 5% bankroll |
| Max total exposure | 30% bankroll |
| Min cash reserve | 50% bankroll |
| Daily stop-loss | 3% bankroll |
| Drawdown pause | -15% |
| Drawdown stop | -20% |
