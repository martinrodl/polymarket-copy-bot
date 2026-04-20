"""Polymarket Copy Trading Bot — entry point."""
from __future__ import annotations

import argparse
import signal
import time

from .config import config
from .db import Database
from .executor import create_executor
from .logger import log, log_banner, DIM, GREEN, RESET
from .models import SignalStatus
from .position_sizer import kelly_size
from .risk_manager import RiskManager
from .signal_engine import SignalEngine
from .wallet_monitor import poll_all_wallets


def run_loop(args) -> None:
    db = Database()
    risk = RiskManager(db)
    engine = SignalEngine(db)
    executor = create_executor(db)

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False
        print(f"\n{DIM}Shutting down...{RESET}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    wallet_names = [w.name for w in config.wallets]

    log_banner("Polymarket Copy Trading Bot", {
        "Mode": config.trading.mode.upper(),
        "Bankroll": f"${config.trading.bankroll:.2f}",
        "Max trade": f"${config.trading.max_trade_size:.2f}",
        "Min consensus": str(config.trading.min_consensus),
        "Signal window": f"{config.trading.signal_window_minutes} min",
        "Poll interval": f"{args.interval}s",
        "Wallets": ", ".join(wallet_names) or "(none configured)",
        "Kelly fraction": str(config.trading.kelly_fraction),
        "DB": str(config.db_path),
    })

    if not config.wallets:
        log("No wallet addresses configured! Add them to .env", "error")
        log("See .env.example for format: WALLET_BADIOSB=0x...", "error")
        return

    poll_count = 0
    total_signals = 0
    total_trades = 0

    while running:
        poll_count += 1
        log(f"{DIM}{'─' * 20} Poll #{poll_count} {'─' * 20}{RESET}")

        try:
            new_trades = poll_all_wallets(db)

            if new_trades:
                log(f"Detected {len(new_trades)} new trade(s) across wallets")

                signals = engine.ingest(new_trades)

                for sig in signals:
                    total_signals += 1
                    portfolio = risk.get_portfolio_state()

                    bet_amount = kelly_size(sig, portfolio)
                    if bet_amount is None:
                        db.update_signal_status(0, SignalStatus.REJECTED.value)
                        continue

                    approved, reason = risk.check_signal(sig, bet_amount)
                    if not approved:
                        log(f"Risk rejected: {reason}", "risk")
                        continue

                    signal_id = db.insert_signal(
                        market_key=sig.market_key,
                        market_slug=sig.market_slug,
                        question=sig.question,
                        outcome=sig.outcome,
                        side=sig.side.value,
                        consensus_count=sig.consensus_count,
                        source_names=",".join(sig.source_names),
                        avg_price=sig.avg_price,
                        status=SignalStatus.EXECUTED.value,
                    )

                    trade = executor.execute(sig, bet_amount, signal_id)
                    if trade:
                        total_trades += 1
            else:
                pending = engine.get_pending_summary()
                if pending:
                    parts = [f"{m}: {c}/{config.trading.min_consensus}"
                             for m, c in pending.items()]
                    log(f"{DIM}Pending signals: {', '.join(parts)}{RESET}")
                else:
                    log(f"{DIM}No new trades detected{RESET}")

            risk.log_state()

            if poll_count % 10 == 0:
                stats = db.get_signals_stats(since_hours=24)
                if stats.get("total", 0) > 0:
                    log(f"24h: {stats['total']} signals, "
                        f"{stats.get('executed', 0)} executed, "
                        f"{stats.get('rejected', 0)} rejected, "
                        f"avg consensus {stats.get('avg_consensus', 0):.1f}")

        except Exception as e:
            log(f"Poll error: {e}", "error")

        if running:
            time.sleep(args.interval)

    log(f"Session: {poll_count} polls, {total_signals} signals, "
        f"{total_trades} trades executed")


def run_status(args) -> None:
    db = Database()
    risk = RiskManager(db)
    state = risk.get_portfolio_state()

    print(f"\n{'─' * 50}")
    print(f"  Bankroll:       ${state.bankroll:.2f}")
    print(f"  Cash available: ${state.cash_available:.2f}")
    print(f"  Exposure:       ${state.total_exposure:.2f}")
    print(f"  Open positions: {state.open_positions}")
    print(f"  Daily P&L:      ${state.daily_pnl:+.2f}")
    print(f"  Drawdown:       {state.drawdown_pct:.1f}%")
    print(f"{'─' * 50}")

    for hours in [1, 6, 24]:
        stats = db.get_signals_stats(since_hours=hours)
        total = stats.get("total", 0)
        if total:
            print(f"  {hours:>2d}h: {total} signals, "
                  f"{stats.get('executed', 0)} executed")
        else:
            print(f"  {hours:>2d}h: no signals")
    print()


def run_wallets(args) -> None:
    if not config.wallets:
        print("No wallets configured. Add addresses to .env")
        return

    print(f"\n{'─' * 60}")
    print(f"  {'Name':<15s} {'Category':<12s} {'Weight':<8s} Address")
    print(f"{'─' * 60}")
    for w in config.wallets:
        addr = w.address[:10] + "..." + w.address[-6:] if len(w.address) > 20 else w.address
        print(f"  {w.name:<15s} {w.category:<12s} {w.weight:<8.1f} {addr}")
    print(f"{'─' * 60}\n")

    if args.test:
        log("Testing wallet polling...")
        db = Database()
        trades = poll_all_wallets(db)
        print(f"\n  Found {len(trades)} new trades across {len(config.wallets)} wallets")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Copy Trading Bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run copy trading loop")
    p_run.add_argument("--interval", type=int, default=config.trading.poll_interval,
                       help=f"Seconds between polls (default: {config.trading.poll_interval})")

    sub.add_parser("status", help="Show portfolio status")

    p_wallets = sub.add_parser("wallets", help="Show configured wallets")
    p_wallets.add_argument("--test", action="store_true",
                           help="Test-poll all wallets for recent trades")

    args = parser.parse_args()

    if args.command == "run":
        run_loop(args)
    elif args.command == "status":
        run_status(args)
    elif args.command == "wallets":
        run_wallets(args)


if __name__ == "__main__":
    main()
