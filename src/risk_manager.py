"""Risk management — pre-trade checks and portfolio limits."""
from __future__ import annotations

from .config import config
from .db import Database
from .logger import log
from .models import PortfolioState, Signal


class RiskManager:
    def __init__(self, db: Database):
        self.db = db
        self.peak_bankroll = config.trading.bankroll

    def get_portfolio_state(self) -> PortfolioState:
        tc = config.trading
        exposure = self.db.get_total_exposure()
        daily_pnl = self.db.get_today_pnl()
        open_pos = self.db.get_open_positions_count()
        bankroll = tc.bankroll + daily_pnl
        cash = bankroll - exposure

        if bankroll > self.peak_bankroll:
            self.peak_bankroll = bankroll

        drawdown = 0.0
        if self.peak_bankroll > 0:
            drawdown = ((self.peak_bankroll - bankroll) / self.peak_bankroll) * 100

        return PortfolioState(
            bankroll=bankroll,
            cash_available=max(0, cash),
            total_exposure=exposure,
            open_positions=open_pos,
            daily_pnl=daily_pnl,
            peak_bankroll=self.peak_bankroll,
            drawdown_pct=drawdown,
        )

    def check_signal(self, signal: Signal, bet_amount: float) -> tuple[bool, str]:
        """Run all risk checks. Returns (approved, reason)."""
        tc = config.trading
        state = self.get_portfolio_state()

        if state.drawdown_pct >= tc.drawdown_stop:
            return False, f"drawdown {state.drawdown_pct:.1f}% >= {tc.drawdown_stop}% stop"

        if state.drawdown_pct >= tc.drawdown_pause:
            return False, f"drawdown {state.drawdown_pct:.1f}% >= {tc.drawdown_pause}% pause"

        daily_loss_limit = state.bankroll * (tc.daily_loss_limit_pct / 100)
        if state.daily_pnl < -daily_loss_limit:
            return False, f"daily loss ${-state.daily_pnl:.2f} >= limit ${daily_loss_limit:.2f}"

        max_exposure = state.bankroll * (tc.max_total_exposure_pct / 100)
        if state.total_exposure + bet_amount > max_exposure:
            return False, f"total exposure ${state.total_exposure + bet_amount:.2f} > max ${max_exposure:.2f}"

        min_cash = state.bankroll * (tc.min_cash_reserve_pct / 100)
        if state.cash_available - bet_amount < min_cash:
            return False, f"cash after trade ${state.cash_available - bet_amount:.2f} < reserve ${min_cash:.2f}"

        market_exposure = self.db.get_market_exposure(signal.market_key)
        max_market = state.bankroll * (tc.max_single_market_pct / 100)
        if market_exposure + bet_amount > max_market:
            return False, f"market exposure ${market_exposure + bet_amount:.2f} > max ${max_market:.2f}"

        return True, "approved"

    def log_state(self) -> None:
        state = self.get_portfolio_state()
        self.db.save_portfolio_snapshot({
            "bankroll": state.bankroll,
            "cash_available": state.cash_available,
            "total_exposure": state.total_exposure,
            "open_positions": state.open_positions,
            "daily_pnl": state.daily_pnl,
            "peak_bankroll": state.peak_bankroll,
            "drawdown_pct": state.drawdown_pct,
        })
        log(f"Portfolio: ${state.bankroll:.2f} bankroll, "
            f"${state.cash_available:.2f} cash, "
            f"${state.total_exposure:.2f} exposure, "
            f"{state.open_positions} positions, "
            f"daily P&L ${state.daily_pnl:+.2f}, "
            f"DD {state.drawdown_pct:.1f}%", "info")
