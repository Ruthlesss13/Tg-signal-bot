# -*- coding: utf-8 -*-
# Version 4.1.0

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import ssl
import sys
import time
import urllib.request
import urllib.error
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set

import ccxt
import jdatetime
import pandas as pd
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===========================
# کتابخانه‌های اختیاری
# ===========================
try:
    import mplfinance as mpf
    MPLFINANCE_AVAILABLE = True
except ImportError:
    mpf = None
    MPLFINANCE_AVAILABLE = False

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    pytz = None
    PYTZ_AVAILABLE = False

# ===========================
# نسخه‌گذاری
# ===========================
VERSION = "4.1.0"
BUILD_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
START_TIME = time.time()

try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN_TZ = None

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("signal_bot")

# ===========================
# تنظیمات (Config)
# ===========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
# پشتیبانی از هر دو نام متغیر برای سازگاری
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
# مهم: پیش‌فرض دیتابیس هم داخل DATA_DIR قرار می‌گیرد تا اگر یک Volume
# پایدار (مثلاً روی Railway) روی DATA_DIR مانت شده باشد، دیتابیس و تنظیمات
# هر دو با آن حفظ شوند و با ریست/ری‌دیپلوی از بین نروند.
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "cryptobot.sqlite3"))
logger.info(f"📁 DATA_DIR={os.path.abspath(DATA_DIR)} | DB_PATH={os.path.abspath(DB_PATH)}")

# لیست ۳۰ ارز
COIN_CODES = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "ADA", "DOGE", "AVAX", "LINK", "DOT",
    "NEAR", "SUI", "APT", "ARB", "OP",
    "POL", "UNI", "LTC", "BCH", "ATOM",
    "SHIB", "PEPE", "FET", "RENDER", "INJ",
    "TIA", "WIF", "FLOKI", "SEI", "RUNE"
]

# تنظیمات فیوچرز
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
RSI_MIN = 35
RSI_MAX = 65
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ATR_PERIOD = 14
VOLUME_MA_PERIOD = 20
STRUCTURE_LOOKBACK = 20
ADX_PERIOD = 14
ADX_RANGE_THRESHOLD = 20
ADX_TREND_MIN = 24
ADX_STRONG = 30
VOLUME_MIN_RATIO = 0.95
VOLUME_STRONG = 1.5
MIN_SIGNAL_SCORE = 66
RSI_LONG_MIN = 52
RSI_LONG_MAX = 65
RSI_SHORT_MIN = 35
RSI_SHORT_MAX = 48
RSI_OVERBOUGHT = 68
RSI_OVERSOLD = 32
PULLBACK_ATR_TOLERANCE = 0.80
BREAKOUT_VOLUME_MIN = 1.20
MIN_DI_GAP = 1.0
MAX_ENTRY_DISTANCE_ATR = 1.50
FUNDING_RATE_MAX_FOR_LONG = 0.0005
NEWS_BLACKOUT_MINUTES = 30
LOW_VOLUME_UTC_START_HOUR = 23
LOW_VOLUME_UTC_END_HOUR = 1
FEAR_GREED_EXTREME_FEAR = 25
FEAR_GREED_EXTREME_GREED = 75
FEAR_GREED_TTL_SECONDS = 3600
HIGH_IMPORTANCE_NEWS_KEYWORDS = [
    "FOMC", "CPI", "NFP", "SEC", "unlock", "Fed", "rate decision", "interest rate",
]
MAX_LEVERAGE = 3
MIN_LEVERAGE = 2
RISK_PER_TRADE_PCT = 1.0
ATR_STOP_MULTIPLIER = 1.5
MIN_RISK_REWARD = 2.0
MAX_CONCURRENT_POSITIONS = 3
OHLCV_LIMIT = 300
MAIN_TF = "1h"
HIGHER_TF = "4h"
PRICE_TTL_SECONDS = 30
IRT_RATE_TTL_SECONDS = 60
SIGNAL_SCAN_INTERVAL_SECONDS = 5 * 60   # اسکن هر ۵ دقیقه — به‌موقع‌تر
SIGNAL_REOPEN_COOLDOWN_SECONDS = 45 * 60
REVERSE_SIGNAL_COOLDOWN_SECONDS = 5 * 60  # بعد از باطل شدن به‌خاطر تغییر روند
CHANNEL_MONITOR_INTERVAL_SECONDS = 60  # پایش هر دقیقه؛ نتیجه بر اساس کندل ۱ دقیقه‌ای ثبت می‌شود
MONITOR_TIMEFRAME = "1m"
MONITOR_CANDLE_LIMIT = 120
AI_TIMEOUT_SECONDS = 30
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")  # مدل تست‌شده روی سرور Railway
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
import threading
_AI_THREAD_LOCK = threading.Lock()  # جلوگیری از 429 با فراخوانی همزمان
CROSS_LOOKBACK = 4  # تقاطع در چند کندل اخیر معتبر است

# ===========================
# تنظیمات ارسال سیگنال
# کانال: پیش‌فرض فعال | ربات/ادمین: پیش‌فرض غیرفعال
# ===========================
SEND_TO_CHANNEL = True
SEND_TO_ADMIN = False

# ===========================
# کش برای سرعت بخشیدن
# ===========================
_analysis_cache = {}
_cache_ttl = 60

# ===========================
# ابزارهای تاریخ و قیمت
# ===========================
def shamsi_now() -> str:
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M:%S")

def fmt_usd(value: float) -> str:
    if value is None:
        return "-"
    if value >= 1:
        return f"${value:,.4f}".rstrip("0").rstrip(".")
    return f"${value:.10f}".rstrip("0").rstrip(".")

def fmt_toman(usd_value: float, rate: float) -> str:
    """نمایش تومان با دقت مناسب برای ارزهای خیلی ارزان (مثل PEPE/FLOKI)."""
    if usd_value is None or rate is None:
        return "-"
    try:
        toman = float(usd_value) * float(rate)
    except (TypeError, ValueError):
        return "-"
    if toman >= 10000:
        return f"{toman:,.0f} تومان"
    if toman >= 100:
        return f"{toman:,.1f} تومان"
    if toman >= 1:
        return f"{toman:,.2f} تومان"
    if toman >= 0.01:
        return f"{toman:.4f} تومان"
    if toman >= 0.0001:
        return f"{toman:.6f} تومان"
    # ارزهای میکرو: تا ۱۰ رقم اعشار معنی‌دار
    s = f"{toman:.10f}".rstrip("0").rstrip(".")
    return (s if s else "0") + " تومان"

def format_duration_since(started_ts: Optional[float]) -> str:
    """مدت زمان سپری‌شده از باز شدن سیگنال تا الان، به‌صورت خوانا (روز/ساعت/دقیقه)"""
    if not started_ts:
        return "نامشخص"
    seconds = max(0, time.time() - started_ts)
    total_minutes = int(seconds // 60)
    days = total_minutes // 1440
    hours = (total_minutes % 1440) // 60
    minutes = total_minutes % 60
    parts = []
    if days > 0:
        parts.append(f"{days} روز")
    if hours > 0 or days > 0:
        parts.append(f"{hours} ساعت")
    parts.append(f"{minutes} دقیقه")
    return " و ".join(parts)

def format_percent(value: float) -> str:
    if value is None:
        return "نامشخص"
    return f"{value:+.2f}%"

def safe_float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)

def _to_float(val, default=None):
    """تبدیل امن به float — برای funding و فیلدهای API که گاهی رشته‌اند"""
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default

def safe_str(value) -> str:
    if value is None:
        return "نامشخص"
    return str(value)

def safe_format_float(value, format_str: str = ".4f") -> str:
    val = safe_float(value)
    return f"{val:{format_str}}"

def safe_format_percent(value) -> str:
    if value is None:
        return "نامشخص"
    return f"{value:.4%}"

# ===========================
# صرافی‌ها
# ===========================
exchange_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

exchange_mexc = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 8000,
    "headers": exchange_headers,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    }
})

exchange_gate = ccxt.gate({
    "enableRateLimit": True,
    "timeout": 8000,
    "headers": exchange_headers,
    "options": {"defaultType": "swap"}
})

# ===========================
# ابزارهای urllib برای درخواست‌های HTTP
# ===========================
_ssl_ctx = ssl._create_unverified_context()

def http_get_json(url: str, timeout: int = 8) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_ssl_ctx) as response:
            data = response.read().decode()
            return json.loads(data)
    except Exception as e:
        logger.warning(f"HTTP GET failed for {url}: {e}")
        return {}

def http_post_json(url: str, payload: dict, timeout: int = 90) -> dict:
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as response:
            resp_data = response.read().decode()
            return json.loads(resp_data)
    except Exception as e:
        logger.warning(f"HTTP POST failed for {url}: {e}")
        return {}

# ===========================
# دریافت داده‌های فیوچرز (با urllib)
# ===========================
def fetch_futures_data_mexc(symbol: str) -> dict:
    url = f"https://api.mexc.com/api/v1/contract/ticker?symbol={symbol}"
    data = http_get_json(url, timeout=5)
    if data.get("success") and data.get("data"):
        d = data["data"]
        return {
            "last_price": d.get("lastPrice"),
            "funding_rate": d.get("fundingRate"),
            "open_interest": d.get("holdVol"),
            "high_24h": d.get("high24Price"),
            "low_24h": d.get("lower24Price"),
            "volume_24h": d.get("volume24"),
        }
    return {}

def fetch_futures_data_gateio(symbol: str) -> dict:
    url = f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={symbol}"
    data = http_get_json(url, timeout=5)
    if data and isinstance(data, list) and len(data) > 0:
        d = data[0]
        return {
            "last_price": d.get("last"),
            "funding_rate": d.get("funding_rate"),
            "open_interest": d.get("open_interest"),
            "high_24h": d.get("high_24h"),
            "low_24h": d.get("low_24h"),
            "volume_24h": d.get("volume_24h"),
        }
    return {}

def get_futures_data(code: str) -> dict:
    symbol = f"{code}_USDT"
    data = fetch_futures_data_mexc(symbol)
    if data.get("last_price") is not None:
        data["exchange"] = "MEXC"
    else:
        data = fetch_futures_data_gateio(symbol)
        if data.get("last_price") is not None:
            data["exchange"] = "Gate.io"
        else:
            return {"exchange": "نامشخص", "last_price": None}
    data["last_price"] = _to_float(data.get("last_price"))
    data["funding_rate"] = _to_float(data.get("funding_rate"))
    data["open_interest"] = _to_float(data.get("open_interest"))
    data["high_24h"] = _to_float(data.get("high_24h"))
    data["low_24h"] = _to_float(data.get("low_24h"))
    data["volume_24h"] = _to_float(data.get("volume_24h"))
    return data

# ===========================
# نرخ تومان (با urllib)
# ===========================
_irt_rate_cache = {"value": None, "ts": 0.0, "last_success": None}

def fetch_irt_rate_sync() -> float:
    now = time.time()
    if _irt_rate_cache["value"] and (now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS):
        return _irt_rate_cache["value"]
    url = "https://api.wallex.ir/v1/markets"
    data = http_get_json(url, timeout=5)
    try:
        rate = float(data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])
        _irt_rate_cache.update(value=rate, ts=now, last_success=shamsi_now())
        return rate
    except (KeyError, ValueError, TypeError):
        logger.warning("Failed to parse IRT rate from Wallex")
        return _irt_rate_cache["value"] or 65000.0

async def fetch_irt_rate() -> float:
    return await asyncio.to_thread(fetch_irt_rate_sync)

def get_irt_rate_status() -> str:
    if _irt_rate_cache["value"]:
        return f"✅ آنلاین (آخرین: {_irt_rate_cache['last_success']})"
    return "🔴 آفلاین"

# ===========================
# شاخص ترس و طمع (با urllib)
# ===========================
_fg_cache = {"value": None, "ts": 0.0, "last_update": None}

def fetch_fear_greed_index_sync() -> Optional[int]:
    now = time.time()
    if _fg_cache["value"] is not None and now - _fg_cache["ts"] < FEAR_GREED_TTL_SECONDS:
        return _fg_cache["value"]
    
    url = "https://api.alternative.me/fng/"
    data = http_get_json(url, timeout=5)
    try:
        value = int(data["data"][0]["value"])
        _fg_cache.update(value=value, ts=now, last_update=shamsi_now())
        return value
    except (KeyError, ValueError, TypeError):
        logger.warning("Failed to parse Fear&Greed index")
        return _fg_cache["value"]

def get_fear_greed_index() -> Optional[int]:
    return fetch_fear_greed_index_sync()

def get_fg_status() -> str:
    if _fg_cache["value"] is not None:
        return f"✅ آخرین مقدار: {_fg_cache['value']} ({_fg_cache['last_update']})"
    return "🔴 در دسترس نیست"

def get_fg_text() -> str:
    fg = get_fear_greed_index()
    if fg is None:
        return "نامشخص"
    if fg <= 25:
        return f"{fg} (ترس شدید 😨)"
    elif fg <= 45:
        return f"{fg} (ترس 😰)"
    elif fg <= 55:
        return f"{fg} (خنثی 😐)"
    elif fg <= 75:
        return f"{fg} (طمع 😊)"
    else:
        return f"{fg} (طمع شدید 🤑)"

