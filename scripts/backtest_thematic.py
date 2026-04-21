#!/usr/bin/env python3
"""
Backtest: Thematic Basket Trade Overlap Analysis
Analyzes trade overlap within two Polymarket baskets (Sports & Geopolitics).
"""

import requests
import time
import json
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import combinations

# ── Basket Definitions ──────────────────────────────────────────────────────

SPORTS_BASKET = {
    "elkmonkey":     "0xead152b855effa6b5b5837f53b24c0756830c76a",
    "gatorr":        "0x93abbc022ce98d6f45d4444b594791cc4b7a9723",
    "sovereign2013": "0xee613b3fc183ee44f9da9c05f53e2da107e3debf",
    "CarlosMC":      "0x777d9f00c2b4f7b829c9de0049ca3e707db05143",
    "swisstony":     "0x204f72f35326db932158cba6adff0b9a1da95e14",
}

GEO_BASKET = {
    "BAdiosB":    "0x909fa9f89976058b8b3ab87adc502ec7415ea8c3",
    "Erasmus":    "0xc6587b11a2209e46dfe3928b31c5514a8e33b784",
    "Domer":      "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
    "Magamyman":  "0x1caA6a7ad0c6916aeF7b67946De2e57Ad24846a0",
}

API_BASE = "https://data-api.polymarket.com/activity"
PAGES = 5          # 0..400 in steps of 100 → up to 500 trades
PAGE_SIZE = 100
SLEEP = 0.2

# ── Fetching ────────────────────────────────────────────────────────────────

def fetch_trades(address: str, name: str) -> list[dict]:
    """Fetch up to 500 trades for a single wallet, paginating."""
    all_trades = []
    for page in range(PAGES):
        offset = page * PAGE_SIZE
        url = f"{API_BASE}?user={address}&limit={PAGE_SIZE}&offset={offset}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [!] Error fetching {name} offset={offset}: {e}")
            break

        # Filter to actual trades only
        trades = [r for r in data if r.get("type") == "TRADE"]
        all_trades.extend(trades)

        # If we got fewer than PAGE_SIZE results, no more pages
        if len(data) < PAGE_SIZE:
            break
        time.sleep(SLEEP)

    return all_trades


def fetch_basket(basket: dict[str, str]) -> dict[str, list[dict]]:
    """Fetch trades for every wallet in a basket."""
    result = {}
    for name, addr in basket.items():
        print(f"  Fetching {name} ({addr[:10]}...)")
        trades = fetch_trades(addr, name)
        result[name] = trades
        print(f"    -> {len(trades)} trades")
        time.sleep(SLEEP)
    return result


# ── Analysis helpers ────────────────────────────────────────────────────────

def parse_ts(ts_val) -> datetime:
    """Parse timestamp from the API (may be int epoch-ms, int epoch-s, or ISO string)."""
    if isinstance(ts_val, (int, float)):
        # Epoch seconds vs milliseconds heuristic
        if ts_val > 1e12:
            return datetime.utcfromtimestamp(ts_val / 1000)
        else:
            return datetime.utcfromtimestamp(ts_val)
    ts_str = str(ts_val)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    try:
        clean = ts_str.rstrip("Z")
        return datetime.fromisoformat(clean)
    except Exception:
        return datetime.min


def direction_key(trade: dict) -> str:
    """Create a direction key from side + outcome."""
    return f"{trade.get('side', '?')}|{trade.get('outcome', '?')}"


def time_bucket(seconds: float) -> str:
    """Classify time difference into buckets."""
    if seconds <= 30 * 60:
        return "<=30min"
    elif seconds <= 60 * 60:
        return "<=1hr"
    elif seconds <= 4 * 3600:
        return "<=4hr"
    elif seconds <= 24 * 3600:
        return "<=24hr"
    else:
        return ">24hr"


