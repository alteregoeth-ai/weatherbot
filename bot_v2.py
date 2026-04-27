#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weatherbet.py — Weather Trading Bot for Polymarket
=====================================================
Tracks weather forecasts from 3 sources (ECMWF, HRRR, METAR),
compares with Polymarket markets, paper trades using Kelly criterion.

Usage:
    python weatherbet.py          # main loop
    python weatherbet.py report   # full report
    python weatherbet.py status   # balance and open positions
"""

import re
import sys
import json
import math
import time
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderArgs, OrderType, BalanceAllowanceParams, AssetType
CLOB_BUY  = "BUY"
CLOB_SELL = "SELL"

# =============================================================================
# CONFIG
# =============================================================================

with open("config.json", encoding="utf-8") as f:
    _cfg = json.load(f)

BALANCE          = _cfg.get("balance", 10000.0)
MAX_BET          = _cfg.get("max_bet", 20.0)        # max bet per trade
MIN_EV           = _cfg.get("min_ev", 0.10)
MAX_PRICE        = _cfg.get("max_price", 0.45)
MIN_VOLUME       = _cfg.get("min_volume", 500)
MIN_HOURS        = _cfg.get("min_hours", 2.0)
MAX_HOURS        = _cfg.get("max_hours", 72.0)
KELLY_FRACTION   = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE     = _cfg.get("max_slippage", 0.03)  # max allowed ask-bid spread
SCAN_INTERVAL    = _cfg.get("scan_interval", 3600)   # every hour
CALIBRATION_MIN  = _cfg.get("calibration_min", 30)
VC_KEY           = _cfg.get("vc_key", "")

# Live trading credentials are loaded from environment variables only.
# Never hardcode these values in source/config files.
PRIVATE_KEY      = os.getenv("PRIVATE_KEY", "")
CHAIN_ID_RAW     = os.getenv("CHAIN_ID", "137")
try:
    CHAIN_ID     = int(CHAIN_ID_RAW)
except ValueError:
    CHAIN_ID     = None
SIGNATURE_TYPE   = os.getenv("SIGNATURE_TYPE", "proxy")
PROXY_KEY        = os.getenv("PROXY_KEY", "")
POLY_API_KEY     = os.getenv("POLY_API_KEY", "")
POLY_SECRET      = os.getenv("POLY_SECRET", "")
POLY_PASSPHRASE  = os.getenv("POLY_PASSPHRASE", "")
POLYGON_RPC_URL  = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
POLYGON_RPC_URLS = [
    u.strip() for u in os.getenv(
        "POLYGON_RPC_URLS",
        f"{POLYGON_RPC_URL},https://rpc.ankr.com/polygon,https://polygon-bor-rpc.publicnode.com"
    ).split(",") if u.strip()
]
WALLET_ADDRESS   = os.getenv("WALLET_ADDRESS", PROXY_KEY)
LIVE_CONFIG_ERRORS = []
if not PRIVATE_KEY:
    LIVE_CONFIG_ERRORS.append("PRIVATE_KEY")
if not POLY_API_KEY:
    LIVE_CONFIG_ERRORS.append("POLY_API_KEY")
if not POLY_SECRET:
    LIVE_CONFIG_ERRORS.append("POLY_SECRET")
if not POLY_PASSPHRASE:
    LIVE_CONFIG_ERRORS.append("POLY_PASSPHRASE")
if not WALLET_ADDRESS:
    LIVE_CONFIG_ERRORS.append("PROXY_KEY or WALLET_ADDRESS")
if CHAIN_ID != 137:
    LIVE_CONFIG_ERRORS.append("CHAIN_ID must be 137")
if SIGNATURE_TYPE.lower() != "proxy":
    LIVE_CONFIG_ERRORS.append("SIGNATURE_TYPE must be proxy")
LIVE_TRADING     = not LIVE_CONFIG_ERRORS

SIGMA_F = 2.0
SIGMA_C = 1.2

DATA_DIR         = Path("data")
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE       = DATA_DIR / "state.json"
MARKETS_DIR      = DATA_DIR / "markets"
MARKETS_DIR.mkdir(exist_ok=True)
CALIBRATION_FILE = DATA_DIR / "calibration.json"

LOCATIONS = {
    "nyc":          {"lat": 40.7772,  "lon":  -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago":      {"lat": 41.9742,  "lon":  -87.9073, "name": "Chicago",       "station": "KORD", "unit": "F", "region": "us"},
    "miami":        {"lat": 25.7959,  "lon":  -80.2870, "name": "Miami",         "station": "KMIA", "unit": "F", "region": "us"},
    "dallas":       {"lat": 32.8471,  "lon":  -96.8518, "name": "Dallas",        "station": "KDAL", "unit": "F", "region": "us"},
    "seattle":      {"lat": 47.4502,  "lon": -122.3088, "name": "Seattle",       "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta":      {"lat": 33.6407,  "lon":  -84.4277, "name": "Atlanta",       "station": "KATL", "unit": "F", "region": "us"},
    "london":       {"lat": 51.5048,  "lon":    0.0495, "name": "London",        "station": "EGLC", "unit": "C", "region": "eu"},
    "paris":        {"lat": 48.9962,  "lon":    2.5979, "name": "Paris",         "station": "LFPG", "unit": "C", "region": "eu"},
    "munich":       {"lat": 48.3537,  "lon":   11.7750, "name": "Munich",        "station": "EDDM", "unit": "C", "region": "eu"},
    "ankara":       {"lat": 40.1281,  "lon":   32.9951, "name": "Ankara",        "station": "LTAC", "unit": "C", "region": "eu"},
    "seoul":        {"lat": 37.4691,  "lon":  126.4505, "name": "Seoul",         "station": "RKSI", "unit": "C", "region": "asia"},
    "tokyo":        {"lat": 35.7647,  "lon":  140.3864, "name": "Tokyo",         "station": "RJTT", "unit": "C", "region": "asia"},
    "shanghai":     {"lat": 31.1443,  "lon":  121.8083, "name": "Shanghai",      "station": "ZSPD", "unit": "C", "region": "asia"},
    "singapore":    {"lat":  1.3502,  "lon":  103.9940, "name": "Singapore",     "station": "WSSS", "unit": "C", "region": "asia"},
    "lucknow":      {"lat": 26.7606,  "lon":   80.8893, "name": "Lucknow",       "station": "VILK", "unit": "C", "region": "asia"},
    "tel-aviv":     {"lat": 32.0114,  "lon":   34.8867, "name": "Tel Aviv",      "station": "LLBG", "unit": "C", "region": "asia"},
    "toronto":      {"lat": 43.6772,  "lon":  -79.6306, "name": "Toronto",       "station": "CYYZ", "unit": "C", "region": "ca"},
    "sao-paulo":    {"lat": -23.4356, "lon":  -46.4731, "name": "Sao Paulo",     "station": "SBGR", "unit": "C", "region": "sa"},
    "buenos-aires": {"lat": -34.8222, "lon":  -58.5358, "name": "Buenos Aires",  "station": "SAEZ", "unit": "C", "region": "sa"},
    "wellington":   {"lat": -41.3272, "lon":  174.8052, "name": "Wellington",    "station": "NZWN", "unit": "C", "region": "oc"},
}

TIMEZONES = {
    "nyc": "America/New_York", "chicago": "America/Chicago",
    "miami": "America/New_York", "dallas": "America/Chicago",
    "seattle": "America/Los_Angeles", "atlanta": "America/New_York",
    "london": "Europe/London", "paris": "Europe/Paris",
    "munich": "Europe/Berlin", "ankara": "Europe/Istanbul",
    "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai", "singapore": "Asia/Singapore",
    "lucknow": "Asia/Kolkata", "tel-aviv": "Asia/Jerusalem",
    "toronto": "America/Toronto", "sao-paulo": "America/Sao_Paulo",
    "buenos-aires": "America/Argentina/Buenos_Aires", "wellington": "Pacific/Auckland",
}

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]

TEMPERATURE_PRODUCTS = {
    "max": {
        "slug_prefix": "highest-temperature-in",
        "forecast_variable": "temperature_2m_max",
        "resolution_element": "tempmax",
    },
    "min": {
        "slug_prefix": "lowest-temperature-in",
        "forecast_variable": "temperature_2m_min",
        "resolution_element": "tempmin",
    },
}
DEFAULT_PRODUCT_KIND = "max"
PRODUCT_KIND_LIST = ("max", "min")
SCAN_TRACE = os.getenv("WEATHERBOT_SCAN_TRACE", "1").lower() in {"1", "true", "yes", "on"}
FORECAST_ATTEMPTS = 2
FORECAST_RETRY_SECONDS = 1
CLOB_POST_ATTEMPTS = 3
CLOB_POST_RETRY_SECONDS = 1
GAMMA_GET_ATTEMPTS = 3
GAMMA_GET_RETRY_SECONDS = 1

TOKEN_MATIC = "0x0000000000000000000000000000000000001010"
TOKEN_USDC_POS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
TOKEN_USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"

# =============================================================================
# CLOB — LIVE ORDER PLACEMENT
# =============================================================================

_clob = None

def require_live_trading_ready():
    if LIVE_CONFIG_ERRORS:
        missing = ", ".join(LIVE_CONFIG_ERRORS)
        raise RuntimeError(f"Live trading is not ready: {missing}")

def live_order_succeeded(resp):
    if not isinstance(resp, dict):
        return False
    if resp.get("errorMsg"):
        return False
    if resp.get("success") is not True:
        return False
    return bool(resp.get("orderID") or resp.get("id"))

def create_signed_order(clob, args):
    if hasattr(clob, "create_order"):
        return clob.create_order(args)
    if hasattr(clob, "create_and_sign_order"):
        return clob.create_and_sign_order(args)
    raise AttributeError("ClobClient has no create_order/create_and_sign_order method")

def create_signed_market_order(clob, args):
    if hasattr(clob, "create_market_order"):
        return clob.create_market_order(args)
    return create_signed_order(clob, args)

def is_transient_clob_exception(exc):
    return getattr(exc, "status_code", None) is None and "Request exception" in str(exc)

def is_fok_not_filled_exception(exc):
    err = getattr(exc, "error_msg", None)
    if isinstance(err, dict):
        msg = str(err.get("error", ""))
    else:
        msg = str(exc)
    msg = msg.lower()
    return "couldn't be fully filled" in msg or "fully filled or killed" in msg

def post_live_order(clob, signed, order_type, action):
    last_exc = None
    for attempt in range(1, CLOB_POST_ATTEMPTS + 1):
        try:
            return clob.post_order(signed, order_type)
        except Exception as e:
            last_exc = e
            if not is_transient_clob_exception(e) or attempt == CLOB_POST_ATTEMPTS:
                raise
            print(f"  [LIVE WARN] {action} post request failed ({e}); retrying {attempt}/{CLOB_POST_ATTEMPTS - 1}")
            time.sleep(CLOB_POST_RETRY_SECONDS * attempt)
    raise last_exc

def get_gamma_json(url, timeout=(5, 8), label="GAMMA"):
    last_exc = None
    for attempt in range(1, GAMMA_GET_ATTEMPTS + 1):
        try:
            return requests.get(url, timeout=timeout).json()
        except Exception as e:
            last_exc = e
            if attempt == GAMMA_GET_ATTEMPTS:
                raise
            print(f"  [{label} WARN] request failed ({e}); retrying {attempt}/{GAMMA_GET_ATTEMPTS - 1}")
            time.sleep(GAMMA_GET_RETRY_SECONDS * attempt)
    raise last_exc

def get_clob():
    global _clob
    require_live_trading_ready()
    if _clob is None:
        creds = ApiCreds(
            api_key=POLY_API_KEY,
            api_secret=POLY_SECRET,
            api_passphrase=POLY_PASSPHRASE,
        )
        _clob = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=CHAIN_ID,
            key=PRIVATE_KEY,
            creds=creds,
            signature_type=1,  # 1 = proxy wallet
            funder=WALLET_ADDRESS,
        )
    return _clob

def get_real_shares(clob, token_id):
    """Query actual on-chain conditional token balance. Returns float shares or None."""
    try:
        params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
        result = clob.get_balance_allowance(params)
        raw = int(result.get("balance", 0))
        return round(raw / 1e6, 4)
    except Exception as e:
        print(f"  [LIVE WARN] could not read on-chain shares: {e}")
        return None

def parse_balance_from_error(exc):
    """Extract actual balance (in raw units) from a 'not enough balance' CLOB error."""
    msg = str(getattr(exc, "error_msg", exc))
    m = re.search(r"balance:\s*(\d+)", msg)
    return int(m.group(1)) if m else None

def place_live_buy(token_id, price, size_usdc):
    """Returns False on failure, or actual on-chain shares (float) on success."""
    if not token_id:
        print("  [LIVE ERR] No token_id — cannot place buy")
        return False
    try:
        clob = get_clob()
        args = MarketOrderArgs(
            token_id=token_id,
            amount=round(float(size_usdc), 2),
            side=CLOB_BUY,
            price=round(float(price), 4),
            order_type=OrderType.FOK,
        )
        signed = create_signed_market_order(clob, args)
        resp = post_live_order(clob, signed, OrderType.FOK, "Buy")
        if not live_order_succeeded(resp):
            print(f"  [LIVE ERR] Buy rejected: {resp}")
            return False
        print(f"  [LIVE] Buy placed — order {resp.get('orderID', '?')}")
        # Fix 1: query actual on-chain shares after settlement
        time.sleep(2)
        real = get_real_shares(clob, token_id)
        if real is not None and real > 0:
            print(f"  [LIVE] Actual shares received: {real}")
            return real
        return True  # success but couldn't read actual amount
    except Exception as e:
        if is_fok_not_filled_exception(e):
            print("  [LIVE SKIP] Buy not filled — FOK order was killed by available liquidity")
            return False
        print(f"  [LIVE ERR] Buy exception: {e}")
        return False

def _do_sell(clob, token_id, price, shares):
    args = OrderArgs(price=round(float(price), 4), size=round(float(shares), 4), side=CLOB_SELL, token_id=token_id)
    signed = create_signed_order(clob, args)
    return post_live_order(clob, signed, OrderType.FOK, "Sell")

def place_live_sell(token_id, price, shares):
    """Returns False on failure, or (sold_shares, fill_price) tuple on success."""
    if not token_id:
        print("  [LIVE ERR] No token_id — cannot place sell")
        return False
    try:
        clob = get_clob()
        sold_shares = float(shares)
        try:
            resp = _do_sell(clob, token_id, price, shares)
        except Exception as e:
            raw_balance = parse_balance_from_error(e)
            if raw_balance is None or raw_balance <= 0:
                raise
            sold_shares = round(raw_balance / 1e6, 4)
            print(f"  [LIVE] Sell failed for {shares} shares; retrying with on-chain {sold_shares}")
            resp = _do_sell(clob, token_id, price, sold_shares)
        if not live_order_succeeded(resp):
            print(f"  [LIVE ERR] Sell rejected: {resp}")
            return False
        print(f"  [LIVE] Sell placed — order {resp.get('orderID', '?')} | sold {sold_shares} shares @ ${price:.3f}")
        return (sold_shares, float(price))
    except Exception as e:
        if is_fok_not_filled_exception(e):
            print("  [LIVE SKIP] Sell not filled — FOK order was killed by available liquidity")
            return False
        print(f"  [LIVE ERR] Sell exception: {e}")
        return False


def print_live_check():
    print(f"\n{'='*55}")
    print("  WEATHERBET — LIVE TRADING CHECK")
    print(f"{'='*55}")
    checks = {
        "PRIVATE_KEY": bool(PRIVATE_KEY),
        "CHAIN_ID": CHAIN_ID == 137,
        "SIGNATURE_TYPE": SIGNATURE_TYPE.lower() == "proxy",
        "PROXY_KEY or WALLET_ADDRESS": bool(WALLET_ADDRESS),
        "POLY_API_KEY": bool(POLY_API_KEY),
        "POLY_SECRET": bool(POLY_SECRET),
        "POLY_PASSPHRASE": bool(POLY_PASSPHRASE),
    }
    for name, ok in checks.items():
        print(f"  {name:<25} {'ok' if ok else 'missing/invalid'}")

    print(f"  Mode:                    {'LIVE' if LIVE_TRADING else 'PAPER'}")
    if LIVE_CONFIG_ERRORS:
        print(f"  Live disabled:           {', '.join(LIVE_CONFIG_ERRORS)}")
        print(f"{'='*55}\n")
        return

    try:
        get_clob()
        print("  CLOB client:             ok")
    except Exception as e:
        print(f"  CLOB client:             error: {e}")

    print(f"{'='*55}\n")


def _trace_scan(msg: str):
    if SCAN_TRACE:
        print(f"  {msg}")

# =============================================================================
# MATH
# =============================================================================

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast, t_low, t_high, sigma=None):
    """For regular buckets — exact match. For edge buckets — normal distribution."""
    s = sigma or 2.0
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / s)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / s)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0

def calc_ev(p, price):
    if price <= 0 or price >= 1: return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)

def calc_kelly(p, price):
    if price <= 0 or price >= 1: return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(0.0, f) * KELLY_FRACTION, 1.0), 4)

def bet_size(kelly, balance):
    raw = kelly * balance
    return round(min(raw, MAX_BET), 2)

# =============================================================================
# CHAIN BALANCES
# =============================================================================

def _rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    last_err = None
    for rpc_url in POLYGON_RPC_URLS:
        try:
            r = requests.post(rpc_url, json=payload, timeout=(5, 10))
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result"), rpc_url
        except Exception as e:
            last_err = f"{rpc_url}: {e}"
    raise RuntimeError(last_err or "all RPC endpoints failed")

def _is_valid_eth_address(addr):
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42

def _erc20_balance_raw(wallet, token):
    # ERC-20 balanceOf(address): 0x70a08231 + 32-byte padded address
    calldata = "0x70a08231" + wallet.lower().replace("0x", "").rjust(64, "0")
    result, rpc_url = _rpc_call("eth_call", [{"to": token, "data": calldata}, "latest"])
    return int(result, 16), rpc_url

def _native_balance_raw(wallet):
    result, rpc_url = _rpc_call("eth_getBalance", [wallet, "latest"])
    return int(result, 16), rpc_url

def print_wallet_balance():
    print(f"\n{'='*55}")
    print("  WEATHERBET — WALLET")
    print(f"{'='*55}")
    print(f"  RPCs:      {len(POLYGON_RPC_URLS)} configured")

    if not _is_valid_eth_address(WALLET_ADDRESS):
        print("  Wallet:    missing/invalid")
        print("  Set PROXY_KEY or WALLET_ADDRESS in environment.")
        print(f"{'='*55}\n")
        return

    print(f"  Wallet:    {WALLET_ADDRESS}")
    try:
        pol_raw, rpc_url = _native_balance_raw(WALLET_ADDRESS)
        usdc_pos_raw, _ = _erc20_balance_raw(WALLET_ADDRESS, TOKEN_USDC_POS)
        usdc_native_raw, _ = _erc20_balance_raw(WALLET_ADDRESS, TOKEN_USDC_NATIVE)
        print(f"  RPC used:  {rpc_url}")
        print(f"  POL:       {pol_raw / 1e18:,.6f}")
        print(f"  USDC PoS:  {usdc_pos_raw / 1e6:,.6f}")
        print(f"  USDC:      {usdc_native_raw / 1e6:,.6f}")
    except Exception as e:
        print(f"  Error:     {e}")

    print(f"{'='*55}\n")

# =============================================================================
# CALIBRATION
# =============================================================================

_cal: dict = {}

def load_cal():
    if CALIBRATION_FILE.exists():
        return json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    return {}

def get_sigma(city_slug, source="ecmwf", product_kind=DEFAULT_PRODUCT_KIND):
    key = f"{product_kind}_{city_slug}_{source}"
    if key in _cal:
        return _cal[key]["sigma"]
    return SIGMA_F if LOCATIONS[city_slug]["unit"] == "F" else SIGMA_C

def run_calibration(markets):
    """Recalculates sigma from resolved markets."""
    resolved = [m for m in markets if m.get("status") == "resolved" and m.get("actual_temp") is not None]
    cal = load_cal()
    updated = []

    for source in ["ecmwf", "hrrr", "metar"]:
        for city in set(m["city"] for m in resolved):
            for product_kind in PRODUCT_KIND_LIST:
                group = [m for m in resolved if m["city"] == city and m.get("product_kind", DEFAULT_PRODUCT_KIND) == product_kind]
                if not group:
                    continue
                errors = []
                for m in group:
                    snap = None
                    for candidate in reversed(m.get("forecast_snapshots", [])):
                        if source == "ecmwf" and candidate.get("ecmwf") is not None:
                            snap = candidate.get("ecmwf")
                            break
                        if source == "hrrr" and candidate.get("hrrr") is not None:
                            snap = candidate.get("hrrr")
                            break
                        if source == "metar" and candidate.get("metar") is not None:
                            snap = candidate.get("metar")
                            break
                    if snap is not None and m.get("actual_temp") is not None:
                        errors.append(abs(float(snap) - float(m["actual_temp"])))
                if len(errors) < CALIBRATION_MIN:
                    continue
                mae  = sum(errors) / len(errors)
                key  = f"{product_kind}_{city}_{source}"
                old  = cal.get(key, {}).get("sigma", SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C)
                new  = round(mae, 3)
                cal[key] = {"sigma": new, "n": len(errors), "updated_at": datetime.now(timezone.utc).isoformat()}
                if abs(new - old) > 0.05:
                    updated.append(f"{LOCATIONS[city]['name']} [{product_kind}] {source}: {old:.2f}->{new:.2f}")

    CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    if updated:
        print(f"  [CAL] {', '.join(updated)}")
    return cal

# =============================================================================
# FORECASTS
# =============================================================================

def get_ecmwf(city_slug, dates, product_kind=DEFAULT_PRODUCT_KIND):
    """ECMWF via Open-Meteo with bias correction. For all cities."""
    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    variable = TEMPERATURE_PRODUCTS[product_kind]["forecast_variable"]
    result = {}
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily={variable}&temperature_unit={temp_unit}"
        f"&forecast_days=7&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        f"&models=ecmwf_ifs025&bias_correction=true"
    )
    _trace_scan(f"[ECMWF] {city_slug}/{product_kind}: requesting {len(dates)}d forecast")
    for attempt in range(FORECAST_ATTEMPTS):
        try:
            started = time.time()
            data = requests.get(url, timeout=(5, 10)).json()
            if SCAN_TRACE:
                _trace_scan(f"[ECMWF] {city_slug}/{product_kind}: request ok in {time.time()-started:.2f}s (attempt {attempt+1})")
            if "error" not in data:
                for date, temp in zip(data["daily"]["time"], data["daily"][variable]):
                    if date in dates and temp is not None:
                        result[date] = round(temp, 1) if unit == "C" else round(temp)
            break
        except Exception as e:
            _trace_scan(f"[ECMWF] {city_slug}/{product_kind}: attempt {attempt+1} failed: {e}")
            if attempt < FORECAST_ATTEMPTS - 1:
                time.sleep(FORECAST_RETRY_SECONDS)
            else:
                print(f"  [ECMWF] {city_slug}: {e}")
    return result

def get_hrrr(city_slug, dates, product_kind=DEFAULT_PRODUCT_KIND):
    """HRRR via Open-Meteo. US cities only, up to 48h horizon."""
    loc = LOCATIONS[city_slug]
    if loc["region"] != "us":
        return {}
    result = {}
    variable = TEMPERATURE_PRODUCTS[product_kind]["forecast_variable"]
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily={variable}&temperature_unit=fahrenheit"
        f"&forecast_days=3&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        f"&models=gfs_seamless"  # HRRR+GFS seamless — best option for US
    )
    _trace_scan(f"[HRRR] {city_slug}/{product_kind}: requesting {len(dates)}d forecast")
    for attempt in range(FORECAST_ATTEMPTS):
        try:
            started = time.time()
            data = requests.get(url, timeout=(5, 10)).json()
            if SCAN_TRACE:
                _trace_scan(f"[HRRR] {city_slug}/{product_kind}: request ok in {time.time()-started:.2f}s (attempt {attempt+1})")
            if "error" not in data:
                for date, temp in zip(data["daily"]["time"], data["daily"][variable]):
                    if date in dates and temp is not None:
                        result[date] = round(temp)
            break
        except Exception as e:
            _trace_scan(f"[HRRR] {city_slug}/{product_kind}: attempt {attempt+1} failed: {e}")
            if attempt < FORECAST_ATTEMPTS - 1:
                time.sleep(FORECAST_RETRY_SECONDS)
            else:
                print(f"  [HRRR] {city_slug}: {e}")
    return result

def get_metar(city_slug):
    """Current observed temperature from METAR station. D+0 only."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    try:
        _trace_scan(f"[METAR] {city_slug}: requesting station {station}")
        started = time.time()
        url = f"https://aviationweather.gov/api/data/metar?ids={station}&format=json"
        data = requests.get(url, timeout=(5, 8)).json()
        if SCAN_TRACE:
            _trace_scan(f"[METAR] {city_slug}: done in {time.time()-started:.2f}s")
        if data and isinstance(data, list):
            temp_c = data[0].get("temp")
            if temp_c is not None:
                if unit == "F":
                    return round(float(temp_c) * 9/5 + 32)
                return round(float(temp_c), 1)
    except Exception as e:
        print(f"  [METAR] {city_slug}: {e}")
    return None

