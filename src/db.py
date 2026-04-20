from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from .config import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_name TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    market_slug TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    trade_timestamp TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(wallet_address, token_id, side, price, trade_timestamp)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_key TEXT NOT NULL,
    market_slug TEXT NOT NULL,
    question TEXT DEFAULT '',
    outcome TEXT NOT NULL,
    side TEXT NOT NULL,
    consensus_count INTEGER NOT NULL,
    source_names TEXT NOT NULL,
    avg_price REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS copy_trades (
    id TEXT PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    cost REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    order_id TEXT DEFAULT '',
    filled_price REAL DEFAULT 0,
    filled_size REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    filled_at TEXT,
    pnl REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bankroll REAL NOT NULL,
    cash_available REAL NOT NULL,
    total_exposure REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    daily_pnl REAL NOT NULL,
    peak_bankroll REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    snapshot_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wt_wallet ON wallet_trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_wt_market ON wallet_trades(condition_id);
CREATE INDEX IF NOT EXISTS idx_wt_detected ON wallet_trades(detected_at);
CREATE INDEX IF NOT EXISTS idx_signals_market ON signals(market_key);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_ct_signal ON copy_trades(signal_id);
"""


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or config.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def has_wallet_trade(self, wallet_address: str, token_id: str, side: str,
                         price: float, timestamp: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM wallet_trades
                   WHERE wallet_address=? AND token_id=? AND side=?
                   AND price=? AND trade_timestamp=?""",
                (wallet_address, token_id, side, price, timestamp),
            ).fetchone()
            return row is not None

    def insert_wallet_trade(
        self, wallet_name: str, wallet_address: str, market_slug: str,
        condition_id: str, token_id: str, outcome: str, side: str,
        price: float, size: float, trade_timestamp: str,
    ) -> int | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO wallet_trades
                       (wallet_name, wallet_address, market_slug, condition_id,
                        token_id, outcome, side, price, size,
                        trade_timestamp, detected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (wallet_name, wallet_address, market_slug, condition_id,
                     token_id, outcome, side, price, size,
                     trade_timestamp, now),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def insert_signal(
        self, market_key: str, market_slug: str, question: str,
        outcome: str, side: str, consensus_count: int,
        source_names: str, avg_price: float, status: str,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO signals
                   (market_key, market_slug, question, outcome, side,
                    consensus_count, source_names, avg_price, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (market_key, market_slug, question, outcome, side,
                 consensus_count, source_names, avg_price, status, now),
            )
            return cur.lastrowid

    def update_signal_status(self, signal_id: int, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE signals SET status=?, executed_at=? WHERE id=?",
                (status, now if status == "executed" else None, signal_id),
            )

    def insert_copy_trade(
        self, trade_id: str, signal_id: int, token_id: str, side: str,
        price: float, size: float, cost: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO copy_trades
                   (id, signal_id, token_id, side, price, size, cost,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (trade_id, signal_id, token_id, side, price, size, cost, now),
            )

    def update_copy_trade(
        self, trade_id: str, status: str,
        filled_price: float = 0, filled_size: float = 0,
        order_id: str = "", pnl: float = 0,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE copy_trades
                   SET status=?, filled_price=?, filled_size=?,
                       order_id=?, pnl=?, filled_at=?
                   WHERE id=?""",
                (status, filled_price, filled_size, order_id, pnl, now, trade_id),
            )

    def get_recent_wallet_trades(self, condition_id: str, minutes: int = 30) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM wallet_trades
                   WHERE condition_id=?
                   AND detected_at > datetime('now', ?)
                   ORDER BY detected_at DESC""",
                (condition_id, f"-{minutes} minutes"),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_today_pnl(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(pnl), 0) as total
                   FROM copy_trades WHERE created_at LIKE ?""",
                (f"{today}%",),
            ).fetchone()
            return row["total"]

    def get_total_exposure(self) -> float:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(cost), 0) as total
                   FROM copy_trades WHERE status IN ('pending', 'filled')
                   AND pnl = 0""",
            ).fetchone()
            return row["total"]

    def get_market_exposure(self, market_key: str) -> float:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(ct.cost), 0) as total
                   FROM copy_trades ct
                   JOIN signals s ON ct.signal_id = s.id
                   WHERE s.market_key = ? AND ct.status IN ('pending', 'filled')
                   AND ct.pnl = 0""",
                (market_key,),
            ).fetchone()
            return row["total"]

    def get_open_positions_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT signal_id) as cnt
                   FROM copy_trades
                   WHERE status IN ('pending', 'filled') AND pnl = 0""",
            ).fetchone()
            return row["cnt"]

    def save_portfolio_snapshot(self, state: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO portfolio_snapshots
                   (bankroll, cash_available, total_exposure, open_positions,
                    daily_pnl, peak_bankroll, drawdown_pct, snapshot_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (state["bankroll"], state["cash_available"],
                 state["total_exposure"], state["open_positions"],
                 state["daily_pnl"], state["peak_bankroll"],
                 state["drawdown_pct"], now),
            )

    def get_signals_stats(self, since_hours: int = 24) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*) as total,
                     SUM(CASE WHEN status='executed' THEN 1 ELSE 0 END) as executed,
                     SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) as confirmed,
                     SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
                     SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) as expired,
                     AVG(consensus_count) as avg_consensus
                   FROM signals
                   WHERE created_at > datetime('now', ?)""",
                (f"-{since_hours} hours",),
            ).fetchone()
            return dict(row) if row else {}
