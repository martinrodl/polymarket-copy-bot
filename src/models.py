from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"   # consensus reached
    EXECUTED = "executed"
    EXPIRED = "expired"
    REJECTED = "rejected"     # risk manager blocked


class TradeStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    FAILED = "failed"


@dataclass
class WalletTrade:
    """A trade detected from a target wallet via Data API."""
    wallet_name: str
    wallet_address: str
    market_slug: str
    condition_id: str
    token_id: str
    outcome: str
    side: Side
    price: float
    size: float
    timestamp: datetime
    asset_id: str = ""
    event_slug: str = ""
    question: str = ""

    @property
    def market_key(self) -> str:
        return self.condition_id or self.market_slug

    @property
    def direction_key(self) -> str:
        """Normalized direction: BUY-YES, BUY-NO, SELL-YES, SELL-NO."""
        return f"{self.side.value}-{self.outcome}"


@dataclass
class Signal:
    """Aggregated signal from multiple wallet trades on the same market."""
    market_key: str
    market_slug: str
    question: str
    outcome: str
    side: Side
    sources: list[WalletTrade] = field(default_factory=list)
    status: SignalStatus = SignalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    executed_at: datetime | None = None

    @property
    def consensus_count(self) -> int:
        return len({t.wallet_name for t in self.sources})

    @property
    def avg_price(self) -> float:
        if not self.sources:
            return 0.0
        return sum(t.price for t in self.sources) / len(self.sources)

    @property
    def total_size(self) -> float:
        return sum(t.size for t in self.sources)

    @property
    def source_names(self) -> list[str]:
        return sorted({t.wallet_name for t in self.sources})

    @property
    def weighted_confidence(self) -> float:
        if not self.sources:
            return 0.0
        from .config import config
        wallet_weights = {w.name: w.weight for w in config.wallets}
        total = sum(wallet_weights.get(t.wallet_name, 0.5) for t in self.sources)
        return total / len(self.sources)


@dataclass
class CopyTrade:
    """A trade we execute based on a confirmed signal."""
    id: str
    signal_market_key: str
    token_id: str
    side: Side
    price: float
    size: float
    cost: float
    status: TradeStatus = TradeStatus.PENDING
    order_id: str = ""
    filled_price: float = 0.0
    filled_size: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: datetime | None = None
    pnl: float = 0.0


@dataclass
class PortfolioState:
    bankroll: float
    cash_available: float
    total_exposure: float
    open_positions: int
    daily_pnl: float
    peak_bankroll: float
    drawdown_pct: float
