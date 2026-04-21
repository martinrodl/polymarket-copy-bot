#!/usr/bin/env python3
"""
Backtest: Historical trade overlap analysis for 5 Polymarket wallets.

Determines how often wallets trade on the same markets and agree on direction.
Used to validate a copy-trading bot that triggers when 2+ wallets reach consensus.

Matching is performed at three levels:
  1. conditionId  -- exact same binary outcome market
  2. slug         -- same market slug (should equal conditionId-level but as safety net)
  3. eventSlug    -- same parent event (e.g. "2026-nba-champion" groups all team sub-markets)
"""

import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

# ── Wallet configuration ──────────────────────────────────────────────────────

WALLETS = {
    "BAdiosB":   "0x909fa9f89976058b8b3ab87adc502ec7415ea8c3",
    "LucasMeow": "0x7f3c8979d0afa00007bae4747d5347122af05613",
    "Erasmus":   "0xc6587b11a2209e46dfe3928b31c5514a8e33b784",
    "elkmonkey": "0xead152b855effa6b5b5837f53b24c0756830c76a",
    "gatorr":    "0x93abbc022ce98d6f45d4444b594791cc4b7a9723",
}

BASE_URL = "https://data-api.polymarket.com/activity"
TRADES_PER_WALLET = 500
PAGE_SIZE = 100
RATE_LIMIT_SLEEP = 0.2  # seconds between API calls


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_trades(name: str, address: str) -> list[dict]:
    """Fetch up to TRADES_PER_WALLET trades for a wallet, paginating as needed."""
    all_trades = []
    offset = 0

    while offset < TRADES_PER_WALLET:
        url = f"{BASE_URL}?user={address}&limit={PAGE_SIZE}&offset={offset}"
        print(f"  Fetching {name} offset={offset} ...", end=" ", flush=True)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "polymarket-backtest/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            print(f"ERROR: {e}")
            break

        if not data:
            print("(no more data)")
            break

        trades = [item for item in data if item.get("type") == "TRADE"]
        all_trades.extend(trades)
        print(f"got {len(data)} items, {len(trades)} trades")

        if len(data) < PAGE_SIZE:
            break  # last page

        offset += PAGE_SIZE
        time.sleep(RATE_LIMIT_SLEEP)

    return all_trades


