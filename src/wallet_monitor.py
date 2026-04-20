"""Polls Polymarket Data API for new trades from target wallets."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from .config import WalletTarget, config
from .db import Database
from .logger import log
from .models import Side, WalletTrade


DATA_API = config.api.data_url


def _parse_timestamp(ts: str | int | float) -> datetime:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def fetch_wallet_trades(
    wallet: WalletTarget,
    limit: int = 50,
) -> list[WalletTrade]:
    """Fetch recent activity for a wallet from the Data API."""
    url = f"{DATA_API}/activity"
    params = {
        "user": wallet.address,
        "limit": limit,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"Data API error for {wallet.name}: {e}", "error")
        return []

    data = resp.json()
    if not isinstance(data, list):
        data = data.get("data", data.get("trades", []))

    trades: list[WalletTrade] = []
    for raw in data:
        try:
            if raw.get("type") != "TRADE":
                continue

            side_str = raw.get("side", "BUY").upper()
            side = Side.BUY if side_str == "BUY" else Side.SELL

            trade = WalletTrade(
                wallet_name=wallet.name,
                wallet_address=wallet.address,
                market_slug=raw.get("slug", raw.get("market", "")),
                condition_id=raw.get("conditionId", ""),
                token_id=raw.get("asset", raw.get("tokenId", "")),
                outcome=raw.get("outcome", raw.get("title", "YES")),
                side=side,
                price=float(raw.get("price", 0)),
                size=float(raw.get("size", raw.get("usdcSize", 0))),
                timestamp=_parse_timestamp(raw.get("timestamp", "")),
                asset_id=raw.get("asset", ""),
                event_slug=raw.get("eventSlug", ""),
                question=raw.get("title", ""),
            )
            if trade.price > 0 and trade.size > 0:
                trades.append(trade)
        except (KeyError, ValueError, TypeError) as e:
            log(f"Parse error for {wallet.name} trade: {e}", "debug")
            continue

    return trades


def fetch_wallet_activity(wallet: WalletTarget) -> list[dict]:
    """Fetch wallet activity (positions, redemptions) from Data API."""
    url = f"{DATA_API}/activity"
    params = {"user": wallet.address, "limit": 50}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except requests.RequestException as e:
        log(f"Activity API error for {wallet.name}: {e}", "error")
        return []


def poll_all_wallets(db: Database) -> list[WalletTrade]:
    """Poll all target wallets and return only NEW trades (not seen before)."""
    new_trades: list[WalletTrade] = []

    for wallet in config.wallets:
        trades = fetch_wallet_trades(wallet)

        for trade in trades:
            ts_str = trade.timestamp.isoformat()
            if db.has_wallet_trade(wallet.address, trade.token_id,
                                   trade.side.value, trade.price, ts_str):
                continue

            db.insert_wallet_trade(
                wallet_name=trade.wallet_name,
                wallet_address=trade.wallet_address,
                market_slug=trade.market_slug,
                condition_id=trade.condition_id,
                token_id=trade.token_id,
                outcome=trade.outcome,
                side=trade.side.value,
                price=trade.price,
                size=trade.size,
                trade_timestamp=ts_str,
            )
            new_trades.append(trade)
            log(f"New trade: {wallet.name} {trade.side.value} "
                f"{trade.outcome} @ ${trade.price:.3f} "
                f"({trade.size:.1f} shares) — {trade.market_slug}",
                "signal")

    return new_trades