# ===========================
# دیتابیس
# ===========================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    targets TEXT NOT NULL,
    leverage INTEGER NOT NULL,
    risk_reward REAL NOT NULL,
    ai_confirmed INTEGER NOT NULL DEFAULT 0,
    ai_raw_text TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    channel_message_id INTEGER,
    highest_tp_hit INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL,
    closed_ts REAL,
    setup_type TEXT DEFAULT '',
    features_json TEXT DEFAULT '',
    postmortem TEXT DEFAULT '',
    market_exchange TEXT DEFAULT '',
    last_checked_candle_ts INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS channel_messages (
    ticker TEXT PRIMARY KEY,
    signal_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    setup_type TEXT DEFAULT '',
    result TEXT NOT NULL,
    entry_rsi REAL,
    entry_adx REAL,
    entry_vol REAL,
    entry_score REAL,
    had_bos INTEGER DEFAULT 0,
    duration_sec REAL,
    lesson TEXT,
    created_ts REAL NOT NULL
);
"""

@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)
        cols = [r[1] for r in c.execute("PRAGMA table_info(signals)").fetchall()]
        for col, decl in (
            ("setup_type", "TEXT DEFAULT ''"),
            ("features_json", "TEXT DEFAULT ''"),
            ("postmortem", "TEXT DEFAULT ''"),
            ("market_exchange", "TEXT DEFAULT ''"),
            ("last_checked_candle_ts", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                try:
                    c.execute(f"ALTER TABLE signals ADD COLUMN {col} {decl}")
                except Exception as e:
                    logger.warning(f"migrate {col}: {e}")
    normalize_experiences()

def normalize_experiences():
    """یک تجربه نهایی برای هر سیگنال نگه می‌دارد تا نرخ برد واقعی بماند."""
    with _conn() as c:
        closed = c.execute(
            "SELECT id, status FROM signals WHERE status IN ('tp3','sl','invalidated')"
        ).fetchall()
        for row in closed:
            sid = row["id"]
            status = row["status"]
            if status == "invalidated":
                c.execute("DELETE FROM experiences WHERE signal_id=?", (sid,))
                continue
            result = "win" if status == "tp3" else "loss"
            exp = c.execute(
                "SELECT id FROM experiences WHERE signal_id=? ORDER BY created_ts DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if exp:
                c.execute("UPDATE experiences SET result=? WHERE id=?", (result, exp["id"]))
                c.execute(
                    "DELETE FROM experiences WHERE signal_id=? AND id<>?",
                    (sid, exp["id"]),
                )
            else:
                # برای سیگنال‌های قدیمی بدون تجربه، از داده خود سیگنال تجربه نهایی نمی‌سازیم.
                pass
        c.execute("DELETE FROM experiences WHERE result NOT IN ('win','loss') AND signal_id IS NULL")

def record_signal(ticker, direction, entry, stop_loss, targets, leverage, risk_reward, ai_confirmed, ai_raw_text, setup_type: str = "", features: Optional[dict] = None, market_exchange: str = "") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO signals (ticker, direction, entry, stop_loss, targets, leverage, risk_reward, ai_confirmed, ai_raw_text, created_ts, setup_type, features_json, market_exchange, last_checked_candle_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticker, direction, entry, stop_loss, json.dumps(targets), leverage, risk_reward,
                int(ai_confirmed), ai_raw_text, time.time(), setup_type or "",
                json.dumps(features or {}, ensure_ascii=False),
                market_exchange or "",
                int(time.time() // 60) * 60000 - 60000,
            ),
        )
        return cur.lastrowid

def save_experience(signal_id: int, ticker: str, direction: str, setup_type: str, result: str,
                    features: dict, duration_sec: float, lesson: str) -> None:
    """فقط نتیجه نهایی معامله را ثبت می‌کند؛ هدف‌های میانی تجربه جداگانه نیستند."""
    result = "win" if result in ("win", "tp3") else "loss"
    with _conn() as c:
        exists = c.execute(
            "SELECT id FROM experiences WHERE signal_id=? LIMIT 1", (signal_id,)
        ).fetchone()
        values = (
            ticker, direction, setup_type or "", result,
            _to_float(features.get("rsi")), _to_float(features.get("adx")),
            _to_float(features.get("vol")), _to_float(features.get("score")),
            1 if features.get("had_bos") else 0, duration_sec, lesson, time.time(),
        )
        if exists:
            c.execute(
                "UPDATE experiences SET ticker=?, direction=?, setup_type=?, result=?, entry_rsi=?, entry_adx=?, entry_vol=?, entry_score=?, had_bos=?, duration_sec=?, lesson=?, created_ts=? WHERE id=?",
                values + (exists["id"],),
            )
        else:
            c.execute(
                "INSERT INTO experiences (signal_id, ticker, direction, setup_type, result, entry_rsi, entry_adx, entry_vol, entry_score, had_bos, duration_sec, lesson, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (signal_id,) + values,
            )
        c.execute("UPDATE signals SET postmortem=? WHERE id=?", (lesson, signal_id))

def estimate_success_from_history(direction: str, setup_type: str, rsi: float, adx: float, vol: float, had_bos: bool) -> dict:
    """برآورد ساده از روی تجربه‌های قبلی — برای اعتماد یا احتیاط روی سیگنال جدید."""
    with _conn() as c:
        rows = c.execute(
            "SELECT result, entry_rsi, entry_adx, entry_vol, had_bos, setup_type, direction FROM experiences "
            "WHERE direction=? ORDER BY created_ts DESC LIMIT 80"
        ).fetchall()
    if not rows:
        return {"pct": None, "sample": 0, "wins": 0, "losses": 0, "note": "هنوز تجربه کافی ثبت نشده"}

    def _similar(r) -> bool:
        score = 0
        if (r["setup_type"] or "") == (setup_type or ""):
            score += 2
        if r["entry_rsi"] is not None and abs(float(r["entry_rsi"]) - rsi) <= 8:
            score += 2
        if r["entry_adx"] is not None and abs(float(r["entry_adx"]) - adx) <= 8:
            score += 1
        if r["entry_vol"] is not None and abs(float(r["entry_vol"]) - vol) <= 0.4:
            score += 1
        if bool(r["had_bos"]) == bool(had_bos):
            score += 1
        return score >= 3

    similar = [r for r in rows if _similar(r)]
    pool = similar if len(similar) >= 3 else list(rows)
    wins = sum(1 for r in pool if r["result"] == "win")
    losses = sum(1 for r in pool if r["result"] == "loss")
    closed = wins + losses
    if closed < 3:
        return {"pct": None, "sample": closed, "wins": wins, "losses": losses, "note": "نمونه مشابه کم است"}
    pct = round(wins / closed * 100)
    if pct >= 60:
        note = "تاریخچه مشابه نسبتاً مثبت — اعتماد بیشتر منطقی است"
    elif pct >= 45:
        note = "تاریخچه مشابه متوسط — با حجم کمتر وارد شو"
    else:
        note = "تاریخچه مشابه ضعیف — احتیاط یا رد منطقی است"
    return {"pct": pct, "sample": closed, "wins": wins, "losses": losses, "note": note, "similar": len(similar)}

def build_postmortem(direction: str, result: str, features: dict, duration_sec: float, price: float, entry: float) -> str:
    """درس کوتاه بعد از بسته شدن — قابل استفاده برای اعتماد بعدی."""
    rsi = _to_float(features.get("rsi"), 0) or 0
    adx = _to_float(features.get("adx"), 0) or 0
    vol = _to_float(features.get("vol"), 0) or 0
    bos = features.get("had_bos")
    move = ((price - entry) / entry * 100) if entry else 0
    if direction == "short":
        move = -move
    hours = duration_sec / 3600 if duration_sec else 0
    parts = []
    if result in ("sl", "loss"):
        parts.append("حد ضرر فعال شد")
        if direction == "short" and rsi >= 48:
            parts.append("RSI نزدیک خنثی بود و شورت روی مومنتوم ضعیف بود")
        if direction == "long" and rsi <= 52:
            parts.append("RSI نزدیک خنثی بود و لانگ روی مومنتوم ضعیف بود")
        if direction == "short" and rsi < RSI_OVERSOLD + 3:
            parts.append("ورود نزدیک اشباع فروش احتمال برگشت را بالا برد")
        if direction == "long" and rsi > RSI_OVERBOUGHT - 3:
            parts.append("ورود نزدیک اشباع خرید احتمال اصلاح را بالا برد")
        if adx < 26:
            parts.append("ADX پایین بود و روند استحکام کافی نداشت")
        if vol < 1.0:
            parts.append("حجم زیر میانگین بود")
        if not bos:
            parts.append("بدون تأیید شکست ساختار وارد شده بود")
        if hours < 2:
            parts.append("خروج سریع؛ احتمالاً نویز کوتاه‌مدت")
    else:
        parts.append("هدف لمس شد")
        if bos:
            parts.append("وجود ساختار به نفع معامله بود")
        if adx >= 28:
            parts.append("ADX قوی روند را حمایت کرد")
        if vol >= 1.2:
            parts.append("حجم خوب ورود را تأیید کرد")
        if (direction == "long" and RSI_LONG_MIN <= rsi <= RSI_LONG_MAX) or (direction == "short" and RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX):
            parts.append("RSI داخل بازه مناسب بود")
    if not parts:
        parts.append("نتیجه ثبت شد")
    lesson = "؛ ".join(parts)
    return f"{lesson} | حرکت تقریبی {move:+.2f}% در {hours:.1f} ساعت"

def update_signal_status(signal_id: int, status: str):
    with _conn() as c:
        c.execute("UPDATE signals SET status=?, closed_ts=? WHERE id=?", (status, time.time() if status != "open" else None, signal_id))

def update_signal_progress(signal_id: int, highest_tp_hit: int, new_stop_loss: float):
    with _conn() as c:
        c.execute("UPDATE signals SET highest_tp_hit=?, stop_loss=? WHERE id=?", (highest_tp_hit, new_stop_loss, signal_id))

def update_monitor_candle(signal_id: int, candle_ts_ms: int):
    with _conn() as c:
        c.execute("UPDATE signals SET last_checked_candle_ts=? WHERE id=?", (int(candle_ts_ms), signal_id))

def open_positions_count() -> int:
    with _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='open'").fetchone()
        return row["n"]

def open_signals() -> list:
    with _conn() as c:
        return c.execute("SELECT * FROM signals WHERE status='open' ORDER BY created_ts DESC").fetchall()

def get_open_signal_for_ticker(ticker: str):
    with _conn() as c:
        return c.execute("SELECT * FROM signals WHERE ticker=? AND status='open' ORDER BY created_ts DESC LIMIT 1", (ticker,)).fetchone()

def get_last_closed_ts(ticker: str) -> Optional[float]:
    with _conn() as c:
        row = c.execute("SELECT MAX(closed_ts) AS ts FROM signals WHERE ticker=? AND status IN ('tp3','sl','invalidated')", (ticker,)).fetchone()
        return row["ts"] if row and row["ts"] is not None else None

def set_channel_thread(ticker: str, signal_id: int, message_id: int, content_hash: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO channel_messages (ticker, signal_id, message_id, content_hash) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET signal_id=excluded.signal_id, message_id=excluded.message_id, content_hash=excluded.content_hash",
            (ticker, signal_id, message_id, content_hash)
        )

def get_channel_thread(ticker: str):
    with _conn() as c:
        return c.execute("SELECT * FROM channel_messages WHERE ticker=?", (ticker,)).fetchone()

def clear_channel_thread(ticker: str):
    with _conn() as c:
        c.execute("DELETE FROM channel_messages WHERE ticker=?", (ticker,))

def set_channel_message_id(signal_id: int, message_id: int):
    with _conn() as c:
        c.execute("UPDATE signals SET channel_message_id=? WHERE id=?", (message_id, signal_id))

def get_db_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        open_count = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='open'").fetchone()["n"]
        tp1 = c.execute("SELECT COUNT(*) AS n FROM signals WHERE highest_tp_hit>=1").fetchone()["n"]
        tp2 = c.execute("SELECT COUNT(*) AS n FROM signals WHERE highest_tp_hit>=2").fetchone()["n"]
        tp3 = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='tp3'").fetchone()["n"]
        sl = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='sl'").fetchone()["n"]
        return {"total": total, "open": open_count, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl}

init_db()

# ===========================
# وضعیت ارسال سیگنال (فایل + دیتابیس برای ماندگاری بعد از ریست)
# ===========================
SIGNAL_SETTINGS_FILE = os.path.join(DATA_DIR, "signal_settings.json")

def _ensure_settings_table(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

def load_signal_settings():
    global SEND_TO_CHANNEL, SEND_TO_ADMIN
    # ۱) از فایل
    try:
        if os.path.exists(SIGNAL_SETTINGS_FILE):
            with open(SIGNAL_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                SEND_TO_CHANNEL = bool(data.get("send_to_channel", True))
                SEND_TO_ADMIN = bool(data.get("send_to_admin", False))
                logger.info(f"✅ تنظیمات ارسال سیگنال از فایل بارگذاری شد: {data}")
                return
    except Exception as e:
        logger.warning(f"Error loading signal settings from file: {e}")
    # ۲) از دیتابیس (مقاوم‌تر روی Railway)
    try:
        with _conn() as c:
            _ensure_settings_table(c)
            row = c.execute("SELECT value FROM bot_settings WHERE key='signal_settings'").fetchone()
            if row:
                data = json.loads(row["value"])
                SEND_TO_CHANNEL = bool(data.get("send_to_channel", True))
                SEND_TO_ADMIN = bool(data.get("send_to_admin", False))
                logger.info(f"✅ تنظیمات ارسال سیگنال از دیتابیس بارگذاری شد: {data}")
            else:
                logger.info("ℹ️ هیچ تنظیمات ذخیره‌شده‌ای پیدا نشد — پیش‌فرض: کانال=فعال، ربات=غیرفعال")
    except Exception as e:
        logger.warning(f"Error loading signal settings from DB: {e}")

def save_signal_settings():
    data = {"send_to_channel": SEND_TO_CHANNEL, "send_to_admin": SEND_TO_ADMIN}
    ok_file, ok_db = False, False
    # فایل
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SIGNAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        ok_file = True
    except Exception as e:
        logger.warning(f"Error saving signal settings to file: {e}")
    # دیتابیس
    try:
        with _conn() as c:
            _ensure_settings_table(c)
            c.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
                ("signal_settings", json.dumps(data)),
            )
        ok_db = True
    except Exception as e:
        logger.warning(f"Error saving signal settings to DB: {e}")
    if ok_file or ok_db:
        logger.info(f"💾 تنظیمات ارسال سیگنال ذخیره شد (فایل={ok_file}, دیتابیس={ok_db}): {data}")
    else:
        logger.error(
            "❌ ذخیره تنظیمات ارسال سیگنال کاملاً ناموفق بود — احتمالاً DATA_DIR روی یک دیسک "
            "پایدار (Volume) مانت نشده و با هر ری‌استارت/دیپلوی پاک می‌شود."
        )

load_signal_settings()

# ===========================
# کش قیمت (برای OHLCV و لیست قیمت‌ها)
# ===========================
class MarketCache:
    def __init__(self):
        self.prices: Dict[str, float] = {}
        self.last_price_update = 0
        self.active_exchange_name = "MEXC"
        self.exchange_status = {"MEXC": {"online": False, "last_check": 0}, "Gate.io": {"online": False, "last_check": 0}}

    async def update_prices(self) -> Dict[str, float]:
        """به‌روزرسانی قیمت‌ها از بازار فیوچرز (برای لیست قیمت‌ها)"""
        now = time.time()
        if now - self.last_price_update < PRICE_TTL_SECONDS and self.prices:
            return self.prices

        # فقط قراردادهای دائمی؛ قیمت نمایشی نباید از بازار دیگری بیاید.
        symbols_swap = [f"{code}/USDT:USDT" for code in COIN_CODES]
        new_prices = {}

        # ۱. MEXC
        try:
            tickers = await asyncio.to_thread(exchange_mexc.fetch_tickers, symbols_swap)
            for code in COIN_CODES:
                sym = f"{code}/USDT:USDT"
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if new_prices:
                self.active_exchange_name = "MEXC"
                self.exchange_status["MEXC"] = {"online": True, "last_check": now}
                self.prices = new_prices
                self.last_price_update = now
                return self.prices
        except Exception as e:
            logger.warning(f"MEXC fetch_tickers failed: {e}")
            self.exchange_status["MEXC"] = {"online": False, "last_check": now}

        # ۲. Gate.io
        try:
            tickers = await asyncio.to_thread(exchange_gate.fetch_tickers, symbols_swap)
            for code in COIN_CODES:
                sym = f"{code}/USDT:USDT"
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if new_prices:
                self.active_exchange_name = "Gate.io"
                self.exchange_status["Gate.io"] = {"online": True, "last_check": now}
                self.prices = new_prices
                self.last_price_update = now
                return self.prices
        except Exception as e:
            logger.warning(f"Gate.io fetch_tickers failed: {e}")
            self.exchange_status["Gate.io"] = {"online": False, "last_check": now}

        # ۳. Fallback تکی
        async def fetch_one(code):
            for sym in [f"{code}/USDT:USDT"]:
                try:
                    ticker = await asyncio.to_thread(exchange_mexc.fetch_ticker, sym)
                    if ticker and ticker.get("last") is not None:
                        return code, float(ticker["last"])
                except:
                    pass
                try:
                    ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, sym)
                    if ticker and ticker.get("last") is not None:
                        return code, float(ticker["last"])
                except:
                    pass
            return code, None

        missing_codes = [code for code in COIN_CODES if code not in new_prices]
        if missing_codes:
            tasks = [fetch_one(code) for code in missing_codes]
            results = await asyncio.gather(*tasks)
            for code, price in results:
                if price is not None:
                    new_prices[code] = price

        if new_prices:
            self.prices = new_prices
            self.last_price_update = now
        return self.prices

    async def get_ohlcv(self, code: str, timeframe: str = "1h", preferred_exchange: Optional[str] = None) -> Optional[pd.DataFrame]:
        """دریافت کندل فقط از قرارداد دائمی همان صرافی مرجع قیمت."""
        exchanges = []
        if preferred_exchange == "MEXC":
            exchanges = [(exchange_mexc, "MEXC")]
        elif preferred_exchange == "Gate.io":
            exchanges = [(exchange_gate, "Gate.io")]
        else:
            exchanges = [(exchange_mexc, "MEXC"), (exchange_gate, "Gate.io")]
        symbol = f"{code}/USDT:USDT"
        for exchange, name in exchanges:
            try:
                raw = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, limit=OHLCV_LIMIT)
                if raw:
                    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col])
                    return df
            except Exception as e:
                logger.debug(f"{name} OHLCV failed for {symbol}: {e}")
        logger.warning(f"OHLCV قرارداد دائمی برای {code} در صرافی مرجع در دسترس نیست")
        return None

    async def get_monitor_candles(self, code: str, preferred_exchange: str, since_ms: int) -> Optional[pd.DataFrame]:
        """کندل‌های ۱ دقیقه‌ای بسته‌شده برای تشخیص دقیق ترتیب برخورد با سطوح."""
        exchange = exchange_mexc if preferred_exchange == "MEXC" else exchange_gate
        symbol = f"{code}/USDT:USDT"
        try:
            raw = await asyncio.to_thread(
                exchange.fetch_ohlcv, symbol, MONITOR_TIMEFRAME, since=max(0, int(since_ms)), limit=MONITOR_CANDLE_LIMIT
            )
            if not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            # کندل جاری هنوز بسته نشده و نباید برای نتیجه‌گیری استفاده شود.
            current_minute_ms = (int(time.time() * 1000) // 60000) * 60000
            df = df[df["timestamp"] < current_minute_ms].copy()
            return df
        except Exception as e:
            logger.debug(f"{preferred_exchange} monitor candles failed for {symbol}: {e}")
            return None

cache = MarketCache()

def get_exchange_status_text() -> str:
    status = []
    for name, data in cache.exchange_status.items():
        if data["online"]:
            status.append(f"🟢 {name}")
        else:
            status.append(f"🔴 {name}")
    return "\n".join(status)

# ===========================
# اندیکاتورها
# ===========================
@dataclass
class IndicatorSnapshot:
    trend_up: bool; trend_down: bool; ema_cross_up: bool; ema_cross_down: bool
    rsi: float; rsi_in_zone: bool; macd_cross_up: bool; macd_cross_down: bool
    atr: float; volume_ratio: float; structure_breakout_up: bool; structure_breakout_down: bool
    structure_level: float; edge_reversal_up: bool; edge_reversal_down: bool; adx: float; close: float
    ema_fast: float=0.0; ema_slow: float=0.0; plus_di: float=0.0; minus_di: float=0.0; macd_hist: float=0.0
    rsi_slope: float=0.0; adx_slope: float=0.0; recent_high: float=0.0; recent_low: float=0.0
    swing_high: float=0.0; swing_low: float=0.0; bullish_candle: bool=False; bearish_candle: bool=False
    lower_high: bool=False; higher_low: bool=False; bos_up: bool=False; bos_down: bool=False
    retest_long: bool=False; retest_short: bool=False; distance_to_ema_atr: float=0.0; bb_width: float=0.0
    regime: str="unknown"

def compute_indicators(df: pd.DataFrame) -> Optional[IndicatorSnapshot]:
    if df is None or len(df) < max(EMA_SLOW,VOLUME_MA_PERIOD,STRUCTURE_LOOKBACK)+20: return None
    df=df.copy().reset_index(drop=True); close,high,low,volume=df.close,df.high,df.low,df.volume
    ef=EMAIndicator(close,window=EMA_FAST).ema_indicator(); es=EMAIndicator(close,window=EMA_SLOW).ema_indicator()
    rs=RSIIndicator(close,window=RSI_PERIOD).rsi(); mi=MACD(close,window_fast=MACD_FAST,window_slow=MACD_SLOW,window_sign=MACD_SIGNAL)
    ats=AverageTrueRange(high,low,close,window=ATR_PERIOD).average_true_range(); ai=ADXIndicator(high,low,close,window=ADX_PERIOD)
    ad=ai.adx(); pdi=ai.adx_pos(); mdi=ai.adx_neg(); bb=BollingerBands(close,window=20)
    def cu(a,b,n=CROSS_LOOKBACK): return any(a.iloc[-i-1]<=b.iloc[-i-1] and a.iloc[-i]>b.iloc[-i] for i in range(1,min(n+1,len(a)-1)))
    def cd(a,b,n=CROSS_LOOKBACK): return any(a.iloc[-i-1]>=b.iloc[-i-1] and a.iloc[-i]<b.iloc[-i] for i in range(1,min(n+1,len(a)-1)))
    c=float(close.iloc[-1]); e50=float(ef.iloc[-1]); e200=float(es.iloc[-1]); atr=float(ats.iloc[-1]); r=float(rs.iloc[-1]); ax=float(ad.iloc[-1]); pp=float(pdi.iloc[-1]); mm=float(mdi.iloc[-1]); hist=float(mi.macd_diff().iloc[-1])
    vm=float(volume.rolling(VOLUME_MA_PERIOD).mean().iloc[-1]); vr=float(volume.iloc[-1]/vm) if vm>0 else 0
    rh=float(high.iloc[-STRUCTURE_LOOKBACK-1:-1].max()); rl=float(low.iloc[-STRUCTURE_LOOKBACK-1:-1].min())
    sh=float(high.iloc[-8:-2].max()); sl=float(low.iloc[-8:-2].min()); psh=float(high.iloc[-16:-8].max()); psl=float(low.iloc[-16:-8].min())
    bu=c>rh; bd=c<rl; lh=sh<psh; hl=sl>psl; o=float(df.open.iloc[-1]); h=float(high.iloc[-1]); l=float(low.iloc[-1]); rng=max(h-l,1e-12)
    bull=c>o and (c-l)/rng>=.60; bear=c<o and (h-c)/rng>=.60; nl=abs(c-rl)<=atr*PULLBACK_ATR_TOLERANCE or abs(l-rl)<=atr*PULLBACK_ATR_TOLERANCE; nh=abs(c-rh)<=atr*PULLBACK_ATR_TOLERANCE or abs(h-rh)<=atr*PULLBACK_ATR_TOLERANCE
    trl=(nh and bull and c>e50) or (abs(c-e50)<=atr*PULLBACK_ATR_TOLERANCE and bull and e50>e200); trs=(nl and bear and c<e50) or (abs(c-e50)<=atr*PULLBACK_ATR_TOLERANCE and bear and e50<e200)
    tu=c>e50>e200 and pp>mm; td=c<e50<e200 and mm>pp; rslope=r-float(rs.iloc[-3]); adslope=ax-float(ad.iloc[-3]); dist=abs(c-e50)/atr if atr else 99
    mid=float(bb.bollinger_mavg().iloc[-1]); bw=(float(bb.bollinger_hband().iloc[-1])-float(bb.bollinger_lband().iloc[-1]))/mid if mid else 0
    regime='range' if ax<ADX_RANGE_THRESHOLD else ('strong_trend' if ax>=ADX_STRONG and (tu or td) else 'trend')
    return IndicatorSnapshot(tu,td,cu(ef,es),cd(ef,es),r,RSI_MIN<=r<=RSI_MAX,cu(mi.macd(),mi.macd_signal()),cd(mi.macd(),mi.macd_signal()),atr,vr,bu,bd,rh if bu else rl,nl and bull and not bd,nh and bear and not bu,ax,c,e50,e200,pp,mm,hist,rslope,adslope,rh,rl,sh,sl,bull,bear,lh,hl,bu,bd,trl,trs,dist,bw,regime)

def setup_score(direction: str, m: IndicatorSnapshot, h: IndicatorSnapshot, funding: Optional[float]) -> tuple[int,list[str],list[str]]:
    score=0; reasons=[]; risks=[]
    rsi_ok = (RSI_LONG_MIN <= m.rsi <= RSI_LONG_MAX) if direction == "long" else (RSI_SHORT_MIN <= m.rsi <= RSI_SHORT_MAX)
    macd_ok = (m.macd_hist > 0 and not m.macd_cross_down) if direction == "long" else (m.macd_hist < 0 and not m.macd_cross_up)
    checks=[
        (m.trend_up if direction=='long' else m.trend_down,18,'روند 1H هم‌جهت'),
        (h.trend_up if direction=='long' else h.trend_down,14,'روند 4H هم‌جهت'),
        ((m.plus_di>m.minus_di+MIN_DI_GAP) if direction=='long' else (m.minus_di>m.plus_di+MIN_DI_GAP),10,'DI هم‌جهت'),
        (m.adx>=ADX_TREND_MIN,8,'قدرت روند'),
        ((m.bos_up or m.retest_long) if direction=='long' else (m.bos_down or m.retest_short),18,'ساختار/پولبک تأییدشده'),
        (rsi_ok and ((m.rsi_slope>0) if direction=='long' else (m.rsi_slope<0)),10,'مومنتوم RSI در بازه'),
        (macd_ok,8,'MACD هم‌جهت بدون تقاطع مخالف'),
        (m.volume_ratio>=VOLUME_MIN_RATIO,5,'حجم کافی'),
        (m.volume_ratio>=VOLUME_STRONG,4,'حجم قوی'),
        (m.distance_to_ema_atr<=MAX_ENTRY_DISTANCE_ATR,5,'ورود نزدیک به EMA'),
    ]
    for ok,pts,label in checks:
        if ok: score+=pts; reasons.append(label)
    fr = _to_float(funding, None)
    if fr is not None and ((direction == "short" and fr > 0) or (direction == "long" and fr < 0)):
        score += 2
        reasons.append("فاندینگ به نفع جهت")
    if (direction=='long' and m.rsi>RSI_OVERBOUGHT) or (direction=='short' and m.rsi<RSI_OVERSOLD):
        risks.append('مومنتوم بیش‌ازحد کشیده شده')
    return min(score,100),reasons,risks

# ===========================
# فیلترها
# ===========================
def check_filters(direction: str, indicators: IndicatorSnapshot, code: str, funding_rate: Optional[float]=None, oi: Optional[float]=None) -> tuple[bool,str]:
    if indicators.adx < ADX_TREND_MIN and not (indicators.edge_reversal_up or indicators.edge_reversal_down or indicators.bos_up or indicators.bos_down):
        return False, f"رژیم نامناسب: ADX={indicators.adx:.1f}"
    if indicators.volume_ratio < VOLUME_MIN_RATIO:
        return False, f"حجم ضعیف: {indicators.volume_ratio:.2f}x"
    if oi is not None and oi <= 0:
        return False, "Open Interest معتبر نیست"
    # اشباع خرید/فروش — رد قطعی
    if direction == "long" and indicators.rsi > RSI_OVERBOUGHT:
        return False, f"RSI اشباع خرید ({indicators.rsi:.1f}) — لانگ پرریسک"
    if direction == "short" and indicators.rsi < RSI_OVERSOLD:
        return False, f"RSI اشباع فروش ({indicators.rsi:.1f}) — شورت پرریسک"
    # تقاطع MACD خلاف جهت — رد قطعی
    if direction == "long" and indicators.macd_cross_down:
        return False, "MACD تقاطع نزولی — خلاف لانگ"
    if direction == "short" and indicators.macd_cross_up:
        return False, "MACD تقاطع صعودی — خلاف شورت"
    if direction == "long":
        if not (indicators.trend_up or indicators.bos_up or indicators.retest_long):
            return False, "تأیید ساختاری لانگ وجود ندارد"
        if indicators.minus_di >= indicators.plus_di:
            return False, "DI هنوز صعودی نشده"
        if not (RSI_LONG_MIN <= indicators.rsi <= RSI_LONG_MAX):
            return False, f"RSI خارج از بازه لانگ ({RSI_LONG_MIN}–{RSI_LONG_MAX}): {indicators.rsi:.1f}"
    else:
        if not (indicators.trend_down or indicators.bos_down or indicators.retest_short):
            return False, "تأیید ساختاری شورت وجود ندارد"
        if indicators.plus_di >= indicators.minus_di:
            return False, "DI هنوز نزولی نشده"
        if not (RSI_SHORT_MIN <= indicators.rsi <= RSI_SHORT_MAX):
            return False, f"RSI خارج از بازه شورت ({RSI_SHORT_MIN}–{RSI_SHORT_MAX}): {indicators.rsi:.1f}"
    h = datetime.now(timezone.utc).hour
    if LOW_VOLUME_UTC_START_HOUR <= h or h < LOW_VOLUME_UTC_END_HOUR:
        return False, f"ساعت {h}:00 UTC در بازه کم‌حجم"
    return True, "تمام فیلترهای ساختاری و مومنتوم عبور کردند"

# ===========================
# مدیریت ریسک
# ===========================
@dataclass
class RiskPlan:
    direction: str
    entry: float
    stop_loss: float
    targets: list[float]
    leverage: int
    position_size_usdt: float
    risk_reward: float
    valid: bool
    reason: str

def build_risk_plan(direction: str, entry: float, atr: float, account_balance_usdt: float = 1000.0, structure_target: Optional[float] = None) -> RiskPlan:
    leverage = min(MAX_LEVERAGE, max(MIN_LEVERAGE, 2))
    stop_distance = atr * ATR_STOP_MULTIPLIER
    if direction == "long":
        stop_loss = entry - stop_distance
        tp1 = entry + stop_distance * MIN_RISK_REWARD
        tp2 = entry + stop_distance * MIN_RISK_REWARD * 1.5
        tp3 = structure_target if structure_target and structure_target > tp2 else entry + stop_distance * MIN_RISK_REWARD * 2
    else:
        stop_loss = entry + stop_distance
        tp1 = entry - stop_distance * MIN_RISK_REWARD
        tp2 = entry - stop_distance * MIN_RISK_REWARD * 1.5
        tp3 = structure_target if structure_target and structure_target < tp2 else entry - stop_distance * MIN_RISK_REWARD * 2

    targets = [tp1, tp2, tp3]
    risk_reward = abs(tp1 - entry) / stop_distance if stop_distance else 0
    # تحمل خطای ممیز شناور (مثلاً 1.999999 در برابر 2.0)
    if risk_reward + 1e-9 < MIN_RISK_REWARD:
        return RiskPlan(direction, entry, stop_loss, targets, leverage, 0.0, risk_reward, False, f"RR {risk_reward:.2f} < {MIN_RISK_REWARD}")

    risk_amount = account_balance_usdt * (RISK_PER_TRADE_PCT / 100)
    position_size = risk_amount / stop_distance if stop_distance else 0
    position_size_usdt = position_size * entry

    return RiskPlan(direction, entry, stop_loss, targets, leverage, position_size_usdt, risk_reward, True, "ok")

# ===========================
# تحلیل کامل ارز (قیمت و OHLCV از قرارداد دائمی همان صرافی)
# ===========================
async def analyze_coin_full_status(code: str) -> str:
    cache_key = f"{code}_{int(time.time() / 60)}"
    if cache_key in _analysis_cache:
        return _analysis_cache[cache_key]

    try:
        # دریافت قیمت از فیوچرز
        futures_data = get_futures_data(code)
        price = futures_data.get("last_price", 0.0)
        if price == 0.0:
            return f"❌ قیمت فیوچرز ارز **{code}** در دسترس نیست. لطفاً دوباره تلاش کنید."

        rate = await fetch_irt_rate()
        irt_price = price * rate

        # دریافت OHLCV از همان قرارداد دائمی و همان صرافی مرجع
        preferred_exchange = futures_exchange = futures_data.get("exchange")
        tasks = [
            cache.get_ohlcv(code, "1h", preferred_exchange),
            cache.get_ohlcv(code, "4h", preferred_exchange),
            cache.get_ohlcv(code, "1d", preferred_exchange)
        ]
        results = await asyncio.gather(*tasks)
        df_1h, df_4h, df_1d = results

        if df_1h is None or len(df_1h) < 20:
            return f"❌ داده‌های تاریخچه برای ارز **{code}** در دسترس نیست."

        ind = compute_indicators(df_1h)
        ind_4h = compute_indicators(df_4h) if df_4h is not None else None
        ind_1d = compute_indicators(df_1d) if df_1d is not None else None

        if ind is None:
            return f"❌ تحلیل **{code}** ناموفق بود."

        funding = futures_data.get("funding_rate")
        oi = futures_data.get("open_interest")
        futures_exchange = futures_data.get("exchange", "نامشخص")
        
        close_series = df_1h["close"]
        price_1h_ago = close_series.iloc[-2] if len(close_series) > 1 else price
        change_1h = ((price - price_1h_ago) / price_1h_ago * 100) if price_1h_ago else 0

        change_24h = 0
        high_24h = price
        low_24h = price
        volume_24h = 0
        if df_1d is not None and len(df_1d) > 1:
            close_24h = df_1d["close"].iloc[-2] if len(df_1d) > 1 else price
            change_24h = ((price - close_24h) / close_24h * 100) if close_24h else 0
            high_24h = df_1d["high"].iloc[-1]
            low_24h = df_1d["low"].iloc[-1]
            volume_24h = df_1d["volume"].iloc[-1]
        
        if futures_data.get("high_24h"):
            high_24h = futures_data["high_24h"]
        if futures_data.get("low_24h"):
            low_24h = futures_data["low_24h"]
        if futures_data.get("volume_24h"):
            volume_24h = futures_data["volume_24h"]

        if df_1d is not None and len(df_1d) >= 7:
            support_weekly = df_1d["low"].tail(7).min()
            resistance_weekly = df_1d["high"].tail(7).max()
        else:
            support_weekly = ind.structure_level if ind.structure_breakout_down else None
            resistance_weekly = ind.structure_level if ind.structure_breakout_up else None

        ema20 = EMAIndicator(df_1h["close"], window=20).ema_indicator().iloc[-1]
        ema50 = EMAIndicator(df_1h["close"], window=50).ema_indicator().iloc[-1]
        ema200 = EMAIndicator(df_1h["close"], window=200).ema_indicator().iloc[-1]

        macd_ind = MACD(df_1h["close"], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL)
        macd_line = macd_ind.macd().iloc[-1]
        macd_signal = macd_ind.macd_signal().iloc[-1]
        macd_hist = macd_ind.macd_diff().iloc[-1]

        bb_ind = BollingerBands(df_1h["close"], window=20)
        bb_upper = bb_ind.bollinger_hband().iloc[-1]
        bb_middle = bb_ind.bollinger_mavg().iloc[-1]
        bb_lower = bb_ind.bollinger_lband().iloc[-1]

        stoch_rsi = StochRSIIndicator(df_1h["close"], window=14).stochrsi().iloc[-1] * 100 if len(df_1h) > 20 else 50

        fg_text = get_fg_text()

        # محاسبه امتیاز و ضریب اطمینان
        score = 0
        max_score = 6
        if ind.trend_up or ind.trend_down:
            score += 1
        if ind.rsi_in_zone:
            score += 1
        if ind.macd_cross_up or ind.macd_cross_down:
            score += 1
        if ind.volume_ratio > 2.0:
            score += 1
        if ind.adx > 30:
            score += 1
        if funding is not None and abs(funding) < 0.0005:
            score += 1
        if oi is not None and oi > 0:
            score += 0.5

        confidence = min(100, int((score / max_score) * 100))
        if confidence >= 80:
            confidence_text = "بسیار بالا 🌟"
        elif confidence >= 60:
            confidence_text = "بالا 🟢"
        elif confidence >= 40:
            confidence_text = "متوسط 🟡"
        else:
            confidence_text = "پایین 🔴"

        if score >= 5:
            signal_strength = "بسیار قوی 🌟"
        elif score >= 4:
            signal_strength = "قوی 🟢"
        elif score >= 2:
            signal_strength = "متوسط 🟡"
        else:
            signal_strength = "ضعیف 🔴"

        regime = "روند" if ind.adx >= ADX_RANGE_THRESHOLD else "رنج"
        trend_fa = "صعودی 🚀" if ind.trend_up else "نزولی 🔻" if ind.trend_down else "خنثی ⚖️"

        if ind.rsi > 70:
            rsi_interpret = "اشباع خرید (overbought)"
        elif ind.rsi < 30:
            rsi_interpret = "اشباع فروش (oversold)"
        elif 40 <= ind.rsi <= 60:
            rsi_interpret = "منطقه تعادل"
        else:
            rsi_interpret = "منطقه معمولی"

        if ind.adx > 40:
            adx_interpret = "روند بسیار قوی"
        elif ind.adx > 25:
            adx_interpret = "روند قوی"
        elif ind.adx > 20:
            adx_interpret = "روند ضعیف"
        else:
            adx_interpret = "بازار رنج (بدون روند)"

        if funding is not None:
            if funding > 0.001:
                funding_interpret = "منفی (لانگ‌ها هزینه می‌دهند)"
            elif funding < -0.001:
                funding_interpret = "مثبت (شورت‌ها هزینه می‌دهند)"
            else:
                funding_interpret = "خنثی"
        else:
            funding_interpret = "نامشخص"

        if oi is not None:
            if oi > 0:
                oi_interpret = "وجود دارد"
            else:
                oi_interpret = "صفر"
        else:
            oi_interpret = "نامشخص"

        trend_4h = "صعودی 🚀" if ind_4h and ind_4h.trend_up else "نزولی 🔻" if ind_4h and ind_4h.trend_down else "خنثی ⚖️" if ind_4h else "نامشخص"
        rsi_4h = ind_4h.rsi if ind_4h else None
        adx_4h = ind_4h.adx if ind_4h else None
        swap_status = "🟢 فعال"

        text = (
            f"📊 **تحلیل جامع فیوچرز {code}**\n"
            f"{'────────────────────'}\n"
            f"💰 **قیمت‌ها و تغییرات:**\n"
            f"   • دلاری: `{fmt_usd(price)}` USDT\n"
            f"   • تومانی: `{fmt_toman(price, rate)}`\n"
            f"   • تغییر ۱ساعته: `{format_percent(change_1h)}`\n"
            f"   • تغییر ۲۴ساعته: `{format_percent(change_24h)}`\n"
            f"   • بیشترین ۲۴h: `{fmt_usd(safe_float(high_24h))}`\n"
            f"   • کمترین ۲۴h: `{fmt_usd(safe_float(low_24h))}`\n"
            f"   • صرافی مرجع فیوچرز: `{futures_exchange}`\n"
            f"{'────────────────────'}\n"
            f"📈 **روند و رژیم بازار:**\n"
            f"   • روند کلی: {trend_fa}\n"
            f"   • رژیم بازار: {regime} (ADX: {safe_format_float(ind.adx, '.1f')})\n"
            f"   • قدرت سیگنال: {signal_strength}\n"
            f"   • ضریب اطمینان: `{confidence}%` ({confidence_text})\n"
            f"   • وضعیت Swap: {swap_status}\n"
            f"   • شاخص ترس و طمع: `{fg_text}`\n"
            f"{'────────────────────'}\n"
            f"📊 **اندیکاتورهای تکنیکال (۱ساعته):**\n"
            f"   • RSI (14): `{safe_format_float(ind.rsi, '.1f')}` ({rsi_interpret})\n"
            f"   • استوکاستیک RSI: `{safe_format_float(stoch_rsi, '.1f')}`\n"
            f"   • MACD: خط `{safe_format_float(macd_line, '.4f')}` | سیگنال `{safe_format_float(macd_signal, '.4f')}` | هیستوگرام `{safe_format_float(macd_hist, '.4f')}`\n"
            f"   • EMA 20: `{fmt_usd(safe_float(ema20))}`\n"
            f"   • EMA 50: `{fmt_usd(safe_float(ema50))}`\n"
            f"   • EMA 200: `{fmt_usd(safe_float(ema200))}`\n"
            f"   • ADX: `{safe_format_float(ind.adx, '.1f')}` ({adx_interpret})\n"
            f"   • ATR: `{fmt_usd(ind.atr)}`\n"
            f"{'────────────────────'}\n"
            f"📊 **بولینگر باند (۲۰):**\n"
            f"   • بالا: `{fmt_usd(safe_float(bb_upper))}`\n"
            f"   • وسط: `{fmt_usd(safe_float(bb_middle))}`\n"
            f"   • پایین: `{fmt_usd(safe_float(bb_lower))}`\n"
            f"   • عرض باند: `{fmt_usd(safe_float(bb_upper - bb_lower))}`\n"
            f"{'────────────────────'}\n"
            f"🎯 **سطوح کلیدی:**\n"
            f"   • حمایت ۲۴h: `{fmt_usd(safe_float(low_24h))}`\n"
            f"   • مقاومت ۲۴h: `{fmt_usd(safe_float(high_24h))}`\n"
            f"   • حمایت هفتگی: `{fmt_usd(safe_float(support_weekly))}`\n"
            f"   • مقاومت هفتگی: `{fmt_usd(safe_float(resistance_weekly))}`\n"
            f"{'────────────────────'}\n"
            f"📊 **داده‌های فیوچرز:**\n"
            f"   • فاندینگ‌ریت: `{safe_format_percent(funding)}` ({funding_interpret})\n"
            f"   • Open Interest: `{safe_float(oi):,.0f}` ({oi_interpret})\n"
            f"{'────────────────────'}\n"
            f"📊 **حجم معاملات:**\n"
            f"   • نسبت به میانگین: `{ind.volume_ratio:.2f}x`\n"
            f"   • حجم ۲۴h: `{volume_24h:,.0f}` USDT\n"
            f"{'────────────────────'}\n"
            f"🔄 **تایم‌فریم بالاتر (۴ساعته):**\n"
            f"   • روند: {trend_4h}\n"
            f"   • RSI: `{safe_format_float(rsi_4h, '.1f')}`\n"
            f"   • ADX: `{safe_format_float(adx_4h, '.1f')}`\n"
            f"{'────────────────────'}\n"
            f"📅 **بروزرسانی:** `{shamsi_now()}`\n"
            f"🏛 **صرافی فیوچرز:** `{futures_exchange}`\n"
        )
        
        _analysis_cache[cache_key] = text
        return text
    except Exception as e:
        logger.error(f"Error analyzing {code}: {e}")
        return f"❌ خطا در تحلیل **{code}**: {safe_str(e)}"

# ===========================
# قالب پیام سیگنال جدید
# ===========================
def get_signal_strength_and_confidence(ind: IndicatorSnapshot, funding: Optional[float], oi: Optional[float]) -> tuple[str,str,int]:
    d='long' if ind.trend_up else 'short'
    score,_,_=setup_score(d,ind,ind,funding)
    if score>=85: return 'بسیار قوی 🌟',f'{score}% امتیاز ساختاری (نه احتمال برد)',score
    if score>=72: return 'قوی 🟢',f'{score}% امتیاز ساختاری (نه احتمال برد)',score
    if score>=60: return 'متوسط 🟡',f'{score}% امتیاز ساختاری (نه احتمال برد)',score
    return 'ضعیف 🔴',f'{score}% امتیاز ساختاری (نه احتمال برد)',score

def format_signal_message(code: str, direction: str, plan: RiskPlan, setup_type: str, ai_status: str, ai_text: str, ind: IndicatorSnapshot, funding: Optional[float], oi: Optional[float], rate: float, hist_est: Optional[dict] = None) -> str:
    """قالب پیام سیگنال — خط اول واضح از پیش‌نمایش کانال"""
    if setup_type in ("trend_up", "trend", "trend_up_reverse"):
        setup_label = "روند صعودی 📈" if "reverse" not in setup_type else "چرخش به صعودی 🔄📈"
    elif setup_type in ("trend_down", "trend_down_reverse"):
        setup_label = "روند نزولی 📉" if "reverse" not in setup_type else "چرخش به نزولی 🔄📉"
    elif setup_type == "range_breakout":
        setup_label = "شکست محدوده ⚡"
    else:
        setup_label = "برگشت از لبه محدوده 🔄"

    is_long = direction == "long"
    dir_fa = "خرید (لانگ) 🟢" if is_long else "فروش (شورت) 🔴"
    # خط اول برای پیش‌نمایش اعلان تلگرام
    headline = (
        f"🟢 سیگنال خرید #{code} | {setup_label}"
        if is_long else
        f"🔴 سیگنال فروش #{code} | {setup_label}"
    )

    strength, confidence_text, score = get_signal_strength_and_confidence(ind, funding, oi)

    # ایموجی هدف‌ها: اول / میانی / نهایی
    tp_emojis = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
    tp_titles = {1: "هدف اول", 2: "هدف دوم", 3: "هدف نهایی"}
    targets_lines = []
    for i, t in enumerate(plan.targets, 1):
        em = tp_emojis.get(i, "🎯")
        title = tp_titles.get(i, f"هدف {i}")
        targets_lines.append(
            f"{em} **{title}**\n"
            f"💵 `{fmt_usd(t)}` USDT\n"
            f"🇮🇷 {fmt_toman(t, rate)}"
        )

    if ai_status == "confirmed":
        ai_line = "✅ تأیید شد"
    elif ai_status == "rejected":
        ai_line = "❌ رد شد"
    else:
        ai_line = "⏳ در دسترس نبود"

    opinion = (ai_text or "").strip()
    for bad in ("CONFIRM", "REJECT", "confirm", "reject"):
        if opinion.upper().startswith(bad):
            opinion = opinion[len(bad):].lstrip(" :-–—|.")
    opinion = opinion.strip()
    if opinion.upper() in ("CONFIRM", "REJECT"):
        opinion = ""
    if ai_status == "rejected" and not opinion:
        opinion = "از نظر هوش مصنوعی قدرت کافی ندارد"
    if ai_status == "confirmed" and not opinion:
        opinion = "از نظر هوش مصنوعی قابل‌قبول است"

    funding_text = safe_format_percent(funding)
    oi_text = f"{safe_float(oi):,.0f}" if oi is not None else "نامشخص"
    rtl = "\u200F"

    # داده‌های تشخیصی برای بررسی بعد از موفقیت/شکست
    trend_1h = "صعودی" if ind.trend_up else ("نزولی" if ind.trend_down else "خنثی")
    ema_x = "تقاطع صعودی اخیر" if ind.ema_cross_up else ("تقاطع نزولی اخیر" if ind.ema_cross_down else "بدون تقاطع اخیر")
    macd_x = "تقاطع صعودی" if ind.macd_cross_up else ("تقاطع نزولی" if ind.macd_cross_down else "بدون تقاطع")
    struct = "شکست بالا" if ind.structure_breakout_up else ("شکست پایین" if ind.structure_breakout_down else "بدون شکست ساختار")
    edge = "برگشت از کف" if ind.edge_reversal_up else ("برگشت از سقف" if ind.edge_reversal_down else "بدون برگشت لبه")
    stop_pct = abs(plan.entry - plan.stop_loss) / plan.entry * 100 if plan.entry else 0
    tp1_pct = abs(plan.targets[0] - plan.entry) / plan.entry * 100 if plan.entry and plan.targets else 0
    regime = "روند" if ind.adx >= ADX_TREND_MIN else ("نیمه‌روند" if ind.adx >= ADX_RANGE_THRESHOLD else "محدوده")

    text = (
        f"{rtl}{headline}\n"
        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{rtl}📊 **جهت معامله:** {dir_fa}\n"
        f"{rtl}📌 **نوع استراتژی:** {setup_label}\n"
        f"{rtl}📈 **قدرت سیگنال:** {strength}\n"
        f"{rtl}🎯 **امتیاز ساختاری:** `{score}/100` ({strength})\n\n"
        f"{rtl}📥 **قیمت ورود**\n"
        f"{rtl}💵 `{fmt_usd(plan.entry)}` USDT\n"
        f"{rtl}🇮🇷 {fmt_toman(plan.entry, rate)}\n\n"
        f"{rtl}🎯 **اهداف قیمتی**\n"
        + "\n".join(f"{rtl}{sub}" for line in targets_lines for sub in line.split("\n")) + "\n\n"
        f"{rtl}🛑 **حد ضرر**\n"
        f"{rtl}💵 `{fmt_usd(plan.stop_loss)}` USDT\n"
        f"{rtl}🇮🇷 {fmt_toman(plan.stop_loss, rate)}\n\n"
        f"{rtl}⚙️ **مدیریت سرمایه**\n"
        f"{rtl}   • اهرم: `{plan.leverage}x`\n"
        f"{rtl}   • نسبت سود به زیان: `1:{plan.risk_reward:.2f}`\n"
        f"{rtl}   • فاصله حد ضرر: `{stop_pct:.2f}%` | هدف اول: `{tp1_pct:.2f}%`\n\n"
        f"{rtl}📊 **وضعیت بازار (۱ ساعته)**\n"
        f"{rtl}   • رژیم: `{regime}`\n"
        f"{rtl}   • جهت روند: `{trend_1h}`\n"
        f"{rtl}   • RSI: `{ind.rsi:.1f}` | ADX: `{ind.adx:.1f}`\n"
        f"{rtl}   • حجم نسبت به میانگین: `{ind.volume_ratio:.2f}x`\n"
        f"{rtl}   • EMA: `{ema_x}`\n"
        f"{rtl}   • MACD: `{macd_x}`\n"
        f"{rtl}   • ساختار: `{struct}` | لبه: `{edge}`\n"
        f"{rtl}   • ATR: `{fmt_usd(ind.atr)}`\n"
        f"{rtl}   • نرخ تأمین مالی: `{funding_text}`\n"
        f"{rtl}   • بهره باز (Open Interest): `{oi_text}`\n"
        f"{rtl}   • ترس و طمع: `{get_fg_text()}`\n\n"
        f"{rtl}📅 **زمان:** `{shamsi_now()}`\n"
        f"{rtl}🏷 **کد استراتژی:** `{setup_type or 'نامشخص'}`\n"
    )
    if hist_est:
        if hist_est.get("pct") is not None:
            text += (
                f"{rtl}📚 **تخمین از تاریخچه ربات:** `{hist_est['pct']}%` "
                f"(نمونه {hist_est['sample']} | برد {hist_est['wins']} | باخت {hist_est['losses']})\n"
                f"{rtl}   • {hist_est.get('note', '')}\n"
            )
        else:
            text += f"{rtl}📚 **تخمین از تاریخچه:** {hist_est.get('note', 'هنوز داده کافی نیست')}\n"
    text += (
        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
        f"{rtl}🤖 **هوش مصنوعی:** {ai_line}"
    )
    if opinion:
        # فقط متن فارسی تمیز برای کانال
        clean = re.sub(r"(?i)(DECISION\s*=\s*\w+\s*\|?\s*)?(CONF\s*=\s*\d+\s*\|?\s*)?(REASON\s*=\s*)?", "", opinion)
        clean = re.sub(r"[A-Za-z]{4,}", " ", clean)
        clean = re.sub(r"\s{2,}", " ", clean).strip(" |:-")
        if clean:
            text += f"\n{rtl}💬 **توضیح:** {clean}"
    return text

# ===========================
# پنل مدیریت کامل (بدون کلمه اسپات)
# ===========================
# ===========================
# تست کامل سیستم (رفع نهایی event loop)
# ===========================
def run_system_test() -> str:
    """اجرای تست کامل سیستم بدون خطای event loop"""
    result = []
    result.append("🧪 گزارش تست کامل سیستم")
    result.append("=" * 40)
    
    result.append("\n🤖 اطلاعات ربات:")
    result.append(f"   • نسخه: {VERSION}")
    result.append(f"   • زمان ساخت: {BUILD_TIME}")
    result.append(f"   • زمان اجرا: {shamsi_now()}")
    uptime = int(time.time() - START_TIME)
    days = uptime // 86400
    hours = (uptime % 86400) // 3600
    minutes = (uptime % 3600) // 60
    result.append(f"   • آپتایم: {days} روز {hours} ساعت {minutes} دقیقه")

    total_users = len(registered_users)
    active_users = len(registered_users - paused_users)
    paused_users_count = len(paused_users)
    result.append("\n👥 آمار کاربران:")
    result.append(f"   • کل کاربران: {total_users}")
    result.append(f"   • فعال: {active_users}")
    result.append(f"   • متوقف: {paused_users_count}")

    result.append("\n⚙️ تنظیمات فعال:")
    result.append(f"   • اهرم: {MIN_LEVERAGE}-{MAX_LEVERAGE}x")
    result.append(f"   • حداقل RR: 1:{MIN_RISK_REWARD}")
    result.append(f"   • ریسک هر معامله: {RISK_PER_TRADE_PCT}%")
    result.append(f"   • فیلتر حجم: {VOLUME_MIN_RATIO}x")
    result.append(f"   • کول‌داون: {SIGNAL_REOPEN_COOLDOWN_SECONDS//60} دقیقه")
    result.append(f"   • پوزیشن‌های همزمان: {MAX_CONCURRENT_POSITIONS}")
    result.append(f"   • ارسال به کانال: {'✅ فعال' if SEND_TO_CHANNEL else '❌ غیرفعال'}")
    result.append(f"   • ارسال به ربات: {'✅ فعال' if SEND_TO_ADMIN else '❌ غیرفعال'}")
    
    result.append("\n🔑 متغیرهای محیطی:")
    result.append(f"   • BOT_TOKEN: {'✅ تنظیم شده' if BOT_TOKEN else '❌ تنظیم نشده'}")
    result.append(f"   • ADMIN_USER_IDS: {'✅ تنظیم شده' if ADMIN_USER_IDS else '❌ تنظیم نشده'}")
    result.append(f"   • CHANNEL_ID: {'✅ تنظیم شده' if CHANNEL_ID else '❌ تنظیم نشده'}")
    result.append(f"   • GROQ_API_KEY: {'✅ تنظیم شده' if GROQ_API_KEY else '❌ تنظیم نشده'}")
    result.append(f"   • DB_PATH: {DB_PATH}")
    
    try:
        db = get_db_stats()
        result.append(f"\n💾 دیتابیس: ✅ متصل")
        result.append(f"   • تعداد سیگنال‌ها: {db['total']}")
        result.append(f"   • سیگنال‌های باز: {db['open']}")
    except Exception as e:
        result.append(f"\n💾 دیتابیس: ❌ خطا: {e}")
    
    # ===== وضعیت صرافی‌ها =====
    result.append("\n🏛 وضعیت صرافی‌ها:")
    try:
        # فقط وضعیت موجود را نمایش بده (بدون به‌روزرسانی)
        for name, data in cache.exchange_status.items():
            if data["online"]:
                result.append(f"   • {name}: ✅ آنلاین")
            else:
                result.append(f"   • {name}: 🔴 آفلاین")
    except Exception as e:
        result.append(f"   ❌ خطا: {e}")
    
    # ===== تست داده‌های فیوچرز =====
    result.append("\n📊 تست داده‌های فیوچرز:")
    for code in ["BTC", "ETH"]:
        data = get_futures_data(code)
        if data.get("last_price"):
            result.append(f"   • {code}: ✅ قیمت دریافت شد (${data['last_price']})")
            if data.get("funding_rate") is not None:
                result.append(f"     - فاندینگ‌ریت: {data['funding_rate']:.4%}")
            else:
                result.append(f"     - فاندینگ‌ریت: ❌ دریافت نشد")
            if data.get("open_interest"):
                result.append(f"     - Open Interest: {data['open_interest']:,.0f}")
            else:
                result.append(f"     - Open Interest: ❌ دریافت نشد")
        else:
            result.append(f"   • {code}: ❌ قیمت دریافت نشد")
    
    # ===== شاخص ترس و طمع =====
    fg = get_fear_greed_index()
    if fg is not None:
        result.append(f"\n📈 شاخص ترس و طمع: ✅ دریافت شد ({fg})")
    else:
        result.append(f"\n📈 شاخص ترس و طمع: ❌ دریافت نشد")
    
    # ===== نرخ تومان =====
    rate = fetch_irt_rate_sync()
    if rate and rate > 0:
        result.append(f"\n🇮🇷 نرخ تتر (Wallex): ✅ دریافت شد ({rate:,.0f} تومان)")
    else:
        result.append(f"\n🇮🇷 نرخ تتر (Wallex): ❌ دریافت نشد")
    
    # ===== هوش مصنوعی =====
    result.append(f"\n🤖 هوش مصنوعی:")
    if not GROQ_API_KEY:
        result.append("   ❌ کلید API تنظیم نشده است")
    else:
        result.append("   ⏳ در حال تست...")
        try:
            status, text = confirm_signal_with_ai(None, {
                "direction": "long",
                "ticker": "BTC",
                "rule_score": 70,
                "1h": {"rsi": 50, "adx": 25, "volume_ratio": 1.2},
                "risk": {"rr": 2.0},
            })
            if status in ("confirmed", "rejected"):
                result.append(f"   ✅ AI فعال است ({status})")
                if text:
                    result.append(f"   💬 {text[:180]}")
            else:
                result.append(f"   ⚠️ AI در دسترس نیست: {text}")
        except Exception as e:
            result.append(f"   ❌ خطا در تست AI: {e}")
    
    # ===== کانال تلگرام =====
    result.append(f"\n📢 کانال تلگرام:")
    if CHANNEL_ID:
        result.append(f"   ✅ شناسه کانال تنظیم شده: {CHANNEL_ID}")
    else:
        result.append(f"   ❌ شناسه کانال تنظیم نشده است")
    
    # ===== بررسی شرایط سیگنال (بدون event loop) =====
    result.append("\n📊 شرایط سیگنال برای BTC:")
    try:
        # فقط قیمت را از فیوچرز دریافت کن
        btc_data = get_futures_data("BTC")
        btc_price = btc_data.get("last_price", 0)
        if btc_price > 0:
            result.append(f"   • قیمت فیوچرز BTC: ${btc_price:.2f}")
            result.append("   • برای مشاهده اندیکاتورها، از بخش تحلیل ارز استفاده کنید.")
        else:
            result.append("   ❌ قیمت BTC در دسترس نیست")
    except Exception as e:
        result.append(f"   ❌ خطا: {e}")
    
    result.append("\n" + "=" * 40)
    result.append("✅ تست سیستم با موفقیت انجام شد.")
    
    return "\n".join(result)

# ===========================
# کیبوردها
# ===========================
MAIN_MENU_TEXT = (
    "🤖 **ربات هوشمند تحلیل فیوچرز ارزهای دیجیتال**\n"
    "📊 قیمت لحظه‌ای | تحلیل تکنیکال | سیگنال معاملاتی\n"
    "⚡️ سریع و دقیق\n\n"
    "👇 **منوی اصلی:**"
)

COIN_SELECT_TEXT = (
    "📊 **تحلیل تکنیکال و داده‌های فیوچرز ارزهای دیجیتال**\n"
    "جهت مشاهده تحلیل کامل (اندیکاتورها، فاندینگ، Open Interest، شاخص ترس و طمع)، یکی از ارزهای زیر را انتخاب کنید:"
)

ADMIN_PANEL_HEADER = (
    "👑 **پنل مدیریت اختصاصی ادمین**\n"
    "در این بخش می‌توانید آمار، وضعیت سیستم و تنظیمات را مدیریت کنید.\n\n"
    "👇 **یکی از گزینه‌ها را انتخاب کنید:**"
)

SIGNAL_SETTINGS_HEADER = (
    "📤 **تنظیمات ارسال سیگنال**\n\n"
    "وضعیت فعلی:\n"
)

def kb_main_menu(is_admin_user=False):
    keyboard = [
        [InlineKeyboardButton("💵 قیمت لحظه‌ای ارزها", callback_data="coins_prices_all"),
         InlineKeyboardButton("📊 وضعیت و تحلیل ارزها", callback_data="coins_status_grid")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت ادمین", callback_data="admin_panel")])
    keyboard.append([
        InlineKeyboardButton("✅ شروع فعالیت", callback_data="bot_start_action"),
        InlineKeyboardButton("⛔ توقف فعالیت", callback_data="bot_stop_action")
    ])
    return InlineKeyboardMarkup(keyboard)

def kb_start_only():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ شروع مجدد ربات", callback_data="bot_start_action")]])

def kb_prices_all_single():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی قیمت‌ها", callback_data="coins_prices_all")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def kb_status_grid():
    buttons = []
    row = []
    for i, code in enumerate(COIN_CODES):
        row.append(InlineKeyboardButton(f"{code} 🟢", callback_data=f"coin_detail_{code}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 آمار و عملکردها", callback_data="admin_signal_stats")],
        [InlineKeyboardButton("📤 تنظیمات ارسال سیگنال", callback_data="admin_signal_settings")],
        [InlineKeyboardButton("🧪 وضعیت سیستم", callback_data="admin_system_test")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def kb_signal_settings():
    channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
    admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
    channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
    admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 ارسال به کانال: {channel_emoji} {channel_status}", callback_data="signal_channel")],
        [InlineKeyboardButton(f"📨 ارسال به ربات: {admin_emoji} {admin_status}", callback_data="signal_admin")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
    ])

def kb_signal_submenu(target: str):
    if target == "channel":
        status = SEND_TO_CHANNEL
        title = "📢 **تنظیم ارسال به کانال**"
        current = "فعال" if status else "غیرفعال"
        emoji = "✅" if status else "❌"
        enable_text = "🟢 فعال کردن ارسال به کانال"
        disable_text = "🔴 غیرفعال کردن ارسال به کانال"
        enable_cb = "toggle_channel_on"
        disable_cb = "toggle_channel_off"
    else:
        status = SEND_TO_ADMIN
        title = "📨 **تنظیم ارسال به ربات**"
        current = "فعال" if status else "غیرفعال"
        emoji = "✅" if status else "❌"
        enable_text = "🟢 فعال کردن ارسال به ربات"
        disable_text = "🔴 غیرفعال کردن ارسال به ربات"
        enable_cb = "toggle_admin_on"
        disable_cb = "toggle_admin_off"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(enable_text, callback_data=enable_cb)],
        [InlineKeyboardButton(disable_text, callback_data=disable_cb)],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_signal_settings")]
    ]), title, current, emoji

def kb_back_admin():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]])

def kb_signal_stats_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 حذف آمار", callback_data="reset_stats_confirm")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
    ])

def kb_reset_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، تمام آمار سیگنال‌ها صفر شود", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ انصراف", callback_data="admin_signal_stats")]
    ])

# ===========================
# متغیرهای سراسری و هندلرها
# ===========================
registered_users: Set[int] = set()
paused_users: Set[int] = set()
_trend_warned: Set[int] = set()  # signal_idهایی که هشدار تغییر روند گرفته‌اند
signal_history: List[Dict] = []
TOTAL_SIGNALS_GENERATED = 0
LAST_REPORT_TIME = None

async def version_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 **نسخه ربات:** `{VERSION}`\n📅 **زمان ساخت:** `{BUILD_TIME}`\n🆔 **شناسه:** `{context.bot.id}`",
        parse_mode="Markdown"
    )

async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_adm = user_id in ADMIN_USER_IDS
    db = get_db_stats()
    text = (
        f"📌 **اطلاعات ربات هوشمند تحلیل فیوچرز ارزهای دیجیتال**\n"
        f"{'────────────────────'}\n"
        f"🤖 **نسخه:** `{VERSION}`\n"
        f"📅 **ساخت:** `{BUILD_TIME}`\n"
        f"🆔 **شناسه:** `{context.bot.id}`\n"
        f"👤 **وضعیت شما:** {'👑 ادمین' if is_adm else '👤 کاربر عادی'}\n"
        f"📊 **تعداد ارزها:** `{len(COIN_CODES)}`\n"
        f"🏛 **صرافی فعال:** `{cache.active_exchange_name}`\n"
        f"📊 **کل سیگنال‌ها:** `{db['total']}`\n"
        f"🔄 **سیگنال‌های باز:** `{db['open']}`\n"
        f"{'────────────────────'}\n"
        f"⚡️ *برای شروع از دستور /start استفاده کنید.*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    registered_users.add(user_id)
    paused_users.discard(user_id)
    is_adm = user_id in ADMIN_USER_IDS
    await update.message.reply_text(MAIN_MENU_TEXT, reply_markup=kb_main_menu(is_adm), parse_mode="Markdown")

async def stop_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    paused_users.add(user_id)
    await update.message.reply_text("⛔ **ربات متوقف شد.**", reply_markup=kb_start_only(), parse_mode="Markdown")

async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ **شما دسترسی به این بخش را ندارید.**", parse_mode="Markdown")
        return
    await update.message.reply_text(ADMIN_PANEL_HEADER, reply_markup=kb_admin_panel(), parse_mode="Markdown")

# ===========================
# Callback Handler
# ===========================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SEND_TO_CHANNEL, SEND_TO_ADMIN
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_adm = user_id in ADMIN_USER_IDS

    if data == "bot_start_action":
        paused_users.discard(user_id)
        registered_users.add(user_id)
        await query.edit_message_text(
            MAIN_MENU_TEXT,
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if data == "bot_stop_action":
        paused_users.add(user_id)
        await query.edit_message_text(
            "⛔ **ربات متوقف شد.**\nبرای استفاده مجدد، روی دکمه زیر کلیک کنید.",
            reply_markup=kb_start_only(),
            parse_mode="Markdown"
        )
        return

    if user_id in paused_users and data != "main_menu":
        await query.edit_message_text(
            "⛔️ **ربات برای شما غیرفعال است.**\nجهت فعال‌سازی روی دکمه زیر کلیک کنید.",
            reply_markup=kb_start_only(),
            parse_mode="Markdown"
        )
        return

    if data == "main_menu":
        await query.edit_message_text(
            MAIN_MENU_TEXT,
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if data == "coins_prices_all":
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...", parse_mode="Markdown")
        prices = await cache.update_prices()
        rate = await fetch_irt_rate()
        exchange_emoji = "🇲" if "MEXC" in cache.active_exchange_name else "🇬"
        text = (
            f"💵 **لیست قیمت لحظه‌ای ۳۰ ارز دیجیتال برتر**\n"
            f"📅 {shamsi_now()}\n"
            f"🇮🇷 نرخ تتر: {rate:,.0f} تومان\n"
            f"{'────────────────────'}\n"
        )
        for code in COIN_CODES:
            p = prices.get(code, 0.0)
            if isinstance(p, str):
                try:
                    p = float(p)
                except:
                    p = 0.0
            if p > 0:
                text += f"‎{exchange_emoji} **{code}**: {fmt_usd(p)} USDT\n‎🇮🇷 {fmt_toman(p, rate)}\n\n"
            else:
                text += f"‎{exchange_emoji} **{code}**: ❌ قیمت در دسترس نیست\n\n"
        await query.edit_message_text(text, reply_markup=kb_prices_all_single(), parse_mode="Markdown")
        return

    if data == "coins_status_grid":
        await query.edit_message_text(
            COIN_SELECT_TEXT,
            reply_markup=kb_status_grid(),
            parse_mode="Markdown"
        )
        return

    if data.startswith("coin_detail_"):
        code = data.split("_")[2]
        await query.edit_message_text(f"⏳ در حال تحلیل جامع فیوچرز {code}...", parse_mode="Markdown")
        text = await analyze_coin_full_status(code)
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 بروزرسانی تحلیل", callback_data=f"coin_detail_{code}")],
                [InlineKeyboardButton("🔙 لیست ارزها", callback_data="coins_status_grid")]
            ]),
            parse_mode="Markdown"
        )
        return

    if data == "admin_panel":
        if not is_adm: return
        await query.edit_message_text(
            ADMIN_PANEL_HEADER,
            reply_markup=kb_admin_panel(),
            parse_mode="Markdown"
        )
        return

    if data == "admin_signal_settings":
        if not is_adm: return
        channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
        admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
        channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
        admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
        text = (
            f"{SIGNAL_SETTINGS_HEADER}"
            f"📢 ارسال به کانال: {channel_emoji} {channel_status}\n"
            f"📨 ارسال به ربات: {admin_emoji} {admin_status}\n\n"
            "برای تغییر هر یک از گزینه‌ها، روی آن کلیک کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_signal_settings(), parse_mode="Markdown")
        return

    if data == "signal_channel":
        if not is_adm: return
        kb, title, current, emoji = kb_signal_submenu("channel")
        text = (
            f"{title}\n\n"
            f"وضعیت فعلی: {emoji} {current}\n\n"
            "برای تغییر وضعیت، یکی از گزینه‌های زیر را انتخاب کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if data == "signal_admin":
        if not is_adm: return
        kb, title, current, emoji = kb_signal_submenu("admin")
        text = (
            f"{title}\n\n"
            f"وضعیت فعلی: {emoji} {current}\n\n"
            "برای تغییر وضعیت، یکی از گزینه‌های زیر را انتخاب کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if data == "toggle_channel_on":
        if not is_adm: return
        SEND_TO_CHANNEL = True
        save_signal_settings()
        channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
        admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
        channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
        admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
        text = (
            f"{SIGNAL_SETTINGS_HEADER}"
            f"📢 ارسال به کانال: {channel_emoji} {channel_status}\n"
            f"📨 ارسال به ربات: {admin_emoji} {admin_status}\n\n"
            "برای تغییر هر یک از گزینه‌ها، روی آن کلیک کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_signal_settings(), parse_mode="Markdown")
        return

    if data == "toggle_channel_off":
        if not is_adm: return
        SEND_TO_CHANNEL = False
        save_signal_settings()
        channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
        admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
        channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
        admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
        text = (
            f"{SIGNAL_SETTINGS_HEADER}"
            f"📢 ارسال به کانال: {channel_emoji} {channel_status}\n"
            f"📨 ارسال به ربات: {admin_emoji} {admin_status}\n\n"
            "برای تغییر هر یک از گزینه‌ها، روی آن کلیک کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_signal_settings(), parse_mode="Markdown")
        return

    if data == "toggle_admin_on":
        if not is_adm: return
        SEND_TO_ADMIN = True
        save_signal_settings()
        channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
        admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
        channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
        admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
        text = (
            f"{SIGNAL_SETTINGS_HEADER}"
            f"📢 ارسال به کانال: {channel_emoji} {channel_status}\n"
            f"📨 ارسال به ربات: {admin_emoji} {admin_status}\n\n"
            "برای تغییر هر یک از گزینه‌ها، روی آن کلیک کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_signal_settings(), parse_mode="Markdown")
        return

    if data == "toggle_admin_off":
        if not is_adm: return
        SEND_TO_ADMIN = False
        save_signal_settings()
        channel_emoji = "✅" if SEND_TO_CHANNEL else "❌"
        admin_emoji = "✅" if SEND_TO_ADMIN else "❌"
        channel_status = "فعال" if SEND_TO_CHANNEL else "غیرفعال"
        admin_status = "فعال" if SEND_TO_ADMIN else "غیرفعال"
        text = (
            f"{SIGNAL_SETTINGS_HEADER}"
            f"📢 ارسال به کانال: {channel_emoji} {channel_status}\n"
            f"📨 ارسال به ربات: {admin_emoji} {admin_status}\n\n"
            "برای تغییر هر یک از گزینه‌ها، روی آن کلیک کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_signal_settings(), parse_mode="Markdown")
        return

    if data == "admin_signal_stats":
        if not is_adm: return
        s = stats_summary()
        winrate = f"{s['winrate']:.1f}%" if s['winrate'] is not None else "بدون داده"
        long_closed = s["long_win"] + s["long_sl"]
        short_closed = s["short_win"] + s["short_sl"]
        long_wr = f"{(s['long_win']/long_closed*100):.0f}%" if long_closed else "—"
        short_wr = f"{(s['short_win']/short_closed*100):.0f}%" if short_closed else "—"
        setup_block = "\n".join(s["setup_lines"]) if s["setup_lines"] else "هنوز داده استراتژی ثبت نشده"
        text = (
            f"📈 **آمار و عملکرد**\n"
            f"────────────────────\n"
            f"🔢 کل سیگنال‌ها: `{s['total_signals']}` | باز: `{s['open']}`\n"
            f"1️⃣ رسید به هدف ۱: `{s['tp1_hit']}`\n"
            f"2️⃣ رسید به هدف ۲: `{s['tp2_hit']}`\n"
            f"3️⃣ هدف نهایی (موفق): `{s['wins']}`\n"
            f"❌ حد ضرر: `{s['losses']}`\n"
            f"🚫 باطل‌شده: `{s['invalidated']}`\n"
            f"🏆 نرخ موفقیت (TP3 در برابر SL): `{winrate}`\n\n"
            f"🤖 هوش مصنوعی: تأیید `{s['ai_ok']}` | عدم تأیید `{s['ai_no']}`\n\n"
            f"📊 **بر اساس جهت**\n"
            f"• خرید (لانگ): `{s['long_n']}` | موفق `{s['long_win']}` | ضرر `{s['long_sl']}` | نرخ {long_wr}\n"
            f"• فروش (شورت): `{s['short_n']}` | موفق `{s['short_win']}` | ضرر `{s['short_sl']}` | نرخ {short_wr}\n\n"
            f"📌 **بر اساس نوع استراتژی**\n"
            f"{setup_block}\n\n"
            f"🥇 بهترین ارز (TP3): `{s['best_coin']}` (`{s['best_coin_count']}`)\n"
            f"🥉 بدترین ارز (SL): `{s['worst_coin']}` (`{s['worst_coin_count']}`)"
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_signal_stats_back(),
            parse_mode="Markdown"
        )
        return

    if data == "admin_system_test":
        if not is_adm: return
        await query.edit_message_text("⏳ در حال اجرای تست سیستم...", parse_mode=None)
        text = run_system_test()
        await query.edit_message_text(text, reply_markup=kb_back_admin(), parse_mode=None)
        return

    if data == "reset_stats_confirm":
        if not is_adm: return
        await query.edit_message_text(
            "⚠️ **آیا از صفر کردن تمام آمار سیگنال‌ها اطمینان دارید؟**",
            reply_markup=kb_reset_confirm(),
            parse_mode="Markdown"
        )
        return

    if data == "reset_stats_do":
        if not is_adm: return
        with _conn() as c:
            c.execute("DELETE FROM signals")
        await query.edit_message_text(
            "✅ **تمامی آمار سیگنال‌ها با موفقیت صفر شد.**",
            reply_markup=kb_signal_stats_back(),
            parse_mode="Markdown"
        )
        return

# ===========================
# هوش مصنوعی (Groq — بدون ذکر نام مدل در پیام کاربر)
# ===========================
def _ai_compact_context(context: dict) -> dict:
    """کاهش حجم payload برای جلوگیری از HTTP 400"""
    h1 = context.get("1h") or {}
    h4 = context.get("4h") or {}
    der = context.get("derivatives") or {}
    risk = context.get("risk") or {}
    return {
        "ticker": context.get("ticker"),
        "direction": context.get("direction"),
        "score": context.get("rule_score"),
        "setup": context.get("setup_type"),
        "rsi": h1.get("rsi"),
        "adx": h1.get("adx"),
        "plus_di": h1.get("plus_di"),
        "minus_di": h1.get("minus_di"),
        "vol": h1.get("volume_ratio"),
        "bos_up": h1.get("bos_up"),
        "bos_down": h1.get("bos_down"),
        "h4_trend_up": h4.get("trend_up"),
        "h4_trend_down": h4.get("trend_down"),
        "h4_adx": h4.get("adx"),
        "funding": der.get("funding_rate"),
        "entry": risk.get("entry"),
        "stop": risk.get("stop"),
        "rr": risk.get("rr"),
        "reasons": (context.get("rule_reasons") or [])[:5],
        "warnings": (context.get("rule_warnings") or [])[:3],
    }

def _extract_ai_text(data: dict) -> str:
    """استخراج متن از پاسخ‌های مختلف Groq / gpt-oss"""
    try:
        msg = (data.get("choices") or [{}])[0].get("message") or {}
    except Exception:
        return ""
    parts = []
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    elif isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                t = p.get("text") or p.get("content") or ""
                if t:
                    parts.append(str(t).strip())
            elif isinstance(p, str) and p.strip():
                parts.append(p.strip())
    for key in ("reasoning", "reasoning_content", "refusal"):
        val = msg.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return "\n".join(parts).strip()

def _parse_ai_decision(raw_s: str, expected: str) -> tuple[str, str]:
    """تبدیل پاسخ مدل به confirmed/rejected + متن فارسی.

    مهم: مدل‌های gpt-oss گاهی فرمت دستور را تکرار می‌کنند
    (مثلاً 'DECISION=BUY or NO_TRADE'). نباید صرفاً با وجود کلمه
    NO_TRADE رد کرد — فقط مقدار صریح DECISION= مهم است.
    """
    if not raw_s:
        return "unavailable", "پاسخ خالی از مدل"

    # JSON
    obj = None
    try:
        cleaned = raw_s
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        obj = json.loads(cleaned)
    except Exception:
        start, end = raw_s.find("{"), raw_s.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(raw_s[start : end + 1])
            except Exception:
                obj = None

    if obj and isinstance(obj, dict):
        decision = str(obj.get("decision", "")).upper().strip()
        try:
            conf = max(0, min(100, int(float(obj.get("confidence", 50) or 50))))
        except Exception:
            conf = 50
        reason = str(obj.get("reason_fa") or obj.get("reason") or "").strip()
        # فقط حروف فارسی/عربی/عدد برای متن کانال
        if reason:
            reason = re.sub(r"[A-Za-z]{3,}.*", "", reason).strip(" |:-")
        text = (reason or decision or "تحلیل شد") + f" | ارزیابی AI: {conf}%"
        if decision == expected:
            return "confirmed", text[:500]
        if decision in ("NO_TRADE", "REJECT", "NONE", ""):
            return "rejected", text[:500]
        return "rejected", text[:500]

    up = raw_s.upper()

    # استخراج صریح DECISION=XXX (آخرین مورد معتبر، نه مثال داخل دستور)
    decisions = re.findall(
        r"DECISION\s*[=:]\s*(BUY|SELL|NO_TRADE|NO TRADE|REJECT|LONG|SHORT)",
        up,
    )
    # حذف مواردی که بعدش "OR" آمده (فرمت نمونه: BUY OR NO_TRADE)
    explicit = None
    for m in re.finditer(
        r"DECISION\s*[=:]\s*(BUY|SELL|NO_TRADE|NO TRADE|REJECT|LONG|SHORT)\b(?:\s*\|\s*CONF|\s*$|\s*\|)",
        up,
        flags=re.M,
    ):
        explicit = m.group(1).replace(" ", "_")
    if explicit is None and decisions:
        # اگر فقط یک تصمیم یکتا باشد
        uniq = {d.replace(" ", "_") for d in decisions}
        if len(uniq) == 1:
            explicit = next(iter(uniq))

    conf = 50
    m_conf = re.search(r"CONF(?:IDENCE)?\s*[=:]\s*(\d{1,3})", up)
    if m_conf:
        conf = max(0, min(100, int(m_conf.group(1))))

    # دلیل: ترجیح متن فارسی
    reason = ""
    m_reason = re.search(r"REASON\s*[=:]\s*(.+?)(?:\n|$)", raw_s, flags=re.I)
    if m_reason:
        reason = m_reason.group(1).strip()
    # پاک کردن انگلیسی اضافه
    if reason:
        reason = re.sub(r"(?i)(the user wants|we need to|provide|one-line|one line|decision\s*=).*$", "", reason).strip(" |:-")
    if not reason:
        # اولین جملهٔ دارای حرف فارسی
        for line in raw_s.splitlines():
            if re.search(r"[\u0600-\u06FF]", line):
                reason = re.sub(r"[A-Za-z]{4,}.*", "", line).strip(" |:-")
                if reason:
                    break
    if not reason:
        reason = "تحلیل انجام شد"
    reason = reason[:220]

    def _is_buy(d: str) -> bool:
        return d in ("BUY", "LONG")

    def _is_sell(d: str) -> bool:
        return d in ("SELL", "SHORT")

    def _is_no(d: str) -> bool:
        return d in ("NO_TRADE", "NO TRADE", "REJECT", "NONE")

    if explicit:
        if expected == "BUY" and _is_buy(explicit):
            return "confirmed", f"{reason} | ارزیابی AI: {conf}%"
        if expected == "SELL" and _is_sell(explicit):
            return "confirmed", f"{reason} | ارزیابی AI: {conf}%"
        if _is_no(explicit):
            return "rejected", f"{reason} | ارزیابی AI: {conf}%"
        return "rejected", f"{reason} | ارزیابی AI: {conf}%"

    # بدون DECISION صریح: از روی متن فارسی/کلیدی حدس نزن — رد محافظه‌کارانه
    # مگر اینکه مدل صریحاً BUY/SELL را بدون NO_TRADE گفته باشد
    has_buy = bool(re.search(r"\bBUY\b|\bLONG\b", up))
    has_sell = bool(re.search(r"\bSELL\b|\bSHORT\b", up))
    has_no = bool(re.search(r"\bNO_TRADE\b|\bNO TRADE\b|\bREJECT\b", up))
    # اگر هر دو BUY و NO_TRADE در متن نمونه باشند، قابل‌اعتماد نیست
    if has_buy and has_no and expected == "BUY":
        # متن فارسی مثبت درباره خرید؟
        if re.search(r"خرید|لانگ|تأیید|مناسب|قوی", reason):
            return "confirmed", f"{reason} | ارزیابی AI: {conf}%"
        return "rejected", f"{reason} | ارزیابی AI: {conf}%"
    if expected == "BUY" and has_buy and not has_no:
        return "confirmed", f"{reason} | ارزیابی AI: {conf}%"
    if expected == "SELL" and has_sell and not has_no:
        return "confirmed", f"{reason} | ارزیابی AI: {conf}%"
    return "rejected", f"{reason} | ارزیابی AI: {conf}%"

def confirm_signal_with_ai(chart_png: Optional[bytes], context: dict) -> tuple[str, str]:
    """تأیید/رد سیگنال با Groq — بدون json_mode (سازگار با gpt-oss)."""
    if not GROQ_API_KEY:
        return "unavailable", "کلید هوش مصنوعی تنظیم نشده است"

    compact = _ai_compact_context(context)
    direction = str(context.get("direction") or "").lower()
    expected = "BUY" if direction == "long" else "SELL"

    hist_note = ""
    he = context.get("hist_est") or {}
    if he.get("pct") is not None:
        hist_note = f" hist_winrate={he['pct']}% sample={he.get('sample')}"
    prompt = (
        f"ارز {compact.get('ticker', '?')} جهت {expected}. "
        f"امتیاز={compact.get('score')} RSI={compact.get('rsi')} ADX={compact.get('adx')} "
        f"حجم={compact.get('vol')} نسبت‌ریسک={compact.get('rr')} "
        f"شکست‌بالا={compact.get('bos_up')} شکست‌پایین={compact.get('bos_down')}{hist_note}. "
        f"اگر ستاپ خوب است فقط بنویس: DECISION={expected}|CONF=75|REASON=دو دلیل کوتاه به فارسی "
        f"اگر ضعیف است فقط بنویس: DECISION=NO_TRADE|CONF=40|REASON=دو دلیل کوتاه به فارسی "
        f"هیچ متن انگلیسی اضافه ننویس."
    )

    def _call(messages, max_tokens=220):
        body = json.dumps(
            {
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
        ).encode()
        req = urllib.request.Request(
            f"{GROQ_BASE_URL}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; SignalBot/4.0)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SECONDS) as r:
            return json.loads(r.read().decode())

    try:
        data = _call(
            [
                {"role": "system", "content": "You filter crypto futures setups. Reply one line only. CONF is only the model assessment score, not win probability. REASON must be short Persian. No English sentences."},
                {"role": "user", "content": prompt},
            ]
        )
        raw_s = _extract_ai_text(data)
        if not raw_s:
            # تلاش دوم با prompt ساده‌تر
            logger.warning(f"AI empty content, retry simple. keys={list(((data.get('choices') or [{}])[0].get('message') or {}).keys())}")
            data = _call(
                [
                    {
                        "role": "user",
                        "content": f"Say only: DECISION={expected} CONF=60 REASON=ok or DECISION=NO_TRADE CONF=40 REASON=weak",
                    }
                ],
                max_tokens=80,
            )
            raw_s = _extract_ai_text(data)
        if not raw_s:
            logger.warning(f"AI still empty: {json.dumps(data)[:500]}")
            return "unavailable", "پاسخ خالی از مدل"

        status, text = _parse_ai_decision(raw_s, expected)
        logger.info(f"AI result: {status} | {text[:120]}")
        return status, text
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:400]
        except Exception:
            pass
        logger.warning(f"AI HTTP {e.code}: {err_body}")
        return "unavailable", f"HTTP {e.code}"
    except Exception as e:
        logger.warning(f"AI analysis failed: {e}")
        return "unavailable", f"تحلیل AI در دسترس نبود: {e}"

# ===========================
# ارزیابی ارز (فیوچرز + OHLCV از بازار)
# ===========================
async def evaluate_coin(code: str, account_balance_usdt: float=1000.0, skip_cooldown: bool=False, prefer_direction: Optional[str]=None, cooldown_seconds: Optional[float]=None):
    if get_open_signal_for_ticker(code): return None,'سیگنال باز وجود دارد',None
    fd=get_futures_data(code); funding=fd.get('funding_rate'); oi=fd.get('open_interest')
    preferred_exchange=fd.get('exchange')
    if not fd.get('last_price') or not preferred_exchange or preferred_exchange == 'نامشخص':
        return None,'قیمت قرارداد دائمی در دسترس نیست',None
    dm,dh=await asyncio.gather(cache.get_ohlcv(code,MAIN_TF,preferred_exchange),cache.get_ohlcv(code,HIGHER_TF,preferred_exchange))
    if dm is None or dh is None: return None,'داده کندل قرارداد دائمی در دسترس نیست',None
    m,h=compute_indicators(dm),compute_indicators(dh)
    if m is None or h is None: return None,'اندیکاتورها محاسبه نشدند',None
    candidates=[]
    for d in (['long','short'] if not prefer_direction else [prefer_direction]):
        if m.regime == 'range':
            if d=='long' and m.edge_reversal_up and m.rsi <= 42 and m.rsi >= RSI_OVERSOLD:
                sc = 74 + (3 if m.volume_ratio >= VOLUME_STRONG else 0) + (3 if m.rsi_slope > 0 else 0)
                candidates.append((min(sc,100),d,['برگشت از حمایت','RSI پایین محدوده','کندل برگشتی'],[]))
            elif d=='short' and m.edge_reversal_down and m.rsi >= 58 and m.rsi <= RSI_OVERBOUGHT:
                sc = 74 + (3 if m.volume_ratio >= VOLUME_STRONG else 0) + (3 if m.rsi_slope < 0 else 0)
                candidates.append((min(sc,100),d,['برگشت از مقاومت','RSI بالای محدوده','کندل برگشتی'],[]))
        else:
            sc,rs,wr=setup_score(d,m,h,funding)
            structural=(m.bos_up or m.retest_long) if d=='long' else (m.bos_down or m.retest_short)
            # در نسخه متعادل، BOS/retest همچنان امتیاز مهمی دارد، اما تنها راه
            # ورود نیست؛ روند قوی + DI + ADX می‌تواند جای ساختار را بگیرد.
            strong_trend = (
                (m.trend_up if d=='long' else m.trend_down)
                and (m.plus_di > m.minus_di + MIN_DI_GAP if d=='long' else m.minus_di > m.plus_di + MIN_DI_GAP)
                and m.adx >= ADX_STRONG
            )
            if sc>=MIN_SIGNAL_SCORE and (structural or strong_trend):
                if not structural:
                    wr = list(wr) + ['بدون BOS/Retest؛ ورود بر اساس روند قوی']
                candidates.append((sc,d,rs,wr))
    if not candidates:
        return None,f'ستاپ رد شد | regime={m.regime} score<{MIN_SIGNAL_SCORE} یا ساختار/روند قوی کافی نیست | ADX={m.adx:.1f} RSI={m.rsi:.1f} +DI/-DI={m.plus_di:.1f}/{m.minus_di:.1f} BOS={m.bos_up}/{m.bos_down}',None
    candidates.sort(reverse=True); score,direction,reasons,warnings=candidates[0]
    ok,reason=check_filters(direction,m,code,funding,oi)
    if not ok: return None,reason,None
    if not skip_cooldown:
        last=get_last_closed_ts(code); cd=cooldown_seconds if cooldown_seconds is not None else SIGNAL_REOPEN_COOLDOWN_SECONDS
        if last and time.time()-last<cd: return None,'در کول‌داون بعد از آخرین بسته‌شدن',None
    target=m.recent_high if direction=='long' else m.recent_low
    plan=build_risk_plan(direction,m.close,m.atr,account_balance_usdt,target)
    if not plan.valid: return None,plan.reason,None
    setup_type = 'trend_up' if direction == 'long' else 'trend_down'
    if m.regime == 'range':
        setup_type = 'range_reversal'
    had_bos = bool(m.bos_up if direction == 'long' else m.bos_down)
    features = {
        "rsi": round(m.rsi, 2), "adx": round(m.adx, 2), "vol": round(m.volume_ratio, 3),
        "score": score, "had_bos": had_bos, "macd_hist": round(m.macd_hist, 6),
        "plus_di": round(m.plus_di, 2), "minus_di": round(m.minus_di, 2),
    }
    hist_est = estimate_success_from_history(direction, setup_type, m.rsi, m.adx, m.volume_ratio, had_bos)
    # اگر تاریخچه مشابه خیلی ضعیف باشد، سیگنال را رد کن (حداقل ۵ نمونه)
    if hist_est.get("pct") is not None and hist_est.get("sample", 0) >= 5 and hist_est["pct"] < 35:
        return None, f"تاریخچه مشابه ضعیف ({hist_est['pct']}% از {hist_est['sample']} مورد) — سیگنال رد شد", None
    ai_status, ai_text = 'unavailable', ''
    ctx = {
        'ticker': code, 'direction': direction, 'rule_score': score, 'setup_type': setup_type,
        'hist_est': hist_est,
        '1h': {'regime': m.regime, 'rsi': m.rsi, 'rsi_slope': m.rsi_slope, 'adx': m.adx, 'adx_slope': m.adx_slope,
               'plus_di': m.plus_di, 'minus_di': m.minus_di, 'macd_hist': m.macd_hist, 'volume_ratio': m.volume_ratio,
               'bos_up': m.bos_up, 'bos_down': m.bos_down, 'retest_long': m.retest_long, 'retest_short': m.retest_short,
               'lower_high': m.lower_high, 'higher_low': m.higher_low, 'distance_to_ema_atr': m.distance_to_ema_atr},
        '4h': {'trend_up': h.trend_up, 'trend_down': h.trend_down, 'adx': h.adx, 'rsi': h.rsi, 'plus_di': h.plus_di, 'minus_di': h.minus_di},
        'derivatives': {'funding_rate': funding, 'open_interest': oi},
        'risk': {'entry': plan.entry, 'stop': plan.stop_loss, 'targets': plan.targets, 'rr': plan.risk_reward},
        'rule_reasons': reasons, 'rule_warnings': warnings,
    }
    if GROQ_API_KEY:
        def _ai_call():
            with _AI_THREAD_LOCK:
                status, text = confirm_signal_with_ai(None, ctx)
                time.sleep(0.7)
                return status, text
        ai_status, ai_text = await asyncio.to_thread(_ai_call)
        if ai_status == "rejected":
            return None, "AI مستقل ستاپ را رد کرد: " + ai_text, None
    rate = fetch_irt_rate_sync()
    # سیگنال تا زمان انتخاب نهایی توسط اسکنر در پایگاه داده ثبت نمی‌شود.
    payload = (plan, setup_type, ai_status, ai_text, direction, m, funding, oi, rate, hist_est, score, features, preferred_exchange)
    return None, 'ستاپ آماده انتخاب', payload

# ===========================
# توابع کمکی
# ===========================
def render_candles_png(df: pd.DataFrame, title: str) -> Optional[bytes]:
    return None

def _setup_label_fa(st: str) -> str:
    st = (st or "").strip()
    mapping = {
        "trend_up": "روند صعودی",
        "trend_down": "روند نزولی",
        "trend_up_reverse": "چرخش به صعودی",
        "trend_down_reverse": "چرخش به نزولی",
        "range_reversal": "برگشت از لبه محدوده",
        "range_breakout": "شکست محدوده",
        "trend": "روند",
    }
    return mapping.get(st, st or "نامشخص")

def stats_summary() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        open_n = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='open'").fetchone()["n"]
        tp1_hit = c.execute("SELECT COUNT(*) AS n FROM signals WHERE highest_tp_hit>=1").fetchone()["n"]
        tp2_hit = c.execute("SELECT COUNT(*) AS n FROM signals WHERE highest_tp_hit>=2").fetchone()["n"]
        wins = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='tp3'").fetchone()["n"]
        losses = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='sl'").fetchone()["n"]
        invalidated = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='invalidated'").fetchone()["n"]
        ai_ok = c.execute("SELECT COUNT(*) AS n FROM signals WHERE ai_confirmed=1").fetchone()["n"]
        ai_no = c.execute("SELECT COUNT(*) AS n FROM signals WHERE ai_confirmed=0").fetchone()["n"]
        long_n = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='long'").fetchone()["n"]
        short_n = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='short'").fetchone()["n"]
        long_win = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='long' AND status='tp3'").fetchone()["n"]
        short_win = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='short' AND status='tp3'").fetchone()["n"]
        long_sl = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='long' AND status='sl'").fetchone()["n"]
        short_sl = c.execute("SELECT COUNT(*) AS n FROM signals WHERE direction='short' AND status='sl'").fetchone()["n"]
        best_row = c.execute("SELECT ticker, COUNT(*) as cnt FROM signals WHERE status='tp3' GROUP BY ticker ORDER BY cnt DESC LIMIT 1").fetchone()
        worst_row = c.execute("SELECT ticker, COUNT(*) as cnt FROM signals WHERE status='sl' GROUP BY ticker ORDER BY cnt DESC LIMIT 1").fetchone()
        by_setup = c.execute(
            "SELECT COALESCE(NULLIF(setup_type,''), 'نامشخص') AS st, "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status='tp3' THEN 1 ELSE 0 END) AS wins, "
            "SUM(CASE WHEN status='sl' THEN 1 ELSE 0 END) AS losses, "
            "SUM(CASE WHEN highest_tp_hit>=1 THEN 1 ELSE 0 END) AS tp1 "
            "FROM signals GROUP BY st ORDER BY total DESC"
        ).fetchall()
    total_closed = wins + losses
    winrate = (wins / total_closed * 100) if total_closed else None
    setup_lines = []
    for r in by_setup:
        t, w, l, t1 = r["total"], r["wins"], r["losses"], r["tp1"]
        closed = w + l
        wr = f"{(w/closed*100):.0f}%" if closed else "—"
        setup_lines.append(
            f"• {_setup_label_fa(r['st'])}: کل {t} | TP1 {t1} | TP3 {w} | SL {l} | نرخ {wr}"
        )
    return {
        "total_signals": total, "open": open_n, "tp1_hit": tp1_hit, "tp2_hit": tp2_hit,
        "wins": wins, "losses": losses, "invalidated": invalidated, "winrate": winrate,
        "ai_ok": ai_ok, "ai_no": ai_no,
        "long_n": long_n, "short_n": short_n,
        "long_win": long_win, "short_win": short_win, "long_sl": long_sl, "short_sl": short_sl,
        "best_coin": best_row["ticker"] if best_row else "نامشخص",
        "best_coin_count": best_row["cnt"] if best_row else 0,
        "worst_coin": worst_row["ticker"] if worst_row else "نامشخص",
        "worst_coin_count": worst_row["cnt"] if worst_row else 0,
        "setup_lines": setup_lines,
    }

# ===========================
# موتور اسکن و پایش پس‌زمینه (v4.0.1 FIX)
# ===========================
async def _safe_send_message(bot, chat_id, text, reply_to_message_id=None):
    if not chat_id:
        return None
    try:
        kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_to_message_id:
            kwargs["reply_to_message_id"] = reply_to_message_id
        return await bot.send_message(**kwargs)
    except Exception as e:
        # بعضی متن‌های AI ممکن است Markdown نامعتبر داشته باشند؛ یک بار بدون Markdown تلاش کن.
        logger.warning(f"Telegram send failed for {chat_id}: {e}")
        try:
            kwargs = {"chat_id": chat_id, "text": text}
            if reply_to_message_id:
                kwargs["reply_to_message_id"] = reply_to_message_id
            return await bot.send_message(**kwargs)
        except Exception as e2:
            logger.error(f"Telegram fallback send failed for {chat_id}: {e2}")
            return None

async def _publish_signal(app: Application, signal_id: int, payload: tuple):
    plan, setup_type, ai_status, ai_text, direction, ind, funding, oi, rate = payload[:9]
    hist_est = payload[9] if len(payload) > 9 else None
    code = None
    with _conn() as c:
        row = c.execute("SELECT ticker FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row:
            code = row["ticker"]
    if not code:
        return
    text = format_signal_message(code, direction, plan, setup_type, ai_status, ai_text, ind, funding, oi, rate, hist_est=hist_est)
    sent_channel = None
    if SEND_TO_CHANNEL and CHANNEL_ID:
        sent_channel = await _safe_send_message(app.bot, CHANNEL_ID, text)
        if sent_channel:
            set_channel_message_id(signal_id, sent_channel.message_id)
            set_channel_thread(code, signal_id, sent_channel.message_id, hashlib.sha256(text.encode("utf-8")).hexdigest())
    if SEND_TO_ADMIN and ADMIN_USER_IDS:
        for uid in list(ADMIN_USER_IDS):
            await _safe_send_message(app.bot, uid, text)
    logger.info(f"📤 Signal published: #{code} {direction} id={signal_id} ai={ai_status}")

async def periodic_scan(app: Application):
    """اسکن دوره‌ای؛ ابتدا همه نامزدها رتبه‌بندی می‌شوند و سپس فقط بهترین‌ها ثبت می‌شوند."""
    await asyncio.sleep(3)
    semaphore = asyncio.Semaphore(4)
    while True:
        started = time.time()
        try:
            slots = max(0, MAX_CONCURRENT_POSITIONS - open_positions_count())
            if slots <= 0:
                logger.info("⏸️ اسکن رد شد: سقف سیگنال‌های باز پر است")
            else:
                async def one(code):
                    async with semaphore:
                        try:
                            return code, await evaluate_coin(code)
                        except Exception as e:
                            logger.exception(f"Scan error for {code}: {e}")
                            return code, (None, f"خطای اسکن: {e}", None)
                results = await asyncio.gather(*(one(c) for c in COIN_CODES))
                candidates = []
                for code, result in results:
                    _sid, reason, payload = result
                    if payload:
                        candidates.append((float(payload[10]), code, payload))
                    elif reason and not reason.startswith(("در کول‌داون", "سیگنال باز", "داده کندل")):
                        logger.info(f"📊 {code}: {reason}")

                candidates.sort(key=lambda x: x[0], reverse=True)
                selected = candidates[:slots]
                published = 0
                for score, code, payload in selected:
                    plan, setup_type, ai_status, ai_text, direction, ind, funding, oi, rate, hist_est, _score, features, exchange_name = payload
                    signal_id = record_signal(
                        code, direction, plan.entry, plan.stop_loss, plan.targets, plan.leverage,
                        plan.risk_reward, ai_status == 'confirmed', ai_text, setup_type,
                        features=features, market_exchange=exchange_name,
                    )
                    await _publish_signal(app, signal_id, payload)
                    published += 1
                logger.info(
                    f"🔎 اسکن کامل: {len(COIN_CODES)} ارز | نامزد={len(candidates)} | "
                    f"ثبت={published}/{slots} | {time.time()-started:.1f}s"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"❌ periodic_scan crashed but will restart: {e}")
        await asyncio.sleep(SIGNAL_SCAN_INTERVAL_SECONDS)

async def _finalize_signal(app: Application, row, result: str, price: float, lesson: str):
    code = row["ticker"]
    direction = row["direction"]
    entry = safe_float(row["entry"])
    sl = safe_float(row["stop_loss"])
    features = {}
    try:
        features = json.loads(row["features_json"] or "{}")
    except Exception:
        pass
    status = "tp3" if result == "win" else "sl"
    update_signal_status(row["id"], status)
    duration = max(0.0, time.time() - float(row["created_ts"] or time.time()))
    save_experience(row["id"], code, direction, row["setup_type"] or "", result, features, duration, lesson)
    if result == "win":
        text = (f"🎯 هدف نهایی خورد | #{code}\n"
                f"📌 جهت: {'خرید (لانگ) 🟢' if direction=='long' else 'فروش (شورت) 🔴'}\n"
                f"💵 قیمت: `{fmt_usd(price)}`\n"
                f"📝 درس تجربه: {lesson}\n"
                f"📅 {shamsi_now()}")
    else:
        text = (f"❌ حد ضرر خورد | #{code}\n"
                f"📌 جهت: {'خرید (لانگ) 🟢' if direction=='long' else 'فروش (شورت) 🔴'}\n"
                f"💵 ورود: `{fmt_usd(entry)}`\n🛑 حد ضرر: `{fmt_usd(sl)}`\n"
                f"📉 قیمت: `{fmt_usd(price)}`\n"
                f"📝 درس تجربه: {lesson}\n"
                f"📅 {shamsi_now()}\nسیگنال بسته شد.")
    thread = get_channel_thread(code)
    if SEND_TO_CHANNEL and CHANNEL_ID:
        await _safe_send_message(app.bot, CHANNEL_ID, text, thread["message_id"] if thread else None)
    if SEND_TO_ADMIN:
        for uid in list(ADMIN_USER_IDS):
            await _safe_send_message(app.bot, uid, text)
    clear_channel_thread(code)

async def monitor_open_signals(app: Application):
    """پایش هر دقیقه با کندل‌های بسته‌شده ۱ دقیقه‌ای از همان صرافی مرجع."""
    await asyncio.sleep(5)
    while True:
        try:
            rows = open_signals()
            for row in rows:
                try:
                    code = row["ticker"]
                    exchange_name = row["market_exchange"]
                    if not exchange_name:
                        fd = await asyncio.to_thread(get_futures_data, code)
                        exchange_name = fd.get("exchange") or "MEXC"
                    since_ms = int(row["last_checked_candle_ts"] or ((int(float(row["created_ts"]) * 1000) // 60000) * 60000 - 60000))
                    candles = await cache.get_monitor_candles(code, exchange_name, since_ms)
                    if candles is None or candles.empty:
                        continue
                    direction = row["direction"]
                    entry = safe_float(row["entry"])
                    sl = safe_float(row["stop_loss"])
                    targets = json.loads(row["targets"] or "[]")
                    highest = int(row["highest_tp_hit"] or 0)
                    last_ts = since_ms
                    closed = False

                    for _, candle in candles.sort_values("timestamp").iterrows():
                        ts_ms = int(candle["timestamp"])
                        if ts_ms <= since_ms:
                            continue
                        high = safe_float(candle["high"])
                        low = safe_float(candle["low"])
                        close = safe_float(candle["close"])
                        last_ts = max(last_ts, ts_ms)

                        # پس از هر هدف، حد ضرر جدید برای همان کندل اعمال می‌شود.
                        active_sl = sl
                        hit_sl = low <= active_sl if direction == "long" else high >= active_sl
                        hit_tp1 = len(targets) >= 1 and (high >= targets[0] if direction == "long" else low <= targets[0])
                        hit_tp2 = len(targets) >= 2 and (high >= targets[1] if direction == "long" else low <= targets[1])
                        hit_tp3 = len(targets) >= 3 and (high >= targets[2] if direction == "long" else low <= targets[2])

                        # اگر حد ضرر و هدف در یک کندل هر دو لمس شوند، برای احتیاط حد ضرر مقدم است.
                        if hit_sl:
                            features = {}
                            try:
                                features = json.loads(row["features_json"] or "{}")
                            except Exception:
                                pass
                            duration = max(0.0, time.time() - float(row["created_ts"] or time.time()))
                            lesson = build_postmortem(direction, "loss", features, duration, close, entry)
                            await _finalize_signal(app, row, "loss", close, lesson)
                            closed = True
                            break

                        new_highest = highest
                        if hit_tp3:
                            new_highest = 3
                        elif hit_tp2:
                            new_highest = max(highest, 2)
                        elif hit_tp1:
                            new_highest = max(highest, 1)

                        if new_highest > highest:
                            new_sl = sl
                            if new_highest >= 1:
                                new_sl = entry
                            if new_highest >= 2 and len(targets) >= 1:
                                new_sl = targets[0]
                            update_signal_progress(row["id"], new_highest, new_sl)
                            highest = new_highest
                            sl = new_sl

                            title = "هدف نهایی" if new_highest == 3 else ("هدف دوم" if new_highest == 2 else "هدف اول")
                            text = (f"🎯 {title} خورد | #{code}\n"
                                    f"📌 جهت: {'خرید (لانگ) 🟢' if direction=='long' else 'فروش (شورت) 🔴'}\n"
                                    f"💵 قیمت: `{fmt_usd(close)}`\n"
                                    f"🔒 حد ضرر جدید: `{fmt_usd(new_sl)}`\n"
                                    f"📅 {shamsi_now()}")
                            thread = get_channel_thread(code)
                            if SEND_TO_CHANNEL and CHANNEL_ID:
                                await _safe_send_message(app.bot, CHANNEL_ID, text, thread["message_id"] if thread else None)
                            if SEND_TO_ADMIN:
                                for uid in list(ADMIN_USER_IDS):
                                    await _safe_send_message(app.bot, uid, text)

                            # اگر هدف و حد ضرر جدید در همان کندل هر دو لمس شده‌اند،
                            # ترتیب دقیق از OHLCV مشخص نیست؛ حالت محافظه‌کارانه را ثبت می‌کنیم.
                            post_stop_touched = False
                            if highest < 3:
                                post_stop_touched = (
                                    low <= new_sl if direction == "long" else high >= new_sl
                                )
                            if post_stop_touched:
                                features = {}
                                try:
                                    features = json.loads(row["features_json"] or "{}")
                                except Exception:
                                    pass
                                duration = max(0.0, time.time() - float(row["created_ts"] or time.time()))
                                lesson = build_postmortem(direction, "loss", features, duration, close, entry)
                                await _finalize_signal(app, row, "loss", close, lesson)
                                closed = True
                                break

                            if highest >= 3:
                                features = {}
                                try:
                                    features = json.loads(row["features_json"] or "{}")
                                except Exception:
                                    pass
                                duration = max(0.0, time.time() - float(row["created_ts"] or time.time()))
                                lesson = build_postmortem(direction, "win", features, duration, close, entry)
                                await _finalize_signal(app, row, "win", close, lesson)
                                closed = True
                                break

                    update_monitor_candle(row["id"], last_ts)
                except Exception as e:
                    logger.exception(f"Monitor error for signal {row['id']}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"❌ monitor_open_signals crashed but will restart: {e}")
        await asyncio.sleep(CHANNEL_MONITOR_INTERVAL_SECONDS)

# ===========================
# راه‌اندازی
# ===========================
async def post_init(app: Application):
    await app.bot.delete_my_commands(scope=BotCommandScopeDefault())
    await app.bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    commands = [
        BotCommand("start", "شروع و نمایش منو"),
        BotCommand("version", "نمایش نسخه ربات"),
        BotCommand("info", "اطلاعات کامل ربات"),
        BotCommand("admin", "پنل مدیریت ادمین"),
        BotCommand("stop", "توقف فعالیت ربات"),
    ]
    await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await app.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    asyncio.create_task(periodic_scan(app))
    asyncio.create_task(monitor_open_signals(app))

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN تنظیم نشده!")
        return
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("version", version_handler))
    app.add_handler(CommandHandler("info", info_handler))
    app.add_handler(CommandHandler("admin", admin_command_handler))
    app.add_handler(CommandHandler("stop", stop_command_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    logger.info(f"🚀 Version {VERSION} started at {BUILD_TIME}")
    logger.info(f"🎯 Signal filters: score>={MIN_SIGNAL_SCORE} | ADX>={ADX_TREND_MIN} | DI gap>={MIN_DI_GAP} | EMA distance<={MAX_ENTRY_DISTANCE_ATR} ATR")
    app.run_polling()

if __name__ == "__main__":
    main()