def fetch_all_wallets() -> dict[str, list[dict]]:
    """Fetch trades for every configured wallet."""
    wallet_trades = {}
    for name, address in WALLETS.items():
        print(f"\n[{name}] ({address})")
        wallet_trades[name] = fetch_trades(name, address)
        time.sleep(RATE_LIMIT_SLEEP)
    return wallet_trades


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_timestamp(ts) -> datetime:
    """Parse a timestamp (ISO string or epoch) into a timezone-aware datetime."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    ts_str = str(ts).replace("Z", "+00:00")
    if "+" not in ts_str:
        ts_str += "+00:00"
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                dt = datetime.strptime(ts_str.split("+")[0], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(timezone.utc)


def compute_direction(trade: dict) -> str:
    """Canonical direction: BUY_Yes, SELL_No, etc."""
    side = str(trade.get("side", "")).upper()
    outcome = str(trade.get("outcome", "")).strip()
    return f"{side}_{outcome}"


def effective_bet(trade: dict) -> str:
    """
    Reduce a trade to its effective bet meaning.
    BUY_Yes  = bullish on this outcome
    SELL_Yes = bearish on this outcome
    BUY_No   = bearish on this outcome
    SELL_No  = bullish on this outcome (in binary market: same as BUY_Yes)
    We return 'LONG' or 'SHORT' relative to the named outcome.
    """
    side = str(trade.get("side", "")).upper()
    outcome = str(trade.get("outcome", "")).strip().lower()
    if (side == "BUY" and outcome == "yes") or (side == "SELL" and outcome == "no"):
        return "LONG"
    else:
        return "SHORT"


# ── Analysis engine ───────────────────────────────────────────────────────────

def run_overlap_analysis(wallet_trades: dict[str, list[dict]], key_field: str,
                         label: str) -> dict:
    """
    Generic overlap analysis using any grouping key (conditionId, slug, eventSlug).
    Returns a summary dict with all computed metrics.
    """
    wallet_names = list(wallet_trades.keys())

    # key -> { wallet_name: [trades] }
    market_wallets: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    # key -> human-readable title (first seen)
    market_titles: dict[str, str] = {}

    for name, trades in wallet_trades.items():
        for t in trades:
            key = t.get(key_field, "")
            if not key:
                continue
            market_wallets[key][name].append(t)
            if key not in market_titles:
                market_titles[key] = t.get("title", t.get("slug", key[:40]))

    overlap_markets = {
        k: wallets for k, wallets in market_wallets.items() if len(wallets) >= 2
    }

    # Consensus: 2+ wallets with same dominant direction on the same key
    consensus_signals = []
    for k, wallets in overlap_markets.items():
        wallet_dirs: dict[str, str] = {}
        wallet_first_ts: dict[str, datetime] = {}
        wallet_detail: dict[str, dict] = {}

        for wname, trades in wallets.items():
            dir_counts: dict[str, int] = defaultdict(int)
            earliest_ts = None
            for t in trades:
                d = compute_direction(t)
                dir_counts[d] += 1
                ts = parse_timestamp(t.get("timestamp", 0))
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
            dominant = max(dir_counts, key=dir_counts.get)
            wallet_dirs[wname] = dominant
            wallet_first_ts[wname] = earliest_ts
            wallet_detail[wname] = {
                "direction": dominant,
                "trade_count": len(trades),
                "first_ts": earliest_ts,
                "total_usdcSize": sum(t.get("usdcSize", 0) for t in trades),
            }

        dir_groups: dict[str, list[str]] = defaultdict(list)
        for wname, d in wallet_dirs.items():
            dir_groups[d].append(wname)

        for direction, agreeing in dir_groups.items():
            if len(agreeing) >= 2:
                times = [wallet_first_ts[w] for w in agreeing if wallet_first_ts.get(w)]
                consensus_signals.append({
                    "key": k,
                    "title": market_titles.get(k, k[:40]),
                    "direction": direction,
                    "wallets": agreeing,
                    "timestamps": times,
                    "wallet_detail": {w: wallet_detail[w] for w in agreeing},
                })

    # Time proximity (30 min)
    close_signals = []
    for sig in consensus_signals:
        k = sig["key"]
        agreeing = sig["wallets"]
        direction = sig["direction"]
        wallet_times: dict[str, list[datetime]] = {}
        for wname in agreeing:
            times = []
            for t in market_wallets[k][wname]:
                if compute_direction(t) == direction:
                    times.append(parse_timestamp(t.get("timestamp", 0)))
            wallet_times[wname] = sorted(times)

        found_close = False
        for w1, w2 in combinations(agreeing, 2):
            for t1 in wallet_times.get(w1, []):
                for t2 in wallet_times.get(w2, []):
                    if abs((t1 - t2).total_seconds()) <= 1800:
                        found_close = True
                        break
                if found_close:
                    break
            if found_close:
                break
        if found_close:
            close_signals.append(sig)

    return {
        "label": label,
        "key_field": key_field,
        "market_wallets": market_wallets,
        "market_titles": market_titles,
        "overlap_markets": overlap_markets,
        "consensus_signals": consensus_signals,
        "close_signals": close_signals,
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_analysis(result: dict, wallet_trades: dict[str, list[dict]],
                   span_days: float, verbose: bool = True):
    """Print a full report for one matching level."""
    label = result["label"]
    key_field = result["key_field"]
    overlap_markets = result["overlap_markets"]
    consensus_signals = result["consensus_signals"]
    close_signals = result["close_signals"]
    market_titles = result["market_titles"]
    market_wallets = result["market_wallets"]

    wallet_names = list(wallet_trades.keys())
    weeks = max(span_days / 7, 1)
    months = max(span_days / 30, 1)

    hdr = f"ANALYSIS LEVEL: {label} (grouped by '{key_field}')"
    print("\n" + "=" * 80)
    print(hdr)
    print("=" * 80)

    # Per-wallet unique keys at this level
    for name, trades in wallet_trades.items():
        unique_keys = set(t.get(key_field, "") for t in trades if t.get(key_field))
        print(f"  {name:>12}: {len(unique_keys):>4} unique {key_field}s")

    # Overlapping markets
    print(f"\n  Markets with 2+ wallets: {len(overlap_markets)}")
    if overlap_markets and verbose:
        for k, wallets in sorted(overlap_markets.items(), key=lambda x: len(x[1]), reverse=True):
            title = market_titles.get(k, k[:50])
            wlist = ", ".join(sorted(wallets.keys()))
            trade_counts = ", ".join(f"{w}:{len(ts)}" for w, ts in sorted(wallets.items()))
            print(f"\n    [{len(wallets)} wallets] {title}")
            print(f"      Wallets     : {wlist}")
            print(f"      Trade counts: {trade_counts}")

    # Consensus signals
    print(f"\n  Consensus signals (2+ wallets, same direction): {len(consensus_signals)}")
    if consensus_signals and verbose:
        for sig in sorted(consensus_signals, key=lambda s: len(s["wallets"]), reverse=True):
            print(f"\n    [{len(sig['wallets'])} wallets] {sig['title']}")
            print(f"      Direction: {sig['direction']}")
            print(f"      Wallets  : {', '.join(sorted(sig['wallets']))}")
            for w, detail in sorted(sig["wallet_detail"].items()):
                ts_str = detail["first_ts"].strftime("%Y-%m-%d %H:%M") if detail["first_ts"] else "?"
                print(f"        {w}: {detail['trade_count']} trades, "
                      f"${detail['total_usdcSize']:.2f} USDC, first trade {ts_str}")

    # Close-time signals
    print(f"\n  Close-time signals (within 30 min): {len(close_signals)}")
    if close_signals and verbose:
        for sig in close_signals:
            print(f"    - {sig['title']} ({', '.join(sorted(sig['wallets']))})")

    # Signal frequency
    print(f"\n  Signal frequency (over {span_days:.0f} days):")
    print(f"    Consensus / week : {len(consensus_signals) / weeks:.2f}")
    print(f"    Consensus / month: {len(consensus_signals) / months:.2f}")
    print(f"    Close-time / week : {len(close_signals) / weeks:.2f}")
    print(f"    Close-time / month: {len(close_signals) / months:.2f}")

    # Pair-wise matrix
    print(f"\n  Pair-wise overlap (shared / consensus):")
    print(f"    {'':>12}", end="")
    for n in wallet_names:
        print(f"  {n:>10}", end="")
    print()
    for w1 in wallet_names:
        print(f"    {w1:>12}", end="")
        for w2 in wallet_names:
            if w1 == w2:
                print(f"  {'--':>10}", end="")
                continue
            shared = 0
            agree = 0
            for k, wallets in market_wallets.items():
                if w1 in wallets and w2 in wallets:
                    shared += 1
                    d1 = set(compute_direction(t) for t in wallets[w1])
                    d2 = set(compute_direction(t) for t in wallets[w2])
                    if d1 & d2:
                        agree += 1
            print(f"  {str(shared) + '/' + str(agree):>10}", end="")
        print()


def analyze_and_report(wallet_trades: dict[str, list[dict]]):
    """Main analysis: run all three levels and print combined report."""

    wallet_names = list(wallet_trades.keys())

    # ── Per-wallet summary ────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("PER-WALLET STATISTICS")
    print("=" * 80)

    all_timestamps = []
    for name, trades in wallet_trades.items():
        cids = set(t.get("conditionId", "") for t in trades if t.get("conditionId"))
        slugs = set(t.get("slug", "") for t in trades if t.get("slug"))
        eslugs = set(t.get("eventSlug", "") for t in trades if t.get("eventSlug"))
        total_usdc = sum(t.get("usdcSize", 0) for t in trades)
        for t in trades:
            ts = t.get("timestamp")
            if ts:
                all_timestamps.append(parse_timestamp(ts))

        print(f"\n  {name}:")
        print(f"    Trades           : {len(trades)}")
        print(f"    Unique markets   : {len(cids)} (conditionId) / {len(slugs)} (slug)")
        print(f"    Unique events    : {len(eslugs)} (eventSlug)")
        print(f"    Total volume     : ${total_usdc:,.2f} USDC")
        # Show top market categories
        titles = [t.get("title", "")[:60] for t in trades[:5]]
        if titles:
            print(f"    Sample markets   : {titles[0]}")
            for tt in titles[1:3]:
                print(f"                       {tt}")

    if all_timestamps:
        earliest = min(all_timestamps)
        latest = max(all_timestamps)
        span_days = max((latest - earliest).total_seconds() / 86400, 1)
    else:
        span_days = 1
        earliest = latest = datetime.now(timezone.utc)

    print(f"\n  Data window: {earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')} ({span_days:.0f} days)")

    # ── Run analysis at all three matching levels ─────────────────────────
    r_cid = run_overlap_analysis(wallet_trades, "conditionId",
                                 "Exact Market (conditionId)")
    r_slug = run_overlap_analysis(wallet_trades, "slug",
                                  "Market Slug")
    r_event = run_overlap_analysis(wallet_trades, "eventSlug",
                                   "Parent Event (eventSlug)")

    for r in [r_cid, r_slug, r_event]:
        print_analysis(r, wallet_trades, span_days, verbose=True)

    # ── Grand Summary ─────────────────────────────────────────────────────
    weeks = max(span_days / 7, 1)
    months = max(span_days / 30, 1)

    print("\n" + "=" * 80)
    print("GRAND SUMMARY")
    print("=" * 80)

    total_trades = sum(len(t) for t in wallet_trades.values())
    all_cids = set()
    for trades in wallet_trades.values():
        for t in trades:
            cid = t.get("conditionId", "")
            if cid:
                all_cids.add(cid)

    print(f"""
  Wallets analyzed          : {len(wallet_trades)}
  Total trades fetched      : {total_trades}
  Unique markets (all)      : {len(all_cids)}
  Data span                 : {span_days:.0f} days ({earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')})

  ---- Overlap at conditionId level (exact market) ----
  Markets with 2+ wallets   : {len(r_cid['overlap_markets'])}
  Consensus signals         : {len(r_cid['consensus_signals'])}
  Close-time signals (30m)  : {len(r_cid['close_signals'])}

  ---- Overlap at slug level ----
  Markets with 2+ wallets   : {len(r_slug['overlap_markets'])}
  Consensus signals         : {len(r_slug['consensus_signals'])}
  Close-time signals (30m)  : {len(r_slug['close_signals'])}

  ---- Overlap at eventSlug level (parent event) ----
  Events with 2+ wallets    : {len(r_event['overlap_markets'])}
  Consensus signals         : {len(r_event['consensus_signals'])}
  Close-time signals (30m)  : {len(r_event['close_signals'])}

  ---- Estimated signal rates (eventSlug level, broadest) ----
  Consensus / week          : {len(r_event['consensus_signals']) / weeks:.2f}
  Consensus / month         : {len(r_event['consensus_signals']) / months:.2f}
  Close-time / week         : {len(r_event['close_signals']) / weeks:.2f}
  Close-time / month        : {len(r_event['close_signals']) / months:.2f}
""")

    # ── Interpretation ────────────────────────────────────────────────────
    print("=" * 80)
    print("INTERPRETATION / RECOMMENDATIONS")
    print("=" * 80)

    cid_overlap = len(r_cid["overlap_markets"])
    event_overlap = len(r_event["overlap_markets"])
    cid_consensus = len(r_cid["consensus_signals"])
    event_consensus = len(r_event["consensus_signals"])

    if cid_overlap == 0 and event_overlap == 0:
        print("""
  These 5 wallets show ZERO overlap on exact markets and ZERO on parent events
  in the last ~{days} days of trading history ({trades} trades across {markets}
  unique markets). They are trading in completely different market segments:

""".format(days=int(span_days), trades=total_trades, markets=len(all_cids)))

        # Show what each wallet focuses on
        for name, trades in wallet_trades.items():
            slugs = list(set(t.get("slug", "")[:50] for t in trades if t.get("slug")))[:5]
            print(f"    {name}: {', '.join(slugs[:3])}")
        print("""
  CONCLUSION: This wallet basket would generate essentially 0 consensus signals
  for a copy-trading bot. The wallets are too specialized/different in their
  market selection to produce actionable overlap.

  RECOMMENDATIONS:
    1. Replace some wallets with traders who have overlapping market interests
    2. Use eventSlug-level matching (parent events) to increase signal surface
    3. Consider tracking more wallets (10-20) to find natural clusters
    4. Lower the consensus threshold or add thematic grouping
       (e.g. all crypto wallets, all sports wallets, all geopolitics wallets)
""")
    elif event_overlap > 0 and cid_overlap == 0:
        print(f"""
  No exact market (conditionId) overlap, but {event_overlap} shared parent events.
  Wallets are trading related but distinct sub-markets within the same events.
  The bot could use eventSlug-level matching for broader signal detection.
  Estimated {event_consensus / weeks:.1f} consensus signals per week at event level.
""")
    else:
        print(f"""
  Found {cid_overlap} exact market overlaps generating {cid_consensus} consensus signals.
  At event level: {event_overlap} overlaps, {event_consensus} consensus signals.
  This basket generates roughly {cid_consensus / weeks:.1f} exact consensus / week
  and {event_consensus / weeks:.1f} event-level consensus / week.
""")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 80)
    print("POLYMARKET COPY-BOT BACKTEST: Wallet Overlap Analysis")
    print("=" * 80)
    print(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Wallets: {', '.join(WALLETS.keys())}")
    print(f"Max trades per wallet: {TRADES_PER_WALLET}")
    print(f"Matching levels: conditionId, slug, eventSlug")

    print("\n--- Fetching trade data ---")
    wallet_trades = fetch_all_wallets()

    analyze_and_report(wallet_trades)