def get_actual_temp(city_slug, date_str, product_kind=DEFAULT_PRODUCT_KIND):
    """Actual temperature via Visual Crossing for closed markets."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    temp_element = TEMPERATURE_PRODUCTS[product_kind]["resolution_element"]
    vc_unit = "us" if unit == "F" else "metric"
    url = (
        f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
        f"/{station}/{date_str}/{date_str}"
        f"?unitGroup={vc_unit}&key={VC_KEY}&include=days&elements={temp_element}"
    )
    try:
        _trace_scan(f"[VC] {city_slug} {date_str}: requesting actual temp ({product_kind})")
        started = time.time()
        data = requests.get(url, timeout=(5, 8)).json()
        if SCAN_TRACE:
            _trace_scan(f"[VC] {city_slug} {date_str}: done in {time.time()-started:.2f}s")
        days = data.get("days", [])
        if days and days[0].get(temp_element) is not None:
            return round(float(days[0][temp_element]), 1)
    except Exception as e:
        print(f"  [VC] {city_slug} {date_str}: {e}")
    return None

def check_market_resolved(market_id):
    """
    Checks if the market closed on Polymarket and who won.
    Returns: None (still open), True (YES won), False (NO won)
    """
    try:
        _trace_scan(f"[RESOLVE] checking market {market_id}")
        started = time.time()
        data = get_gamma_json(
            f"https://gamma-api.polymarket.com/markets/{market_id}",
            timeout=(5, 8),
            label=f"RESOLVE {market_id}",
        )
        if SCAN_TRACE:
            _trace_scan(f"[RESOLVE] market {market_id}: response in {time.time()-started:.2f}s")
        closed = data.get("closed", False)
        if not closed:
            return None
        # Check YES price — if ~1.0 then WIN, if ~0.0 then LOSS
        prices = json.loads(data.get("outcomePrices", "[0.5,0.5]"))
        yes_price = float(prices[0])
        if yes_price >= 0.95:
            return True   # WIN
        elif yes_price <= 0.05:
            return False  # LOSS
        return None  # not yet determined
    except Exception as e:
        print(f"  [RESOLVE] {market_id}: {e}")
    return None

# =============================================================================
# POLYMARKET
# =============================================================================

def get_polymarket_event(city_slug, month, day, year, product_kind=DEFAULT_PRODUCT_KIND):
    prefix = TEMPERATURE_PRODUCTS[product_kind]["slug_prefix"]
    slug = f"{prefix}-{city_slug}-on-{month}-{day}-{year}"
    try:
        _trace_scan(f"[EVENT] {city_slug}/{product_kind} slug {slug}")
        started = time.time()
        data = get_gamma_json(
            f"https://gamma-api.polymarket.com/events?slug={slug}",
            timeout=(5, 8),
            label=f"EVENT {city_slug}/{product_kind}",
        )
        if SCAN_TRACE:
            _trace_scan(f"[EVENT] {city_slug}/{product_kind} done in {time.time()-started:.2f}s")
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
    except Exception:
        pass
    return None

def get_market_price(market_id):
    try:
        data = get_gamma_json(
            f"https://gamma-api.polymarket.com/markets/{market_id}",
            timeout=(3, 5),
            label=f"PRICE {market_id}",
        )
        prices = json.loads(data.get("outcomePrices", "[0.5,0.5]"))
        return float(prices[0])
    except Exception:
        return None

def parse_temp_range(question):
    if not question: return None
    num = r'(-?\d+(?:\.\d+)?)'
    if re.search(r'or below', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or below', question, re.IGNORECASE)
        if m: return (-999.0, float(m.group(1)))
    if re.search(r'or higher', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or higher', question, re.IGNORECASE)
        if m: return (float(m.group(1)), 999.0)
    m = re.search(r'between ' + num + r'-' + num + r'[°]?[FC]', question, re.IGNORECASE)
    if m: return (float(m.group(1)), float(m.group(2)))
    m = re.search(r'be ' + num + r'[°]?[FC] on', question, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return (v, v)
    return None

def hours_to_resolution(end_date_str):
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return 999.0

def in_bucket(forecast, t_low, t_high):
    if t_low == t_high:
        return round(float(forecast)) == round(t_low)
    return t_low <= float(forecast) <= t_high

# =============================================================================
# MARKET DATA STORAGE
# Each market is stored as: data/markets/{product}_{city}_{date}.json
# =============================================================================

def market_path(city_slug, date_str, product_kind=DEFAULT_PRODUCT_KIND):
    return MARKETS_DIR / f"{product_kind}_{city_slug}_{date_str}.json"

def load_market(city_slug, date_str, product_kind=DEFAULT_PRODUCT_KIND):
    p = market_path(city_slug, date_str, product_kind)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    legacy_p = MARKETS_DIR / f"{city_slug}_{date_str}.json"
    if legacy_p.exists():
        data = json.loads(legacy_p.read_text(encoding="utf-8"))
        data["product_kind"] = DEFAULT_PRODUCT_KIND
        return data
    return None

def save_market(market):
    product_kind = market.get("product_kind", DEFAULT_PRODUCT_KIND)
    p = market_path(market["city"], market["date"], product_kind)
    p.write_text(json.dumps(market, indent=2, ensure_ascii=False), encoding="utf-8")

def load_all_markets():
    markets = []
    for f in MARKETS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["product_kind"] = data.get("product_kind", DEFAULT_PRODUCT_KIND)
            markets.append(data)
        except Exception:
            pass
    return markets

def new_market(city_slug, date_str, event, hours, product_kind=DEFAULT_PRODUCT_KIND):
    loc = LOCATIONS[city_slug]
    return {
        "product_kind":       product_kind,
        "city":               city_slug,
        "city_name":          loc["name"],
        "date":               date_str,
        "unit":               loc["unit"],
        "station":            loc["station"],
        "event_slug":         event.get("slug"),
        "resolution_element": TEMPERATURE_PRODUCTS[product_kind]["resolution_element"],
        "event_end_date":     event.get("endDate", ""),
        "hours_at_discovery": round(hours, 1),
        "status":             "open",           # open | closed | resolved
        "position":           None,             # filled when position opens
        "actual_temp":        None,             # filled after resolution
        "resolved_outcome":   None,             # win / loss / no_position
        "pnl":                None,
        "forecast_snapshots": [],               # list of forecast snapshots
        "market_snapshots":   [],               # list of market price snapshots
        "all_outcomes":       [],               # all market buckets
        "created_at":         datetime.now(timezone.utc).isoformat(),
    }

# =============================================================================
# STATE (balance and open positions)
# =============================================================================

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "balance":          BALANCE,
        "starting_balance": BALANCE,
        "total_trades":     0,
        "wins":             0,
        "losses":           0,
        "peak_balance":     BALANCE,
    }

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# =============================================================================
# CORE LOGIC
# =============================================================================

def take_forecast_snapshot(city_slug, dates, product_kind=DEFAULT_PRODUCT_KIND):
    """Fetches forecasts from all sources and returns a snapshot."""
    now_str = datetime.now(timezone.utc).isoformat()
    ecmwf   = get_ecmwf(city_slug, dates, product_kind=product_kind)
    hrrr    = get_hrrr(city_slug, dates, product_kind=product_kind)
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snapshots = {}
    for date in dates:
        metar_value = get_metar(city_slug) if product_kind == DEFAULT_PRODUCT_KIND and date == today else None
        snap = {
            "ts":    now_str,
            "ecmwf": ecmwf.get(date),
            "hrrr":  hrrr.get(date) if date <= (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d") else None,
            "metar": metar_value,
            "product_kind": product_kind,
        }
        # Best forecast: HRRR for US D+0/D+1, otherwise ECMWF
        loc = LOCATIONS[city_slug]
        if loc["region"] == "us" and snap["hrrr"] is not None:
            snap["best"] = snap["hrrr"]
            snap["best_source"] = "hrrr"
        elif snap["ecmwf"] is not None:
            snap["best"] = snap["ecmwf"]
            snap["best_source"] = "ecmwf"
        else:
            snap["best"] = None
            snap["best_source"] = None
        snapshots[date] = snap
    return snapshots

def scan_and_update():
    """Main function of one cycle: updates forecasts, opens/closes positions."""
    global _cal
    now      = datetime.now(timezone.utc)
    state    = load_state()
    balance  = state["balance"]
    new_pos  = 0
    closed   = 0
    resolved = 0

    for city_slug, loc in LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']}...", end=" ", flush=True)
        _trace_scan(f"{loc['name']} scan start")

        dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(4)]

        for product_kind in PRODUCT_KIND_LIST:
            _trace_scan(f"[{loc['name']}] {product_kind}: forecast snapshot")
            try:
                snapshots = take_forecast_snapshot(city_slug, dates, product_kind=product_kind)
                time.sleep(0.3)
            except Exception as e:
                print(f"  [{product_kind}] skipped ({e})")
                continue

            for i, date in enumerate(dates):
                try:
                    dt    = datetime.strptime(date, "%Y-%m-%d")
                    event = get_polymarket_event(city_slug, MONTHS[dt.month - 1], dt.day, dt.year, product_kind=product_kind)
                    if not event:
                        _trace_scan(f"[{loc['name']}] {product_kind} {date}: no event")
                        continue

                    end_date = event.get("endDate", "")
                    hours    = hours_to_resolution(end_date) if end_date else 0
                    horizon  = f"D+{i}"

                    # Load or create market record
                    mkt = load_market(city_slug, date, product_kind=product_kind)
                    if mkt is None or mkt.get("product_kind", DEFAULT_PRODUCT_KIND) != product_kind:
                        if hours < MIN_HOURS or hours > MAX_HOURS:
                            continue
                        mkt = new_market(city_slug, date, event, hours, product_kind=product_kind)

                    # Skip if market already resolved
                    if mkt["status"] == "resolved":
                        continue

                    # Update outcomes list — prices taken directly from event
                    outcomes = []
                    for market in event.get("markets", []):
                        question = market.get("question", "")
                        mid      = str(market.get("id", ""))
                        volume   = float(market.get("volume", 0))
                        rng      = parse_temp_range(question)
                        if not rng:
                            continue
                        try:
                            prices = json.loads(market.get("outcomePrices", "[0.5,0.5]"))
                            bid = float(prices[0])
                            ask = float(prices[1]) if len(prices) > 1 else bid
                        except Exception:
                            continue
                        outcomes.append({
                            "question":  question,
                            "market_id": mid,
                            "range":     rng,
                            "bid":       round(bid, 4),
                            "ask":       round(ask, 4),
                            "price":     round(bid, 4),   # for compatibility
                            "spread":    round(ask - bid, 4),
                            "volume":    round(volume, 0),
                        })

                    outcomes.sort(key=lambda x: x["range"][0])
                    mkt["all_outcomes"] = outcomes

                    # Forecast snapshot
                    snap = snapshots.get(date, {})
                    forecast_snap = {
                        "ts":           snap.get("ts"),
                        "horizon":      horizon,
                        "hours_left":   round(hours, 1),
                        "ecmwf":        snap.get("ecmwf"),
                        "hrrr":         snap.get("hrrr"),
                        "metar":        snap.get("metar"),
                        "best":         snap.get("best"),
                        "best_source":  snap.get("best_source"),
                        "product_kind": product_kind,
                    }
                    mkt["forecast_snapshots"].append(forecast_snap)

                    # Market price snapshot
                    top = max(outcomes, key=lambda x: x["price"]) if outcomes else None
                    market_snap = {
                        "ts":       snap.get("ts"),
                        "top_bucket": f"{top['range'][0]}-{top['range'][1]}{unit_sym}" if top else None,
                        "top_price":  top["price"] if top else None,
                    }
                    mkt["market_snapshots"].append(market_snap)

                    forecast_temp = snap.get("best")
                    best_source   = snap.get("best_source")

                    # --- STOP-LOSS AND TRAILING STOP ---
                    if mkt.get("position") and mkt["position"].get("status") == "open":
                        pos = mkt["position"]
                        current_price = None
                        for o in outcomes:
                            if o["market_id"] == pos["market_id"]:
                                current_price = o["price"]
                                break

                        if current_price is not None:
                            current_price = o.get("bid", current_price)  # sell at bid
                            entry = pos["entry_price"]
                            stop  = pos.get("stop_price", entry * 0.80)  # 20% stop by default

                            # Trailing: if up 20%+ — move stop to breakeven
                            if current_price >= entry * 1.20 and stop < entry:
                                pos["stop_price"] = entry
                                pos["trailing_activated"] = True

                            # Check stop
                            # Stop is conditional on forecast: only close if price hit stop AND forecast is out of bucket
                            forecast_invalid = forecast_temp is None or not in_bucket(forecast_temp, pos["bucket_low"], pos["bucket_high"])
                            if current_price <= stop and forecast_invalid:
                                live_sell_ok = True
                                actual_shares = pos["shares"]
                                actual_price = current_price
                                if LIVE_TRADING:
                                    sell_result = place_live_sell(pos.get("token_id"), current_price, pos["shares"])
                                    if sell_result and isinstance(sell_result, tuple):
                                        actual_shares, actual_price = sell_result
                                    else:
                                        live_sell_ok = bool(sell_result)
                                if live_sell_ok:
                                    proceeds = actual_shares * actual_price
                                    pnl = round(proceeds - pos["cost"], 2)
                                    balance += proceeds
                                    pos["closed_at"]    = snap.get("ts")
                                    pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
                                    pos["exit_price"]   = actual_price
                                    pos["sold_shares"]  = actual_shares
                                    pos["pnl"]          = pnl
                                    pos["status"]       = "closed"
                                    closed += 1
                                    reason = "STOP" if current_price < entry else "TRAILING BE"
                                    print(f"  [{reason}] {loc['name']} [{product_kind}] {date} | entry ${entry:.3f} exit ${actual_price:.3f} | sold {actual_shares} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
                                else:
                                    print(f"  [LIVE ERR] Stop close not recorded for {loc['name']} [{product_kind}] {date}")

                    # --- CLOSE POSITION if forecast shifted 2+ degrees ---
                    if mkt.get("position") and mkt["position"].get("status") == "open" and forecast_temp is not None:
                        pos = mkt["position"]
                        old_bucket_low  = pos["bucket_low"]
                        old_bucket_high = pos["bucket_high"]
                        # 2-degree buffer — avoid closing on small forecast fluctuations
                        buffer = 2.0 if unit == "F" else 1.0
                        mid_bucket = (old_bucket_low + old_bucket_high) / 2 if old_bucket_low != -999 and old_bucket_high != 999 else forecast_temp
                        forecast_far = abs(forecast_temp - mid_bucket) > (abs(mid_bucket - old_bucket_low) + buffer)
                        if not in_bucket(forecast_temp, old_bucket_low, old_bucket_high) and forecast_far:
                            current_price = None
                            for o in outcomes:
                                if o["market_id"] == pos["market_id"]:
                                    current_price = o["price"]
                                    break
                            if current_price is not None:
                                live_sell_ok = True
                                actual_shares = pos["shares"]
                                actual_price = current_price
                                if LIVE_TRADING:
                                    sell_result = place_live_sell(pos.get("token_id"), current_price, pos["shares"])
                                    if sell_result and isinstance(sell_result, tuple):
                                        actual_shares, actual_price = sell_result
                                    else:
                                        live_sell_ok = bool(sell_result)
                                if live_sell_ok:
                                    proceeds = actual_shares * actual_price
                                    pnl = round(proceeds - pos["cost"], 2)
                                    balance += proceeds
                                    mkt["position"]["closed_at"]    = snap.get("ts")
                                    mkt["position"]["close_reason"] = "forecast_changed"
                                    mkt["position"]["exit_price"]   = actual_price
                                    mkt["position"]["sold_shares"]  = actual_shares
                                    mkt["position"]["pnl"]          = pnl
                                    mkt["position"]["status"]       = "closed"
                                    closed += 1
                                    print(f"  [CLOSE] {loc['name']} [{product_kind}] {date} — forecast changed | sold {actual_shares} @ ${actual_price:.3f} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
                                else:
                                    print(f"  [LIVE ERR] Forecast-change close not recorded for {loc['name']} [{product_kind}] {date}")

                    # --- CLOSE POSITION if market top bucket has diverged for 12+ hours ---
                    if mkt.get("position") and outcomes and mkt["position"].get("status") == "open":
                        pos = mkt["position"]
                        my_bucket = (pos["bucket_low"], pos["bucket_high"])
                        top = max(outcomes, key=lambda x: x["price"])
                        top_bucket = (top["range"][0], top["range"][1])
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if my_bucket != top_bucket:
                            if not pos.get("top_divergence_start"):
                                pos["top_divergence_start"] = now_iso
                            else:
                                started = datetime.fromisoformat(pos["top_divergence_start"])
                                hours_diverged = (datetime.now(timezone.utc) - started).total_seconds() / 3600
                                if hours_diverged >= 12.0:
                                    current_price = None
                                    for o in outcomes:
                                        if o["market_id"] == pos["market_id"]:
                                            current_price = o.get("bid", o["price"])
                                            break
                                    if current_price is not None:
                                        live_sell_ok = True
                                        actual_shares = pos["shares"]
                                        actual_price = current_price
                                        if LIVE_TRADING:
                                            sell_result = place_live_sell(pos.get("token_id"), current_price, pos["shares"])
                                            if sell_result and isinstance(sell_result, tuple):
                                                actual_shares, actual_price = sell_result
                                            else:
                                                live_sell_ok = bool(sell_result)
                                        if live_sell_ok:
                                            proceeds = actual_shares * actual_price
                                            pnl = round(proceeds - pos["cost"], 2)
                                            balance += proceeds
                                            pos["closed_at"]    = snap.get("ts")
                                            pos["close_reason"] = "market_diverged_12h"
                                            pos["exit_price"]   = actual_price
                                            pos["sold_shares"]  = actual_shares
                                            pos["pnl"]          = pnl
                                            pos["status"]       = "closed"
                                            closed += 1
                                            print(f"  [DIVERGED] {loc['name']} [{product_kind}] {date} — market top {int(top_bucket[0])}-{int(top_bucket[1])} ≠ mine {int(my_bucket[0])}-{int(my_bucket[1])} for {hours_diverged:.1f}h | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
                                        else:
                                            print(f"  [LIVE ERR] Divergence close not recorded for {loc['name']} [{product_kind}] {date}")
                        else:
                            if pos.get("top_divergence_start"):
                                pos["top_divergence_start"] = None

                    # --- OPEN POSITION ---
                    # Cooldown: if a position was closed in this market within the last 6h,
                    # skip re-opening to avoid forecast-oscillation ping-pong.
                    cooldown_ok = True
                    prev = mkt.get("position")
                    if prev and prev.get("status") == "closed" and prev.get("closed_at"):
                        try:
                            closed_at = datetime.fromisoformat(prev["closed_at"])
                            hours_since_close = (datetime.now(timezone.utc) - closed_at).total_seconds() / 3600
                            if hours_since_close < 6.0:
                                cooldown_ok = False
                        except Exception:
                            pass
                    can_open = (not mkt.get("position") or (mkt.get("position", {}).get("status") == "closed" and cooldown_ok))
                    if can_open and forecast_temp is not None and hours >= MIN_HOURS:
                        sigma = get_sigma(city_slug, best_source or "ecmwf", product_kind=product_kind)
                        best_signal = None

                        # Find exactly ONE bucket that matches the forecast
                        # If forecast doesn't fit any bucket cleanly — skip this market
                        matched_bucket = None
                        for o in outcomes:
                            t_low, t_high = o["range"]
                            if in_bucket(forecast_temp, t_low, t_high):
                                matched_bucket = o
                                break

                        if matched_bucket:
                            o = matched_bucket
                            t_low, t_high = o["range"]
                            volume = o["volume"]
                            bid    = o.get("bid", o["price"])
                            ask    = o.get("ask", o["price"])
                            spread = o.get("spread", 0)

                            # All filters — if any fails, skip this market entirely
                            if volume >= MIN_VOLUME:
                                p  = bucket_prob(forecast_temp, t_low, t_high, sigma)
                                ev = calc_ev(p, ask)
                                if ev >= MIN_EV:
                                    kelly = calc_kelly(p, ask)
                                    size  = bet_size(kelly, balance)
                                    if size >= 0.50:
                                        best_signal = {
                                            "market_id":    o["market_id"],
                                            "question":     o["question"],
                                            "bucket_low":   t_low,
                                            "bucket_high":  t_high,
                                            "entry_price":  ask,
                                            "bid_at_entry": bid,
                                            "spread":       spread,
                                            "shares":       round(size / ask, 2),
                                            "cost":         size,
                                            "p":            round(p, 4),
                                            "ev":           round(ev, 4),
                                            "kelly":        round(kelly, 4),
                                            "forecast_temp":forecast_temp,
                                            "forecast_src": best_source,
                                            "sigma":        sigma,
                                            "forecast_product": product_kind,
                                            "opened_at":    snap.get("ts"),
                                            "status":       "open",
                                            "pnl":          None,
                                            "exit_price":   None,
                                            "close_reason": None,
                                            "closed_at":    None,
                                        }

                        if best_signal:
                            _trace_scan(f"[{loc['name']}] {product_kind} {date}: candidate bucket {best_signal['bucket_low']}-{best_signal['bucket_high']}{unit_sym}")
                            # Fetch real bestAsk from Polymarket API for accurate entry price
                            skip_position = False
                            try:
                                _trace_scan(f"[{loc['name']}] {product_kind} {date}: refreshing entry market {best_signal['market_id']}")
                                mdata = get_gamma_json(
                                    f"https://gamma-api.polymarket.com/markets/{best_signal['market_id']}",
                                    timeout=(3, 5),
                                    label=f"ENTRY {best_signal['market_id']}",
                                )
                                real_ask = float(mdata.get("bestAsk", best_signal["entry_price"]))
                                real_bid = float(mdata.get("bestBid", best_signal["bid_at_entry"]))
                                real_spread = round(real_ask - real_bid, 4)
                                # Re-check slippage and price with real values
                                if real_spread > MAX_SLIPPAGE or real_ask >= MAX_PRICE:
                                    print(f"  [SKIP] {loc['name']} [{product_kind}] {date} — real ask ${real_ask:.3f} spread ${real_spread:.3f}")
                                    skip_position = True
                                else:
                                    best_signal["entry_price"]  = real_ask
                                    best_signal["bid_at_entry"] = real_bid
                                    best_signal["spread"]       = real_spread
                                    best_signal["shares"]       = round(best_signal["cost"] / real_ask, 2)
                                    best_signal["ev"]           = round(calc_ev(best_signal["p"], real_ask), 4)
                                    clob_ids = json.loads(mdata.get("clobTokenIds", "[]"))
                                    best_signal["token_id"] = clob_ids[0] if clob_ids else None
                            except Exception as e:
                                print(f"  [WARN] Could not fetch real ask for {best_signal['market_id']}: {e}")

                            if not skip_position and best_signal["entry_price"] < MAX_PRICE:
                                if LIVE_TRADING:
                                    result = place_live_buy(best_signal.get("token_id"), best_signal["entry_price"], best_signal["cost"])
                                    if not result:
                                        print(f"  [LIVE ERR] Buy failed — skipping position")
                                        skip_position = True
                                    elif isinstance(result, (int, float)) and not isinstance(result, bool):
                                        best_signal["shares"] = result  # use real on-chain shares
                            if not skip_position and best_signal["entry_price"] < MAX_PRICE:
                                balance -= best_signal["cost"]
                                mkt["position"] = best_signal
                                state["total_trades"] += 1
                                new_pos += 1
                                bucket_label = f"{best_signal['bucket_low']}-{best_signal['bucket_high']}{unit_sym}"
                                print(f"  [BUY]  {loc['name']} [{product_kind}] {horizon} {date} | {bucket_label} | "
                                      f"${best_signal['entry_price']:.3f} | EV {best_signal['ev']:+.2f} | "
                                      f"${best_signal['cost']:.2f} ({(best_signal['forecast_src'] or product_kind).upper()})")

                    # Market closed by time
                    if hours < 0.5 and mkt["status"] == "open":
                        mkt["status"] = "closed"

                    save_market(mkt)
                    time.sleep(0.1)
                except Exception as e:
                    print(f"  [ERROR] {loc['name']} [{product_kind}] {date}: {e}")

        _trace_scan(f"{loc['name']} scan complete")
        print("ok")

    # --- AUTO-RESOLUTION ---
    open_markets = [
        mkt for mkt in load_all_markets()
        if mkt["status"] != "resolved" and mkt.get("position") and mkt["position"].get("status") == "open"
    ]
    _trace_scan(f"[RESOLVE] {len(open_markets)} open market records")
    for mkt in open_markets:
        _trace_scan(f"[RESOLVE] {mkt.get('city_name')} {mkt['date']} start")
        if mkt["status"] == "resolved":
            continue

        pos = mkt.get("position")
        if not pos or pos.get("status") != "open":
            continue

        market_id = pos.get("market_id")
        if not market_id:
            continue

        # Check if market closed on Polymarket
        _trace_scan(f"[RESOLVE] checking {market_id}")
        won = check_market_resolved(market_id)
        if won is None:
            continue  # market still open

        # Market closed — record result
        product_kind = mkt.get("product_kind", DEFAULT_PRODUCT_KIND)
        _trace_scan(f"[RESOLVE] {mkt.get('city_name')} fetching actual temp ({product_kind})")
        actual_temp = get_actual_temp(mkt["city"], mkt["date"], product_kind=product_kind)
        price  = pos["entry_price"]
        size   = pos["cost"]
        shares = pos["shares"]
        pnl    = round(shares - size, 2) if won else round(-size, 2)

        balance += size + pnl
        pos["exit_price"]   = 1.0 if won else 0.0
        pos["pnl"]          = pnl
        pos["close_reason"] = "resolved"
        pos["closed_at"]    = now.isoformat()
        pos["status"]       = "closed"
        mkt["pnl"]          = pnl
        mkt["actual_temp"]  = actual_temp
        mkt["status"]       = "resolved"
        mkt["resolved_outcome"] = "win" if won else "loss"

        if won:
            state["wins"] += 1
        else:
            state["losses"] += 1

        result = "WIN" if won else "LOSS"
        print(f"  [{result}] [{product_kind.upper()}] {mkt['city_name']} {mkt['date']} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
        resolved += 1

        save_market(mkt)
        time.sleep(0.3)

    state["balance"]      = round(balance, 2)
    state["peak_balance"] = max(state.get("peak_balance", balance), balance)
    save_state(state)

    # Run calibration if enough data collected
    all_mkts = load_all_markets()
    resolved_count = len([m for m in all_mkts if m["status"] == "resolved"])
    if resolved_count >= CALIBRATION_MIN:
        global _cal
        _cal = run_calibration(all_mkts)

    return new_pos, closed, resolved

# =============================================================================
# REPORT
# =============================================================================

def print_status():
    state    = load_state()
    markets  = load_all_markets()
    open_pos = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
    resolved = [m for m in markets if m["status"] == "resolved" and m.get("pnl") is not None]

    bal     = state["balance"]
    start   = state["starting_balance"]
    ret_pct = (bal - start) / start * 100
    wins    = state["wins"]
    losses  = state["losses"]
    total   = wins + losses

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STATUS")
    print(f"{'='*55}")
    print(f"  Balance:     ${bal:,.2f}  (start ${start:,.2f}, {'+'if ret_pct>=0 else ''}{ret_pct:.1f}%)")
    print(f"  Trades:      {total} | W: {wins} | L: {losses} | WR: {wins/total:.0%}" if total else "  No trades yet")
    print(f"  Open:        {len(open_pos)}")
    print(f"  Resolved:    {len(resolved)}")

    if open_pos:
        print(f"\n  Open positions:")
        total_unrealized = 0.0
        for m in open_pos:
            pos      = m["position"]
            unit_sym = "F" if m["unit"] == "F" else "C"
            label    = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"
            product  = m.get("product_kind", DEFAULT_PRODUCT_KIND)

            # Current price from latest market snapshot
            current_price = pos["entry_price"]
            snaps = m.get("market_snapshots", [])
            if snaps:
                # Find our bucket price in all_outcomes
                for o in m.get("all_outcomes", []):
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

            unrealized = round((current_price - pos["entry_price"]) * pos["shares"], 2)
            total_unrealized += unrealized
            pnl_str = f"{'+'if unrealized>=0 else ''}{unrealized:.2f}"

            print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | "
                  f"entry ${pos['entry_price']:.3f} -> ${current_price:.3f} | "
                  f"PnL: {pnl_str} | {product.upper()} | {pos['forecast_src'].upper()}")

        sign = "+" if total_unrealized >= 0 else ""
        print(f"\n  Unrealized PnL: {sign}{total_unrealized:.2f}")

    print(f"{'='*55}\n")

def print_report():
    markets  = load_all_markets()
    resolved = [m for m in markets if m["status"] == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — FULL REPORT")
    print(f"{'='*55}")

    if not resolved:
        print("  No resolved markets yet.")
        return

    total_pnl = sum(m["pnl"] for m in resolved)
    wins      = [m for m in resolved if m["resolved_outcome"] == "win"]
    losses    = [m for m in resolved if m["resolved_outcome"] == "loss"]

    print(f"\n  Total resolved: {len(resolved)}")
    print(f"  Wins:           {len(wins)} | Losses: {len(losses)}")
    print(f"  Win rate:       {len(wins)/len(resolved):.0%}")
    print(f"  Total PnL:      {'+'if total_pnl>=0 else ''}{total_pnl:.2f}")

    print(f"\n  By city:")
    for city in sorted(set(m["city"] for m in resolved)):
        group = [m for m in resolved if m["city"] == city]
        w     = len([m for m in group if m["resolved_outcome"] == "win"])
        pnl   = sum(m["pnl"] for m in group)
        name  = LOCATIONS[city]["name"]
        print(f"    {name:<16} {w}/{len(group)} ({w/len(group):.0%})  PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")

    print(f"\n  By product:")
    for product_kind in PRODUCT_KIND_LIST:
        group = [m for m in resolved if m.get("product_kind", DEFAULT_PRODUCT_KIND) == product_kind]
        w     = len([m for m in group if m["resolved_outcome"] == "win"])
        pnl   = sum(m["pnl"] for m in group)
        product_label = product_kind.upper()
        if len(group) > 0:
            rate = f"{w/len(group):.0%}"
            line = f"{w}/{len(group)}"
        else:
            rate = "n/a"
            line = "0/0"
        print(f"    {product_label:<8} {line} ({rate})  PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")

    print(f"\n  Market details:")
    for m in sorted(resolved, key=lambda x: x["date"]):
        pos      = m.get("position", {})
        unit_sym = "F" if m["unit"] == "F" else "C"
        snaps    = m.get("forecast_snapshots", [])
        first_fc = snaps[0]["best"] if snaps else None
        last_fc  = snaps[-1]["best"] if snaps else None
        label    = f"{pos.get('bucket_low')}-{pos.get('bucket_high')}{unit_sym}" if pos else "no position"
        result   = m["resolved_outcome"].upper()
        pnl_str  = f"{'+'if m['pnl']>=0 else ''}{m['pnl']:.2f}" if m["pnl"] is not None else "-"
        fc_str   = f"forecast {first_fc}->{last_fc}{unit_sym}" if first_fc else "no forecast"
        actual   = f"actual {m['actual_temp']}{unit_sym}" if m["actual_temp"] else ""
        product  = m.get("product_kind", DEFAULT_PRODUCT_KIND).upper()
        print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | {fc_str} | {actual} | {product} {result} {pnl_str}")

    print(f"{'='*55}\n")

# =============================================================================
# MAIN LOOP
# =============================================================================

MONITOR_INTERVAL = 600  # monitor positions every 10 minutes

def monitor_positions():
    """Quick stop check on open positions without full scan."""
    markets  = load_all_markets()
    open_pos = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
    if not open_pos:
        return 0

    state   = load_state()
    balance = state["balance"]
    closed  = 0

    for mkt in open_pos:
        pos = mkt["position"]
        mid = pos["market_id"]

        # Fetch real bestBid from Polymarket API — actual sell price
        current_price = None
        try:
            mdata = get_gamma_json(
                f"https://gamma-api.polymarket.com/markets/{mid}",
                timeout=(3, 5),
                label=f"MONITOR {mid}",
            )
            best_bid = mdata.get("bestBid")
            if best_bid is not None:
                current_price = float(best_bid)
        except Exception:
            pass

        # Fallback to cached price if API failed
        if current_price is None:
            for o in mkt.get("all_outcomes", []):
                if o["market_id"] == mid:
                    current_price = o.get("bid", o["price"])
                    break

        if current_price is None:
            continue

        entry = pos["entry_price"]
        stop  = pos.get("stop_price", entry * 0.80)
        city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])

        # Hours left to resolution
        end_date = mkt.get("event_end_date", "")
        hours_left = hours_to_resolution(end_date) if end_date else 999.0

        # Take-profit threshold based on hours to resolution
        if hours_left < 24:
            take_profit = None        # hold to resolution
        elif hours_left < 48:
            take_profit = 0.85        # 24-48h: take profit at $0.85
        else:
            take_profit = 0.75        # 48h+: take profit at $0.75

        # Trailing: if up 20%+ — move stop to breakeven
        if current_price >= entry * 1.20 and stop < entry:
            pos["stop_price"] = entry
            pos["trailing_activated"] = True
            print(f"  [TRAILING] {city_name} {mkt['date']} — stop moved to breakeven ${entry:.3f}")

        # Check take-profit
        take_triggered = take_profit is not None and current_price >= take_profit
        # Check stop — only if forecast also says we're out of bucket
        snaps = mkt.get("forecast_snapshots", [])
        latest_forecast = snaps[-1].get("best") if snaps else None
        forecast_invalid = latest_forecast is None or not in_bucket(latest_forecast, pos["bucket_low"], pos["bucket_high"])
        stop_triggered = current_price <= stop and forecast_invalid

        if take_triggered or stop_triggered:
            live_sell_ok = True
            actual_shares = pos["shares"]
            actual_price = current_price
            if LIVE_TRADING:
                sell_result = place_live_sell(pos.get("token_id"), current_price, pos["shares"])
                if sell_result and isinstance(sell_result, tuple):
                    actual_shares, actual_price = sell_result
                else:
                    live_sell_ok = bool(sell_result)
            if not live_sell_ok:
                print(f"  [LIVE ERR] Monitor close not recorded for {city_name} {mkt['date']}")
                continue

            if take_triggered:
                reason = "TAKE"
            elif current_price < entry:
                reason = "STOP"
            else:
                reason = "TRAILING BE"
            proceeds = actual_shares * actual_price
            pnl = round(proceeds - pos["cost"], 2)
            balance += proceeds
            pos["closed_at"]    = datetime.now(timezone.utc).isoformat()
            pos["close_reason"] = {
                "TAKE": "take_profit",
                "STOP": "stop_loss",
                "TRAILING BE": "trailing_stop",
            }[reason]
            pos["exit_price"]   = actual_price
            pos["sold_shares"]  = actual_shares
            pos["pnl"]          = pnl
            pos["status"]       = "closed"
            closed += 1
            print(f"  [{reason}] {city_name} {mkt['date']} | entry ${entry:.3f} exit ${actual_price:.3f} | sold {actual_shares} | {hours_left:.0f}h left | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
            save_market(mkt)

    if closed:
        state["balance"] = round(balance, 2)
        save_state(state)
        print(f"  balance: ${state['balance']:,.2f}")

    return closed


def run_loop():
    global _cal
    _cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STARTING")
    print(f"{'='*55}")
    print(f"  Cities:     {len(LOCATIONS)}")
    print(f"  Balance:    ${BALANCE:,.0f} | Max bet: ${MAX_BET}")
    print(f"  Scan:       {SCAN_INTERVAL//60} min | Monitor: {MONITOR_INTERVAL//60} min")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Mode:       {'LIVE' if LIVE_TRADING else 'PAPER'}")
    print(f"  Data:       {DATA_DIR.resolve()}")
    print(f"  Ctrl+C to stop\n")

    last_full_scan = 0

    while True:
        now_ts  = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Full scan once per hour
        if now_ts - last_full_scan >= SCAN_INTERVAL:
            print(f"[{now_str}] full scan...")
            try:
                new_pos, closed, resolved = scan_and_update()
                state = load_state()
                print(f"  balance: ${state['balance']:,.2f} | "
                      f"new: {new_pos} | closed: {closed} | resolved: {resolved}")
                last_full_scan = time.time()
            except KeyboardInterrupt:
                print(f"\n  Stopping — saving state...")
                save_state(load_state())
                print(f"  Done. Bye!")
                break
            except requests.exceptions.ConnectionError:
                print(f"  Connection lost — waiting 60 sec")
                time.sleep(60)
                continue
            except Exception as e:
                print(f"  Error: {e} — waiting 60 sec")
                time.sleep(60)
                continue
        else:
            # Quick stop monitoring
            print(f"[{now_str}] monitoring positions...")
            try:
                stopped = monitor_positions()
                if stopped:
                    state = load_state()
                    print(f"  balance: ${state['balance']:,.2f}")
            except Exception as e:
                print(f"  Monitor error: {e}")

        try:
            time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n  Stopping — saving state...")
            save_state(load_state())
            print(f"  Done. Bye!")
            break

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run_loop()
    elif cmd == "status":
        _cal = load_cal()
        print_status()
    elif cmd == "report":
        _cal = load_cal()
        print_report()
    elif cmd == "wallet":
        print_wallet_balance()
    elif cmd == "livecheck":
        print_live_check()
    else:
        print("Usage: python weatherbet.py [run|status|report|wallet|livecheck]")
