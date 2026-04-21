"""Aggregates wallet trades into consensus signals."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .config import config
from .db import Database
from .logger import log
from .models import Signal, SignalStatus, WalletTrade


# Wallets marked as solo_follow
_SOLO_WALLETS = {w.name for w in config.wallets if w.solo_follow}


class SignalEngine:
    def __init__(self, db: Database):
        self.db = db
        self._pending_trades: dict[str, list[WalletTrade]] = defaultdict(list)

    def ingest(self, trades: list[WalletTrade]) -> list[Signal]:
        """Ingest new trades. Emit signals from consensus OR solo-follow wallets."""
        now = datetime.now(timezone.utc)
        window = timedelta(minutes=config.trading.signal_window_minutes)

        solo_signals: list[Signal] = []
        consensus_trades: list[WalletTrade] = []

        for trade in trades:
            if trade.wallet_name in _SOLO_WALLETS:
                solo_signals.append(self._make_solo_signal(trade))
            else:
                consensus_trades.append(trade)

        consensus_signals = self._process_consensus(consensus_trades, now, window)
        return solo_signals + consensus_signals

    def _make_solo_signal(self, trade: WalletTrade) -> Signal:
        signal = Signal(
            market_key=trade.market_key,
            market_slug=trade.market_slug,
            question=trade.question,
            outcome=trade.outcome,
            side=trade.side,
            sources=[trade],
            status=SignalStatus.CONFIRMED,
        )

        self.db.insert_signal(
            market_key=signal.market_key,
            market_slug=signal.market_slug,
            question=signal.question,
            outcome=signal.outcome,
            side=signal.side.value,
            consensus_count=1,
            source_names=trade.wallet_name,
            avg_price=signal.avg_price,
            status=signal.status.value,
        )

        log(f"SOLO: {trade.wallet_name} → "
            f"{trade.side.value} {trade.outcome} @ ${trade.price:.3f} "
            f"on {trade.market_slug}",
            "signal")
        return signal

    def _process_consensus(self, trades: list[WalletTrade],
                           now: datetime, window: timedelta) -> list[Signal]:
        for trade in trades:
            key = f"{trade.market_key}:{trade.direction_key}"
            self._pending_trades[key].append(trade)

        self._expire_old_trades(now, window)

        confirmed: list[Signal] = []
        keys_to_clear: list[str] = []

        for key, group_trades in self._pending_trades.items():
            unique_wallets = {t.wallet_name for t in group_trades}

            if len(unique_wallets) < config.trading.min_consensus:
                continue

            representative = group_trades[0]
            signal = Signal(
                market_key=representative.market_key,
                market_slug=representative.market_slug,
                question=representative.question,
                outcome=representative.outcome,
                side=representative.side,
                sources=list(group_trades),
                status=SignalStatus.CONFIRMED,
            )

            self.db.insert_signal(
                market_key=signal.market_key,
                market_slug=signal.market_slug,
                question=signal.question,
                outcome=signal.outcome,
                side=signal.side.value,
                consensus_count=signal.consensus_count,
                source_names=",".join(signal.source_names),
                avg_price=signal.avg_price,
                status=signal.status.value,
            )

            log(f"CONSENSUS: {signal.consensus_count} traders agree → "
                f"{signal.side.value} {signal.outcome} @ avg ${signal.avg_price:.3f} "
                f"on {signal.market_slug} "
                f"[{', '.join(signal.source_names)}]",
                "signal")

            confirmed.append(signal)
            keys_to_clear.append(key)

        for key in keys_to_clear:
            del self._pending_trades[key]

        return confirmed

    def _expire_old_trades(self, now: datetime, window: timedelta) -> None:
        expired_keys: list[str] = []
        for key, trades in self._pending_trades.items():
            self._pending_trades[key] = [
                t for t in trades if (now - t.timestamp) < window
            ]
            if not self._pending_trades[key]:
                expired_keys.append(key)

        for key in expired_keys:
            del self._pending_trades[key]

    def get_pending_summary(self) -> dict[str, int]:
        """Return count of unique wallets per pending market for monitoring."""
        summary = {}
        for key, trades in self._pending_trades.items():
            unique = len({t.wallet_name for t in trades})
            if unique > 0:
                market = trades[0].market_slug or key.split(":")[0][:30]
                summary[market] = unique
        return summary
