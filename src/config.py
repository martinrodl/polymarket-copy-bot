from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_float(key: str, default: float = 0.0) -> float:
    v = _env(key)
    return float(v) if v else default


def _env_int(key: str, default: int = 0) -> int:
    v = _env(key)
    return int(v) if v else default


@dataclass(frozen=True)
class WalletTarget:
    name: str
    address: str
    category: str = "general"
    weight: float = 1.0


# Default basket — addresses must be filled in .env or passed at runtime
DEFAULT_BASKET = [
    WalletTarget("BAdiosB", _env("WALLET_BADIOSB"), "mispricing", 1.0),
    WalletTarget("LucasMeow", _env("WALLET_LUCASMEOW"), "crypto", 0.8),
    WalletTarget("Erasmus", _env("WALLET_ERASMUS"), "politics", 0.9),
    WalletTarget("elkmonkey", _env("WALLET_ELKMONKEY"), "sports", 0.7),
    WalletTarget("gatorr", _env("WALLET_GATORR"), "general", 0.7),
]


@dataclass(frozen=True)
class APIConfig:
    data_url: str = "https://data-api.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    profile_url: str = "https://polymarket.com"

    poly_api_key: str = field(default_factory=lambda: _env("POLY_API_KEY"))
    poly_api_secret: str = field(default_factory=lambda: _env("POLY_API_SECRET"))
    poly_passphrase: str = field(default_factory=lambda: _env("POLY_PASSPHRASE"))
    poly_funder: str = field(default_factory=lambda: _env("POLY_FUNDER"))


@dataclass(frozen=True)
class TradingConfig:
    mode: str = field(default_factory=lambda: _env("MODE", "paper"))
    bankroll: float = field(default_factory=lambda: _env_float("BANKROLL", 100.0))
    max_trade_size: float = field(default_factory=lambda: _env_float("MAX_TRADE_SIZE", 5.0))

    # Copy signal rules
    min_consensus: int = 2          # min basket traders agreeing to trigger
    signal_window_minutes: int = 30  # max age of a signal before it decays
    max_copy_delay_minutes: int = 30 # don't copy if trade is older than this

    # Position sizing (fractional Kelly)
    kelly_fraction: float = 0.25
    max_single_market_pct: float = 5.0   # max 5% per trade ($5 on $100)
    max_total_exposure_pct: float = 30.0
    min_cash_reserve_pct: float = 50.0

    # Drawdown protocol
    daily_loss_limit_pct: float = 3.0
    drawdown_reduce_50: float = 10.0
    drawdown_pause: float = 15.0
    drawdown_stop: float = 20.0

    # Polling
    poll_interval: int = field(default_factory=lambda: _env_int("POLL_INTERVAL", 60))

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


@dataclass(frozen=True)
class AlertsConfig:
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))

    @property
    def enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


@dataclass(frozen=True)
class Config:
    api: APIConfig = field(default_factory=APIConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    wallets: list[WalletTarget] = field(default_factory=lambda: [w for w in DEFAULT_BASKET if w.address])
    db_path: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "copytrade.db")


config = Config()
