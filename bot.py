# -*- coding: utf-8 -*-
"""
ربات هوشمند تحلیل ارزهای دیجیتال - نسخه ۳.۰.۱

"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set

import ccxt
import jdatetime
import pandas as pd
import requests
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===========================
# کتابخانه‌های اختیاری (با مدیریت خطا)
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
VERSION = "3.0.1"
BUILD_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "cryptobot.sqlite3")
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

# لیست ۳۰ ارز (همان کد قبلی)
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
RSI_MIN = 45
RSI_MAX = 65
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ATR_PERIOD = 14
VOLUME_MA_PERIOD = 20
STRUCTURE_LOOKBACK = 20
ADX_PERIOD = 14
ADX_RANGE_THRESHOLD = 20
VOLUME_MIN_RATIO = 1.5
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
SIGNAL_SCAN_INTERVAL_SECONDS = 15 * 60
SIGNAL_REOPEN_COOLDOWN_SECONDS = 45 * 60
CHANNEL_MONITOR_INTERVAL_SECONDS = 5 * 60
AI_TIMEOUT_SECONDS = 12
GEMINI_MODEL = "gemini-2.0-flash"

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

# ===========================
# صرافی‌ها (MEXC + Gate.io)
# ===========================
exchange_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

exchange_mexc = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 10000,
    "headers": exchange_headers,
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,
    }
})

exchange_gate = ccxt.gate({
    "enableRateLimit": True,
    "timeout": 10000,
    "headers": exchange_headers,
    "options": {"defaultType": "spot"}
})

# ===========================
# نرخ تومان (Wallex)
# ===========================
_irt_rate_cache = {"value": None, "ts": 0.0}

async def fetch_irt_rate() -> float:
    now = time.time()
    if _irt_rate_cache["value"] and (now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS):
        return _irt_rate_cache["value"]
    try:
        def _get():
            return requests.get("https://api.wallex.ir/v1/markets", timeout=5)
        r = await asyncio.to_thread(_get)
        if r.status_code == 200:
            rate = float(r.json()["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])
            _irt_rate_cache.update(value=rate, ts=now)
            return rate
    except Exception as e:
        logger.warning(f"Error fetching IRT rate: {e}")
    return _irt_rate_cache["value"] or 65000.0

# ===========================
# دیتابیس SQLite
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

def stats_summary() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
        wins = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='tp3'").fetchone()["n"]
        losses = c.execute("SELECT COUNT(*) AS n FROM signals WHERE status='sl'").fetchone()["n"]
        rejected_by_ai = c.execute("SELECT COUNT(*) AS n FROM signals WHERE ai_confirmed=0").fetchone()["n"]
    total_closed = wins + losses
    winrate = (wins / total_closed * 100) if total_closed else None
    return {"total_signals": total, "wins": wins, "losses": losses, "winrate": winrate, "rejected_by_ai": rejected_by_ai}

init_db()

# ===========================
# کش قیمت
# ===========================
class MarketCache:
    def __init__(self):
        self.prices: Dict[str, float] = {}
        self.last_price_update = 0
        self.active_exchange_name = "MEXC"

    async def update_prices(self) -> Dict[str, float]:
        now = time.time()
        if now - self.last_price_update < PRICE_TTL_SECONDS and self.prices:
            return self.prices

        symbols = [f"{code}/USDT" for code in COIN_CODES]
        new_prices = {}

        # ۱. MEXC
        try:
            tickers = await asyncio.to_thread(exchange_mexc.fetch_tickers, symbols)
            for code in COIN_CODES:
                sym = f"{code}/USDT"
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if new_prices:
                self.active_exchange_name = "MEXC"
                self.prices = new_prices
                self.last_price_update = now
                return self.prices
        except Exception as e:
            logger.warning(f"MEXC fetch_tickers failed: {e}")

        # ۲. Gate.io
        try:
            gate_symbols = [f"{code}/USDT" for code in COIN_CODES]
            tickers = await asyncio.to_thread(exchange_gate.fetch_tickers, gate_symbols)
            for i, code in enumerate(COIN_CODES):
                sym = gate_symbols[i]
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if new_prices:
                self.active_exchange_name = "Gate.io"
                self.prices = new_prices
                self.last_price_update = now
                return self.prices
        except Exception as e:
            logger.warning(f"Gate.io fetch_tickers failed: {e}")

        # ۳. Fallback تکی
        async def fetch_one(code):
            try:
                ticker = await asyncio.to_thread(exchange_mexc.fetch_ticker, f"{code}/USDT")
                if ticker and ticker.get("last") is not None:
                    return code, float(ticker["last"])
            except:
                pass
            try:
                ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, f"{code}/USDT")
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
        try:
            raw = await asyncio.to_thread(exchange_mexc.fetch_ohlcv, f"{code}/USDT", timeframe, limit=OHLCV_LIMIT)
            if raw:
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col])
                return df
        except Exception as e:
            logger.warning(f"MEXC OHLCV failed for {code}: {e}")

        try:
            raw = await asyncio.to_thread(exchange_gate.fetch_ohlcv, f"{code}/USDT", timeframe, limit=OHLCV_LIMIT)
            if raw:
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col])
                return df
        except Exception as e:
            logger.warning(f"Gate.io OHLCV failed for {code}: {e}")

        return None

cache = MarketCache()

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

    last_close = float(close.iloc[-1])
    trend_up = last_close > ema_fast.iloc[-1] > ema_slow.iloc[-1]
    trend_down = last_close < ema_fast.iloc[-1] < ema_slow.iloc[-1]
    ema_cross_up = ema_fast.iloc[-2] <= ema_slow.iloc[-2] and ema_fast.iloc[-1] > ema_slow.iloc[-1]
    ema_cross_down = ema_fast.iloc[-2] >= ema_slow.iloc[-2] and ema_fast.iloc[-1] < ema_slow.iloc[-1]

    last_rsi = float(rsi.iloc[-1])
    rsi_in_zone = RSI_MIN <= last_rsi <= RSI_MAX

    macd_cross_up = macd_line.iloc[-2] <= macd_signal.iloc[-2] and macd_line.iloc[-1] > macd_signal.iloc[-1]
    macd_cross_down = macd_line.iloc[-2] >= macd_signal.iloc[-2] and macd_line.iloc[-1] < macd_signal.iloc[-1]

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
def get_fear_greed_index() -> Optional[int]:
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5)
        if r.status_code == 200:
            return int(r.json()["data"][0]["value"])
    except:
        pass
    return None

def fetch_funding_rate(code: str) -> Optional[float]:
    try:
        ticker = exchange_mexc.fetch_ticker(f"{code}/USDT")
        return ticker.get("fundingRate")
    except:
        pass
    try:
        ticker = exchange_gate.fetch_ticker(f"{code}/USDT")
        return ticker.get("fundingRate")
    except:
        pass
    return None

def fetch_open_interest(code: str) -> Optional[float]:
    try:
        oi = exchange_mexc.fetch_open_interest(f"{code}/USDT")
        return oi.get("openInterestAmount")
    except:
        pass
    try:
        oi = exchange_gate.fetch_open_interest(f"{code}/USDT")
        return oi.get("openInterestAmount")
    except:
        pass
    return None

def check_filters(direction: str, indicators: IndicatorSnapshot, code: str) -> tuple[bool, str]:
    # ۱. حجم
    if indicators.volume_ratio < VOLUME_MIN_RATIO:
        return False, f"نسبت حجم {indicators.volume_ratio:.2f} کمتر از {VOLUME_MIN_RATIO}"

    # ۲. فاندینگ ریت
    funding = fetch_funding_rate(code)
    if funding is not None and direction == "long" and funding > FUNDING_RATE_MAX_FOR_LONG:
        return False, f"فاندینگ {funding:.4%} برای لانگ خیلی مثبت است"

    # ۳. Open Interest
    oi = fetch_open_interest(code)
    if oi is not None and oi <= 0:
        return False, "Open Interest صفر یا منفی است"

    # ۴. ترس/طمع
    fg = get_fear_greed_index()
    if fg is not None:
        if direction == "long" and fg >= FEAR_GREED_EXTREME_GREED:
            return False, f"شاخص طمع شدید ({fg})"
        if direction == "short" and fg <= FEAR_GREED_EXTREME_FEAR:
            return False, f"شاخص ترس شدید ({fg})"

    # ۵. ساعات کم‌حجم
    h = datetime.now(timezone.utc).hour
    if (h >= LOW_VOLUME_UTC_START_HOUR) or (h < LOW_VOLUME_UTC_END_HOUR):
        return False, f"ساعت {h}:00 UTC در بازه کم‌حجم"

    # ۶. بازار رنج (ADX)
    is_reversal = indicators.edge_reversal_up or indicators.edge_reversal_down
    if indicators.adx < ADX_RANGE_THRESHOLD and not is_reversal:
        return False, f"ADX={indicators.adx:.1f} زیر {ADX_RANGE_THRESHOLD} (بازار رنج)"

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
# چارت (با مدیریت خطا)
# ===========================
def render_candles_png(df: pd.DataFrame, title: str) -> Optional[bytes]:
    if not MPLFINANCE_AVAILABLE:
        logger.warning("mplfinance not installed. Chart rendering disabled.")
        return None
    try:
        plot_df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]].tail(120)
        buf = io.BytesIO()
        mpf.plot(plot_df, type="candle", style="charles", volume=True, title=title, savefig=dict(fname=buf, dpi=110, bbox_inches="tight"))
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"Chart rendering failed: {e}")
        return None

# ===========================
# هوش مصنوعی Gemini
# ===========================
AI_PROMPT_TEMPLATE = (
    "شما یک تحلیل‌گر ریسک‌گریز هستید. فقط اگر روند، حجم، فاندینگ و Open Interest همگی با سیگنال زیر هم‌جهت باشند با کلمه CONFIRM پاسخ دهید، در غیر این صورت REJECT.\n\n"
    "جهت: {direction}\nنماد: {ticker}\nورود: {entry}\nحد ضرر: {stop_loss}\nتارگت‌ها: {targets}\n"
    "RSI: {rsi} | ADX: {adx} | حجم: {volume_ratio}\nفاندینگ: {funding_rate} | OI: {oi_change}\n"
)

def confirm_signal_with_ai(chart_png: Optional[bytes], context: dict) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        return "unavailable", "GEMINI_API_KEY تنظیم نشده"
    if chart_png is None:
        return "unavailable", "چارت در دسترس نیست"
    prompt = AI_PROMPT_TEMPLATE.format(**context)
    image_b64 = base64.b64encode(chart_png).decode("ascii")
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_b64}}]}]}
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY}, json=payload, timeout=AI_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        status = "confirmed" if text.upper().startswith("CONFIRM") else "rejected"
        return status, text
    except Exception as e:
        logger.warning(f"AI failed: {e}")
        return "unavailable", str(e)

# ===========================
# پایپ‌لاین سیگنال
# ===========================
def evaluate_coin(code: str, account_balance_usdt: float = 1000.0):
    existing = get_open_signal_for_ticker(code)
    if existing:
        return None, "سیگنال باز وجود دارد", None

    df_main = asyncio.run(cache.get_ohlcv(code, MAIN_TF))
    df_higher = asyncio.run(cache.get_ohlcv(code, HIGHER_TF))
    if df_main is None or df_higher is None:
        return None, "داده OHLCV در دسترس نیست", None

    ind_main = compute_indicators(df_main)
    ind_higher = compute_indicators(df_higher)
    if ind_main is None or ind_higher is None:
        return None, "اندیکاتورها محاسبه نشدند", None

    # تعیین جهت
    direction = None
    setup_type = ""
    if ind_main.adx >= ADX_RANGE_THRESHOLD:
        if ind_main.trend_up and ind_main.rsi_in_zone and (ind_main.macd_cross_up or ind_main.ema_cross_up):
            direction, setup_type = "long", "trend"
        elif ind_main.trend_down and ind_main.rsi_in_zone and (ind_main.macd_cross_down or ind_main.ema_cross_down):
            direction, setup_type = "short", "trend"
    else:
        if ind_main.edge_reversal_up:
            direction, setup_type = "long", "range_reversal"
        elif ind_main.edge_reversal_down:
            direction, setup_type = "short", "range_reversal"

    if direction is None:
        return None, f"هیچ ستاپ معتبری در رژیم {'روند' if ind_main.adx >= ADX_RANGE_THRESHOLD else 'رنج'} شکل نگرفت", None

    # فیلترها
    ok, reason = check_filters(direction, ind_main, code)
    if not ok:
        return None, reason, None

    # ریسک
    plan = build_risk_plan(direction, ind_main.close, ind_main.atr, account_balance_usdt, ind_main.structure_level)
    if not plan.valid:
        return None, plan.reason, None

    # کول‌داون
    last_closed = get_last_closed_ts(code)
    if last_closed and time.time() - last_closed < SIGNAL_REOPEN_COOLDOWN_SECONDS:
        return None, "در کول‌داون بعد از آخرین بسته‌شدن", None

    # AI
    chart_png = render_candles_png(df_main, f"{code} ({MAIN_TF})")
    ai_status, ai_text = "unavailable", ""
    if GEMINI_API_KEY and chart_png is not None:
        context = {
            "direction": "لانگ" if direction == "long" else "شورت",
            "ticker": code, "entry": f"{plan.entry:.6f}", "stop_loss": f"{plan.stop_loss:.6f}",
            "targets": ", ".join(f"{t:.6f}" for t in plan.targets),
            "rsi": f"{ind_main.rsi:.1f}", "adx": f"{ind_main.adx:.1f}", "volume_ratio": f"{ind_main.volume_ratio:.2f}",
            "funding_rate": f"{fetch_funding_rate(code) or 0:.4%}", "oi_change": "نامشخص",
        }
        ai_status, ai_text = confirm_signal_with_ai(chart_png, context)

    # ثبت
    signal_id = record_signal(code, direction, plan.entry, plan.stop_loss, plan.targets, plan.leverage, plan.risk_reward, ai_status == "confirmed", ai_text)
    return signal_id, "سیگنال صادر شد", (plan, setup_type, ai_status, ai_text, direction)

# ===========================
# ارسال به کانال و ادمین‌ها
# ===========================
def format_signal_message(code: str, direction: str, plan: RiskPlan, setup_type: str, ai_status: str, ai_text: str) -> str:
    setup_label = "تعقیب روند" if setup_type == "trend" else "برگشت از لبه رنج"
    dir_fa = "لانگ 🟢" if direction == "long" else "شورت 🔴"
    text = (
        f"🚨 **سیگنال جدید** — {code}\n"
        f"جهت: {dir_fa} | نوع: {setup_label}\n"
        f"ورود: {plan.entry:.6f}\n"
        f"حد ضرر: {plan.stop_loss:.6f}\n"
        f"تارگت‌ها: {', '.join(f'{t:.6f}' for t in plan.targets)}\n"
        f"اهرم: {plan.leverage}x | RR: 1:{plan.risk_reward:.2f}\n"
        f"{shamsi_now()}\n"
    )
    if ai_status == "confirmed":
        text += f"\n🤖 **AI:** ✅ تأیید\n{ai_text}"
    elif ai_status == "rejected":
        text += f"\n🤖 **AI:** ⚠️ عدم تأیید (فقط اطلاعاتی)\n{ai_text}"
    else:
        text += f"\n🤖 **AI:** در دسترس نبود"
    return text

async def send_signal(app: Application, code: str, signal_id: int, direction: str, plan: RiskPlan, setup_type: str, ai_status: str, ai_text: str):
    text = format_signal_message(code, direction, plan, setup_type, ai_status, ai_text)
    thread = get_channel_thread(code)
    reply_to_id = thread["message_id"] if thread else None
    if CHANNEL_ID:
        try:
            msg = await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=reply_to_id)
            set_channel_thread(code, signal_id, msg.message_id, hashlib.sha256(text.encode()).hexdigest())
            set_channel_message_id(signal_id, msg.message_id)
        except Exception as e:
            logger.warning(f"Send to channel failed: {e}")
    for admin_id in ADMIN_USER_IDS:
        try:
            await app.bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Send to admin {admin_id} failed: {e}")

# ===========================
# مانیتورینگ سیگنال‌های باز
# ===========================
async def monitor_open_signals(app: Application):
    while True:
        try:
            for row in open_signals():
                code = row["ticker"]
                price = (await cache.update_prices()).get(code, 0.0)
                if price == 0.0:
                    continue
                targets = json.loads(row["targets"])
                direction = row["direction"]
                stop_loss = row["stop_loss"]
                hit_sl = (price <= stop_loss) if direction == "long" else (price >= stop_loss)
                if hit_sl:
                    text = f"❌ **حد ضرر خورد** — {code}\nورود: {row['entry']:.6f} | SL: {stop_loss:.6f}\n{shamsi_now()}"
                    await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=row["channel_message_id"])
                    update_signal_status(row["id"], "sl")
                    clear_channel_thread(code)
                    continue

                highest = row["highest_tp_hit"]
                if highest < 1:
                    if (price >= targets[0] if direction == "long" else price <= targets[0]):
                        text = f"✅ **TP1 زده شد** — {code}\nحد ضرر به نقطه ورود منتقل شد: {row['entry']:.6f}\n{shamsi_now()}"
                        await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=row["channel_message_id"])
                        update_signal_progress(row["id"], 1, row["entry"])
                        continue
                if highest < 2:
                    if (price >= targets[1] if direction == "long" else price <= targets[1]):
                        text = f"✅ **TP2 زده شد** — {code}\nحد ضرر به TP1 منتقل شد: {targets[0]:.6f}\n{shamsi_now()}"
                        await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=row["channel_message_id"])
                        update_signal_progress(row["id"], 2, targets[0])
                        continue
                if (price >= targets[2] if direction == "long" else price <= targets[2]):
                    text = f"🏆 **TP3 زده شد** — {code}\nسیگنال با موفقیت بسته شد\n{shamsi_now()}"
                    await app.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_to_message_id=row["channel_message_id"])
                    update_signal_status(row["id"], "tp3")
                    clear_channel_thread(code)
            await asyncio.sleep(CHANNEL_MONITOR_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            await asyncio.sleep(60)

# ===========================
# اسکن دوره‌ای
# ===========================
async def periodic_scan(app: Application):
    while True:
        try:
            logger.info("🔍 اسکن دوره‌ای شروع شد...")
            for code in COIN_CODES:
                try:
                    signal_id, reason, data = evaluate_coin(code)
                    if signal_id and data:
                        plan, setup_type, ai_status, ai_text, direction = data
                        await send_signal(app, code, signal_id, direction, plan, setup_type, ai_status, ai_text)
                except Exception as e:
                    logger.exception(f"Error scanning {code}: {e}")
            logger.info("✅ اسکن دوره‌ای تمام شد")
            await asyncio.sleep(SIGNAL_SCAN_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            await asyncio.sleep(60)

# ===========================
# کیبوردها
# ===========================
MAIN_MENU_TEXT = (
    "🤖 **ربات هوشمند تحلیل ارزهای دیجیتال**\n"
    "📊 قیمت لحظه‌ای | تحلیل تکنیکال | سیگنال معاملاتی\n"
    "⚡️ سریع و دقیق\n\n"
    "👇 **منوی اصلی:**"
)

def kb_main_menu(is_admin_user=False):
    keyboard = [
        [InlineKeyboardButton("💵 قیمت لحظه‌ای", callback_data="coins_prices_all"),
         InlineKeyboardButton("📊 وضعیت و تحلیل", callback_data="coins_status_grid")],
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
    buttons, row = [], []
    for code in COIN_CODES:
        row.append(InlineKeyboardButton(f"{code} 🟢", callback_data=f"coin_detail_{code}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 آمار سیگنال‌ها", callback_data="admin_signal_stats")],
        [InlineKeyboardButton("👥 آمار کاربران و سیستم", callback_data="admin_system_stats")],
        [InlineKeyboardButton("🗑 صفر کردن آمار", callback_data="reset_stats_confirm")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def kb_back_admin():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_panel")]])

def kb_reset_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، صفر شود", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ انصراف", callback_data="admin_panel")]
    ])

# ===========================
# هندلرها
# ===========================
async def version_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 **نسخه ربات:** `{VERSION}`\n📅 **زمان ساخت:** `{BUILD_TIME}`\n🆔 **شناسه:** `{context.bot.id}`",
        parse_mode="Markdown"
    )

async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_adm = user_id in ADMIN_USER_IDS
    await update.message.reply_text(
        f"📌 **اطلاعات ربات هوشمند تحلیل ارزهای دیجیتال**\n"
        f"{'────────────────────'}\n"
        f"🤖 **نسخه:** `{VERSION}`\n"
        f"📅 **ساخت:** `{BUILD_TIME}`\n"
        f"🆔 **شناسه:** `{context.bot.id}`\n"
        f"👤 **وضعیت شما:** {'👑 ادمین' if is_adm else '👤 کاربر عادی'}\n"
        f"📊 **تعداد ارزها:** `{len(COIN_CODES)}`\n"
        f"🏛 **صرافی فعال:** `{cache.active_exchange_name}`\n"
        f"{'────────────────────'}\n"
        f"⚡️ *برای شروع از دستور /start استفاده کنید.*",
        parse_mode="Markdown"
    )

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_adm = user_id in ADMIN_USER_IDS
    await update.message.reply_text(MAIN_MENU_TEXT, reply_markup=kb_main_menu(is_adm), parse_mode="Markdown")

async def stop_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ **ربات متوقف شد.**", reply_markup=kb_start_only(), parse_mode="Markdown")

async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ **شما دسترسی به این بخش را ندارید.**", parse_mode="Markdown")
        return
    await update.message.reply_text("👑 **پنل مدیریت ادمین**", reply_markup=kb_admin_panel(), parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_adm = user_id in ADMIN_USER_IDS

    if data == "bot_start_action":
        await query.edit_message_text(MAIN_MENU_TEXT, reply_markup=kb_main_menu(is_adm), parse_mode="Markdown")
    elif data == "bot_stop_action":
        await query.edit_message_text("⛔ **ربات متوقف شد.**", reply_markup=kb_start_only(), parse_mode="Markdown")
    elif data == "main_menu":
        await query.edit_message_text(MAIN_MENU_TEXT, reply_markup=kb_main_menu(is_adm), parse_mode="Markdown")
    elif data == "coins_prices_all":
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...", parse_mode="Markdown")
        prices = await cache.update_prices()
        rate = await fetch_irt_rate()
        exchange_emoji = "🇲" if "MEXC" in cache.active_exchange_name else "🇬"
        text = f"💵 **لیست قیمت ارزها**\n📅 {shamsi_now()}\n🇮🇷 نرخ تتر: {rate:,.0f} تومان\n{'────────────────────'}\n"
        for code in COIN_CODES:
            p = prices.get(code, 0.0)
            text += f"‎{exchange_emoji} **{code}**: {fmt_usd(p)} USDT\n‎🇮🇷 {fmt_toman(p, rate)}\n\n"
        await query.edit_message_text(text, reply_markup=kb_prices_all_single(), parse_mode="Markdown")
    elif data == "coins_status_grid":
        await query.edit_message_text("📊 **تحلیل تکنیکال ارزها**\nارز مورد نظر را انتخاب کنید:", reply_markup=kb_status_grid(), parse_mode="Markdown")
    elif data.startswith("coin_detail_"):
        code = data.split("_")[2]
        await query.edit_message_text(f"⏳ در حال تحلیل {code}...", parse_mode="Markdown")
        df = await cache.get_ohlcv(code, "1h")
        if df is None:
            await query.edit_message_text(f"❌ داده‌های {code} در دسترس نیست.", reply_markup=kb_status_grid(), parse_mode="Markdown")
            return
        ind = compute_indicators(df)
        if ind is None:
            await query.edit_message_text(f"❌ تحلیل {code} ناموفق بود.", reply_markup=kb_status_grid(), parse_mode="Markdown")
            return
        rate = await fetch_irt_rate()
        price = (await cache.update_prices()).get(code, 0.0)
        text = (
            f"📊 **تحلیل تکنیکال {code}**\n{'────────────────────'}\n"
            f"💵 قیمت: {fmt_usd(price)} | {fmt_toman(price, rate)}\n"
            f"📈 روند: {'صعودی 🚀' if ind.trend_up else 'نزولی 🔻' if ind.trend_down else 'خنثی ⚖️'}\n"
            f"📊 RSI: {ind.rsi:.1f} ({'منطقه' if ind.rsi_in_zone else 'خارج از منطقه'})\n"
            f"📈 MACD: {'صعودی 🟢' if ind.macd_cross_up else 'نزولی 🔴' if ind.macd_cross_down else 'خنثی'}\n"
            f"📊 ADX: {ind.adx:.1f} ({'روند' if ind.adx >= ADX_RANGE_THRESHOLD else 'رنج'})\n"
            f"📊 ATR: {fmt_usd(ind.atr)}\n"
            f"📊 حجم: نسبت {ind.volume_ratio:.2f} به میانگین\n"
            f"🎯 سطح کلیدی: {fmt_usd(ind.structure_level)}\n"
            f"{'────────────────────'}\n"
            f"{shamsi_now()}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"coin_detail_{code}")],
            [InlineKeyboardButton("🔙 لیست ارزها", callback_data="coins_status_grid")]
        ]), parse_mode="Markdown")
    elif data == "admin_panel":
        if not is_adm: return
        await query.edit_message_text("👑 **پنل مدیریت**", reply_markup=kb_admin_panel(), parse_mode="Markdown")
    elif data == "admin_signal_stats":
        if not is_adm: return
        s = stats_summary()
        winrate = f"{s['winrate']:.1f}%" if s['winrate'] is not None else "بدون داده"
        await query.edit_message_text(
            f"📈 **آمار سیگنال‌ها**\n{'────────────────────'}\n"
            f"🔢 کل: {s['total_signals']}\n"
            f"✅ موفق: {s['wins']}\n"
            f"❌ ناموفق: {s['losses']}\n"
            f"🏆 وین‌ریت: {winrate}\n"
            f"🤖 رد شده توسط AI: {s['rejected_by_ai']}",
            reply_markup=kb_back_admin(), parse_mode="Markdown"
        )
    elif data == "admin_system_stats":
        if not is_adm: return
        await query.edit_message_text(
            f"👥 **آمار سیستم**\n{'────────────────────'}\n"
            f"🏛 صرافی: {cache.active_exchange_name}\n"
            f"📊 تعداد ارزها: {len(COIN_CODES)}\n"
            f"🤖 نسخه: {VERSION}\n"
            f"⏱ {shamsi_now()}",
            reply_markup=kb_back_admin(), parse_mode="Markdown"
        )
    elif data == "reset_stats_confirm":
        if not is_adm: return
        await query.edit_message_text("⚠️ **آیا از صفر کردن آمار اطمینان دارید؟**", reply_markup=kb_reset_confirm(), parse_mode="Markdown")
    elif data == "reset_stats_do":
        if not is_adm: return
        with _conn() as c:
            c.execute("DELETE FROM signals")
        await query.edit_message_text("✅ **آمار با موفقیت صفر شد.**", reply_markup=kb_back_admin(), parse_mode="Markdown")

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
    # شروع وظایف دوره‌ای
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
