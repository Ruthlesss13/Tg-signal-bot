# -*- coding: utf-8 -*-
"""
ربات هوشمند تحلیل فیوچرز ارزهای دیجیتال - نسخه ۳.۵.۰
- سه مسیر جدا: روند صعودی / روند نزولی / رنج
- سیگنال در شرایط مختلف بازار
- هشدار تغییر روند با ریپلای
- باطل شدن + صدور فوری سیگنال مخالف
- قالب راست‌چین + TP با ایموجی
- فیلتر حجم متعادل + تأیید AI (Groq)
- ذخیره پایدار تنظیمات ارسال سیگنال
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
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
VERSION = "3.5.2"
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
DB_PATH = os.getenv("DB_PATH", "cryptobot.sqlite3")
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

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
ADX_TREND_MIN = 22          # حداقل ADX برای سیگنال روند مطمئن
VOLUME_MIN_RATIO = 0.80     # متعادل — بازار کم‌حجم هم سیگنال می‌دهد
VOLUME_STRONG = 1.3         # حجم قوی برای امتیاز بیشتر
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
SIGNAL_SCAN_INTERVAL_SECONDS = 10 * 60
SIGNAL_REOPEN_COOLDOWN_SECONDS = 45 * 60
REVERSE_SIGNAL_COOLDOWN_SECONDS = 5 * 60  # بعد از باطل شدن به‌خاطر تغییر روند
CHANNEL_MONITOR_INTERVAL_SECONDS = 5 * 60
AI_TIMEOUT_SECONDS = 30
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")  # سریع و مناسب CONFIRM/REJECT
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CROSS_LOOKBACK = 4  # تقاطع در چند کندل اخیر معتبر است

# ===========================
# تنظیمات ارسال سیگنال (پیش‌فرض فعال)
# ===========================
SEND_TO_CHANNEL = True
SEND_TO_ADMIN = True

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
    if usd_value is None or rate is None:
        return "-"
    toman = usd_value * rate
    if toman >= 1:
        return f"{toman:,.0f} تومان"
    return f"{toman:.6f}".rstrip("0").rstrip(".") + " تومان"

def format_percent(value: float) -> str:
    if value is None:
        return "نامشخص"
    return f"{value:+.2f}%"

def safe_float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)

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
        return data
    data = fetch_futures_data_gateio(symbol)
    if data.get("last_price") is not None:
        data["exchange"] = "Gate.io"
        return data
    return {"exchange": "نامشخص", "last_price": None}

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
    closed_ts REAL
);

CREATE TABLE IF NOT EXISTS channel_messages (
    ticker TEXT PRIMARY KEY,
    signal_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL
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

def record_signal(ticker, direction, entry, stop_loss, targets, leverage, risk_reward, ai_confirmed, ai_raw_text) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO signals (ticker, direction, entry, stop_loss, targets, leverage, risk_reward, ai_confirmed, ai_raw_text, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, direction, entry, stop_loss, json.dumps(targets), leverage, risk_reward, int(ai_confirmed), ai_raw_text, time.time())
        )
        return cur.lastrowid

def update_signal_status(signal_id: int, status: str):
    with _conn() as c:
        c.execute("UPDATE signals SET status=?, closed_ts=? WHERE id=?", (status, time.time() if status != "open" else None, signal_id))

def update_signal_progress(signal_id: int, highest_tp_hit: int, new_stop_loss: float):
    with _conn() as c:
        c.execute("UPDATE signals SET highest_tp_hit=?, stop_loss=? WHERE id=?", (highest_tp_hit, new_stop_loss, signal_id))

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
        tp3 = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='tp3'").fetchone()["n"]
        sl = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='sl'").fetchone()["n"]
        return {"total": total, "open": open_count, "tp3": tp3, "sl": sl}

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
                SEND_TO_ADMIN = bool(data.get("send_to_admin", True))
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
                SEND_TO_ADMIN = bool(data.get("send_to_admin", True))
    except Exception as e:
        logger.warning(f"Error loading signal settings from DB: {e}")

def save_signal_settings():
    data = {"send_to_channel": SEND_TO_CHANNEL, "send_to_admin": SEND_TO_ADMIN}
    # فایل
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SIGNAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
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
            c.commit()
    except Exception as e:
        logger.warning(f"Error saving signal settings to DB: {e}")

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

        # نمادهای فیوچرز و اسپات (fallback)
        symbols_swap = [f"{code}/USDT:USDT" for code in COIN_CODES]
        symbols_spot = [f"{code}/USDT" for code in COIN_CODES]
        new_prices = {}

        # ۱. MEXC
        try:
            tickers = await asyncio.to_thread(exchange_mexc.fetch_tickers, symbols_swap)
            for code in COIN_CODES:
                sym = f"{code}/USDT:USDT"
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if not new_prices:
                tickers = await asyncio.to_thread(exchange_mexc.fetch_tickers, symbols_spot)
                for code in COIN_CODES:
                    sym = f"{code}/USDT"
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
            if not new_prices:
                tickers = await asyncio.to_thread(exchange_gate.fetch_tickers, symbols_spot)
                for code in COIN_CODES:
                    sym = f"{code}/USDT"
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
            for sym in [f"{code}/USDT:USDT", f"{code}/USDT"]:
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

    async def get_ohlcv(self, code: str, timeframe: str = "1h") -> Optional[pd.DataFrame]:
        """دریافت OHLCV از بازار فیوچرز (swap)"""
        symbols_to_try = [f"{code}/USDT:USDT", f"{code}/USDT"]

        for exchange, name in [(exchange_mexc, "MEXC"), (exchange_gate, "Gate.io")]:
            for symbol in symbols_to_try:
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
                    continue

        logger.warning(f"OHLCV unavailable for {code} on all exchanges/symbols")
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
    trend_up: bool
    trend_down: bool
    ema_cross_up: bool
    ema_cross_down: bool
    rsi: float
    rsi_in_zone: bool
    macd_cross_up: bool
    macd_cross_down: bool
    atr: float
    volume_ratio: float
    structure_breakout_up: bool
    structure_breakout_down: bool
    structure_level: float
    edge_reversal_up: bool
    edge_reversal_down: bool
    adx: float
    close: float

def compute_indicators(df: pd.DataFrame) -> Optional[IndicatorSnapshot]:
    if df is None or len(df) < max(EMA_SLOW, VOLUME_MA_PERIOD, STRUCTURE_LOOKBACK) + 5:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    ema_fast = EMAIndicator(close, window=EMA_FAST).ema_indicator()
    ema_slow = EMAIndicator(close, window=EMA_SLOW).ema_indicator()
    rsi = RSIIndicator(close, window=RSI_PERIOD).rsi()
    macd_ind = MACD(close, window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL)
    macd_line = macd_ind.macd()
    macd_signal = macd_ind.macd_signal()
    atr = AverageTrueRange(high, low, close, window=ATR_PERIOD).average_true_range()
    adx = ADXIndicator(high, low, close, window=ADX_PERIOD).adx()
    stoch_rsi = StochRSIIndicator(close, window=14).stochrsi().iloc[-1] * 100 if len(close) > 20 else 50
    bollinger = BollingerBands(close, window=20)
    bb_upper = bollinger.bollinger_hband().iloc[-1] if len(close) > 20 else close.iloc[-1] * 1.05
    bb_lower = bollinger.bollinger_lband().iloc[-1] if len(close) > 20 else close.iloc[-1] * 0.95

    last_close = float(close.iloc[-1])
    trend_up = last_close > ema_fast.iloc[-1] > ema_slow.iloc[-1]
    trend_down = last_close < ema_fast.iloc[-1] < ema_slow.iloc[-1]

    # تقاطع در چند کندل اخیر (به جای فقط کندل آخر) — سیگنال بیشتر و معتبرتر
    def _recent_cross_up(fast_s, slow_s, lookback: int = CROSS_LOOKBACK) -> bool:
        for i in range(1, min(lookback + 1, len(fast_s) - 1)):
            if fast_s.iloc[-i - 1] <= slow_s.iloc[-i - 1] and fast_s.iloc[-i] > slow_s.iloc[-i]:
                return True
        return False

    def _recent_cross_down(fast_s, slow_s, lookback: int = CROSS_LOOKBACK) -> bool:
        for i in range(1, min(lookback + 1, len(fast_s) - 1)):
            if fast_s.iloc[-i - 1] >= slow_s.iloc[-i - 1] and fast_s.iloc[-i] < slow_s.iloc[-i]:
                return True
        return False

    ema_cross_up = _recent_cross_up(ema_fast, ema_slow)
    ema_cross_down = _recent_cross_down(ema_fast, ema_slow)

    last_rsi = float(rsi.iloc[-1])
    rsi_in_zone = RSI_MIN <= last_rsi <= RSI_MAX

    macd_cross_up = _recent_cross_up(macd_line, macd_signal)
    macd_cross_down = _recent_cross_down(macd_line, macd_signal)

    vol_ma = volume.rolling(VOLUME_MA_PERIOD).mean().iloc[-1]
    volume_ratio = float(volume.iloc[-1] / vol_ma) if vol_ma else 0.0

    recent_high = float(high.iloc[-STRUCTURE_LOOKBACK:-1].max())
    recent_low = float(low.iloc[-STRUCTURE_LOOKBACK:-1].min())
    structure_breakout_up = last_close > recent_high
    structure_breakout_down = last_close < recent_low

    last_open = float(df["open"].iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])
    last_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0
    near_low = (last_low - recent_low) <= last_atr
    near_high = (recent_high - last_high) <= last_atr
    bullish_rejection_candle = last_close > last_open and last_close > (last_low + (last_high - last_low) * 0.5)
    bearish_rejection_candle = last_close < last_open and last_close < (last_high - (last_high - last_low) * 0.5)
    edge_reversal_up = near_low and bullish_rejection_candle and not structure_breakout_down
    edge_reversal_down = near_high and bearish_rejection_candle and not structure_breakout_up

    return IndicatorSnapshot(
        trend_up=trend_up,
        trend_down=trend_down,
        ema_cross_up=bool(ema_cross_up),
        ema_cross_down=bool(ema_cross_down),
        rsi=last_rsi,
        rsi_in_zone=rsi_in_zone,
        macd_cross_up=bool(macd_cross_up),
        macd_cross_down=bool(macd_cross_down),
        atr=float(atr.iloc[-1]),
        volume_ratio=volume_ratio,
        structure_breakout_up=structure_breakout_up,
        structure_breakout_down=structure_breakout_down,
        structure_level=recent_high if structure_breakout_up else recent_low,
        edge_reversal_up=edge_reversal_up,
        edge_reversal_down=edge_reversal_down,
        adx=float(adx.iloc[-1]),
        close=last_close,
    )

# ===========================
# فیلترها
# ===========================
def check_filters(direction: str, indicators: IndicatorSnapshot, code: str, funding_rate: Optional[float] = None, oi: Optional[float] = None) -> tuple[bool, str]:
    if indicators.volume_ratio < VOLUME_MIN_RATIO:
        return False, f"نسبت حجم {indicators.volume_ratio:.2f} کمتر از {VOLUME_MIN_RATIO}"
    
    if funding_rate is not None and direction == "long" and funding_rate > FUNDING_RATE_MAX_FOR_LONG:
        return False, f"فاندینگ {funding_rate:.4%} برای لانگ خیلی مثبت است"
    
    if oi is not None and oi <= 0:
        return False, "Open Interest صفر یا منفی است"
    
    fg = get_fear_greed_index()
    if fg is not None:
        if direction == "long" and fg >= FEAR_GREED_EXTREME_GREED:
            return False, f"شاخص طمع شدید ({fg})"
        if direction == "short" and fg <= FEAR_GREED_EXTREME_FEAR:
            return False, f"شاخص ترس شدید ({fg})"
    
    h = datetime.now(timezone.utc).hour
    if (h >= LOW_VOLUME_UTC_START_HOUR) or (h < LOW_VOLUME_UTC_END_HOUR):
        return False, f"ساعت {h}:00 UTC در بازه کم‌حجم"
    
    return True, "تمام فیلترها عبور کردند"

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
    if risk_reward < MIN_RISK_REWARD:
        return RiskPlan(direction, entry, stop_loss, targets, leverage, 0.0, risk_reward, False, f"RR {risk_reward:.2f} < {MIN_RISK_REWARD}")

    risk_amount = account_balance_usdt * (RISK_PER_TRADE_PCT / 100)
    position_size = risk_amount / stop_distance if stop_distance else 0
    position_size_usdt = position_size * entry

    return RiskPlan(direction, entry, stop_loss, targets, leverage, position_size_usdt, risk_reward, True, "ok")

# ===========================
# تحلیل کامل ارز (قیمت از فیوچرز، OHLCV از اسپات)
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

        # دریافت OHLCV از اسپات
        tasks = [
            cache.get_ohlcv(code, "1h"),
            cache.get_ohlcv(code, "4h"),
            cache.get_ohlcv(code, "1d")
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
def get_signal_strength_and_confidence(ind: IndicatorSnapshot, funding: Optional[float], oi: Optional[float]) -> tuple[str, str, int]:
    """محاسبه قدرت سیگنال، ضریب اطمینان و امتیاز"""
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
        strength = "بسیار قوی 🌟"
        conf_text = f"{confidence}% (بسیار بالا 🌟)"
    elif confidence >= 60:
        strength = "قوی 🟢"
        conf_text = f"{confidence}% (بالا 🟢)"
    elif confidence >= 40:
        strength = "متوسط 🟡"
        conf_text = f"{confidence}% (متوسط 🟡)"
    else:
        strength = "ضعیف 🔴"
        conf_text = f"{confidence}% (پایین 🔴)"
    return strength, conf_text, score

def format_signal_message(code: str, direction: str, plan: RiskPlan, setup_type: str, ai_status: str, ai_text: str, ind: IndicatorSnapshot, funding: Optional[float], oi: Optional[float], rate: float) -> str:
    """قالب‌بندی پیام سیگنال — شیک، راست‌چین، TP با ایموجی"""
    if setup_type in ("trend_up", "trend", "trend_up_reverse"):
        setup_label = "روند صعودی 📈" if "reverse" not in setup_type else "چرخش به صعودی 🔄📈"
    elif setup_type in ("trend_down", "trend_down_reverse"):
        setup_label = "روند نزولی 📉" if "reverse" not in setup_type else "چرخش به نزولی 🔄📉"
    elif setup_type == "range_breakout":
        setup_label = "شکست رنج ⚡"
    else:
        setup_label = "برگشت از لبه رنج 🔄"
    dir_fa = "لانگ 🟢" if direction == "long" else "شورت 🔴"

    strength, confidence_text, score = get_signal_strength_and_confidence(ind, funding, oi)

    tp_emojis = {1: "🚀", 2: "💰", 3: "🏆"}
    targets_lines = []
    for i, t in enumerate(plan.targets, 1):
        em = tp_emojis.get(i, "🎯")
        targets_lines.append(
            f"{em} **TP{i}**\n"
            f"   • دلاری: `{fmt_usd(t)}` USDT\n"
            f"   • تومانی: {fmt_toman(t, rate)}"
        )

    if ai_status == "confirmed":
        ai_line = "✅ تأیید"
    elif ai_status == "rejected":
        ai_line = "⚠️ عدم تأیید (فقط اطلاعاتی)"
    else:
        ai_line = "⏳ در دسترس نبود"

    # نظر کوتاه AI
    opinion = (ai_text or "").strip()
    for bad in ("CONFIRM", "REJECT", "confirm", "reject"):
        if opinion.upper().startswith(bad):
            opinion = opinion[len(bad):].lstrip(" :-–—|.")
    opinion = opinion.strip()
    if opinion.upper() in ("CONFIRM", "REJECT"):
        opinion = ""
    # اگر AI رد کرده ولی نظری نداده، حداقل یک توضیح پیش‌فرض
    if ai_status == "rejected" and not opinion:
        opinion = "ستاپ از نظر AI قدرت کافی ندارد"
    if ai_status == "confirmed" and not opinion:
        opinion = "ستاپ از نظر AI قابل‌قبول است"

    funding_text = safe_format_percent(funding)
    oi_text = f"{safe_float(oi):,.0f}" if oi is not None else "نامشخص"
    rtl = "\u200F"

    text = (
        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
        f"{rtl}🚨 **سیگنال جدید فیوچرز** — #{code}\n"
        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{rtl}📊 **جهت:** {dir_fa}\n"
        f"{rtl}📌 **استراتژی:** {setup_label}\n"
        f"{rtl}📈 **قدرت:** {strength}\n"
        f"{rtl}🎯 **اطمینان:** {confidence_text}\n\n"
        f"{rtl}💰 **قیمت ورود**\n"
        f"{rtl}   • دلاری: `{fmt_usd(plan.entry)}` USDT\n"
        f"{rtl}   • تومانی: {fmt_toman(plan.entry, rate)}\n\n"
        f"{rtl}🎯 **اهداف**\n"
        + "\n".join(f"{rtl}{line}" for line in targets_lines) + "\n\n"
        f"{rtl}🛑 **حد ضرر**\n"
        f"{rtl}   • دلاری: `{fmt_usd(plan.stop_loss)}` USDT\n"
        f"{rtl}   • تومانی: {fmt_toman(plan.stop_loss, rate)}\n\n"
        f"{rtl}⚙️ **ریسک**\n"
        f"{rtl}   • اهرم: `{plan.leverage}x`\n"
        f"{rtl}   • R:R  `1:{plan.risk_reward:.2f}`\n\n"
        f"{rtl}📊 **داده بازار**\n"
        f"{rtl}   • RSI `{ind.rsi:.1f}`  |  ADX `{ind.adx:.1f}`\n"
        f"{rtl}   • حجم `{ind.volume_ratio:.2f}x`  |  فاندینگ `{funding_text}`\n"
        f"{rtl}   • OI `{oi_text}`  |  ترس‌وطمع `{get_fg_text()}`\n\n"
        f"{rtl}📅 `{shamsi_now()}`\n"
        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
        f"{rtl}🤖 **هوش مصنوعی:** {ai_line}"
    )
    if opinion:
        text += f"\n{rtl}💬 **نظر:** {opinion}"
    return text

# ===========================
# پنل مدیریت کامل (بدون کلمه اسپات)
# ===========================
def get_admin_stats_text() -> str:
    db = get_db_stats()
    uptime = int(time.time() - START_TIME)
    days = uptime // 86400
    hours = (uptime % 86400) // 3600
    minutes = (uptime % 3600) // 60

    total_users = len(registered_users)
    active_users = len(registered_users - paused_users)
    paused_users_count = len(paused_users)

    total_signals = db["total"]
    open_signals = db["open"]
    closed = db["tp3"] + db["sl"]
    wins = db["tp3"]
    losses = db["sl"]
    winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    best_coin = "نامشخص"
    worst_coin = "نامشخص"
    with _conn() as c:
        best_row = c.execute("SELECT ticker, COUNT(*) as cnt FROM signals WHERE status='tp3' GROUP BY ticker ORDER BY cnt DESC LIMIT 1").fetchone()
        if best_row:
            best_coin = best_row["ticker"]
        worst_row = c.execute("SELECT ticker, COUNT(*) as cnt FROM signals WHERE status='sl' GROUP BY ticker ORDER BY cnt DESC LIMIT 1").fetchone()
        if worst_row:
            worst_coin = worst_row["ticker"]

    text = (
        f"👑 **پنل مدیریت جامع**\n"
        f"{'────────────────────'}\n"
        f"🤖 **اطلاعات برنامه:**\n"
        f"   • نسخه: `{VERSION}`\n"
        f"   • زمان ساخت: `{BUILD_TIME}`\n"
        f"   • زمان اجرا: `{shamsi_now()}`\n"
        f"   • آپتایم: `{days} روز {hours} ساعت {minutes} دقیقه`\n"
        f"   • پایتون: `{sys.version.split()[0]}`\n"
        f"{'────────────────────'}\n"
        f"👥 **آمار کاربران:**\n"
        f"   • کل کاربران: `{total_users}`\n"
        f"   • فعال: `{active_users}`\n"
        f"   • متوقف: `{paused_users_count}`\n"
        f"{'────────────────────'}\n"
        f"📊 **آمار سیگنال‌ها:**\n"
        f"   • کل تولیدشده: `{total_signals}`\n"
        f"   • باز: `{open_signals}`\n"
        f"   • بسته شده: `{closed}`\n"
        f"   • موفق (TP3): `{wins}`\n"
        f"   • ناموفق (SL): `{losses}`\n"
        f"   • وین‌ریت: `{winrate:.1f}%`\n"
        f"   • بهترین ارز: `{best_coin}`\n"
        f"   • بدترین ارز: `{worst_coin}`\n"
        f"{'────────────────────'}\n"
        f"🏛 **وضعیت سیستم:**\n"
        f"   • صرافی فعال: `{cache.active_exchange_name}`\n"
        f"   • وضعیت صرافی‌ها:\n{get_exchange_status_text()}\n"
        f"   • نرخ تتر (Wallex): {get_irt_rate_status()}\n"
        f"   • شاخص ترس/طمع: {get_fg_status()}\n"
        f"   • هوش مصنوعی: {'✅ فعال' if GROQ_API_KEY else '❌ غیرفعال'}\n"
        f"{'────────────────────'}\n"
        f"💾 **دیتابیس:**\n"
        f"   • مسیر: `{DB_PATH}`\n"
        f"   • تعداد رکوردها: `{total_signals}`\n"
        f"{'────────────────────'}\n"
        f"📢 **کانال تلگرام:**\n"
        f"   • شناسه: `{CHANNEL_ID if CHANNEL_ID else 'تنظیم نشده'}`\n"
        f"{'────────────────────'}\n"
        f"⚙️ **تنظیمات فعال:**\n"
        f"   • اهرم: `{MIN_LEVERAGE}-{MAX_LEVERAGE}x`\n"
        f"   • حداقل RR: `1:{MIN_RISK_REWARD}`\n"
        f"   • ریسک هر معامله: `{RISK_PER_TRADE_PCT}%`\n"
        f"   • فیلتر حجم: `{VOLUME_MIN_RATIO}x`\n"
        f"   • کول‌داون: `{SIGNAL_REOPEN_COOLDOWN_SECONDS//60} دقیقه`\n"
        f"   • پوزیشن‌های همزمان: `{MAX_CONCURRENT_POSITIONS}`\n"
        f"   • ارسال به کانال: {'✅ فعال' if SEND_TO_CHANNEL else '❌ غیرفعال'}\n"
        f"   • ارسال به ربات: {'✅ فعال' if SEND_TO_ADMIN else '❌ غیرفعال'}\n"
    )
    return text

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
                "direction": "long", "ticker": "BTC", "rsi": "50", "adx": "25",
                "volume_ratio": "1.2", "funding_rate": "0.01%",
            })
            if status in ("confirmed", "rejected"):
                result.append("   ✅ AI فعال است و پاسخ می‌دهد")
            else:
                result.append(f"   ⚠️ AI پاسخ نامعتبر: {text}")
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
        [InlineKeyboardButton("📈 آمار دقیق سیگنال‌ها و عملکرد", callback_data="admin_signal_stats")],
        [InlineKeyboardButton("👥 آمار کاربران و وضعیت سیستم", callback_data="admin_system_stats")],
        [InlineKeyboardButton("📤 تنظیمات ارسال سیگنال", callback_data="admin_signal_settings")],
        [InlineKeyboardButton("🧪 تست کامل سیستم", callback_data="admin_system_test")],
        [InlineKeyboardButton("🗑 صفر کردن تمام آمار سیگنال‌ها", callback_data="reset_stats_confirm")],
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

def kb_reset_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، تمام آمار سیگنال‌ها صفر شود", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ انصراف", callback_data="admin_panel")]
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
        await query.edit_message_text(
            f"📈 **آمار سیگنال‌ها**\n{'────────────────────'}\n"
            f"🔢 کل سیگنال‌های تولیدشده: `{s['total_signals']}`\n"
            f"✅ سیگنال‌های موفق (TP3): `{s['wins']}`\n"
            f"❌ سیگنال‌های ناموفق (SL): `{s['losses']}`\n"
            f"🏆 نرخ پیروزی (وین‌ریت): `{winrate}`\n"
            f"🤖 رد شده توسط هوش مصنوعی: `{s['rejected_by_ai']}`",
            reply_markup=kb_back_admin(),
            parse_mode="Markdown"
        )
        return

    if data == "admin_system_stats":
        if not is_adm: return
        text = get_admin_stats_text()
        await query.edit_message_text(text, reply_markup=kb_back_admin(), parse_mode="Markdown")
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
            reply_markup=kb_back_admin(),
            parse_mode="Markdown"
        )
        return

# ===========================
# هوش مصنوعی (Groq — بدون ذکر نام مدل در پیام کاربر)
# ===========================
AI_PROMPT_TEMPLATE = (
    "Crypto futures setup filter.\n"
    "Reply in EXACTLY this format (2 lines):\n"
    "CONFIRM or REJECT\n"
    "Short reason in Persian (max 15 words)\n\n"
    "Setup: {direction} {ticker} | RSI:{rsi} | ADX:{adx} | Vol:{volume_ratio}x | Funding:{funding_rate}\n"
    "CONFIRM if ADX>=18 and RSI 28-72 and direction looks ok. Else REJECT with reason."
)

def confirm_signal_with_ai(chart_png: Optional[bytes], context: dict) -> tuple[str, str]:
    if not GROQ_API_KEY:
        return "unavailable", ""

    prompt = AI_PROMPT_TEMPLATE.format(**context)
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Always answer with 2 lines.\n"
                    "Line1: only CONFIRM or REJECT\n"
                    "Line2: short useful reason in Persian about RSI/ADX/volume/entry quality."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 120,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{GROQ_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; SignalBot/3.5)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SECONDS) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        text = str(text).strip()
        lines = [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
        status_line = lines[0] if lines else text
        upper = status_line.upper()

        opinion_parts = []
        for ln in lines[1:]:
            clean = ln.strip()
            if clean.upper() in ("CONFIRM", "REJECT"):
                continue
            opinion_parts.append(clean)
        opinion = " ".join(opinion_parts).strip()

        if not opinion:
            for sep in (" - ", " – ", " — ", ": ", "| ", ". "):
                if sep in status_line:
                    left, right = status_line.split(sep, 1)
                    if left.upper().strip() in ("CONFIRM", "REJECT"):
                        opinion = right.strip()
                        upper = left.upper().strip()
                        break
            if not opinion and " " in status_line:
                toks = status_line.split(None, 1)
                if toks[0].upper() in ("CONFIRM", "REJECT") and len(toks) > 1:
                    upper = toks[0].upper()
                    opinion = toks[1].strip()

        for bad in ("CONFIRM", "REJECT", "confirm", "reject"):
            if opinion.upper().startswith(bad):
                opinion = opinion[len(bad):].lstrip(" :-–—|.")
        opinion = opinion.strip()[:200]

        if upper.startswith("CONFIRM") and not upper.startswith("REJECT"):
            return "confirmed", opinion
        if "REJECT" in upper:
            return "rejected", opinion
        return "rejected", (opinion or text[:160])
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:200]
        except Exception:
            pass
        logger.warning(f"AI HTTP {e.code}: {err_body}")
        return "unavailable", ""
    except Exception as e:
        logger.warning(f"AI error: {e}")
        return "unavailable", ""

# ===========================
# توابع اسکن و مانیتورینگ
# ===========================
async def periodic_scan(app: Application):
    while True:
        try:
            logger.info("🔍 اسکن دوره‌ای فیوچرز شروع شد...")
            issued = 0
            rejected = 0
            for code in COIN_CODES:
                try:
                    signal_id, reason, data = await evaluate_coin(code)
                    if signal_id and data:
                        plan, setup_type, ai_status, ai_text, direction, ind, funding, oi, rate = data
                        await send_signal(app, code, signal_id, direction, plan, setup_type, ai_status, ai_text, ind, funding, oi, rate)
                        issued += 1
                        logger.info(f"✅ {code}: سیگنال صادر شد | جهت={direction} | setup={setup_type} | AI={ai_status} | دلیل={reason}")
                    else:
                        rejected += 1
                        logger.info(f"❌ {code}: رد شد — {reason}")
                except Exception as e:
                    rejected += 1
                    logger.exception(f"Error scanning {code}: {e}")
            logger.info(f"✅ اسکن تمام شد | صادر={issued} | رد={rejected} | کل={len(COIN_CODES)}")
            await asyncio.sleep(SIGNAL_SCAN_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            await asyncio.sleep(60)

async def monitor_open_signals(app: Application):
    while True:
        try:
            for row in open_signals():
                code = row["ticker"]
                futures_data = get_futures_data(code)
                price = futures_data.get("last_price")
                if price is None or price == 0.0:
                    continue
                
                targets = json.loads(row["targets"])
                direction = row["direction"]
                stop_loss = row["stop_loss"]
                signal_id = row["id"]
                reply_id = row["channel_message_id"]
                highest = row["highest_tp_hit"]
                rtl = "\u200F"

                # ——— حد ضرر ———
                hit_sl = (price <= stop_loss) if direction == "long" else (price >= stop_loss)
                if hit_sl:
                    text = (
                        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                        f"{rtl}❌ **حد ضرر فعال شد** — #{code}\n"
                        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"{rtl}📌 جهت: {'لانگ 🟢' if direction == 'long' else 'شورت 🔴'}\n"
                        f"{rtl}💰 ورود: `{row['entry']:.6f}`\n"
                        f"{rtl}🛑 حد ضرر: `{stop_loss:.6f}`\n"
                        f"{rtl}📉 قیمت فعلی: `{price:.6f}`\n\n"
                        f"{rtl}سیگنال بسته شد.\n"
                        f"{rtl}📅 `{shamsi_now()}`"
                    )
                    if CHANNEL_ID and reply_id:
                        await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_id)
                    update_signal_status(signal_id, "sl")
                    clear_channel_thread(code)
                    _trend_warned.discard(signal_id)
                    continue

                # ——— تارگت‌ها ———
                if highest < 1:
                    if (price >= targets[0] if direction == "long" else price <= targets[0]):
                        text = (
                            f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                            f"{rtl}🚀 **TP1 محقق شد** — #{code}\n"
                            f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"{rtl}🎯 هدف ۱: `{targets[0]:.6f}`\n"
                            f"{rtl}📉 قیمت فعلی: `{price:.6f}`\n"
                            f"{rtl}🔒 حد ضرر → نقطه ورود: `{row['entry']:.6f}`\n\n"
                            f"{rtl}بخشی از سود را می‌توانید ذخیره کنید.\n"
                            f"{rtl}📅 `{shamsi_now()}`"
                        )
                        if CHANNEL_ID and reply_id:
                            await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_id)
                        update_signal_progress(signal_id, 1, row["entry"])
                        continue
                if highest < 2:
                    if (price >= targets[1] if direction == "long" else price <= targets[1]):
                        text = (
                            f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                            f"{rtl}💰 **TP2 محقق شد** — #{code}\n"
                            f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"{rtl}🎯 هدف ۲: `{targets[1]:.6f}`\n"
                            f"{rtl}📉 قیمت فعلی: `{price:.6f}`\n"
                            f"{rtl}🔒 حد ضرر → TP1: `{targets[0]:.6f}`\n\n"
                            f"{rtl}ریسک معامله عملاً پوشش داده شد.\n"
                            f"{rtl}📅 `{shamsi_now()}`"
                        )
                        if CHANNEL_ID and reply_id:
                            await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_id)
                        update_signal_progress(signal_id, 2, targets[0])
                        continue
                if (price >= targets[2] if direction == "long" else price <= targets[2]):
                    text = (
                        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                        f"{rtl}🏆 **TP3 محقق شد** — #{code}\n"
                        f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"{rtl}🎯 هدف نهایی: `{targets[2]:.6f}`\n"
                        f"{rtl}📉 قیمت فعلی: `{price:.6f}`\n\n"
                        f"{rtl}✅ سیگنال با موفقیت بسته شد.\n"
                        f"{rtl}📅 `{shamsi_now()}`"
                    )
                    if CHANNEL_ID and reply_id:
                        await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_id)
                    update_signal_status(signal_id, "tp3")
                    clear_channel_thread(code)
                    _trend_warned.discard(signal_id)
                    continue

                # ——— هشدار تغییر روند (قبل و بعد از تارگت) ———
                if signal_id not in _trend_warned and CHANNEL_ID and reply_id:
                    try:
                        df_1h = await cache.get_ohlcv(code, MAIN_TF)
                        df_4h = await cache.get_ohlcv(code, HIGHER_TF)
                        ind_1h = compute_indicators(df_1h) if df_1h is not None else None
                        ind_4h = compute_indicators(df_4h) if df_4h is not None else None
                        flipped = False
                        reason_bits = []
                        if ind_1h:
                            if direction == "long" and ind_1h.trend_down and ind_1h.adx >= ADX_RANGE_THRESHOLD:
                                flipped = True
                                reason_bits.append(f"۱س: روند نزولی (ADX={ind_1h.adx:.1f})")
                            if direction == "short" and ind_1h.trend_up and ind_1h.adx >= ADX_RANGE_THRESHOLD:
                                flipped = True
                                reason_bits.append(f"۱س: روند صعودی (ADX={ind_1h.adx:.1f})")
                        if ind_4h:
                            if direction == "long" and ind_4h.trend_down and ind_4h.adx >= ADX_TREND_MIN:
                                flipped = True
                                reason_bits.append(f"۴س: روند نزولی قوی (ADX={ind_4h.adx:.1f})")
                            if direction == "short" and ind_4h.trend_up and ind_4h.adx >= ADX_TREND_MIN:
                                flipped = True
                                reason_bits.append(f"۴س: روند صعودی قوی (ADX={ind_4h.adx:.1f})")
                        if flipped:
                            if highest == 0:
                                stage = "هنوز هیچ تارگتی نخورده"
                            else:
                                stage = f"پس از رسیدن به TP{highest}"
                            text = (
                                f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                                f"{rtl}⚠️ **هشدار تغییر روند** — #{code}\n"
                                f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"{rtl}📌 سیگنال باز: {'لانگ 🟢' if direction == 'long' else 'شورت 🔴'}\n"
                                f"{rtl}📍 وضعیت: {stage}\n"
                                f"{rtl}🔍 دلیل: {' | '.join(reason_bits)}\n\n"
                                f"{rtl}لطفاً مدیریت ریسک و حد ضرر را بررسی کنید.\n"
                                f"{rtl}📅 `{shamsi_now()}`"
                            )
                            await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_id)
                            _trend_warned.add(signal_id)
                            # اگر هنوز هیچ تارگتی نزده و روند خلاف قوی است → باطل + تلاش برای سیگنال مخالف
                            if highest == 0 and ind_4h and (
                                (direction == "long" and ind_4h.trend_down and ind_4h.adx >= ADX_TREND_MIN) or
                                (direction == "short" and ind_4h.trend_up and ind_4h.adx >= ADX_TREND_MIN)
                            ):
                                inv_text = (
                                    f"{rtl}━━━━━━━━━━━━━━━━━━━━\n"
                                    f"{rtl}🚫 **سیگنال باطل شد** — #{code}\n"
                                    f"{rtl}━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"{rtl}دلیل: تغییر روند قوی در تایم بالاتر\n"
                                    f"{rtl}در حال بررسی جهت مخالف...\n\n"
                                    f"{rtl}📅 `{shamsi_now()}`"
                                )
                                await app.bot.send_message(CHANNEL_ID, inv_text, parse_mode="Markdown", reply_to_message_id=reply_id)
                                update_signal_status(signal_id, "invalidated")
                                clear_channel_thread(code)
                                _trend_warned.discard(signal_id)

                                # صدور فوری سیگنال مخالف (بدون فرصت‌سوزی)
                                opp = "short" if direction == "long" else "long"
                                try:
                                    new_id, rev_reason, rev_data = await evaluate_coin(
                                        code,
                                        skip_cooldown=True,
                                        prefer_direction=opp,
                                        cooldown_seconds=REVERSE_SIGNAL_COOLDOWN_SECONDS,
                                    )
                                    if new_id and rev_data:
                                        plan, setup_type, ai_status, ai_text, new_dir, ind, funding, oi, rate = rev_data
                                        await send_signal(
                                            app, code, new_id, new_dir, plan, setup_type,
                                            ai_status, ai_text, ind, funding, oi, rate,
                                        )
                                        logger.info(
                                            f"🔄 {code}: سیگنال مخالف صادر شد | {direction}→{new_dir} | "
                                            f"setup={setup_type} | AI={ai_status}"
                                        )
                                    else:
                                        logger.info(f"🔄 {code}: سیگنال مخالف صادر نشد — {rev_reason}")
                                except Exception as re:
                                    logger.warning(f"Reverse signal failed for {code}: {re}")
                    except Exception as te:
                        logger.warning(f"Trend-check failed for {code}: {te}")

            await asyncio.sleep(CHANNEL_MONITOR_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            await asyncio.sleep(60)

# ===========================
# ارسال سیگنال (با در نظر گرفتن تنظیمات)
# ===========================
async def send_signal(app: Application, code: str, signal_id: int, direction: str, plan: RiskPlan, setup_type: str, ai_status: str, ai_text: str, ind: IndicatorSnapshot, funding: Optional[float], oi: Optional[float], rate: float):
    text = format_signal_message(code, direction, plan, setup_type, ai_status, ai_text, ind, funding, oi, rate)
    thread = get_channel_thread(code)
    reply_to_id = thread["message_id"] if thread else None
    
    if SEND_TO_CHANNEL and CHANNEL_ID:
        try:
            msg = await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_to_id)
            set_channel_thread(code, signal_id, msg.message_id, hashlib.sha256(text.encode()).hexdigest())
            set_channel_message_id(signal_id, msg.message_id)
        except Exception as e:
            logger.warning(f"Send to channel failed: {e}")
    
    if SEND_TO_ADMIN:
        for admin_id in ADMIN_USER_IDS:
            try:
                await app.bot.send_message(admin_id, text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Send to admin {admin_id} failed: {e}")

# ===========================
# ارزیابی ارز (فیوچرز + OHLCV از بازار)
# ===========================
async def evaluate_coin(
    code: str,
    account_balance_usdt: float = 1000.0,
    skip_cooldown: bool = False,
    prefer_direction: Optional[str] = None,
    cooldown_seconds: Optional[float] = None,
):
    """
    prefer_direction: فقط همین جهت را بررسی کن (مثلاً بعد از باطل شدن سیگنال مخالف)
    skip_cooldown: نادیده گرفتن کول‌داون عادی
    cooldown_seconds: اگر داده شود به‌جای کول‌داون پیش‌فرض استفاده می‌شود
    """
    existing = get_open_signal_for_ticker(code)
    if existing:
        return None, "سیگنال باز وجود دارد", None

    df_main_task = cache.get_ohlcv(code, MAIN_TF)
    df_higher_task = cache.get_ohlcv(code, HIGHER_TF)
    df_main, df_higher = await asyncio.gather(df_main_task, df_higher_task)
    
    if df_main is None or df_higher is None:
        return None, "داده OHLCV در دسترس نیست", None

    ind_main = compute_indicators(df_main)
    ind_higher = compute_indicators(df_higher)
    if ind_main is None or ind_higher is None:
        return None, "اندیکاتورها محاسبه نشدند", None

    direction = None
    setup_type = ""

    # ——— مسیر ۱: روند صعودی (بدون نیاز اجباری به تقاطع) ———
    if ind_main.adx >= ADX_RANGE_THRESHOLD and ind_main.trend_up:
        if 30 <= ind_main.rsi <= 70:
            direction, setup_type = "long", "trend_up"

    # ——— مسیر ۲: روند نزولی ———
    if direction is None and ind_main.adx >= ADX_RANGE_THRESHOLD and ind_main.trend_down:
        if 30 <= ind_main.rsi <= 70:
            direction, setup_type = "short", "trend_down"

    # ——— مسیر ۳: رنج (برگشت از لبه یا نزدیک حمایت/مقاومت) ———
    if direction is None and ind_main.adx < ADX_RANGE_THRESHOLD:
        if ind_main.edge_reversal_up and ind_main.rsi <= 45:
            direction, setup_type = "long", "range_reversal"
        elif ind_main.edge_reversal_down and ind_main.rsi >= 55:
            direction, setup_type = "short", "range_reversal"
        elif ind_main.structure_breakout_up and ind_main.rsi >= 45 and ind_main.volume_ratio >= VOLUME_MIN_RATIO:
            direction, setup_type = "long", "range_breakout"
        elif ind_main.structure_breakout_down and ind_main.rsi <= 55 and ind_main.volume_ratio >= VOLUME_MIN_RATIO:
            direction, setup_type = "short", "range_breakout"

    # اگر جهت خاصی خواسته شده (سیگنال مخالف)، فقط همان را قبول کن
    if prefer_direction and direction and direction != prefer_direction:
        return None, f"ستاپ پیدا شد ولی جهت مخالف خواسته نبود ({direction})", None
    if prefer_direction and direction is None:
        # تلاش مجدد فقط روی مسیر ترجیحی در روند قوی
        if prefer_direction == "long" and ind_main.trend_up and ind_main.adx >= ADX_RANGE_THRESHOLD and 28 <= ind_main.rsi <= 72:
            direction, setup_type = "long", "trend_up_reverse"
        elif prefer_direction == "short" and ind_main.trend_down and ind_main.adx >= ADX_RANGE_THRESHOLD and 28 <= ind_main.rsi <= 72:
            direction, setup_type = "short", "trend_down_reverse"

    if direction is None:
        regime = "روند" if ind_main.adx >= ADX_RANGE_THRESHOLD else "رنج"
        detail = (
            f"رژیم={regime} | ADX={ind_main.adx:.1f} | RSI={ind_main.rsi:.1f} | "
            f"trend_up={ind_main.trend_up} trend_down={ind_main.trend_down} | "
            f"ema_x={ind_main.ema_cross_up}/{ind_main.ema_cross_down} | "
            f"macd_x={ind_main.macd_cross_up}/{ind_main.macd_cross_down} | "
            f"rev={ind_main.edge_reversal_up}/{ind_main.edge_reversal_down} | "
            f"vol={ind_main.volume_ratio:.2f}x"
        )
        return None, f"ستاپ شکل نگرفت ({detail})", None

    # تأیید نرم تایم‌فریم بالاتر
    if direction == "long" and ind_higher and ind_higher.trend_down and ind_higher.adx >= ADX_TREND_MIN:
        return None, "تایم‌فریم ۴ ساعته هم‌جهت نیست (نزولی قوی)", None
    if direction == "short" and ind_higher and ind_higher.trend_up and ind_higher.adx >= ADX_TREND_MIN:
        return None, "تایم‌فریم ۴ ساعته هم‌جهت نیست (صعودی قوی)", None

    futures_data = get_futures_data(code)
    funding_rate = futures_data.get("funding_rate")
    oi = futures_data.get("open_interest")

    ok, reason = check_filters(direction, ind_main, code, funding_rate, oi)
    if not ok:
        return None, reason, None

    plan = build_risk_plan(direction, ind_main.close, ind_main.atr, account_balance_usdt, ind_main.structure_level)
    if not plan.valid:
        return None, plan.reason, None

    if not skip_cooldown:
        last_closed = get_last_closed_ts(code)
        cd = cooldown_seconds if cooldown_seconds is not None else SIGNAL_REOPEN_COOLDOWN_SECONDS
        if last_closed and time.time() - last_closed < cd:
            return None, "در کول‌داون بعد از آخرین بسته‌شدن", None

    ai_status, ai_text = "unavailable", ""
    if GROQ_API_KEY:
        context = {
            "direction": "long" if direction == "long" else "short",
            "ticker": code,
            "rsi": f"{ind_main.rsi:.1f}",
            "adx": f"{ind_main.adx:.1f}",
            "volume_ratio": f"{ind_main.volume_ratio:.2f}",
            "funding_rate": f"{funding_rate or 0:.4%}",
        }
        # غیرمسدودکننده — event loop فریز نمی‌شود
        ai_status, ai_text = await asyncio.to_thread(confirm_signal_with_ai, None, context)

    signal_id = record_signal(code, direction, plan.entry, plan.stop_loss, plan.targets, plan.leverage, plan.risk_reward, ai_status == "confirmed", ai_text)
    
    rate = fetch_irt_rate_sync()
    extra_data = (plan, setup_type, ai_status, ai_text, direction, ind_main, funding_rate, oi, rate)
    return signal_id, "سیگنال صادر شد", extra_data

# ===========================
# توابع کمکی
# ===========================
def render_candles_png(df: pd.DataFrame, title: str) -> Optional[bytes]:
    return None

def stats_summary() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        wins = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='tp3'").fetchone()["n"]
        losses = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='sl'").fetchone()["n"]
        rejected_by_ai = c.execute("SELECT COUNT(*) AS n FROM signals WHERE ai_confirmed=0").fetchone()["n"]
    total_closed = wins + losses
    winrate = (wins / total_closed * 100) if total_closed else None
    return {"total_signals": total, "wins": wins, "losses": losses, "winrate": winrate, "rejected_by_ai": rejected_by_ai}

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
    app.run_polling()

if __name__ == "__main__":
    main()
