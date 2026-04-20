"""Tests for Kelly position sizing."""
from datetime import datetime, timezone

from src.models import PortfolioState, Side, Signal, WalletTrade
from src.position_sizer import kelly_size


def _make_signal(price: float = 0.65, consensus: int = 2,
                 side: Side = Side.BUY) -> Signal:
    sources = []
    names = ["BAdiosB", "LucasMeow", "elkmonkey", "gatorr", "Erasmus"]
    for i in range(consensus):
        sources.append(WalletTrade(
            wallet_name=names[i % len(names)],
            wallet_address=f"0x{names[i]}",
            market_slug="test",
            condition_id="cond-1",
            token_id="tok-1",
            outcome="Yes",
            side=side,
            price=price,
            size=100.0,
            timestamp=datetime.now(timezone.utc),
        ))

    return Signal(
        market_key="cond-1",
        market_slug="test",
        question="Test?",
        outcome="Yes",
        side=side,
        sources=sources,
    )


def _make_portfolio(bankroll: float = 100.0, drawdown: float = 0.0) -> PortfolioState:
    return PortfolioState(
        bankroll=bankroll,
        cash_available=bankroll * 0.7,
        total_exposure=bankroll * 0.3,
        open_positions=2,
        daily_pnl=0.0,
        peak_bankroll=bankroll,
        drawdown_pct=drawdown,
    )


def test_basic_sizing():
    signal = _make_signal(price=0.65, consensus=2)
    portfolio = _make_portfolio(100.0)
    amount = kelly_size(signal, portfolio)
    assert amount is not None
    assert 0.50 <= amount <= 5.0


def test_max_capped_at_5():
    signal = _make_signal(price=0.60, consensus=4)
    portfolio = _make_portfolio(1000.0)
    amount = kelly_size(signal, portfolio)
    assert amount is not None
    assert amount <= 5.0


def test_no_cash_returns_none():
    signal = _make_signal()
    portfolio = PortfolioState(
        bankroll=100.0, cash_available=0.0, total_exposure=100.0,
        open_positions=5, daily_pnl=-10.0, peak_bankroll=110.0,
        drawdown_pct=9.0,
    )
    assert kelly_size(signal, portfolio) is None


def test_drawdown_stop_returns_none():
    signal = _make_signal()
    portfolio = _make_portfolio(100.0, drawdown=25.0)
    assert kelly_size(signal, portfolio) is None


def test_high_price_low_edge():
    signal = _make_signal(price=0.95, consensus=2)
    portfolio = _make_portfolio(100.0)
    amount = kelly_size(signal, portfolio)
    # At 95c, very little edge even with consensus
    # May return None or a very small amount
    if amount is not None:
        assert amount <= 5.0
