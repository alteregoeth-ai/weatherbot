"""Fit forecast-error sigma from historical actual temperatures.

Primary source: Visual Crossing API (keyed, no rate limits, station-based).
Fallback:       IEM ASOS archive (free, same data as Wunderground/Polymarket).
Writes data/sigma_calibration.json consumed by get_sigma() in bot_v2.py.
"""
import datetime as dt
import glob
import json
import os
import statistics
import time
import urllib.request
import urllib.parse

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETS_DIR = os.path.join(ROOT, "data", "markets")
OUT_FILE    = os.path.join(ROOT, "data", "sigma_calibration.json")

with open(os.path.join(ROOT, "config.json")) as _f:
    _cfg = json.load(_f)
VC_KEY = _cfg.get("vc_key", "")

# City display names for Visual Crossing queries (city name or lat,lon works)
VC_LOCATION = {
    "nyc": "New York City,NY,US", "chicago": "Chicago,IL,US",
    "miami": "Miami,FL,US", "dallas": "Dallas,TX,US",
    "seattle": "Seattle,WA,US", "atlanta": "Atlanta,GA,US",
    "london": "London,UK", "paris": "Paris,France",
    "munich": "Munich,Germany", "ankara": "Ankara,Turkey",
    "seoul": "Seoul,South Korea", "tokyo": "Tokyo,Japan",
    "shanghai": "Shanghai,China", "singapore": "Singapore",
    "lucknow": "Lucknow,India", "tel-aviv": "Tel Aviv,Israel",
    "toronto": "Toronto,Canada", "sao-paulo": "Sao Paulo,Brazil",
    "buenos-aires": "Buenos Aires,Argentina", "wellington": "Wellington,New Zealand",
}

STATION = {
    "nyc": "KLGA", "chicago": "KORD", "miami": "KMIA", "dallas": "KDAL",
    "seattle": "KSEA", "atlanta": "KATL", "london": "EGLC", "paris": "LFPG",
    "munich": "EDDM", "ankara": "LTAC", "seoul": "RKSI", "tokyo": "RJTT",
    "shanghai": "ZSPD", "singapore": "WSSS", "lucknow": "VILK",
    "tel-aviv": "LLBG", "toronto": "CYYZ", "sao-paulo": "SBGR",
    "buenos-aires": "SAEZ", "wellington": "NZWN",
}


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "weatherbot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()


def vc_fetch(city, date_str, product_kind, unit):
    """Fetch daily max or min from Visual Crossing. Returns temp in city's native unit."""
    if not VC_KEY:
        return None
    loc    = urllib.parse.quote(VC_LOCATION.get(city, city))
    ug     = "us" if unit == "F" else "metric"
    url    = (f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services"
              f"/timeline/{loc}/{date_str}?key={VC_KEY}&include=days"
              f"&elements=tempmax,tempmin&unitGroup={ug}&contentType=json")
    data   = json.loads(_http_get(url))
    day    = data.get("days", [{}])[0]
    return day.get("tempmax") if product_kind == "max" else day.get("tempmin")


def iem_fetch(station, date_str, product_kind):
    """Fetch daily max or min from IEM ASOS. Returns temp in °F. Retries once on 429."""
    d   = dt.date.fromisoformat(date_str)
    url = (
        "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
        f"?station={station}&data=tmpf"
        f"&year1={d.year}&month1={d.month}&day1={d.day}"
        f"&year2={d.year}&month2={d.month}&day2={d.day}"
        "&tz=UTC&format=onlycomma&missing=M&trace=T&direct=no&report_type=3"
    )
    for attempt in range(2):
        try:
            lines = _http_get(url).strip().split("\n")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(3)
                continue
            raise
    vals = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) >= 3 and parts[2] not in ("M", "T", ""):
            try:
                vals.append(float(parts[2]))
            except ValueError:
                pass
    if not vals:
        return None
    return max(vals) if product_kind == "max" else min(vals)


def f_to_c(f): return (f - 32) * 5 / 9


def load_positions():
    now  = dt.datetime.now(dt.timezone.utc)
    rows = []
    for fp in sorted(glob.glob(os.path.join(MARKETS_DIR, "*.json"))):
        try:
            with open(fp) as f:
                m = json.load(f)
        except Exception:
            continue
        pos = m.get("position")
        if not pos:
            continue
        if pos.get("status") == "closed":
            pass
        elif pos.get("status") == "open":
            end = m.get("event_end_date")
            if not end:
                continue
            try:
                edt = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
            except ValueError:
                continue
            if edt >= now:
                continue
        else:
            continue
        rows.append({
            "city":         m.get("city"),
            "date":         m.get("date"),
            "product_kind": m.get("product_kind", "max"),
            "unit":         m.get("unit", "F"),
            "station":      m.get("station") or STATION.get(m.get("city", ""), ""),
            "forecast_temp":pos.get("forecast_temp"),
            "forecast_src": pos.get("forecast_src") or "ecmwf",
            "hours_left":   m.get("hours_at_discovery"),
            "actual_temp":  m.get("actual_temp"),
        })
    return rows


