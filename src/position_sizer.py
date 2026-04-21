"""Quarter-Kelly position sizing for copy trade signals."""
from __future__ import annotations

import math

from .config import config
from .logger import log
from .models import PortfolioState, Signal


def kelly_size(
    signal: Signal,
    portfolio: PortfolioState,
) -> float | None:
    """Calculate position size using fractional Kelly criterion.

    Returns the dollar amount to bet, or None if the trade should be skipped.
    """
    tc = config.trading

    if portfolio.cash_available <= 0:
        log("No cash available — skipping", "risk")
        return None

    if portfolio.drawdown_pct >= tc.drawdown_stop:
        log(f"Drawdown {portfolio.drawdown_pct:.1f}% >= stop threshold — halted", "risk")
        return None

    if portfolio.drawdown_pct >= tc.drawdown_pause:
        log(f"Drawdown {portfolio.drawdown_pct:.1f}% >= pause threshold — skipping", "risk")
        return None

    # Estimate edge from signal quality
    base_win_prob = _estimate_win_probability(signal)
    if base_win_prob <= 0.5:
        log(f"Estimated win prob {base_win_prob:.2f} <= 0.50 — no edge", "risk")
        return None

    price = signal.avg_price
    if price <= 0 or price >= 1:
        return None

    # Kelly: f* = (b*p - q) / b, where b = (1-price)/price for binary outcome
    b = (1.0 - price) / price  # payout odds
    p = base_win_prob
    q = 1.0 - p

    full_kelly = (b * p - q) / b if b > 0 else 0
    if full_kelly <= 0:
        log(f"Kelly fraction negative (p={p:.2f}, price={price:.3f}) — no edge", "risk")
        return None

    fractional = full_kelly * tc.kelly_fraction

    # Scale by drawdown
    scale = 1.0
    if portfolio.drawdown_pct >= tc.drawdown_reduce_50:
        scale = 0.5
        log(f"Drawdown {portfolio.drawdown_pct:.1f}% — sizing reduced 50%", "risk")

    bet_pct = fractional * scale
    bet_amount = portfolio.bankroll * bet_pct

    # Apply caps
    max_single = portfolio.bankroll * (tc.max_single_market_pct / 100)
    bet_amount = min(bet_amount, max_single)
    bet_amount = min(bet_amount, tc.max_trade_size)
    bet_amount = min(bet_amount, portfolio.cash_available)

    min_bet = 0.50
    if bet_amount < min_bet:
        log(f"Bet ${bet_amount:.2f} below minimum ${min_bet} — skipping", "risk")
        return None

    bet_amount = math.floor(bet_amount * 100) / 100

    log(f"Kelly: p={p:.2f} b={b:.2f} f*={full_kelly:.3f} "
        f"frac={fractional:.3f} → ${bet_amount:.2f}", "trade")
    return bet_amount


def _estimate_win_probability(signal: Signal) -> float:
    """Estimate win probability from signal properties.

    Heuristic based on:
    - Number of agreeing traders (consensus)
    - Average price (market's implied probability)
    - Weighted confidence of sources
    """
    market_prob = signal.avg_price
    consensus = signal.consensus_count
    confidence = signal.weighted_confidence

    # Base: trust the market price
    p = market_prob

    # Solo follow gets smaller bonus than consensus
    consensus_bonus = (consensus - 1) * 0.03  # +3% per extra trader

    # Confidence bonus from wallet quality weights
    confidence_bonus = (confidence - 0.5) * 0.05

    # Only apply bonus if traders are BUYING (directional conviction)
    if signal.side.value == "BUY":
        p = min(0.95, p + consensus_bonus + confidence_bonus)
    else:
        p = max(0.05, (1.0 - market_prob) + consensus_bonus + confidence_bonus)

    return p