def analyze_basket(basket_name: str, wallet_trades: dict[str, list[dict]]):
    """Full overlap analysis for one basket."""
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  BASKET: {basket_name}")
    print(sep)

    # ── 1. Trades per wallet ────────────────────────────────────────────
    print(f"\n--- Trades per wallet ---")
    total_trades = 0
    for name, trades in wallet_trades.items():
        print(f"  {name:20s}: {len(trades):4d} trades")
        total_trades += len(trades)
    print(f"  {'TOTAL':20s}: {total_trades:4d} trades")

    # Collect timestamps range
    all_ts = []
    for trades in wallet_trades.values():
        for t in trades:
            ts = t.get("timestamp") or t.get("createdAt") or ""
            if ts:
                all_ts.append(parse_ts(ts))
    all_ts = [t for t in all_ts if t != datetime.min]
    if all_ts:
        min_ts = min(all_ts)
        max_ts = max(all_ts)
        span_days = max((max_ts - min_ts).total_seconds() / 86400, 1)
        print(f"\n  Date range: {min_ts.strftime('%Y-%m-%d')} to {max_ts.strftime('%Y-%m-%d')} ({span_days:.0f} days)")
    else:
        span_days = 1
        print("\n  Date range: unknown")

    # ── 2. Group by conditionId ─────────────────────────────────────────
    cid_map = defaultdict(list)   # conditionId -> [(wallet, trade), ...]
    eslug_map = defaultdict(list) # eventSlug   -> [(wallet, trade), ...]

    for name, trades in wallet_trades.items():
        for t in trades:
            cid = t.get("conditionId")
            eslug = t.get("eventSlug")
            if cid:
                cid_map[cid].append((name, t))
            if eslug:
                eslug_map[eslug].append((name, t))

    # ── 3. Find overlaps (2+ distinct wallets) ─────────────────────────
    def find_overlaps(grouped: dict, label: str):
        overlaps = {}
        for key, entries in grouped.items():
            wallets_involved = set(e[0] for e in entries)
            if len(wallets_involved) >= 2:
                overlaps[key] = entries
        return overlaps

    cid_overlaps = find_overlaps(cid_map, "conditionId")
    eslug_overlaps = find_overlaps(eslug_map, "eventSlug")

    print(f"\n--- Overlap counts ---")
    print(f"  conditionId-level overlaps : {len(cid_overlaps):4d} markets with 2+ wallets")
    print(f"  eventSlug-level overlaps   : {len(eslug_overlaps):4d} events with 2+ wallets")

    # ── 4. Detailed overlap report (conditionId level) ──────────────────
    print(f"\n--- Overlapping markets (conditionId level) ---")
    if not cid_overlaps:
        print("  (none)")
    else:
        direction_agree = 0
        direction_total = 0
        time_proximity = defaultdict(int)
        consensus_count = 0

        for cid, entries in sorted(cid_overlaps.items(), key=lambda x: -len(set(e[0] for e in x[1]))):
            wallets_here = sorted(set(e[0] for e in entries))
            # Get representative title / slug
            title = entries[0][1].get("title", "?")
            slug = entries[0][1].get("slug", "?")
            event_slug = entries[0][1].get("eventSlug", "?")

            print(f"\n  Market: {title}")
            print(f"    conditionId: {cid[:16]}...")
            print(f"    slug: {slug}")
            print(f"    eventSlug: {event_slug}")
            print(f"    Wallets ({len(wallets_here)}): {', '.join(wallets_here)}")

            # Per-wallet detail
            for w in wallets_here:
                w_trades = [e[1] for e in entries if e[0] == w]
                for wt in w_trades:
                    ts_raw = wt.get("timestamp") or wt.get("createdAt") or "?"
                    side = wt.get("side", "?")
                    outcome = wt.get("outcome", "?")
                    price = wt.get("price", "?")
                    size = wt.get("size", "?")
                    print(f"      {w:18s}  {side:4s} {outcome:4s}  price={price}  size={size}  ts={ts_raw}")

            # Direction agreement: check all pairs of distinct wallets
            wallet_directions = defaultdict(set)
            wallet_timestamps = defaultdict(list)
            for w, t in entries:
                wallet_directions[w].add(direction_key(t))
                ts_raw = t.get("timestamp") or t.get("createdAt") or ""
                if ts_raw:
                    wallet_timestamps[w].append(parse_ts(ts_raw))

            for w1, w2 in combinations(wallets_here, 2):
                direction_total += 1
                if wallet_directions[w1] & wallet_directions[w2]:
                    direction_agree += 1
                    consensus_count += 1

                # Time proximity: min time delta between any trade pair
                if wallet_timestamps[w1] and wallet_timestamps[w2]:
                    min_delta = min(
                        abs((t1 - t2).total_seconds())
                        for t1 in wallet_timestamps[w1]
                        for t2 in wallet_timestamps[w2]
                    )
                    bucket = time_bucket(min_delta)
                    time_proximity[bucket] += 1

        # Summary stats
        print(f"\n--- Direction agreement (conditionId level) ---")
        if direction_total > 0:
            rate = direction_agree / direction_total * 100
            print(f"  Agreeing pairs: {direction_agree}/{direction_total} = {rate:.1f}%")
        else:
            print("  No pairs to compare")

        print(f"\n--- Time proximity breakdown (conditionId level) ---")
        for bucket in ["<=30min", "<=1hr", "<=4hr", "<=24hr", ">24hr"]:
            cnt = time_proximity.get(bucket, 0)
            print(f"  {bucket:10s}: {cnt:4d} pairs")

        weeks = max(span_days / 7, 1)
        print(f"\n--- Estimated consensus signals ---")
        print(f"  Total consensus pairs (same direction): {consensus_count}")
        print(f"  Span: {span_days:.0f} days ({weeks:.1f} weeks)")
        print(f"  Consensus signals per week: {consensus_count / weeks:.2f}")

    # ── 5. Event-slug level overlaps ────────────────────────────────────
    print(f"\n--- Overlapping events (eventSlug level) ---")
    if not eslug_overlaps:
        print("  (none)")
    else:
        eslug_direction_agree = 0
        eslug_direction_total = 0
        eslug_time_proximity = defaultdict(int)
        eslug_consensus_count = 0

        for eslug, entries in sorted(eslug_overlaps.items(), key=lambda x: -len(set(e[0] for e in x[1]))):
            wallets_here = sorted(set(e[0] for e in entries))
            # Get representative title
            titles = set(e[1].get("title", "?") for e in entries)
            print(f"\n  Event: {eslug}")
            print(f"    Sub-markets: {', '.join(list(titles)[:5])}")
            print(f"    Wallets ({len(wallets_here)}): {', '.join(wallets_here)}")

            # Per-wallet counts
            for w in wallets_here:
                w_count = sum(1 for e in entries if e[0] == w)
                print(f"      {w:18s}: {w_count} trades in this event")

            # Direction agreement at event level
            wallet_directions_ev = defaultdict(set)
            wallet_timestamps_ev = defaultdict(list)
            for w, t in entries:
                wallet_directions_ev[w].add(direction_key(t))
                ts_raw = t.get("timestamp") or t.get("createdAt") or ""
                if ts_raw:
                    wallet_timestamps_ev[w].append(parse_ts(ts_raw))

            for w1, w2 in combinations(wallets_here, 2):
                eslug_direction_total += 1
                if wallet_directions_ev[w1] & wallet_directions_ev[w2]:
                    eslug_direction_agree += 1
                    eslug_consensus_count += 1

                if wallet_timestamps_ev[w1] and wallet_timestamps_ev[w2]:
                    min_delta = min(
                        abs((t1 - t2).total_seconds())
                        for t1 in wallet_timestamps_ev[w1]
                        for t2 in wallet_timestamps_ev[w2]
                    )
                    bucket = time_bucket(min_delta)
                    eslug_time_proximity[bucket] += 1

        print(f"\n--- Direction agreement (eventSlug level) ---")
        if eslug_direction_total > 0:
            rate = eslug_direction_agree / eslug_direction_total * 100
            print(f"  Agreeing pairs: {eslug_direction_agree}/{eslug_direction_total} = {rate:.1f}%")
        else:
            print("  No pairs to compare")

        print(f"\n--- Time proximity breakdown (eventSlug level) ---")
        for bucket in ["<=30min", "<=1hr", "<=4hr", "<=24hr", ">24hr"]:
            cnt = eslug_time_proximity.get(bucket, 0)
            print(f"  {bucket:10s}: {cnt:4d} pairs")

        weeks = max(span_days / 7, 1)
        print(f"\n--- Estimated consensus signals (eventSlug level) ---")
        print(f"  Total consensus pairs (same direction): {eslug_consensus_count}")
        print(f"  Span: {span_days:.0f} days ({weeks:.1f} weeks)")
        print(f"  Consensus signals per week: {eslug_consensus_count / weeks:.2f}")

    print(f"\n{sep}\n")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  POLYMARKET THEMATIC BASKET OVERLAP BACKTEST")
    print("  Date: ", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    print("=" * 72)

    print("\n[1/2] Fetching SPORTS basket...")
    sports_trades = fetch_basket(SPORTS_BASKET)

    print("\n[2/2] Fetching GEOPOLITICS basket...")
    geo_trades = fetch_basket(GEO_BASKET)

    analyze_basket("SPORTS", sports_trades)
    analyze_basket("GEOPOLITICS", geo_trades)

    print("Done.")


if __name__ == "__main__":
    main()
