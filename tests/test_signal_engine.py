"""Tests for signal aggregation logic."""
from datetime import datetime, timezone

import pytest

from src.models import Side, Signal, SignalStatus, WalletTrade
from src.signal_engine import SignalEngine


class FakeDB:
    def __init__(self):
        self.signals = []

    def insert_signal(self, **kwargs):
        self.signals.append(kwargs)
        return len(self.signals)


def _make_trade(wallet_name: str, condition_id: str = "cond-1",
                outcome: str = "Yes", side: Side = Side.BUY,
                price: float = 0.65, slug: str = "test-market") -> WalletTrade:
    return WalletTrade(
        wallet_name=wallet_name,
        wallet_address=f"0x{wallet_name}",
        market_slug=slug,
        condition_id=condition_id,
        token_id=f"tok-{condition_id}-{outcome}",
        outcome=outcome,
        side=side,
        price=price,
        size=100.0,
        timestamp=datetime.now(timezone.utc),
    )


def test_no_signal_below_consensus():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [_make_trade("BAdiosB")]
    signals = engine.ingest(trades)
    assert len(signals) == 0


def test_signal_on_consensus():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [
        _make_trade("BAdiosB"),
        _make_trade("LucasMeow"),
    ]
    signals = engine.ingest(trades)
    assert len(signals) == 1
    assert signals[0].consensus_count == 2
    assert signals[0].status == SignalStatus.CONFIRMED


def test_same_wallet_twice_no_consensus():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [
        _make_trade("BAdiosB"),
        _make_trade("BAdiosB"),
    ]
    signals = engine.ingest(trades)
    assert len(signals) == 0


def test_different_markets_no_cross_signal():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [
        _make_trade("BAdiosB", condition_id="cond-1"),
        _make_trade("LucasMeow", condition_id="cond-2"),
    ]
    signals = engine.ingest(trades)
    assert len(signals) == 0


def test_different_sides_no_signal():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [
        _make_trade("BAdiosB", side=Side.BUY),
        _make_trade("LucasMeow", side=Side.SELL),
    ]
    signals = engine.ingest(trades)
    assert len(signals) == 0


def test_three_trader_consensus():
    db = FakeDB()
    engine = SignalEngine(db)
    trades = [
        _make_trade("BAdiosB"),
        _make_trade("LucasMeow"),
        _make_trade("elkmonkey"),
    ]
    signals = engine.ingest(trades)
    assert len(signals) == 1
    assert signals[0].consensus_count == 3
