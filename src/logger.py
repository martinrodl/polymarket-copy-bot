from __future__ import annotations

import sys
from datetime import datetime, timezone

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

LEVEL_COLORS = {
    "info": "",
    "signal": GREEN,
    "trade": CYAN,
    "risk": YELLOW,
    "error": RED,
    "debug": DIM,
}


def log(msg: str, level: str = "info") -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    color = LEVEL_COLORS.get(level, "")
    tag = level.upper().ljust(7)
    print(f"{DIM}{ts}{RESET} {color}{tag}{RESET} {msg}", flush=True)


def log_banner(title: str, params: dict[str, str]) -> None:
    width = 60
    print(f"\n{CYAN}{'═' * width}{RESET}")
    print(f"{CYAN}  {BOLD}{title}{RESET}")
    print(f"{CYAN}{'─' * width}{RESET}")
    for k, v in params.items():
        print(f"  {k:<22s} {v}")
    print(f"{CYAN}{'═' * width}{RESET}\n")