def horizon_bucket(hours):
    if hours is None: return "unknown"
    if hours <= 12:   return "D+0"
    if hours <= 36:   return "D+1"
    return "D+2+"


def main():
    rows = load_positions()
    print(f"Found {len(rows)} closed/expired positions\n")

    pairs = []
    for r in rows:
        fc = r["forecast_temp"]
        if fc is None:
            print(f"  SKIP {r['city']} {r['date']}: no forecast_temp")
            continue

        actual = r["actual_temp"]
        src    = "market_file"

        if actual is None:
            # Try Visual Crossing first
            try:
                actual = vc_fetch(r["city"], r["date"], r["product_kind"], r["unit"])
                if actual is not None:
                    src = "vc"
            except Exception as e:
                print(f"  VC   {r['city']} {r['date']}: {e} — trying IEM")

            # IEM fallback (returns °F, convert for °C cities)
            if actual is None:
                station = r["station"]
                if not station:
                    print(f"  SKIP {r['city']} {r['date']}: no station code")
                    continue
                try:
                    actual_f = iem_fetch(station, r["date"], r["product_kind"])
                    time.sleep(2)
                    if actual_f is not None:
                        actual = f_to_c(actual_f) if r["unit"] == "C" else actual_f
                        src = "iem"
                except Exception as e:
                    print(f"  ERR  {r['city']} {r['date']} ({station}): {e}")

        if actual is None:
            print(f"  MISS {r['city']} {r['date']}: no actual temp from any source")
            continue

        residual = float(fc) - float(actual)
        pairs.append({**r, "actual": actual, "residual": residual, "data_src": src})
        print(f"  OK   {r['city']} {r['date']} fc={fc} actual={actual:.1f} resid={residual:+.2f} [{src}]")

    if len(pairs) < 2:
        print("\nNot enough pairs to compute sigma. Exiting.")
        return

    # MAD-based outlier filter
    MAD_CUTOFF = 2.5
    _med = statistics.median(p["residual"] for p in pairs)
    _mad = statistics.median(abs(p["residual"] - _med) for p in pairs) or 1e-6
    _thresh = MAD_CUTOFF * _mad
    dropped = [p for p in pairs if abs(p["residual"] - _med) > _thresh]
    pairs   = [p for p in pairs if abs(p["residual"] - _med) <= _thresh]
    for p in dropped:
        print(f"  OUTLIER {p['city']} {p['date']} resid={p['residual']:+.2f}  (>{_thresh:.2f} from median) — excluded")

    print(f"\n{'='*60}")
    print(f"Sigma calibration — {len(pairs)} pairs  ({len(dropped)} outlier(s) excluded)")
    print(f"{'='*60}")

    residuals = [p["residual"] for p in pairs]

    def std(vals):
        return statistics.stdev(vals) if len(vals) >= 2 else None

    global_sigma = std(residuals)
    print(f"  Global σ = {global_sigma:.3f}  (mean bias = {statistics.mean(residuals):+.3f})")

    groups = {"C": [], "F": [], "ecmwf": [], "hrrr": [], "D+0": [], "D+1": [], "D+2+": [], "unknown": []}
    for p in pairs:
        groups[p["unit"]].append(p["residual"])
        groups[p["forecast_src"]].append(p["residual"])
        groups[horizon_bucket(p["hours_left"])].append(p["residual"])

    print("\n  By unit:")
    for k in ("C", "F"):
        v = groups[k]
        if v: print(f"    {k}: σ={std(v):.3f}  n={len(v)}")

    print("\n  By source:")
    for k in ("ecmwf", "hrrr"):
        v = groups[k]
        if v: print(f"    {k}: σ={std(v):.3f}  n={len(v)}")

    print("\n  By horizon:")
    for k in ("D+0", "D+1", "D+2+"):
        v = groups[k]
        if v: print(f"    {k}: σ={std(v):.3f}  n={len(v)}")

    cal = {
        "global": round(global_sigma, 3),
        "n_pairs": len(pairs),
        "computed_at": dt.date.today().isoformat(),
    }
    for key in ("C", "F", "ecmwf", "hrrr"):
        v = groups[key]
        if len(v) >= 3:
            cal[key] = round(std(v), 3)

    for unit in ("C", "F"):
        for s in ("ecmwf", "hrrr"):
            combo = [p["residual"] for p in pairs if p["unit"] == unit and p["forecast_src"] == s]
            if len(combo) >= 3:
                cal[f"{s}_{unit}"] = round(std(combo), 3)

    with open(OUT_FILE, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"\n  Written → {OUT_FILE}")
    print(f"  {json.dumps(cal, indent=2)}")


if __name__ == "__main__":
    main()
