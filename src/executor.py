"""Trade execution — paper trading and live order placement."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import requests

from .config import config
from .db import Database
from .logger import log
from .models import CopyTrade, Signal, TradeStatus


class PaperExecutor:
    """Simulates trade execution for paper trading mode."""

    def __init__(self, db: Database):
        self.db = db

    def execute(self, signal: Signal, bet_amount: float, signal_id: int) -> CopyTrade | None:
        price = signal.avg_price
        if price <= 0 or price >= 1:
            log(f"Invalid price {price} — skipping", "error")
            return None

        size = bet_amount / price
        trade_id = f"paper-{uuid.uuid4().hex[:12]}"

        trade = CopyTrade(
            id=trade_id,
            signal_market_key=signal.market_key,
            token_id=signal.sources[0].token_id if signal.sources else "",
            side=signal.side,
            price=price,
            size=size,
            cost=bet_amount,
            status=TradeStatus.FILLED,
            filled_price=price,
            filled_size=size,
            filled_at=datetime.now(timezone.utc),
        )

        self.db.insert_copy_trade(
            trade_id=trade.id,
            signal_id=signal_id,
            token_id=trade.token_id,
            side=trade.side.value,
            price=trade.price,
            size=trade.size,
            cost=trade.cost,
        )
        self.db.update_copy_trade(
            trade_id=trade.id,
            status="filled",
            filled_price=price,
            filled_size=size,
        )

        log(f"PAPER TRADE: {signal.side.value} {signal.outcome} "
            f"@ ${price:.3f} × {size:.1f} shares = ${bet_amount:.2f} "
            f"— {signal.market_slug}", "trade")
        return trade


class LiveExecutor:
    """Places real orders via Polymarket CLOB API."""

    def __init__(self, db: Database):
        self.db = db

    def execute(self, signal: Signal, bet_amount: float, signal_id: int) -> CopyTrade | None:
        price = signal.avg_price
        size = bet_amount / price
        trade_id = f"live-{uuid.uuid4().hex[:12]}"

        token_id = signal.sources[0].token_id if signal.sources else ""
        if not token_id:
            log("No token_id available — cannot execute", "error")
            return None

        self.db.insert_copy_trade(
            trade_id=trade_id,
            signal_id=signal_id,
            token_id=token_id,
            side=signal.side.value,
            price=price,
            size=size,
            cost=bet_amount,
        )

        order_payload = {
            "tokenID": token_id,
            "price": str(round(price, 2)),
            "size": str(round(size, 1)),
            "side": signal.side.value,
            "type": "GTC",
        }

        try:
            resp = requests.post(
                f"{config.api.clob_url}/order",
                json=order_payload,
                headers=self._auth_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            order_id = result.get("orderID", result.get("id", ""))

            self.db.update_copy_trade(
                trade_id=trade_id,
                status="filled",
                filled_price=price,
                filled_size=size,
                order_id=order_id,
            )

            log(f"LIVE ORDER: {signal.side.value} {signal.outcome} "
                f"@ ${price:.3f} × {size:.1f} = ${bet_amount:.2f} "
                f"order={order_id}", "trade")

            return CopyTrade(
                id=trade_id,
                signal_market_key=signal.market_key,
                token_id=token_id,
                side=signal.side,
                price=price,
                size=size,
                cost=bet_amount,
                status=TradeStatus.FILLED,
                order_id=order_id,
                filled_price=price,
                filled_size=size,
                filled_at=datetime.now(timezone.utc),
            )

        except requests.RequestException as e:
            log(f"Order failed: {e}", "error")
            self.db.update_copy_trade(trade_id=trade_id, status="failed")
            return None

    def _auth_headers(self) -> dict[str, str]:
        return {
            "POLY-ADDRESS": config.api.poly_funder,
            "POLY-API-KEY": config.api.poly_api_key,
            "POLY-PASSPHRASE": config.api.poly_passphrase,
            "Content-Type": "application/json",
        }


def create_executor(db: Database) -> PaperExecutor | LiveExecutor:
    if config.trading.is_live:
        if not config.api.poly_api_key:
            log("Live mode requested but no API key — falling back to paper", "risk")
            return PaperExecutor(db)
        return LiveExecutor(db)
    return PaperExecutor(db)
