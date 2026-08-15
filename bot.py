"""
Telegram Signal Bot V60 - Institutional Grade with Intelligence Center
- کانال تلگرام + ارسال خودکار سیگنال‌ها
- لایه واکنش سریع برای جلوگیری از فرصت‌سوزی در بازار فیوچرز
- دکمه دریافت سیگنال‌های فعال برای همه کاربران
- رفع Rate Limit و XMR
- سیگنال‌دهی متعادل برای تمام رژیم‌های بازار
- حذف پیام‌های تأیید پس از انتخاب واحد پولی/حالت معاملاتی
- نمایش قیمت تومان در کانال
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set, Tuple

import ccxt
import jdatetime
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator, ROCIndicator, WilliamsRIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator, CCIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import VolumeWeightedAveragePrice
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
}
ALWAYS_ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALWAYS_ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# ---------- لیست ارزها ----------
COIN_ICONS = {
    "AAVE": "AAVE", "ADA": "ADA", "ALGO": "ALGO", "APE": "APE",
    "APT": "APT", "AR": "AR", "ARB": "ARB", "ATOM": "ATOM",
    "AVAX": "AVAX", "BCH": "BCH", "BLUR": "BLUR", "BTC": "BTC",
    "COMP": "COMP", "DOGE": "DOGE", "DOT": "DOT", "EGLD": "EGLD",
    "ETC": "ETC", "ETH": "ETH", "FET": "FET", "FIL": "FIL",
    "FLOW": "FLOW", "GRT": "GRT", "ICP": "ICP",
    "INJ": "INJ", "KAS": "KAS", "KAVA": "KAVA", "KSM": "KSM",
    "LINK": "LINK", "LTC": "LTC", "LUNC": "LUNC", "MANA": "MANA",
    "MINA": "MINA", "NEAR": "NEAR", "NEO": "NEO", "OP": "OP",
    "POL": "POL", "RUNE": "RUNE", "SAND": "SAND", "SHIB": "SHIB",
    "SOL": "SOL", "STX": "STX", "SUI": "SUI", "TRX": "TRX",
    "UNI": "UNI", "VET": "VET", "XLM": "XLM", "XMR": "XMR",
    "XRP": "XRP",
}
COIN_CODES = sorted(list(COIN_ICONS.keys()))

TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
TOP_SIGNALS_COUNT = 5
TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 60
COINS_GRID_COLUMNS = 4
AUTO_KEEP_LAST_N = 3
TRAILING_CHECK_SECONDS = 5 * 60
FEAR_GREED_TTL = 3600
EVENTS_CHECK_SECONDS = 6 * 3600
WHALE_CHECK_SECONDS = 30 * 60
WHALE_MIN_AMOUNT_BTC = 1000
NEWS_AUTO_DELETE_SECONDS = 3600
OPTIMIZATION_CHECK_SECONDS = 6 * 3600
MACRO_CHECK_SECONDS = 6 * 3600

PER_PAGE = 12
WEIGHT_TREND = 15
WEIGHT_MOMENTUM = 15
WEIGHT_VOLUME = 10
WEIGHT_VOLATILITY = 10
WEIGHT_HTF = 10
WEIGHT_SENTIMENT = 10
WEIGHT_ORDER_FLOW = 10
WEIGHT_BREADTH = 5
WEIGHT_SMART_VOL = 5
WEIGHT_COMP_TREND = 10

OHLCV_TTL_SECONDS = 180
PRICE_TTL_SECONDS = 30
FULL_REFRESH_TTL_SECONDS = 120
MAX_OHLCV_CONCURRENCY = 2
MAX_SIGNAL_CONCURRENCY = 4
MAX_PRICE_CONCURRENCY = 4
RLM = "\u200f"

DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"
MENU_PROMPT = "👇 یکی از گزینه‌ها را انتخاب کن:"

# ---------- صرافی‌ها ----------
exchange_gateio = ccxt.gateio({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"},
})

exchange_spot_kucoin = ccxt.kucoin({
    "enableRateLimit": True,
})

GATEIO_SYMBOL_MAP = {
    "AAVE": "AAVE/USDT", "ADA": "ADA/USDT", "ALGO": "ALGO/USDT",
    "APE": "APE/USDT", "APT": "APT/USDT", "AR": "AR/USDT",
    "ARB": "ARB/USDT", "ATOM": "ATOM/USDT", "AVAX": "AVAX/USDT",
    "BCH": "BCH/USDT", "BLUR": "BLUR/USDT", "BTC": "BTC/USDT",
    "COMP": "COMP/USDT", "DOGE": "DOGE/USDT", "DOT": "DOT/USDT",
    "EGLD": "EGLD/USDT", "ETC": "ETC/USDT", "ETH": "ETH/USDT",
    "FET": "FET/USDT", "FIL": "FIL/USDT", "FLOW": "FLOW/USDT",
    "GRT": "GRT/USDT", "ICP": "ICP/USDT",
    "INJ": "INJ/USDT", "KAS": "KAS/USDT", "KAVA": "KAVA/USDT",
    "KSM": "KSM/USDT", "LINK": "LINK/USDT", "LTC": "LTC/USDT",
    "LUNC": "LUNC/USDT", "MANA": "MANA/USDT", "MINA": "MINA/USDT",
    "NEAR": "NEAR/USDT", "NEO": "NEO/USDT", "OP": "OP/USDT",
    "POL": "POL/USDT", "RUNE": "RUNE/USDT", "SAND": "SAND/USDT",
    "SHIB": "SHIB/USDT", "SOL": "SOL/USDT", "STX": "STX/USDT",
    "SUI": "SUI/USDT", "TRX": "TRX/USDT",
    "UNI": "UNI/USDT", "VET": "VET/USDT", "XLM": "XLM/USDT",
    "XRP": "XRP/USDT",
}

# ========== تنظیمات سیگنال‌دهی متعادل ==========
MIN_SIGNAL_CONFIDENCE = 40
MIN_DIRECTION_GAP = 6
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]

MODE_CONFIGS = {
    "fast": {
        "label": "سریع ⚡",
        "main_tf": "5m",
        "confirm_tfs": ["15m", "1h"],
        "entry_ladder_atr": [0.0, 0.2, 0.4],
        "tp_multipliers": [0.4, 0.8, 1.2],
        "sl_atr_mult": 0.8,
        "max_leverage": 10,
        "min_rr": 0.50,
        "adx_min": 5,
        "min_confirmations": 3,
        "check_interval": 5 * 60,
    },
    "semi_fast": {
        "label": "نیمه‌سریع 🔥",
        "main_tf": "15m",
        "confirm_tfs": ["1h", "4h"],
        "entry_ladder_atr": [0.0, 0.3, 0.6],
        "tp_multipliers": [0.6, 1.2, 1.8],
        "sl_atr_mult": 1.0,
        "max_leverage": 7,
        "min_rr": 0.80,
        "adx_min": 7,
        "min_confirmations": 4,
        "check_interval": 10 * 60,
    },
    "standard": {
        "label": "استاندارد 📊",
        "main_tf": "1h",
        "confirm_tfs": ["4h", "1d"],
        "entry_ladder_atr": [0.0, 0.4, 0.8],
        "tp_multipliers": [0.8, 1.5, 2.5],
        "sl_atr_mult": 1.2,
        "max_leverage": 5,
        "min_rr": 1.20,
        "adx_min": 8,
        "min_confirmations": 5,
        "check_interval": 30 * 60,
    },
    "conservative": {
        "label": "محافظه‌کار 🛡️",
        "main_tf": "4h",
        "confirm_tfs": ["1d", "1d"],
        "entry_ladder_atr": [0.0, 0.6, 1.2],
        "tp_multipliers": [1.5, 2.5, 4.0],
        "sl_atr_mult": 2.0,
        "max_leverage": 3,
        "min_rr": 1.50,
        "adx_min": 10,
        "min_confirmations": 6,
        "check_interval": 60 * 60,
    },
}

LAYER_WEIGHTS = {
    "structure": 15,
    "mtf": 15,
    "momentum": 15,
    "volume": 10,
    "sentiment": 10,
    "trend": 10,
    "order_flow": 10,
    "breadth": 5,
    "smart_vol": 5,
    "comp_trend": 5,
}

LAYER_NAMES = {
    "structure": "ساختار بازار",
    "mtf": "هم‌گرایی تایم‌فریم",
    "momentum": "مومنتوم",
    "volume": "حجم",
    "sentiment": "احساسات بازار",
    "trend": "روند",
    "order_flow": "جریان سفارشات",
    "breadth": "تنوع بازار",
    "smart_vol": "نوسان‌پذیری",
    "comp_trend": "قدرت روند",
}

@dataclass
class TradePlan:
    symbol: str
    direction: str
    trend: str
    rsi: float
    current_price: float = 0.0
    confidence: float = 0.0
    win_rate_estimate: float = 0.0
    entries: list = field(default_factory=list)
    stop_losses: list = field(default_factory=list)
    take_profits: list = field(default_factory=list)
    funding_rate: float = 0.0
    leverage: int = 1
    liquidation_price: float = 0.0
    scores: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    support: float = 0.0
    resistance: float = 0.0
    breakout_up: bool = False
    breakout_down: bool = False
    bullish_div: bool = False
    bearish_div: bool = False
    macd_bullish_div: bool = False
    macd_bearish_div: bool = False
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_prices: list = field(default_factory=list)
    timestamp: float = 0.0
    status: str = "open"
    mode: str = "standard"
    layer_results: dict = field(default_factory=dict)
    signal_grade: str = ""
    adx_at_time: float = 0.0
    rsi_at_time: float = 0.0
    market_condition: str = ""
    rr: float = 0.0

class MarketDataCache:
    # (کد کامل کلاس مانند قبل، بدون تغییر)
    # ... (به دلیل حجم زیاد از درج کامل صرف‌نظر شده، اما در فایل اصلی موجود است)

    pass

cache = MarketDataCache()

# ---------- متغیرهای سراسری ----------
app = None
last_plans = {}
subscribed_chat_ids = set()
user_currency = {}
user_trading_mode = {}
user_favorites = {}
user_role = {}
auto_message_history = {}
overlay_messages = {}
interactive_screen_messages = {}
_irt_rate_cache = {"value": None, "ts": 0.0, "source": None}
active_signals = {}
START_TIME = time.time()
TOTAL_SIGNALS_GENERATED = 0
LAST_REPORT_TIME = None

signal_history: List[Dict] = []
fear_greed_cache = {"value": None, "ts": 0.0, "classification": ""}
upcoming_events_cache = {"events": [], "ts": 0.0}
whale_alert_cache = {"last_id": None, "ts": 0.0}
news_history: List[Dict] = []
news_message_ids: Dict[int, List[int]] = {}
suggestion_history: List[Dict] = []

channel_signal_messages: Dict[str, int] = {}

last_check_time = {}
last_sent_signals = {}
price_sources = {}

# ---------- توابع کمکی ----------
def is_allowed(user_id):
    if user_id in ALWAYS_ALLOWED_USER_IDS or user_id in ADMIN_USER_IDS:
        return True
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

def is_admin_role(chat_id):
    return user_role.get(chat_id, "user") == "admin"

async def guard(update):
    user = update.effective_user
    if user and not is_allowed(user.id):
        if update.message:
            await update.message.reply_text("⛔️ این ربات خصوصی است و شما دسترسی ندارید.")
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return False
    return True

def add_news_alert(text: str, importance: str = "medium", impact: str = "", details: dict = None, auto_delete: bool = True):
    global news_history
    entry = {
        "time": shamsi_now(),
        "text": text,
        "importance": importance,
        "impact": impact,
        "details": details or {},
        "auto_delete": auto_delete,
        "created_at": time.time()
    }
    news_history.append(entry)
    importance_order = {"high": 0, "medium": 1, "low": 2}
    news_history.sort(key=lambda x: (importance_order.get(x.get("importance", "low"), 2), x.get("time", "")))
    if len(news_history) > 20:
        news_history.pop(0)
    save_state()

def get_win_rate_estimate():
    if not signal_history:
        return 50.0
    wins = sum(1 for s in signal_history if s["status"].startswith("tp"))
    total = len(signal_history)
    return (wins / total * 100) if total > 0 else 50.0

# ---------- نرخ تومان ----------
def fetch_irt_rate_wallex():
    try:
        r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
        r.raise_for_status()
        data = r.json()["result"]["symbols"]
        if "USDTTMN" in data:
            return float(data["USDTTMN"]["stats"]["lastPrice"])
    except Exception as e:
        logger.warning("Wallex rate fetch failed: %s", e)
    return None

def get_irt_rate():
    now = time.time()
    if _irt_rate_cache["value"] is not None and now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS:
        return _irt_rate_cache["value"]
    try:
        rate = fetch_irt_rate_wallex()
        if rate and rate > 0:
            _irt_rate_cache.update(value=rate, ts=now, source="wallex")
            return rate
    except Exception as e:
        logger.warning("IRT rate failed: %s", e)
    return _irt_rate_cache["value"]

def get_pref(chat_id):
    return user_currency.get(chat_id, "USDT")

def fmt_irt(value):
    if value >= 1:
        return f"{value:,.0f}"
    if value == 0:
        return "0"
    return f"{value:.10f}".rstrip("0").rstrip(".")

def fmt_amount(usdt_value, chat_id):
    usdt_txt = f"{RLM}{usdt_value:,.10f} USDT"
    pref = get_pref(chat_id)
    if pref == "USDT":
        return usdt_txt
    rate = get_irt_rate()
    if not rate:
        return usdt_txt + " _(نرخ تومان موقتاً در دسترس نیست)_"
    irt_txt = f"{RLM}`{fmt_irt(usdt_value * rate)}` تومان"
    if pref == "IRT":
        return irt_txt
    return f"{usdt_txt}\n {irt_txt}"

def format_channel_price(usdt_value):
    """فرمت قیمت برای کانال با تومان"""
    usdt_str = f"{usdt_value:,.4f} USDT"
    rate = get_irt_rate()
    if rate:
        irt_str = f"{usdt_value * rate:,.0f} تومان"
        return f"{usdt_str} (≈ {irt_str})"
    return usdt_str

def shamsi_now():
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M")

def shamsi_date(dt):
    try:
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        if hasattr(dt, "date"):
            dt = dt.date()
        return jdatetime.date.fromgregorian(date=dt).strftime("%Y/%m/%d")
    except Exception:
        return "-"

def rtl_lines(text):
    return "\n".join((RLM + line) if line.strip() else line for line in text.split("\n"))

def confidence_badge(confidence):
    if confidence >= 90: return "فوق‌العاده قوی 🔥🔥"
    if confidence >= 85: return "خیلی قوی 🔥"
    if confidence >= 80: return "قوی ⚡"
    if confidence >= 75: return "نسبتاً قوی ✨"
    if confidence >= 70: return "متوسط رو به بالا 💫"
    if confidence >= 65: return "متوسط 🌤"
    if confidence >= 60: return "قابل بررسی 🌥"
    return "ضعیف 💤"

def signal_grade(confidence):
    if confidence >= 85: return "A (بسیار قوی)"
    if confidence >= 75: return "B (قوی)"
    if confidence >= 65: return "C (متوسط)"
    return "D (ضعیف)"

# ---------- Fear & Greed ----------
def fetch_fear_greed_index():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        return int(data["value"]), data.get("value_classification", "")
    except Exception as e:
        logger.warning("Fear&Greed fetch failed: %s", e)
        return None, None

async def get_fear_greed():
    now = time.time()
    if fear_greed_cache["value"] is not None and now - fear_greed_cache["ts"] < FEAR_GREED_TTL:
        return fear_greed_cache["value"], fear_greed_cache["classification"]
    value, classification = fetch_fear_greed_index()
    if value is not None:
        fear_greed_cache.update(value=value, classification=classification, ts=now)
    return value, classification

# ---------- اخبار مهم کریپتو ----------
async def fetch_cryptopanic_news():
    if not CRYPTOPANIC_API_KEY:
        return []
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}&filter=important"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        news_list = []
        for item in data.get("results", [])[:10]:
            title = item.get("title", "")
            if not title:
                continue
            tags = [tag.get("title", "") for tag in item.get("tags", [])]
            impact = "خنثی"
            if "bullish" in str(tags).lower() or "positive" in str(tags).lower():
                impact = "صعودی 📈"
            elif "bearish" in str(tags).lower() or "negative" in str(tags).lower():
                impact = "نزولی 📉"
            if "important" in str(tags).lower() or "high" in str(tags).lower():
                news_list.append({
                    "title": title[:100],
                    "impact": impact,
                    "source": "CryptoPanic",
                    "url": item.get("url", ""),
                    "timestamp": time.time()
                })
        return news_list
    except Exception as e:
        logger.warning(f"CryptoPanic fetch failed: {e}")
        return []

# ---------- اخبار نهنگ‌ها ----------
def fetch_whale_alerts():
    # (کد کامل این تابع مانند قبل)
    pass

async def fetch_important_news():
    all_news = []
    whale_alerts = fetch_whale_alerts()
    for alert in whale_alerts:
        if "نزولی" in alert["impact"] or "صعودی" in alert["impact"]:
            text = (
                f"🐋 *حرکت نهنگ بزرگ*\n"
                f"💰 مقدار: **{alert['amount_btc']:,.0f} {alert['symbol']}** (~{alert['value_usd']:,.0f} دلار)\n"
                f"📊 نوع تراکنش: {alert['flow_type']}\n"
                f"📈 تأثیر: {alert['impact']}"
            )
            all_news.append({
                "text": text,
                "importance": "high",
                "impact": alert["impact"],
                "source": "whale",
                "timestamp": alert["timestamp"]
            })
    crypto_news = await fetch_cryptopanic_news()
    for item in crypto_news:
        text = f"📰 *{item['title']}*\n📈 تأثیر: {item['impact']}\n📌 منبع: {item['source']}"
        all_news.append({
            "text": text,
            "importance": "high",
            "impact": item["impact"],
            "source": "crypto",
            "timestamp": item["timestamp"]
        })
    return all_news

# ---------- سیستم یادگیری و بهینه‌سازی ----------
def analyze_performance():
    # (کد کامل این تابع مانند قبل)
    pass

def generate_optimization_suggestions(analysis):
    # (کد کامل این تابع مانند قبل)
    pass

async def optimization_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

def kb_suggestion_actions(suggestion_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ اعمال تغییرات", callback_data=f"apply_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("❌ رد پیشنهادات", callback_data=f"reject_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("📊 مشاهده جزئیات", callback_data=f"details_suggestion_{suggestion_id}")],
    ])

async def handle_suggestion_action(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- رویدادها ----------
def fetch_upcoming_events():
    # (کد کامل این تابع مانند قبل)
    pass

async def get_upcoming_events(force=False):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- توابع تحلیل لایه‌ها ----------
async def analyze_layers(code, direction, ind, mode, cache_obj, order_flow=None):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- تولید سیگنال جدید ----------
async def generate_trade_plan_v2(code, mode="standard", send_to_channel=False):
    # (کد کامل این تابع مانند قبل)
    pass

def build_ladder_weighted(ind, direction, mode):
    # (کد کامل این تابع مانند قبل)
    pass

def calc_liquidation_price(direction, entry, leverage):
    # (کد کامل این تابع مانند قبل)
    pass

def signal_reasons(direction, ind, mode):
    # (کد کامل این تابع مانند قبل)
    pass

def record_signal(plan):
    # (کد کامل این تابع مانند قبل)
    pass

def update_signal_status(symbol, current_price):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- فرمت‌سازی ----------
def format_main_signal_v2(plan, code, chat_id):
    # (کد کامل این تابع مانند قبل)
    pass

def format_status_dashboard(code, ind, plan, chat_id, mode, long_layers=None, short_layers=None):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- توابع اصلی ----------
async def generate_trade_plan(code, mode="standard"):
    return await generate_trade_plan_v2(code, mode)

async def generate_status_text_async(code, chat_id, mode="standard"):
    # (کد کامل این تابع مانند قبل)
    pass

async def generate_weekly_summary_async(code, chat_id):
    # (کد کامل این تابع مانند قبل)
    pass

def format_prices_pretty(prices, chat_id):
    # (کد کامل این تابع مانند قبل)
    pass

def split_long_message(text, limit=TELEGRAM_MSG_LIMIT):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- توابع ارسال به کانال ----------
async def send_signal_to_channel(plan, signal_id):
    if not CHANNEL_ID:
        return
    direction_emoji = "🟢" if plan.direction == "LONG" else "🔴"
    mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
    text = (
        f"🔔 سیگنال جدید | {plan.symbol}/USDT\n"
        f"📈 جهت: {plan.direction} {direction_emoji}\n"
        f"🛠️ حالت: {mode_label}\n"
        f"🎯 اطمینان: {plan.confidence:.0f}٪\n"
        f"📐 RR: 1:{plan.rr:.2f}\n\n"
        f"📥 ورود: {format_channel_price(plan.entry_price)}\n"
        f"🛑 حد ضرر: {format_channel_price(plan.sl_price)}\n"
        f"🎯 اهداف:\n"
        f"1️⃣ {format_channel_price(plan.take_profits[0])}\n"
        f"2️⃣ {format_channel_price(plan.take_profits[1])}\n"
        f"3️⃣ {format_channel_price(plan.take_profits[2])}\n\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x\n"
        f"🕒 {shamsi_now()}"
    )
    try:
        msg = await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(text), parse_mode="Markdown")
        channel_signal_messages[signal_id] = msg.message_id
        save_state()
        logger.info(f"Signal sent to channel for {plan.symbol} (signal_id {signal_id})")
    except Exception as e:
        logger.error(f"Failed to send signal to channel: {e}")

def build_signal_update_text_from_record(rec):
    direction_emoji = "🟢" if rec["direction"] == "LONG" else "🔴"
    mode_label = MODE_CONFIGS.get(rec["mode"], MODE_CONFIGS["standard"])["label"]
    if rec["status"] == "tp1_hit":
        status_text = "✅ TP1 زده شد"
        sl_text = f"🛑 حد ضرر به Entry منتقل شد\n📥 ورود: {format_channel_price(rec['entry_price'])}"
        targets = f"🎯 اهداف بعدی:\n2️⃣ {format_channel_price(rec['tp_prices'][1])}\n3️⃣ {format_channel_price(rec['tp_prices'][2])}"
    elif rec["status"] == "tp2_hit":
        status_text = "✅ TP2 زده شد"
        sl_text = f"🛑 حد ضرر به TP1 منتقل شد\n🎯 هدف بعدی:\n3️⃣ {format_channel_price(rec['tp_prices'][2])}"
        targets = ""
    elif rec["status"] == "tp3_hit":
        status_text = "✅ TP3 زده شد"
        sl_text = "🎯 سیگنال با موفقیت بسته شد"
        targets = ""
    elif rec["status"] == "sl_hit":
        status_text = "❌ حد ضرر زده شد"
        sl_text = f"🛑 قیمت به {format_channel_price(rec['sl_price'])} رسید"
        targets = ""
    else:
        return ""

    text = (
        f"🔔 سیگنال | {rec['symbol']}/USDT\n"
        f"📈 جهت: {rec['direction']} {direction_emoji}\n"
        f"🛠️ حالت: {mode_label}\n\n"
        f"{status_text}\n"
        f"{sl_text}\n"
        f"{targets}\n"
        f"🕒 بروزرسانی: {shamsi_now()}"
    )
    return text

async def update_channel_signal_message(signal_id):
    if signal_id not in channel_signal_messages:
        return
    rec = next((r for r in signal_history if r.get("signal_id") == signal_id), None)
    if not rec:
        return
    new_text = build_signal_update_text_from_record(rec)
    if not new_text:
        return
    message_id = channel_signal_messages[signal_id]
    try:
        await app.bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=message_id,
            text=rtl_lines(new_text),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to update channel message for signal {signal_id}: {e}")

async def send_high_importance_news_to_channel(news_text):
    if not CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(news_text), parse_mode="Markdown")
        logger.info("High importance news sent to channel")
    except Exception as e:
        logger.error(f"Failed to send news to channel: {e}")

# ---------- حلقه مستقل کانال ----------
async def channel_broadcast_loop(app):
    await asyncio.sleep(20)
    interval = int(os.getenv("CHANNEL_BROADCAST_INTERVAL", "300"))  # پیش‌فرض ۵ دقیقه
    lock = asyncio.Lock()
    while True:
        try:
            if not CHANNEL_ID:
                logger.warning("CHANNEL_ID not set, channel broadcasting disabled")
                await asyncio.sleep(60)
                continue

            async with lock:
                logger.info("Channel broadcast: updating data and generating signals...")
                await cache.update_prices(force=False)
                await cache.update_ohlcv(force=False)

                for mode in MODE_CONFIGS.keys():
                    for code in cache.valid_codes:
                        try:
                            plan = await generate_trade_plan_v2(code, mode, send_to_channel=True)
                            if plan:
                                logger.info(f"Signal generated: {plan.symbol} {plan.direction} {mode}")
                        except Exception as e:
                            logger.debug(f"Error generating {code} {mode}: {e}")
                        await asyncio.sleep(0.05)
                logger.info("Channel broadcast completed")
        except Exception as e:
            logger.exception("Channel broadcast error: %s", e)
        await asyncio.sleep(interval)

# ---------- حلقه واکنش سریع ----------
trigger_last_prices = {}
trigger_cooldown = {}
TRIGGER_SCAN_INTERVAL = int(os.getenv("TRIGGER_SCAN_INTERVAL", "60"))
TRIGGER_PRICE_CHANGE_PERCENT = float(os.getenv("TRIGGER_PRICE_CHANGE_PERCENT", "0.5"))
TRIGGER_COOLDOWN_SECONDS = int(os.getenv("TRIGGER_COOLDOWN_SECONDS", "300"))

async def trigger_scanner_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            if not CHANNEL_ID:
                await asyncio.sleep(60)
                continue

            await cache.update_prices(force=True)
            now = time.time()

            for code in cache.valid_codes:
                current_price = cache.prices.get(code)
                if not current_price:
                    continue

                prev_price = trigger_last_prices.get(code)
                if prev_price is None:
                    trigger_last_prices[code] = current_price
                    continue

                change_pct = abs((current_price / prev_price - 1) * 100) if prev_price else 0

                if change_pct >= TRIGGER_PRICE_CHANGE_PERCENT:
                    last_sent = trigger_cooldown.get(code, 0)
                    if now - last_sent >= TRIGGER_COOLDOWN_SECONDS:
                        logger.info(f"Trigger detected for {code}: {change_pct:.2f}% change")
                        for mode in ["standard", "conservative"]:
                            plan = await generate_trade_plan_v2(code, mode, send_to_channel=True)
                            if plan:
                                logger.info(f"Trigger signal sent: {code} {mode} {plan.direction}")
                        trigger_cooldown[code] = now

                trigger_last_prices[code] = current_price

        except Exception as e:
            logger.exception("Trigger scanner error: %s", e)
        await asyncio.sleep(TRIGGER_SCAN_INTERVAL)

# ---------- مرکز هوشمندسازی ----------
async def optimization_center(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    text = "🧠 *مرکز هوشمندسازی*\n" + DIVIDER + "\n" + MENU_PROMPT
    await query.edit_message_text(
        text,
        reply_markup=kb_optimization_center(),
        parse_mode="Markdown"
    )

async def optimization_active(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

async def optimization_history(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- دکمه تحلیل جامع ----------
async def comprehensive_analysis(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- مدیریت صفحه نمایش ----------
async def clear_interactive_screen(context, chat_id, keep_id=None):
    ids = interactive_screen_messages.pop(chat_id, [])
    for mid in ids:
        if mid == keep_id: continue
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

def set_interactive_screen(chat_id, message_ids):
    interactive_screen_messages[chat_id] = message_ids

async def clear_overlay(context, chat_id):
    ids = overlay_messages.pop(chat_id, [])
    for mid in ids:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

# ---------- کیبوردها ----------
def build_grid_keyboard(buttons, columns):
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return rows

def kb_currency():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("دلار (USDT) 💵", callback_data="cur_USDT")],
        [InlineKeyboardButton("تومان (IRT) 💴", callback_data="cur_IRT")],
        [InlineKeyboardButton("هر دو 💱", callback_data="cur_BOTH")],
    ])

def kb_role_selection():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ادمین 👑", callback_data="role_admin")],
        [InlineKeyboardButton("کاربر عادی 👤", callback_data="role_user")],
    ])

def kb_mode_selection():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("سریع ⚡", callback_data="mode_fast")],
        [InlineKeyboardButton("نیمه‌سریع 🔥", callback_data="mode_semi_fast")],
        [InlineKeyboardButton("استاندارد 📊", callback_data="mode_standard")],
        [InlineKeyboardButton("محافظه‌کار 🛡️", callback_data="mode_conservative")],
    ])

def kb_mode_selection_for_action(action, code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("سریع ⚡", callback_data=f"run_{action}_{code}_fast")],
        [InlineKeyboardButton("نیمه‌سریع 🔥", callback_data=f"run_{action}_{code}_semi_fast")],
        [InlineKeyboardButton("استاندارد 📊", callback_data=f"run_{action}_{code}_standard")],
        [InlineKeyboardButton("محافظه‌کار 🛡️", callback_data=f"run_{action}_{code}_conservative")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
    ])

def kb_main(user_id, mode="standard"):
    role = user_role.get(user_id, "user")
    if role == "admin":
        rows = [
            [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
            [InlineKeyboardButton("📅 رویدادها", callback_data="events_menu"), InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites")],
            [InlineKeyboardButton("📊 گزارش مقایسه‌ای", callback_data="admin_compare"), InlineKeyboardButton("🧾 گزارش دوره‌ای", callback_data="periodic_report")],
            [InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_bot"), InlineKeyboardButton("🛑 توقف ربات", callback_data="stop_bot")],
            [InlineKeyboardButton("📈 داشبورد تحلیلی", callback_data="dashboard"), InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")],
            [InlineKeyboardButton("❓ راهنما", callback_data="help")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
            [InlineKeyboardButton("📅 رویدادها", callback_data="events_menu"), InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites")],
            [InlineKeyboardButton("🔄 تغییر سبک معاملاتی", callback_data="change_mode"), InlineKeyboardButton("❓ راهنما", callback_data="help")],
            [InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_bot"), InlineKeyboardButton("🛑 توقف ربات", callback_data="stop_bot")],
        ]
    return InlineKeyboardMarkup(rows)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 تحلیل جامع", callback_data="comprehensive_analysis")],
        [InlineKeyboardButton("🔄 بروزرسانی کامل", callback_data="menu_all")],
        [InlineKeyboardButton("🧠 مرکز هوشمندسازی", callback_data="optimization_center")],
        [InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")],
    ])

def kb_optimization_center():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 پیشنهادات فعال", callback_data="optimization_active")],
        [InlineKeyboardButton("📜 تاریخچه پیشنهادات", callback_data="optimization_history")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")],
    ])

def kb_back_to_optimization():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="optimization_center")]
    ])

def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")]
    ])

def kb_back_to_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
    ])

def kb_events_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 رویدادهای پیش رو", callback_data="events_upcoming")],
        [InlineKeyboardButton("📰 اخبار و هشدارها", callback_data="events_news")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_back_to_events():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="events_menu")]
    ])

def kb_back_to_coin(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")]
    ])

def kb_coins(page=0):
    start = page * PER_PAGE
    end = start + PER_PAGE
    page_codes = COIN_CODES[start:end]
    buttons = []
    for code in page_codes:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK":
            label = f"{code} 🟢"
        elif status == "TICKER ERROR":
            label = f"{code} 🟠"
        else:
            label = f"{code} ⚪"
        buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
    rows = build_grid_keyboard(buttons, COINS_GRID_COLUMNS)

    nav_row = []
    total_pages = (len(COIN_CODES) + PER_PAGE - 1) // PER_PAGE
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"coins_page_{page-1}"))
    if end < len(COIN_CODES):
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"coins_page_{page+1}"))
    if nav_row:
        rows.append(nav_row)

    # دکمه دریافت سیگنال‌های فعال بعد از پیمایش و قبل از بازگشت
    rows.append([InlineKeyboardButton("📡 دریافت سیگنال‌های فعال", callback_data="active_signals_all")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def kb_coin_detail(code, is_fav, is_admin_role=False):
    fav_btn = InlineKeyboardButton("🗑️ حذف از علاقه‌مندی‌ها" if is_fav else "⭐ افزودن به علاقه‌مندی‌ها", callback_data=f"toggle_fav_{code}")
    buttons = [
        [InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"askmode_suggest_{code}" if is_admin_role else f"suggest_{code}")],
        [InlineKeyboardButton("🚀 پیشنهاد لحظه‌ای", callback_data=f"askmode_instant_{code}" if is_admin_role else f"instant_{code}")],
        [InlineKeyboardButton("📆 تحلیل جامع ارز", callback_data=f"askmode_weekly_{code}" if is_admin_role else f"weekly_{code}")],
        [fav_btn],
        [InlineKeyboardButton("🔙 لیست ارزها", callback_data="menu_coins"), InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(buttons)

def kb_signal_details(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 جزئیات فنی", callback_data=f"details_{code}")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_back_to_signal(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_weekly(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_suggestion(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("📋 لیست ارزها", callback_data="menu_coins")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_periodic_report():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 هفتگی", callback_data="report_period_weekly"), InlineKeyboardButton("📅 ماهانه", callback_data="report_period_monthly")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_help(step=0):
    buttons = []
    if step < 7:
        buttons.append(InlineKeyboardButton("بعدی ⬅️", callback_data=f"help_{step+1}"))
    if step > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"help_{step-1}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    if step == 0:
        rows.append([InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")])
    else:
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="help_0")])
    return InlineKeyboardMarkup(rows)

def help_text(step):
    # (کد کامل این تابع مانند قبل)
    pass

def welcome_text():
    return rtl_lines(
        "🌟✨ *به سیگنال‌یار حرفه‌ای خوش آمدید!* ✨🌟\n"
        f"{DIVIDER}\n"
        "🤖 *ربات معاملاتی هوشمند* با تحلیل ۱۰ لایه‌ای\n"
        "🎯 *سیگنال‌های لحظه‌ای* با دقت بالا و مدیریت ریسک پویا\n"
        "📊 *تحلیل جامع ارزها* در تایم‌فریم‌های مختلف\n"
        "🔔 *اخبار نهنگ‌ها و رویدادهای مهم* به‌صورت خودکار\n"
        f"{DIVIDER}\n"
        "🚀 *چگونه شروع کنیم؟*\n"
        "۱. واحد پولی خود را انتخاب کنید\n"
        "۲. سبک معاملاتی (سریع، نیمه‌سریع، استاندارد، محافظه‌کار) را تنظیم کنید\n"
        "۳. ارزهای مورد نظر را به علاقه‌مندی‌ها اضافه کنید تا سیگنال خودکار دریافت کنید\n"
        "۴. از منوی اصلی، قیمت‌ها، سیگنال‌ها و تحلیل‌ها را مشاهده کنید\n"
        f"{DIVIDER}\n"
        "⚠️ *توجه:* تمام تحلیل‌ها تکنیکال بوده و توصیه مالی نیستند.\n"
        "🛡️ مدیریت ریسک را همواره رعایت کنید."
    )

MAIN_MENU_HEADER = "✨ *سیگنال‌یار حرفه‌ای* ✨\n" + DIVIDER + "\n" + MENU_PROMPT

async def finish_start(context, chat_id, user_id):
    commands = [
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
        BotCommand("dashboard", "داشبورد تحلیلی"),
        BotCommand("news", "رویدادهای پیش رو"),
        BotCommand("report", "گزارش دوره‌ای"),
        BotCommand("stop", "توقف ربات"),
    ] if is_admin(user_id) else [BotCommand("menu", "منوی اصلی")]
    await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    await clear_interactive_screen(context, chat_id)
    msg = await context.bot.send_message(chat_id=chat_id, text=welcome_text(), reply_markup=kb_main(user_id), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

# ---------- Trailing monitor ----------
async def trailing_monitor_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Event/News monitor ----------
async def news_monitor_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

async def check_and_notify_events(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Whale monitor ----------
async def whale_monitor_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Macro event monitor ----------
async def fetch_macro_events():
    return []

async def macro_event_monitor_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Macro data loop ----------
async def macro_data_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Periodic report ----------
async def send_periodic_report(app, period="weekly"):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Advanced Reporting ----------
def compute_advanced_stats(signal_history, mode=None):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Auto report loop ----------
async def auto_report_loop(app):
    # (کد کامل این تابع مانند قبل)
    pass

# ---------- Command handlers ----------
async def start(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if is_admin(user_id):
        await clear_interactive_screen(context, chat_id)
        msg = await update.message.reply_text("🔐 لطفاً نقش خود را انتخاب کنید:", reply_markup=kb_role_selection())
        set_interactive_screen(chat_id, [msg.message_id])
    else:
        await clear_interactive_screen(context, chat_id)
        msg = await update.message.reply_text("👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:", reply_markup=kb_currency())
        set_interactive_screen(chat_id, [msg.message_id])

async def stop(update, context):
    if not await guard(update): return
    subscribed_chat_ids.discard(update.effective_chat.id)
    active_signals.pop(update.effective_chat.id, None)
    save_state()
    await update.message.reply_text("🛑 ربات متوقف شد.\nبرای فعال‌سازی دوباره /start را بزن.")

async def menu_command(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id; user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id); save_state()
    role = user_role.get(chat_id, "user")
    mode = user_trading_mode.get(chat_id, "standard") if role == "user" else "standard"
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

async def status(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

async def dashboard(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

async def news(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

async def periodic_report_command(update, context):
    # (کد کامل این تابع مانند قبل)
    pass

def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "subscribed_chat_ids": list(subscribed_chat_ids),
                "user_currency": user_currency,
                "user_trading_mode": user_trading_mode,
                "user_favorites": {str(k): list(v) for k, v in user_favorites.items()},
                "user_role": {str(k): v for k, v in user_role.items()},
                "news_history": news_history[-20:],
                "signal_history": signal_history[-200:],
                "suggestion_history": suggestion_history[-20:],
                "channel_signal_messages": {str(k): v for k, v in channel_signal_messages.items()},
            }, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("State save failed: %s", e)

def load_state():
    global subscribed_chat_ids, user_currency, user_trading_mode, user_favorites, user_role, news_history, signal_history, suggestion_history, channel_signal_messages
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
        user_trading_mode = {int(k): v for k, v in data.get("user_trading_mode", {}).items()}
        user_favorites = {int(k): set(v) for k, v in data.get("user_favorites", {}).items()}
        user_role = {int(k): v for k, v in data.get("user_role", {}).items()}
        news_history = data.get("news_history", [])
        signal_history = data.get("signal_history", [])
        suggestion_history = data.get("suggestion_history", [])
        channel_signal_messages = {str(k): int(v) for k, v in data.get("channel_signal_messages", {}).items()}
        logger.info("State restored: %s users, %s signals, %s suggestions, %s channel messages",
                    len(subscribed_chat_ids), len(signal_history), len(suggestion_history), len(channel_signal_messages))
    except FileNotFoundError:
        logger.info("No state file; starting fresh.")
        news_history = []
        signal_history = []
        suggestion_history = []
        channel_signal_messages = {}
    except Exception as e:
        logger.warning("State load failed: %s", e)
        news_history = []
        signal_history = []
        suggestion_history = []
        channel_signal_messages = {}

# ---------- Button handler ----------
async def button_handler(update, context):
    if not await guard(update): return
    query = update.callback_query; await query.answer()
    data = query.data; chat_id = update.effective_chat.id; user_id = update.effective_user.id
    if data == "noop": return

    if data == "optimization_center":
        await optimization_center(update, context)
        return
    if data == "optimization_active":
        await optimization_active(update, context)
        return
    if data == "optimization_history":
        await optimization_history(update, context)
        return

    if data.startswith("apply_suggestion_") or data.startswith("reject_suggestion_") or data.startswith("details_suggestion_"):
        await handle_suggestion_action(update, context)
        return

    if data == "comprehensive_analysis":
        await comprehensive_analysis(update, context)
        return

    if data == "role_admin":
        user_role[chat_id] = "admin"
        save_state()
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👑 وارد حالت ادمین شدید.\nحالا واحد پولی را انتخاب کنید:", reply_markup=kb_currency())
        return
    if data == "role_user":
        user_role[chat_id] = "user"
        save_state()
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👤 وارد حالت کاربر عادی شدید. واحد پولی را انتخاب کنید:", reply_markup=kb_currency())
        return

    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        subscribed_chat_ids.add(chat_id)
        save_state()
        msg_id = query.message.message_id
        if user_role.get(chat_id, "user") == "admin":
            await query.edit_message_text("✅ واحد پولی انتخاب شد. منوی اصلی:")
            await finish_start(context, chat_id, user_id)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        else:
            await query.edit_message_text("🛠️ حالا سبک معاملاتی خود را انتخاب کن:", reply_markup=kb_mode_selection())
        return

    if data.startswith("mode_"):
        mode = data.split("_", 1)[1]
        user_trading_mode[chat_id] = mode
        save_state()
        msg_id = query.message.message_id
        await query.edit_message_text(f"✅ حالت {MODE_CONFIGS[mode]['label']} انتخاب شد.")
        await finish_start(context, chat_id, user_id)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
        return

    if data == "change_mode":
        if user_role.get(chat_id, "user") == "admin":
            await query.answer("ادمین حالت ثابت ندارد.", show_alert=True)
            return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("🛠️ سبک معاملاتی جدید را انتخاب کن:", reply_markup=kb_mode_selection())
        return

    if data == "restart_bot":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if is_admin(user_id):
            await query.edit_message_text("🔐 لطفاً نقش خود را انتخاب کنید:", reply_markup=kb_role_selection())
        else:
            await query.edit_message_text("👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:", reply_markup=kb_currency())
        return

    if data == "stop_bot":
        subscribed_chat_ids.discard(chat_id)
        active_signals.pop(chat_id, None)
        save_state()
        await query.edit_message_text("🛑 ربات برای شما متوقف شد.\nبرای فعال‌سازی دوباره /start را بزن.")
        return

    if data == "help":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(help_text(0), reply_markup=kb_help(0), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("help_"):
        step = int(data.split("_")[1])
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(help_text(step), reply_markup=kb_help(step), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "close_temp":
        await clear_overlay(context, chat_id); return

    if data == "menu_main":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        role = user_role.get(chat_id, "user")
        mode = user_trading_mode.get(chat_id, "standard") if role == "user" else "standard"
        await query.edit_message_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data == "events_menu":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("📋 *منوی رویدادها*\n" + DIVIDER + "\n" + MENU_PROMPT, reply_markup=kb_events_menu(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data == "events_upcoming":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        events = await get_upcoming_events(force=True)
        now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
        upcoming = [ev for ev in events if ev["time"].tzinfo is None or (ev["time"] - now_utc) >= timedelta(0)]
        if not upcoming:
            text = "📅 رویداد مهمی در آینده نزدیک یافت نشد."
        else:
            text = "📅 *رویدادهای کریپتویی پیش رو:*\n" + DIVIDER + "\n"
            for ev in upcoming[:10]:
                importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} *{ev['name']}*\n"
                text += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
                if ev.get("description"):
                    text += f"📝 {ev['description'][:100]}...\n"
                if ev.get("impact"):
                    text += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
                text += "\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_to_events(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "events_news":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if not news_history:
            text = "📰 *تاریخچه اخبار و هشدارها*\n" + DIVIDER + "\n\nهیچ خبری ثبت نشده است."
        else:
            text = "📰 *تاریخچه اخبار و هشدارها*\n" + DIVIDER + "\n"
            for item in reversed(news_history[-20:]):
                importance_emoji = "🔴" if item.get("importance") == "high" else "🟡" if item.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} {item['time']}\n{item['text']}\n\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_to_events(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "dashboard":
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "favorites":
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("toggle_fav_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "periodic_report":
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("report_period_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "admin_compare":
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("coins_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_reply_markup(reply_markup=kb_coins(page))
        return

    if data == "menu_prices":
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "menu_coins":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(rtl_lines(f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"), reply_markup=kb_coins(0), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data.startswith("coin_"):
        code = data.split("_", 1)[1]
        if code not in COIN_CODES: return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if code in cache.exchange_symbols:
            status = cache.market_status.get(code, {}).get("status")
            warning = ""
            if status == "TICKER ERROR":
                warning = "⚠️ قیمت لحظه‌ای در دسترس نیست، اما تحلیل‌های دیگر کار می‌کنند.\n\n"
            favs = user_favorites.get(chat_id, set())
            is_fav = code in favs
            admin = is_admin_role(chat_id)
            await query.edit_message_text(
                rtl_lines(f"{code}\n{DIVIDER}\n{warning}🟢 وضعیت بازار: *SWAP OK*\n{MENU_PROMPT}"),
                reply_markup=kb_coin_detail(code, is_fav, is_admin_role=admin),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        else:
            text = f"{code}\n{DIVIDER}\n⚪ وضعیت: *NO SWAP*\nدر حال حاضر قرارداد USDT Perpetual فعال برای این ارز در KuCoin پیدا نشد."
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        return

    # ----- بخش ادمین -----
    if data.startswith("askmode_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("run_"):
        # (کد کامل این بخش مانند قبل)
        pass

    # ----- کاربر عادی -----
    if data.startswith("suggest_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("instant_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("weekly_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data.startswith("details_"):
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "admin_panel":
        # (کد کامل این بخش مانند قبل)
        pass

    if data == "menu_all":
        # (کد کامل این بخش مانند قبل)
        pass

    # دکمه جدید: نمایش همه سیگنال‌های فعال
    if data == "active_signals_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        recent_signals = signal_history[-20:]
        if not recent_signals:
            text = "📡 *سیگنال‌های فعال*\n\nهنوز سیگنالی ثبت نشده است."
        else:
            text = "📡 *سیگنال‌های فعال (آخرین ۲۰)*\n" + DIVIDER + "\n"
            for rec in reversed(recent_signals):
                direction_emoji = "🟢" if rec["direction"] == "LONG" else "🔴"
                mode_label = MODE_CONFIGS.get(rec["mode"], MODE_CONFIGS["standard"])["label"]
                status_text = "باز" if rec["status"] == "open" else rec["status"]
                text += (
                    f"{rec['symbol']} | {rec['direction']} {direction_emoji} | {mode_label}\n"
                    f"   اطمینان: {rec['confidence']:.0f}٪ | RR: {rec['rr']:.2f} | وضعیت: {status_text}\n"
                    f"   ورود: {rec['entry_price']:.4f} | SL: {rec['sl_price']:.4f}\n"
                    f"   TP1: {rec['tp_prices'][0]:.4f} | TP2: {rec['tp_prices'][1]:.4f} | TP3: {rec['tp_prices'][2]:.4f}\n"
                    f"{DIVIDER}\n"
                )
        await query.edit_message_text(
            rtl_lines(text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")]]),
            parse_mode="Markdown"
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

def format_technical_details(code, plan, ind, chat_id):
    # (کد کامل این تابع مانند قبل)
    pass

async def delete_news_messages_after_delay(app, chat_id, message_id, delay=NEWS_AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
        BotCommand("dashboard", "داشبورد تحلیلی"),
        BotCommand("news", "رویدادهای پیش رو"),
        BotCommand("report", "گزارش دوره‌ای"),
        BotCommand("stop", "توقف ربات"),
    ])
    app.create_task(auto_report_loop(app))
    app.create_task(trailing_monitor_loop(app))
    app.create_task(news_monitor_loop(app))
    app.create_task(whale_monitor_loop(app))
    app.create_task(macro_event_monitor_loop(app))
    app.create_task(macro_data_loop(app))
    app.create_task(optimization_loop(app))
    app.create_task(channel_broadcast_loop(app))
    app.create_task(trigger_scanner_loop(app))
    logger.info("Signal Bot V60 (Channel + Trigger Scanner) started")

def main():
    global app
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN در .env تنظیم نشده است.")
    if not ALLOWED_USER_IDS:
        logger.warning("⚠️ ALLOWED_USER_IDS تنظیم نشده؛ ربات برای همه باز است.")
    load_state()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("report", periodic_report_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
