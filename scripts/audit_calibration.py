"""Calibration audit for weatherbot forecast-based q.

Reads data/markets/*.json, finds every closed position, and reports whether
the bot's predicted probability `p` (q in article terms) was calibrated
against actual outcomes. Read-only — touches nothing.
"""
import glob
import json
import os
import statistics
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETS_DIR = os.path.join(ROOT, "data", "markets")


def load_closed_positions():
    rows = []
    for fp in sorted(glob.glob(os.path.join(MARKETS_DIR, "*.json"))):
        try:
            with open(fp) as f:
                m = json.load(f)
        except Exception:
            continue
        pos = m.get("position")
        if not pos or pos.get("status") != "closed":
            continue
        pnl = pos.get("pnl")
        if pnl is None:
            continue
        won = 1 if pnl > 0 else 0
        is_edge_bucket = pos.get("bucket_low") == -999 or pos.get("bucket_high") == 999
        rows.append({
            "file": os.path.basename(fp),
            "city": m.get("city"),
            "q": float(pos.get("p", 0)),
            "entry": float(pos.get("entry_price", 0)),
            "ev": float(pos.get("ev", 0)),
            "kelly": float(pos.get("kelly", 0)),
            "cost": float(pos.get("cost", 0)),
            "pnl": float(pnl),
            "won": won,
            "edge_bucket": is_edge_bucket,
            "close_reason": pos.get("close_reason"),
        })
    return rows


def fmt_pct(x):
    return f"{x*100:5.1f}%"


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    rows = load_closed_positions()
    n = len(rows)
    if n == 0:
        print("No closed positions found in data/markets/")
        return

    wins = sum(r["won"] for r in rows)
    losses = n - wins
    mean_q = statistics.mean(r["q"] for r in rows)
    mean_entry = statistics.mean(r["entry"] for r in rows)
    mean_ev = statistics.mean(r["ev"] for r in rows)
    mean_pnl = statistics.mean(r["pnl"] for r in rows)
    total_pnl = sum(r["pnl"] for r in rows)
    total_cost = sum(r["cost"] for r in rows)
    brier = statistics.mean((r["q"] - r["won"]) ** 2 for r in rows)
    realized_edge = statistics.mean(r["won"] - r["entry"] for r in rows)

    section(f"Overall calibration ({n} closed positions)")
    print(f"  Wins / Losses        : {wins} / {losses}  ({fmt_pct(wins/n)} hit rate)")
    print(f"  Mean predicted q     : {mean_q:.3f}   (perfectly calibrated bot would equal hit rate)")
    print(f"  Calibration gap      : {mean_q - wins/n:+.3f}   (positive = overconfident)")
    print(f"  Brier score          : {brier:.4f}   (0 = perfect, 0.25 = random, 1 = worst)")
    print(f"  Mean entry price     : {mean_entry:.3f}")
    print(f"  Realized edge (q-p)  : {realized_edge:+.3f}   (mean(outcome - entry); >0 = real edge)")
    print(f"  Mean ev (predicted)  : {mean_ev:+.3f}")
    print(f"  Mean PnL / trade     : ${mean_pnl:+.2f}")
    print(f"  Total PnL / cost     : ${total_pnl:+.2f} on ${total_cost:.2f} risked  ({fmt_pct(total_pnl/total_cost) if total_cost else 'n/a'})")

    section("Hit rate by predicted-q band")
    bands = [(0.0, 0.5), (0.5, 0.9), (0.9, 0.999), (0.999, 1.001)]
    for lo, hi in bands:
        sub = [r for r in rows if lo <= r["q"] < hi]
        if not sub:
            continue
        sub_wins = sum(r["won"] for r in sub)
        sub_q = statistics.mean(r["q"] for r in sub)
        label = f"q in [{lo:.2f}, {hi:.2f})"
        print(f"  {label:22s} n={len(sub):2d}  hit={fmt_pct(sub_wins/len(sub))}  mean_q={sub_q:.3f}  gap={sub_q - sub_wins/len(sub):+.3f}")

    section("Hit rate by predicted-EV band")
    ev_bands = [(-99, 0.5), (0.5, 1.0), (1.0, 99)]
    for lo, hi in ev_bands:
        sub = [r for r in rows if lo <= r["ev"] < hi]
        if not sub:
            continue
        sub_wins = sum(r["won"] for r in sub)
        sub_pnl = sum(r["pnl"] for r in sub)
        print(f"  ev in [{lo:>5.1f}, {hi:>5.1f})  n={len(sub):2d}  hit={fmt_pct(sub_wins/len(sub))}  total_pnl=${sub_pnl:+.2f}")

    section("Bucket type breakdown")
    for label, subset in [("Regular buckets (binary q)", [r for r in rows if not r["edge_bucket"]]),
                          ("Edge buckets (CDF q)",        [r for r in rows if r["edge_bucket"]])]:
        if not subset:
            print(f"  {label}: n=0")
            continue
        sw = sum(r["won"] for r in subset)
        sq = statistics.mean(r["q"] for r in subset)
        sb = statistics.mean((r["q"] - r["won"]) ** 2 for r in subset)
        sp = sum(r["pnl"] for r in subset)
        print(f"  {label:35s} n={len(subset):2d}  hit={fmt_pct(sw/len(subset))}  mean_q={sq:.3f}  brier={sb:.3f}  total_pnl=${sp:+.2f}")

    section("Close reasons")
    reasons = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for r in rows:
        reasons[r["close_reason"] or "unknown"]["n"] += 1
        reasons[r["close_reason"] or "unknown"]["pnl"] += r["pnl"]
    for reason, agg in sorted(reasons.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {reason:20s} n={agg['n']:2d}  total_pnl=${agg['pnl']:+.2f}")

    section("Verdict")
    if realized_edge > 0.05:
        verdict = "EDGE CONFIRMED. Forecast q is producing positive realized edge."
    elif realized_edge > -0.02:
        verdict = "MARGINAL. Realized edge near zero — q is approximately calibrated to market, no real alpha."
    else:
        verdict = "NEGATIVE EDGE. Forecast-based q is losing money systematically."
    print(f"  {verdict}")
    if mean_q - wins/n > 0.20:
        print(f"  OVERCONFIDENT. Predicted q exceeds realized hit rate by {(mean_q - wins/n)*100:.0f} points.")
    print(f"  Suggestion: see plan decision-tree for next spike based on these numbers.")


if __name__ == "__main__":
    main()
