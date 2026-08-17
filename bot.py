"""
Telegram Signal Bot V62 - Institutional Grade with Intelligence Center
(نسخه اصلاح‌شده - رفع باگ‌های سیگنال‌دهی کانال)

خلاصه اصلاحات نسبت به V61:
1) کانال دیگر بر اساس «حالت/نوع معامله» سیگنال جدا صادر نمی‌کند؛ برای هر ارز فقط یک
   تحلیل واحد (CHANNEL_SIGNAL_MODE) با آستانه‌های سخت‌گیرانه‌تر (CHANNEL_MIN_*) بررسی می‌شود
   تا حداکثر یک سیگنال زنده به‌ازای هر ارز در کانال وجود داشته باشد.
2) رفع باگ حیاتی در update_signal_status: در نسخه قبل به‌محض برخورد قیمت به TP1، رکورد
   سیگنال دیگر هرگز برای TP2/TP3/برخورد بعدی حد ضرر پیگیری نمی‌شد (چون فقط رکوردهای
   status == "open" بررسی می‌شدند). اکنون پیگیری تا رسیدن به وضعیت نهایی ادامه دارد و
   حد ضرر هم به‌صورت پویا (Trailing) بعد از هر TP جابه‌جا می‌شود.
3) رفع باگ: پایش TP/SL سیگنال‌های کانال قبلاً فقط از طریق «سیگنال‌های فعال شخصی هر
   کاربر» (active_signals) انجام می‌شد؛ یعنی اگر هیچ کاربری یک سیگنال کانال را شخصاً
   دنبال نکرده بود، آن سیگنال هرگز TP/SL‌اش چک نمی‌شد و پیام کانال هرگز بروزرسانی/حذف
   نمی‌شد. حلقه مستقل channel_signal_monitor_loop این مشکل را برطرف کرده است.
4) حذف حلقه قدیمی trigger_scanner_loop که با هر نوسان ۰.۵٪ قیمت، سیگنال تازه (با آستانه
   پایین) برای دو حالت معاملاتی صادر می‌کرد و منبع اصلی سیگنال‌های کاذب/تکراری بود.
5) رفع باگ در auto_report_loop: این حلقه برای گزارش خصوصی هر کاربر، اشتباهاً
   send_to_channel=True صدا می‌زد و به همین دلیل سیگنال‌های شخصی/دلخواه هر کاربر
   (با مود دلخواه خودش) هم وارد کانال عمومی می‌شد.
6) افزایش آستانه‌های اطمینان/اختلاف جهت/تعداد لایه‌های تاییدی و افزودن فیلتر ADX
   مخصوص کانال، تا فقط سیگنال‌های با اطمینان بالا در کانال منتشر شوند.
7) وقتی جهت یک سیگنال باز کاملاً برعکس می‌شود، رکورد قبلی به‌جای بازنویسی خاموش،
   status="invalidated" می‌گیرد (از آمار موفق/ناموفق حذف می‌شود) و سیگنال تازه با
   شناسه جدید ثبت و در کانال به‌عنوان «سیگنال جدید» ارسال می‌شود؛ وقتی فقط ورود/اهداف
   کمی تغییر کرده (همان جهت)، همان پیام با متن «سیگنال اصلاح شد» جایگزین می‌شود.
8) کول‌داون ۴۵ دقیقه‌ای بعد از بسته‌شدن هر سیگنال کانال، برای جلوگیری از باز شدن فوری
   سیگنال بعدی همان ارز (کاهش تعداد سیگنال‌ها طبق درخواست).

--- اصلاحات دور بعدی (این نسخه) ---
9)  رفع باگ امنیتی حیاتی: is_admin_role فقط user_role را چک می‌کرد (که با یک
    callback_data ساختگی «role_admin» توسط هر کاربری قابل تغییر بود)؛ اکنون علاوه بر
    آن حتماً باید chat_id واقعاً در ADMIN_USER_IDS (.env) هم باشد. دکمه‌ی «ادمین 👑» هم
    مستقیماً is_admin() را چک می‌کند.
10) رفع باگ: TOTAL_SIGNALS_GENERATED و LAST_REPORT_TIME هرگز بروزرسانی نمی‌شدند (همیشه
    ۰ و خالی نمایش داده می‌شدند)؛ اکنون در record_signal() بروزرسانی می‌شوند.
11) افزوده شدن escape_markdown و اعمال آن روی هر متنی که از منابع بیرونی (CryptoPanic،
    CoinGecko events، برچسب‌های Whale-Alert) می‌آید، تا کاراکترهای خاص Markdown باعث
    fail شدن کامل ارسال پیام نشوند.
12) سیگنال‌دهی به‌طور کلی سخت‌گیرانه‌تر شد: سطح سخت‌گیری قبلیِ حالت «استاندارد» تقریباً
    به حالت «سریع» منتقل شد و سه حالت دیگر هم به همان نسبت سخت‌گیرانه‌تر شدند
    (min_confirmations/adx_min/min_rr در هر ۴ حالت بالا رفت، هم‌چنین
    MIN_SIGNAL_CONFIDENCE/MIN_DIRECTION_GAP و آستانه‌های کانال). مسیر جایگزین ضعیف در
    انتخاب جهت سیگنال شخصی (که با گپ نزدیک صفر هم سیگنال می‌داد) حذف شد.
13) مرکز هوشمندسازی بازطراحی شد: تحلیل عملکرد اکنون به‌تفکیک هر حالت معاملاتی (نه فقط
    استاندارد) انجام می‌شود و پیشنهادها پارامترهای واقعی همان حالت (adx_min،
    min_confirmations، min_rr) را هدف می‌گیرند. صفحه‌ی «پیشنهادات فعال» دیگر فقط
    پیشنهادهای pending را نشان نمی‌دهد؛ همیشه آخرین پیشنهاد را با جزئیات کامل و دکمه‌های
    فعال نشان می‌دهد تا صرف‌نظر از اتفاقی که برای پیام مستقیم افتاده، بشود تصمیم را در
    هر زمان اعمال/رد/تغییر داد (رد کردن یک پیشنهاد قبلاً اعمال‌شده پارامترها را برمی‌گرداند).
14) پیام سیگنال کانال اکنون حالت معاملاتی را در خط دوم نشان می‌دهد. وقتی سیگنالی به‌طور
    نهایی بسته می‌شود (TP3 یا SL)، به‌جای یک خط خلاصه، پیام کامل شامل جهت، حالت، تمام
    ورودها/اهداف/حد ضرر، اهرم، اطمینان اولیه، RR و مدت‌زمان باز بودن معامله جایگزین پیام
    قبلی می‌شود (پیام قبلی حذف و پیام تازه با اطلاعات کامل ارسال می‌شود).
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
MAX_OHLCV_CONCURRENCY = 4
MAX_SIGNAL_CONCURRENCY = 4
MAX_PRICE_CONCURRENCY = 6
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

# ========== تنظیمات سیگنال‌دهی (سخت‌گیرانه‌تر شده) ==========
# طبق درخواست: کل سیستم سیگنال‌دهی سخت‌گیرانه‌تر شد. سطح سخت‌گیری قبلیِ حالت
# «استاندارد» اکنون تقریباً معادل سخت‌گیری حالت «سریع» جدید است و سه حالت دیگر هم به
# همان نسبت سخت‌گیرانه‌تر شدند (min_confirmations/adx_min/min_rr همه بالاتر رفتند).
# نتیجه: سیگنال‌های کمتر ولی با کیفیت و اطمینان بالاتر در همه حالت‌ها، نه فقط کانال.
MIN_SIGNAL_CONFIDENCE = 55      # قبلاً 40
MIN_DIRECTION_GAP = 10          # قبلاً 6
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]

# ========== تنظیمات اختصاصی سیگنال‌های کانال (سخت‌گیرانه‌تر از حالت پایه، برای کاهش بیشتر سیگنال‌های کاذب) ==========
# در کانال دیگر بر اساس «نوع معامله/حالت» سیگنال جدا ارسال نمی‌شود؛ برای هر ارز فقط
# یک تحلیل واحد و معتبرتر (بر پایه‌ی حالت CHANNEL_SIGNAL_MODE) در نظر گرفته می‌شود.
CHANNEL_SIGNAL_MODE = "standard"
CHANNEL_CHECK_INTERVAL_SECONDS = 20 * 60       # هر ۲۰ دقیقه یک دور بررسی کامل روی همه ارزها
CHANNEL_REOPEN_COOLDOWN_SECONDS = 45 * 60      # بعد از بسته‌شدن یک سیگنال، حداقل فاصله تا سیگنال بعدی همان ارز
CHANNEL_MIN_SIGNAL_CONFIDENCE = 78             # قبلاً 68 — حداقل اطمینان برای انتشار در کانال
CHANNEL_MIN_DIRECTION_GAP = 25                 # قبلاً 18 — اختلاف امتیاز لانگ/شورت باید کاملاً واضح باشد
CHANNEL_MIN_CONFIRMATIONS_BONUS = 1            # لایه تاییدی اضافه نسبت به حداقل حالت پایه (که خودش بالا رفته)
CHANNEL_ADX_MIN = 22                           # قبلاً 20 — فقط در بازار با روند نسبتاً قوی سیگنال کانال صادر شود

MODE_CONFIGS = {
    "fast": {
        "label": "سریع ⚡",
        "main_tf": "5m",
        "confirm_tfs": ["15m", "1h"],
        "entry_ladder_atr": [0.0, 0.2, 0.4],
        "tp_multipliers": [0.8, 1.5, 2.5],
        "sl_atr_mult": 0.8,
        "max_leverage": 10,
        "min_rr": 1.00,          # قبلاً 0.50
        "adx_min": 8,            # قبلاً 5
        "min_confirmations": 5,  # قبلاً 3 (تقریباً معادل سخت‌گیری «استاندارد» قدیم)
        "check_interval": 5 * 60,
    },
    "semi_fast": {
        "label": "نیمه‌سریع 🔥",
        "main_tf": "15m",
        "confirm_tfs": ["1h", "4h"],
        "entry_ladder_atr": [0.0, 0.3, 0.6],
        "tp_multipliers": [1.2, 2.5, 4.0],
        "sl_atr_mult": 1.0,
        "max_leverage": 7,
        "min_rr": 1.30,          # قبلاً 0.80
        "adx_min": 11,           # قبلاً 7
        "min_confirmations": 6,  # قبلاً 4
        "check_interval": 10 * 60,
    },
    "standard": {
        "label": "استاندارد 📊",
        "main_tf": "1h",
        "confirm_tfs": ["4h", "1d"],
        "entry_ladder_atr": [0.0, 0.4, 0.8],
        "tp_multipliers": [1.5, 3.0, 5.0],
        "sl_atr_mult": 1.2,
        "max_leverage": 5,
        "min_rr": 1.60,          # قبلاً 1.20
        "adx_min": 14,           # قبلاً 8
        "min_confirmations": 7,  # قبلاً 5
        "check_interval": 30 * 60,
    },
    "conservative": {
        "label": "محافظه‌کار 🛡️",
        "main_tf": "4h",
        "confirm_tfs": ["1d", "1d"],
        "entry_ladder_atr": [0.0, 0.6, 1.2],
        "tp_multipliers": [2.0, 4.0, 6.0],
        "sl_atr_mult": 2.0,
        "max_leverage": 3,
        "min_rr": 2.00,          # قبلاً 1.50
        "adx_min": 18,           # قبلاً 10
        "min_confirmations": 8,  # قبلاً 6
        "check_interval": 60 * 60,
    },
}

MIN_TP_PERCENTAGES = {
    "fast": [0.4, 0.8, 1.5],
    "semi_fast": [0.6, 1.2, 2.5],
    "standard": [0.8, 1.5, 3.0],
    "conservative": [1.2, 2.5, 5.0],
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
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.prices = {}
        self.ohlcv = {tf: {} for tf in TIMEFRAMES}
        self.ohlcv_updated_at = {tf: {} for tf in TIMEFRAMES}
        self.valid_codes = []
        self.exchange_symbols = {}
        self.symbol_sources = {}
        self.market_status = {
            code: {"status": "NO SWAP", "symbol": None, "error": None, "source": None}
            for code in COIN_CODES
        }
        self.last_price_update = 0.0
        self.last_full_ohlcv_update = 0.0
        self._sem = asyncio.Semaphore(MAX_OHLCV_CONCURRENCY)
        self._price_sem = asyncio.Semaphore(MAX_PRICE_CONCURRENCY)
        self._update_lock = asyncio.Lock()
        self._symbol_locks = {}
        self._breadth_cache = {"value": None, "ts": 0.0}
        self._breadth_sample_count = 0
        self._sentiment_cache = {}
        self._macro_cache = {"data": {}, "ts": 0.0}
        self._load_markets()

    def _symbol_lock(self, code):
        if code not in self._symbol_locks:
            self._symbol_locks[code] = asyncio.Lock()
        return self._symbol_locks[code]

    def _load_markets(self):
        try:
            gateio_markets = exchange_gateio.load_markets()
            kucoin_markets = None
            selected = {}
            sources = {}
            for code in COIN_CODES:
                found = False
                gateio_symbol = GATEIO_SYMBOL_MAP.get(code)
                if gateio_symbol and gateio_symbol in gateio_markets:
                    market = gateio_markets[gateio_symbol]
                    if market.get("active") is not False and market.get("type") == "spot":
                        selected[code] = gateio_symbol
                        sources[code] = "gateio"
                        self.market_status[code] = {"status": "SWAP OK", "symbol": gateio_symbol, "error": None, "source": "gateio"}
                        found = True
                if not found:
                    if kucoin_markets is None:
                        try:
                            kucoin_markets = exchange_spot_kucoin.load_markets()
                        except Exception as e:
                            logger.warning("KuCoin load markets failed: %s", e)
                            kucoin_markets = {}
                    kucoin_symbol = f"{code}/USDT"
                    if kucoin_symbol in kucoin_markets:
                        market = kucoin_markets[kucoin_symbol]
                        if market.get("active") is not False and market.get("type") == "spot":
                            selected[code] = kucoin_symbol
                            sources[code] = "kucoin"
                            self.market_status[code] = {"status": "SWAP OK", "symbol": kucoin_symbol, "error": None, "source": "kucoin"}
                            found = True
                if not found:
                    logger.warning(f"ارز {code} در Gate.io و KuCoin یافت نشد.")
                    selected[code] = code
                    sources[code] = "unknown"
                    self.market_status[code] = {"status": "NO SWAP", "symbol": code, "error": "Not found", "source": "unknown"}
            self.exchange_symbols = selected
            self.symbol_sources = sources
            self.valid_codes = [code for code in COIN_CODES if sources.get(code) != "unknown"]
            logger.info("Markets loaded: %s/%s from Gate.io + KuCoin", len(self.valid_codes), len(COIN_CODES))
        except Exception as e:
            logger.exception("load_markets failed: %s", e)

    def symbol_for_code(self, code) -> Optional[str]:
        return self.exchange_symbols.get(code)

    def source_for_code(self, code) -> Optional[str]:
        return self.symbol_sources.get(code, "unknown")

    @staticmethod
    def _to_dataframe(raw):
        if raw is None:
            return None
        if isinstance(raw, pd.DataFrame):
            df = raw.copy()
        else:
            if not isinstance(raw, (list, tuple)) or not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        if any(col not in df.columns for col in required):
            return None
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=required).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df if not df.empty else None

    async def update_macro_data(self):
        try:
            url = "https://api.coingecko.com/api/v3/global"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()["data"]
            self._macro_cache = {
                "data": {
                    "btc_dominance": float(data.get("market_cap_percentage", {}).get("btc", 50)),
                    "total_market_cap": float(data.get("total_market_cap", {}).get("usd", 0)),
                    "total_volume": float(data.get("total_volume", {}).get("usd", 0)),
                },
                "ts": time.time()
            }
            logger.info("Macro data updated: BTC dominance %.1f%%", self._macro_cache["data"]["btc_dominance"])
        except Exception as e:
            logger.warning(f"Macro data fetch failed: {e}")

    def get_macro_data(self):
        return self._macro_cache["data"] if self._macro_cache["data"] else None

    def _get_coingecko_prices(self, codes):
        prices = {}
        try:
            ids_map = {
                "AAVE": "aave", "ADA": "cardano", "ALGO": "algorand", "APE": "apecoin",
                "APT": "aptos", "AR": "arweave", "ARB": "arbitrum", "ATOM": "cosmos",
                "AVAX": "avalanche-2", "BCH": "bitcoin-cash", "BLUR": "blur", "BTC": "bitcoin",
                "COMP": "compound-governance-token", "DOGE": "dogecoin", "DOT": "polkadot",
                "EGLD": "elrond-erd-2", "ETC": "ethereum-classic", "ETH": "ethereum",
                "FET": "fetch-ai", "FIL": "filecoin", "FLOW": "flow",
                "GRT": "the-graph", "ICP": "internet-computer", "INJ": "injective-protocol",
                "KAS": "kaspa", "KAVA": "kava", "KSM": "kusama", "LINK": "chainlink",
                "LTC": "litecoin", "LUNC": "terra-luna-classic", "MANA": "decentraland",
                "MINA": "mina-protocol", "NEAR": "near", "NEO": "neo", "OP": "optimism",
                "POL": "polygon-ecosystem-token", "RUNE": "thorchain", "SAND": "the-sandbox",
                "SHIB": "shiba-inu", "SOL": "solana", "STX": "blockstack", "SUI": "sui",
                "TRX": "tron", "UNI": "uniswap",
                "VET": "vechain", "XLM": "stellar", "XMR": "monero", "XRP": "ripple",
            }
            ids = [ids_map[code] for code in codes if code in ids_map]
            if not ids:
                return prices
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": ",".join(ids), "vs_currencies": "usd"}
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            reverse_map = {v: k for k, v in ids_map.items()}
            for cg_id, info in data.items():
                if cg_id in reverse_map:
                    code = reverse_map[cg_id]
                    price = info.get("usd")
                    if price:
                        prices[code] = float(price)
        except Exception as e:
            logger.warning("CoinGecko fetch failed: %s", e)
        return prices

    async def update_prices(self, force=False, codes=None):
        target_codes = codes if codes is not None else COIN_CODES
        now = time.time()
        if not force and self.prices and self.last_price_update and now - self.last_price_update < PRICE_TTL_SECONDS:
            return self.prices

        new_prices = {}
        price_sources.clear()

        gateio_codes = [code for code in target_codes if GATEIO_SYMBOL_MAP.get(code)]
        if gateio_codes:
            try:
                valid_gateio_codes = [c for c in gateio_codes if GATEIO_SYMBOL_MAP[c] in exchange_gateio.markets]
                symbols = [GATEIO_SYMBOL_MAP[c] for c in valid_gateio_codes]
                if symbols:
                    tickers = await asyncio.to_thread(exchange_gateio.fetch_tickers, symbols)
                    for code in valid_gateio_codes:
                        sym = GATEIO_SYMBOL_MAP.get(code)
                        if sym in tickers:
                            ticker = tickers[sym]
                            price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                            if price and price > 0:
                                new_prices[code] = float(price)
                                price_sources[code] = "G"
            except Exception as e:
                logger.warning(f"Gate.io fetch_tickers failed: {e}")

        missing = [code for code in target_codes if code not in new_prices]
        if missing:
            try:
                symbols = [f"{code}/USDT" for code in missing]
                tickers = await asyncio.to_thread(exchange_spot_kucoin.fetch_tickers, symbols)
                for code in missing:
                    sym = f"{code}/USDT"
                    if sym in tickers:
                        ticker = tickers[sym]
                        price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                        if price and price > 0:
                            new_prices[code] = float(price)
                            price_sources[code] = "K"
            except Exception as e:
                logger.warning(f"KuCoin fetch_tickers failed: {e}")

        still_missing = [code for code in target_codes if code not in new_prices]
        if still_missing:
            try:
                gecko_prices = await asyncio.to_thread(self._get_coingecko_prices, still_missing)
                for code, price in gecko_prices.items():
                    if price and price > 0:
                        new_prices[code] = price
                        price_sources[code] = "C"
            except Exception as e:
                logger.warning(f"CoinGecko fetch failed: {e}")

        for code in target_codes:
            if code in new_prices:
                self.prices[code] = new_prices[code]
        self.last_price_update = time.time()
        logger.info("Prices loaded: %s/%s", len(self.prices), len(COIN_CODES))
        return self.prices

    def _get_market_breadth(self):
        now = time.time()
        if self._breadth_cache["value"] is not None and now - self._breadth_cache["ts"] < 60:
            return self._breadth_cache["value"]
        count_above = 0
        total = 0
        for code in self.valid_codes:
            df = self.ohlcv.get("1h", {}).get(code)
            if df is not None and len(df) > 20:
                close = df["close"]
                ema20 = EMAIndicator(close, window=20).ema_indicator()
                if len(ema20) > 0 and pd.notna(ema20.iloc[-1]):
                    if close.iloc[-1] > ema20.iloc[-1]:
                        count_above += 1
                    total += 1
        breadth = count_above / total * 100 if total > 0 else 50
        self._breadth_sample_count = total
        self._breadth_cache = {"value": breadth, "ts": now}
        return breadth

    async def _get_order_flow(self, code):
        try:
            symbol = self.symbol_for_code(code)
            if not symbol:
                return 0.0
            source = self.source_for_code(code)
            if source == "gateio":
                order_book = await asyncio.to_thread(exchange_gateio.fetch_order_book, symbol, limit=5)
            elif source == "kucoin":
                order_book = await asyncio.to_thread(exchange_spot_kucoin.fetch_order_book, symbol, limit=5)
            else:
                return 0.0
            bids_volume = sum(bid[1] for bid in order_book["bids"][:5])
            asks_volume = sum(ask[1] for ask in order_book["asks"][:5])
            if asks_volume == 0:
                return 0.0
            ratio = bids_volume / asks_volume
            return min(2.0, ratio)
        except Exception as e:
            logger.debug(f"Order flow failed for {code}: {e}")
            return 0.0

    async def _calculate_sentiment_score(self, code, ind):
        price_change_1h = 0
        price_change_4h = 0
        price_change_24h = 0
        df_1h = self.ohlcv.get("1h", {}).get(code)
        df_4h = self.ohlcv.get("4h", {}).get(code)
        df_1d = self.ohlcv.get("1d", {}).get(code)
        if df_1h is not None and len(df_1h) > 2:
            price_change_1h = (df_1h["close"].iloc[-1] / df_1h["close"].iloc[-2] - 1) * 100
        if df_4h is not None and len(df_4h) > 2:
            price_change_4h = (df_4h["close"].iloc[-1] / df_4h["close"].iloc[-2] - 1) * 100
        if df_1d is not None and len(df_1d) > 2:
            price_change_24h = (df_1d["close"].iloc[-1] / df_1d["close"].iloc[-2] - 1) * 100
        weighted_price_change = (price_change_1h * 0.5) + (price_change_4h * 0.3) + (price_change_24h * 0.2)
        price_score = max(-1, min(1, weighted_price_change / 5))
        volume_ratio = ind.get("volume_ratio", 1.0)
        if volume_ratio > 2.0:
            volume_score = 1.0
        elif volume_ratio > 1.5:
            volume_score = 0.5
        elif volume_ratio < 0.5:
            volume_score = -0.5
        else:
            volume_score = 0.0
        fg_value, _ = await get_fear_greed()
        if fg_value is not None:
            fg_score = (fg_value - 50) / 50
            fg_score = max(-1, min(1, fg_score))
        else:
            fg_score = 0.0
        sentiment_score = (price_score * 0.4) + (volume_score * 0.4) + (fg_score * 0.2)
        return max(-1, min(1, sentiment_score))

    def _get_smart_volatility(self, ind):
        bb_percent = ind.get("bb_percent", 0.5)
        if bb_percent > 0.8:
            return 0.7
        elif bb_percent < 0.2:
            return -0.7
        else:
            return 0.0

    def _get_complementary_trend(self, ind):
        plus_di = ind.get("plus_di", 0)
        minus_di = ind.get("minus_di", 0)
        diff = plus_di - minus_di
        if diff > 15:
            return 0.7
        elif diff < -15:
            return -0.7
        else:
            return 0.0

    async def _fetch_ohlcv_symbol(self, code, timeframe, limit=500):
        symbol = self.symbol_for_code(code)
        if not symbol:
            return None
        source = self.source_for_code(code)

        exchanges = []
        if source == "gateio":
            exchanges.append((exchange_gateio, "gateio", symbol))
            exchanges.append((exchange_spot_kucoin, "kucoin", f"{code}/USDT"))
        elif source == "kucoin":
            exchanges.append((exchange_spot_kucoin, "kucoin", f"{code}/USDT"))
        else:
            return None

        async with self._sem:
            for ex, name, sym in exchanges:
                for attempt in range(3):
                    try:
                        raw = await asyncio.to_thread(ex.fetch_ohlcv, sym, timeframe, None, limit)
                        df = self._to_dataframe(raw)
                        if df is None or len(df) < 10:
                            logger.debug(f"OHLCV {code} {timeframe} from {name}: insufficient rows {len(df) if df is not None else 0}")
                            await asyncio.sleep(2 ** attempt)
                            continue
                        logger.debug(f"OHLCV {code} {timeframe} fetched from {name}")
                        return df
                    except Exception as e:
                        wait = 2 ** attempt
                        logger.warning(f"OHLCV {code} {timeframe} from {name} attempt {attempt} failed: {e}, wait {wait}s")
                        await asyncio.sleep(wait)
                logger.warning(f"OHLCV {code} {timeframe} failed from {name}")
            logger.warning(f"OHLCV {code} {timeframe} failed from all sources")
            return None

    async def ensure_symbol_data(self, code, timeframes=None, force=False):
        if timeframes is None:
            timeframes = TIMEFRAMES
        missing = [tf for tf in timeframes if force or code not in self.ohlcv.get(tf, {}) or time.time() - self.ohlcv_updated_at.get(tf, {}).get(code, 0) > OHLCV_TTL_SECONDS]
        if not missing:
            return True
        async with self._symbol_lock(code):
            missing = [tf for tf in timeframes if force or code not in self.ohlcv.get(tf, {}) or time.time() - self.ohlcv_updated_at.get(tf, {}).get(code, 0) > OHLCV_TTL_SECONDS]
            for tf in missing:
                df = await self._fetch_ohlcv_symbol(code, tf)
                if df is not None:
                    self.ohlcv.setdefault(tf, {})[code] = df
                    self.ohlcv_updated_at.setdefault(tf, {})[code] = time.time()
            return all(code in self.ohlcv.get(tf, {}) for tf in timeframes)

    async def update_ohlcv(self, force=False, codes=None):
        async with self._update_lock:
            now = time.time()
            if not force and self.last_full_ohlcv_update and now - self.last_full_ohlcv_update < FULL_REFRESH_TTL_SECONDS:
                return
            if not self.valid_codes:
                self._load_markets()
            if not self.valid_codes:
                return
            target_codes = list(codes if codes is not None else self.valid_codes)
            tasks = [self.ensure_symbol_data(code, TIMEFRAMES, force=force) for code in target_codes]
            await asyncio.gather(*tasks)
            self.last_full_ohlcv_update = time.time()
            logger.info("OHLCV refresh complete: %s", {tf: len(self.ohlcv.get(tf, {})) for tf in TIMEFRAMES})

    async def get_indicators(self, code, mode="standard"):
        config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
        main_tf = config["main_tf"]
        confirm_tfs = config["confirm_tfs"]
        needed = [main_tf] + confirm_tfs
        ok = await self.ensure_symbol_data(code, needed)
        if not ok:
            ok = await self.ensure_symbol_data(code, needed, force=True)
            if not ok:
                return None
        df = self.ohlcv.get(main_tf, {}).get(code)
        if df is None or len(df) < 210:
            await self.ensure_symbol_data(code, [main_tf], force=True)
            df = self.ohlcv.get(main_tf, {}).get(code)
            if df is None or len(df) < 210:
                return None
        confirm_dfs = []
        for tf in confirm_tfs:
            cdf = self.ohlcv.get(tf, {}).get(code)
            if cdf is not None and len(cdf) >= 200:
                confirm_dfs.append(cdf)
            else:
                confirm_dfs.append(None)

        try:
            close = df["close"]
            ema20 = EMAIndicator(close, window=20).ema_indicator()
            ema50 = EMAIndicator(close, window=50).ema_indicator()
            ema200 = EMAIndicator(close, window=200).ema_indicator()
            rsi = RSIIndicator(close, window=14).rsi()
            stoch = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
            stoch_k = stoch.stochrsi_k() * 100
            macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
            macd_hist = macd.macd_diff()
            macd_line = macd.macd()
            macd_signal = macd.macd_signal()
            roc = ROCIndicator(close, window=12).roc()
            cci = CCIIndicator(df["high"], df["low"], close, window=20).cci()
            williams = WilliamsRIndicator(df["high"], df["low"], close, lbp=14).williams_r()
            adx_ind = ADXIndicator(df["high"], df["low"], close, window=14)
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()
            atr = AverageTrueRange(df["high"], df["low"], close, window=14).average_true_range()
            bb = BollingerBands(close, window=20, window_dev=2)
            bb_percent = bb.bollinger_pband()
            bb_width = bb.bollinger_wband()
            volume_ratio = df["volume"] / df["volume"].rolling(20).mean()
            volume_ma20 = df["volume"].rolling(20).mean()
            volume_ma50 = df["volume"].rolling(50).mean()
            vwap = VolumeWeightedAveragePrice(high=df["high"], low=df["low"], close=close, volume=df["volume"], window=20).volume_weighted_average_price()

            price = float(close.iloc[-1])
            price_prev = float(close.iloc[-2])
            atr_value = float(atr.iloc[-1])
            atr_pct = (atr_value / price * 100) if price > 0 else 0
            ema20_value = float(ema20.iloc[-1])
            ema50_value = float(ema50.iloc[-1])
            ema200_value = float(ema200.iloc[-1])
            price_ema200_pct = ((price - ema200_value) / ema200_value * 100)
            price_ema50_pct = ((price - ema50_value) / ema50_value * 100)

            ema20_prev = float(ema20.iloc[-2]) if len(ema20) >= 2 else ema20_value
            ema50_prev = float(ema50.iloc[-2]) if len(ema50) >= 2 else ema50_value
            bullish_cross = (ema20_prev <= ema50_prev and ema20_value > ema50_value)
            bearish_cross = (ema20_prev >= ema50_prev and ema20_value < ema50_value)

            rsi_prev = float(rsi.iloc[-2]) if len(rsi) >= 2 else float(rsi.iloc[-1])
            macd_hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else float(macd_hist.iloc[-1])

            vr = float(volume_ratio.iloc[-1])
            volume_spike = vr >= 1.5
            volume_trend_up = (float(volume_ma20.iloc[-1]) > float(volume_ma50.iloc[-1]))

            confirm_up = 0
            confirm_down = 0
            for cdf in confirm_dfs:
                if cdf is not None:
                    c_close = cdf["close"]
                    c_ema200 = EMAIndicator(c_close, window=200).ema_indicator()
                    c_ema200_val = c_ema200.iloc[-1]
                    if pd.notna(c_ema200_val):
                        if c_close.iloc[-1] > c_ema200_val:
                            confirm_up += 1
                        else:
                            confirm_down += 1

            support = float(df["low"].iloc[-20:].min())
            resistance = float(df["high"].iloc[-20:].max())
            breakout_up = price > resistance * 1.001
            breakout_down = price < support * 0.999

            rsi_bullish_div = (price < price_prev and rsi.iloc[-1] > rsi_prev)
            rsi_bearish_div = (price > price_prev and rsi.iloc[-1] < rsi_prev)
            macd_bullish_div = (price < price_prev and macd_hist.iloc[-1] > macd_hist_prev)
            macd_bearish_div = (price > price_prev and macd_hist.iloc[-1] < macd_hist_prev)

            values = {
                "price": price, "price_prev": price_prev,
                "ema20": ema20_value, "ema50": ema50_value, "ema200": ema200_value,
                "price_above_ema20": price > ema20_value,
                "price_above_ema50": price > ema50_value,
                "price_above_ema200": price > ema200_value,
                "price_ema50_pct": price_ema50_pct,
                "price_ema200_pct": price_ema200_pct,
                "ema20_above_ema50": ema20_value > ema50_value,
                "ema20_bullish_cross": bullish_cross,
                "ema20_bearish_cross": bearish_cross,
                "rsi": float(rsi.iloc[-1]), "rsi_prev": rsi_prev,
                "stoch_k": float(stoch_k.iloc[-1]),
                "macd": float(macd_line.iloc[-1]), "macd_signal": float(macd_signal.iloc[-1]),
                "macd_hist": float(macd_hist.iloc[-1]), "macd_hist_prev": macd_hist_prev,
                "roc": float(roc.iloc[-1]), "cci": float(cci.iloc[-1]), "williams_r": float(williams.iloc[-1]),
                "adx": float(adx.iloc[-1]), "plus_di": float(plus_di.iloc[-1]), "minus_di": float(minus_di.iloc[-1]),
                "atr": atr_value, "atr_pct": atr_pct,
                "bb_percent": float(bb_percent.iloc[-1]), "bb_width": float(bb_width.iloc[-1]),
                "volume_ratio": vr, "volume_spike": volume_spike, "volume_trend_up": volume_trend_up,
                "vwap": float(vwap.iloc[-1]), "price_above_vwap": price > float(vwap.iloc[-1]),
                "confirm_up_count": confirm_up, "confirm_down_count": confirm_down,
                "higher_tf_trend_up": confirm_up >= len(confirm_dfs) if confirm_dfs else None,
                "higher_tf_trend_down": confirm_down >= len(confirm_dfs) if confirm_dfs else None,
                "trend_label": "صعودی 📈" if price > ema200_value else "نزولی 📉",
                "is_trending": bool(adx.iloc[-1] >= config["adx_min"]),
                "support": support, "resistance": resistance,
                "breakout_up": breakout_up, "breakout_down": breakout_down,
                "bullish_div": rsi_bullish_div, "bearish_div": rsi_bearish_div,
                "macd_bullish_div": macd_bullish_div, "macd_bearish_div": macd_bearish_div,
            }
            if any(pd.isna(v) for v in values.values() if isinstance(v, (int, float))):
                return None
            return values
        except Exception as e:
            logger.exception("Indicator error | code=%s | mode=%s | error=%s", code, mode, e)
            return None

    async def get_weekly_data(self, code):
        ok = await self.ensure_symbol_data(code, ("1d",))
        if not ok:
            await self.ensure_symbol_data(code, ("1d",), force=True)
        df = self.ohlcv.get("1d", {}).get(code)
        if df is None or df.empty:
            return None
        end = df["timestamp"].iloc[-1]
        start = end - pd.Timedelta(days=7)
        week = df[df["timestamp"] >= start].copy()
        if len(week) < 2:
            week = df.tail(min(8, len(df))).copy()
        return week if len(week) >= 2 else None

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
# کلید این دیکشنری از نسخه اصلاح‌شده فقط نماد ارز است (نه ارز+حالت معاملاتی)
# چون در کانال برای هر ارز فقط یک تحلیل/سیگنال نهایی وجود دارد
channel_message_map: Dict[str, Dict] = {}
# آخرین زمانی که سیگنال یک ارز در کانال بسته شد (TP3 یا SL)، برای جلوگیری از باز شدن فوری سیگنال جدید
last_channel_signal_close_time: Dict[str, float] = {}

signal_history_lock = asyncio.Lock()
channel_lock = asyncio.Lock()

last_check_time = {}
last_sent_signals = {}
price_sources = {}
last_mode_broadcast_time = {}

# ---------- توابع کمکی ----------
def is_allowed(user_id):
    if user_id in ALWAYS_ALLOWED_USER_IDS or user_id in ADMIN_USER_IDS:
        return True
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

_MARKDOWN_SPECIAL_RE = None

def escape_markdown(text):
    """
    فرار از کاراکترهای خاص Markdown (نسخه legacy تلگرام) برای هر متنی که از منابع
    بیرونی (CryptoPanic, CoinGecko, Whale-Alert و ...) می‌آید. بدون این کار، عنوان یا
    توضیحی که به‌طور طبیعی شامل _ * ` [ باشد می‌تواند کل ارسال پیام را با خطای
    "can't parse entities" fail کند و آن پیام هرگز به کاربر/کانال نرسد.
    """
    global _MARKDOWN_SPECIAL_RE
    if not text:
        return text
    if _MARKDOWN_SPECIAL_RE is None:
        import re as _re
        _MARKDOWN_SPECIAL_RE = _re.compile(r'([_*`\[])')
    return _MARKDOWN_SPECIAL_RE.sub(r'\\\1', str(text))

def is_admin_role(chat_id):
    # نکته امنیتی: صرفاً چک کردن user_role کافی نیست چون آن دیکشنری با یک callback_data
    # ساختگی («role_admin») هم قابل تغییر بود؛ اکنون علاوه بر آن، حتماً باید chat_id
    # واقعاً عضو ADMIN_USER_IDS (تعریف‌شده در .env) هم باشد.
    return chat_id in ADMIN_USER_IDS and user_role.get(chat_id, "user") == "admin"

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
                    "title": escape_markdown(title[:100]),
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
    try:
        if WHALE_ALERT_API_KEY:
            url = f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value={WHALE_MIN_AMOUNT_BTC * 1000000}&limit=10"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json().get("transactions", [])
            alerts = []
            for tx in data:
                amount_btc = float(tx.get("amount", 0))
                symbol = tx.get("symbol", "BTC")
                from_address = tx.get("from", {}).get("address", "")
                to_address = tx.get("to", {}).get("address", "")
                from_owner = tx.get("from", {}).get("owner_type", "")
                to_owner = tx.get("to", {}).get("owner_type", "")
                exchange_keywords = ["exchange", "wallet", "binance", "coinbase", "kraken", "okx", "bybit"]
                from_is_exchange = any(kw in from_owner.lower() for kw in exchange_keywords) if from_owner else False
                to_is_exchange = any(kw in to_owner.lower() for kw in exchange_keywords) if to_owner else False
                flow_type = "unknown"
                if from_is_exchange and not to_is_exchange:
                    flow_type = "خروج از صرافی (احتمال فروش)"
                elif not from_is_exchange and to_is_exchange:
                    flow_type = "ورود به صرافی (احتمال فروش)"
                elif from_is_exchange and to_is_exchange:
                    flow_type = "انتقال بین صرافی‌ها"
                else:
                    flow_type = "انتقال بین کیف‌پول‌ها"
                impact = "خنثی"
                if flow_type == "خروج از صرافی" and amount_btc > 2000:
                    impact = "نزولی 📉 (احتمال فروش)"
                elif flow_type == "ورود به صرافی" and amount_btc > 2000:
                    impact = "نزولی 📉 (احتمال فروش)"
                elif amount_btc > 5000:
                    impact = "صعودی 📈 (انباشت نهنگ)"
                alerts.append({
                    "amount_btc": amount_btc,
                    "symbol": symbol,
                    "timestamp": time.time(),
                    "from_address": from_address[:10] + "...",
                    "to_address": to_address[:10] + "...",
                    "from_owner": from_owner or "ناشناس",
                    "to_owner": to_owner or "ناشناس",
                    "flow_type": flow_type,
                    "impact": impact,
                    "value_usd": amount_btc * cache.prices.get("BTC", 0)
                })
            return alerts
        else:
            url = "https://blockchain.info/unconfirmed-transactions?format=json"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            txs = r.json().get("txs", [])
            alerts = []
            for tx in txs:
                total_out = sum(out.get("value", 0) for out in tx.get("out", [])) / 1e8
                if total_out >= WHALE_MIN_AMOUNT_BTC:
                    alerts.append({
                        "amount_btc": total_out,
                        "symbol": "BTC",
                        "timestamp": time.time(),
                        "from_address": "مشخص نیست",
                        "to_address": "مشخص نیست",
                        "from_owner": "ناشناس",
                        "to_owner": "ناشناس",
                        "flow_type": "نامشخص",
                        "impact": "مشخص نیست",
                        "value_usd": total_out * cache.prices.get("BTC", 0)
                    })
            return alerts[:5]
    except Exception as e:
        logger.warning("Whale alert fetch failed: %s", e)
        return []

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
    if len(signal_history) < 10:
        return None
    closed = [s for s in signal_history if s["status"] in ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit"]]
    if len(closed) < 5:
        return None
    wins = [s for s in closed if s["status"].startswith("tp")]
    losses = [s for s in closed if s["status"] == "sl_hit"]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    tp3_count = len([s for s in closed if s["status"] == "tp3_hit"])
    tp2_count = len([s for s in closed if s["status"] == "tp2_hit"])
    tp1_count = len([s for s in closed if s["status"] == "tp1_hit"])
    sl_count = len(losses)

    mode_performance = {}
    for mode in MODE_CONFIGS.keys():
        mode_signals = [s for s in closed if s.get("mode") == mode]
        if mode_signals:
            mode_wins = [s for s in mode_signals if s["status"].startswith("tp")]
            rr_vals = [s.get("rr", 0) for s in mode_signals if "rr" in s]
            conf_vals = [s.get("confidence", 0) for s in mode_signals]
            mode_performance[mode] = {
                "count": len(mode_signals),
                "win_rate": len(mode_wins) / len(mode_signals) * 100 if mode_signals else 0,
                "avg_rr": sum(rr_vals) / len(rr_vals) if rr_vals else 0,
                "avg_confidence": sum(conf_vals) / len(conf_vals) if conf_vals else 0,
            }
    best_mode = max(mode_performance, key=lambda x: mode_performance[x]["win_rate"]) if mode_performance else None
    worst_mode = min(mode_performance, key=lambda x: mode_performance[x]["win_rate"]) if mode_performance else None
    rr_values = [s.get("rr", 0) for s in closed if "rr" in s]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0
    conf_values = [s.get("confidence", 0) for s in closed]
    avg_confidence = sum(conf_values) / len(conf_values) if conf_values else 0

    return {
        "win_rate": win_rate,
        "best_mode": best_mode,
        "worst_mode": worst_mode,
        "avg_rr": avg_rr,
        "avg_confidence": avg_confidence,
        "total_signals": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "tp1_count": tp1_count,
        "tp2_count": tp2_count,
        "tp3_count": tp3_count,
        "sl_count": sl_count,
        "mode_performance": mode_performance,
    }

def generate_optimization_suggestions(analysis):
    """
    برای هر حالت معاملاتی که داده کافی (حداقل ۵ سیگنال بسته‌شده) دارد، عملکرد آن حالت
    به‌طور مستقل بررسی می‌شود (نه فقط «استاندارد») و پارامترهای واقعی همان حالت
    (min_rr، adx_min، min_confirmations) بسته به نرخ برد پیشنهاد تغییر می‌گیرند:
    - نرخ برد پایین (زیر ۴۰٪) → سخت‌گیرانه‌تر شدن پیشنهاد می‌شود (adx_min و
      min_confirmations بالاتر) چون یعنی فیلترها برای رد سیگنال‌های ضعیف کافی نبوده‌اند.
    - نرخ برد بسیار بالا (بالای ۷۵٪) با تعداد نمونه کافی → کمی سخت‌گیری کمتر در min_rr
      پیشنهاد می‌شود تا فرصت‌های بیشتری از دست نرود، بدون این‌که به‌کلی فیلترها باز شوند.
    """
    if not analysis or analysis["total_signals"] < 10:
        return []
    suggestions = []
    for mode, perf in analysis.get("mode_performance", {}).items():
        if perf["count"] < 5:
            continue
        cfg = MODE_CONFIGS[mode]
        if perf["win_rate"] < 40:
            new_adx = min(35, cfg["adx_min"] + 3)
            if new_adx != cfg["adx_min"]:
                suggestions.append({
                    "parameter": "adx_min",
                    "mode": mode,
                    "current": cfg["adx_min"],
                    "suggested": new_adx,
                    "reason": f"نرخ برد حالت {cfg['label']} پایین است ({perf['win_rate']:.1f}% از {perf['count']} سیگنال)؛ افزایش حداقل ADX یعنی فقط در روندهای قوی‌تر سیگنال صادر شود."
                })
            new_conf = min(10, cfg["min_confirmations"] + 1)
            if new_conf != cfg["min_confirmations"]:
                suggestions.append({
                    "parameter": "min_confirmations",
                    "mode": mode,
                    "current": cfg["min_confirmations"],
                    "suggested": new_conf,
                    "reason": f"نرخ برد حالت {cfg['label']} پایین است ({perf['win_rate']:.1f}%)؛ افزایش حداقل لایه‌های تاییدی می‌تواند سیگنال‌های ضعیف‌تر را حذف کند."
                })
        elif perf["win_rate"] > 75:
            new_rr = round(max(0.3, cfg["min_rr"] - 0.10), 2)
            if new_rr != cfg["min_rr"]:
                suggestions.append({
                    "parameter": "min_rr",
                    "mode": mode,
                    "current": cfg["min_rr"],
                    "suggested": new_rr,
                    "reason": f"نرخ برد حالت {cfg['label']} بسیار بالاست ({perf['win_rate']:.1f}% از {perf['count']} سیگنال)؛ کمی کاهش حداقل RR می‌تواند بدون افت کیفیت، فرصت‌های بیشتری ثبت کند."
                })
    if analysis.get("best_mode"):
        best = analysis["best_mode"]
        if analysis["mode_performance"][best]["count"] >= 5:
            suggestions.append({
                "parameter": "mode",
                "mode": best,
                "current": "—",
                "suggested": best,
                "reason": f"در بین حالت‌های با داده کافی، حالت {MODE_CONFIGS[best]['label']} بهترین نرخ برد را دارد ({analysis['mode_performance'][best]['win_rate']:.1f}%). این صرفاً اطلاع‌رسانی است، پارامتری تغییر نمی‌دهد."
            })
    return suggestions

def build_suggestion_detail_text(sug_entry):
    """
    متن کامل و غنی یک پیشنهاد بهینه‌سازی: تحلیل کامل عملکرد (کلی + به تفکیک هر حالت)
    و لیست کامل پیشنهادات با دلیل هرکدام. هم در پیام مستقیم به ادمین، هم در «پیشنهادات
    فعال» و هم در «مشاهده جزئیات» از همین تابع استفاده می‌شود تا اطلاعات همه‌جا یکسان
    و کامل باشد (نه فقط ۲-۳ مورد اول).
    """
    a = sug_entry["analysis"]
    text = (
        f"🧠 *پیشنهاد بهینه‌سازی تنظیمات*\n"
        f"{DIVIDER}\n"
        f"📊 *تحلیل کلی* ({a.get('total_signals', 0)} سیگنال بسته‌شده)\n"
        f"• نرخ برد کلی: {a.get('win_rate', 0):.1f}% ({a.get('wins', 0)} برد / {a.get('losses', 0)} باخت)\n"
        f"• تفکیک برد: TP1️⃣ {a.get('tp1_count', 0)} | TP2️⃣ {a.get('tp2_count', 0)} | TP3️⃣ {a.get('tp3_count', 0)} | SL {a.get('sl_count', 0)}\n"
        f"• میانگین RR: {a.get('avg_rr', 0):.2f}\n"
        f"• میانگین اطمینان سیگنال‌ها: {a.get('avg_confidence', 0):.1f}%\n"
    )
    if a.get("best_mode") and a.get("mode_performance", {}).get(a["best_mode"]):
        text += f"• بهترین حالت: {MODE_CONFIGS[a['best_mode']]['label']} ({a['mode_performance'][a['best_mode']]['win_rate']:.1f}%)\n"
    if a.get("worst_mode") and a.get("worst_mode") != a.get("best_mode") and a.get("mode_performance", {}).get(a["worst_mode"]):
        text += f"• ضعیف‌ترین حالت: {MODE_CONFIGS[a['worst_mode']]['label']} ({a['mode_performance'][a['worst_mode']]['win_rate']:.1f}%)\n"
    if a.get("mode_performance"):
        text += f"{DIVIDER}\n📋 *عملکرد به تفکیک حالت:*\n"
        for mode, perf in a["mode_performance"].items():
            label = MODE_CONFIGS.get(mode, {}).get("label", mode)
            text += (
                f"• {label}: {perf.get('count', 0)} سیگنال | برد {perf.get('win_rate', 0):.1f}% | "
                f"RR {perf.get('avg_rr', 0):.2f} | اطمینان {perf.get('avg_confidence', 0):.1f}%\n"
            )
    text += f"{DIVIDER}\n💡 *پیشنهادات ({len(sug_entry['suggestions'])} مورد):*\n"
    if not sug_entry["suggestions"]:
        text += "موردی برای پیشنهاد یافت نشد.\n"
    for sug in sug_entry["suggestions"]:
        if sug["parameter"] == "mode":
            text += f"ℹ️ {sug['reason']}\n"
            continue
        param_fa = {
            "min_rr": "حداقل نسبت ریسک به بازده",
            "adx_min": "حداقل ADX",
            "min_confirmations": "حداقل لایه‌های تاییدی",
        }.get(sug["parameter"], sug["parameter"])
        text += f"• {MODE_CONFIGS.get(sug['mode'], {}).get('label', sug['mode'])} — {param_fa}: {sug['current']} ← {sug['suggested']}\n"
        text += f"  📌 {sug['reason']}\n"
    return text

async def optimization_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            analysis = analyze_performance()
            if analysis:
                suggestions = generate_optimization_suggestions(analysis)
                if suggestions:
                    entry = {
                        "id": f"sug_{int(time.time())}",
                        "timestamp": time.time(),
                        "analysis": analysis,
                        "suggestions": suggestions,
                        "status": "pending",
                        "expires_at": time.time() + 86400
                    }
                    suggestion_history.append(entry)
                    if len(suggestion_history) > 20:
                        suggestion_history.pop(0)
                    save_state()
                    for admin_id in ADMIN_USER_IDS:
                        try:
                            text = build_suggestion_detail_text(entry)
                            text += (
                                f"\n{DIVIDER}\n"
                                f"⏳ اعتبار پیشنهاد: ۲۴ ساعت\n"
                                f"💡 حتی بعد از اعمال یا رد، هر زمان می‌توانید از «مرکز هوشمندسازی → "
                                f"پیشنهادات فعال» همین پیشنهاد را دوباره ببینید و تصمیم را عوض کنید."
                            )
                            await app.bot.send_message(
                                chat_id=admin_id,
                                text=text,
                                reply_markup=kb_suggestion_actions(entry["id"]),
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send suggestion to admin {admin_id}: {e}")
        except Exception as e:
            logger.exception(f"Optimization loop error: {e}")
        await asyncio.sleep(OPTIMIZATION_CHECK_SECONDS)

def kb_suggestion_actions(suggestion_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ اعمال تغییرات", callback_data=f"apply_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("❌ رد پیشنهادات", callback_data=f"reject_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("📊 مشاهده جزئیات", callback_data=f"details_suggestion_{suggestion_id}")],
    ])

def _apply_suggestion_params(target):
    for sug in target["suggestions"]:
        if sug["parameter"] == "mode":
            continue
        if sug["mode"] in MODE_CONFIGS and sug["parameter"] in MODE_CONFIGS[sug["mode"]]:
            MODE_CONFIGS[sug["mode"]][sug["parameter"]] = sug["suggested"]

def _revert_suggestion_params(target):
    for sug in target["suggestions"]:
        if sug["parameter"] == "mode":
            continue
        if sug["mode"] in MODE_CONFIGS and sug["parameter"] in MODE_CONFIGS[sug["mode"]]:
            MODE_CONFIGS[sug["mode"]][sug["parameter"]] = sug["current"]

async def handle_suggestion_action(update, context):
    """
    اصلاح: قبلاً وقتی یک پیشنهاد applied/rejected می‌شد، دیگر هرگز قابل تغییر نبود
    ("این پیشنهاد قبلاً ... شده است"). اکنون تصمیم همیشه قابل تغییر است: رد کردن یک
    پیشنهادِ قبلاً اعمال‌شده، پارامترها را به مقدار قبل از پیشنهاد (current) برمی‌گرداند؛
    اعمال دوباره‌ی یک پیشنهادِ قبلاً ردشده هم دوباره مقدار suggested را می‌گذارد.
    """
    query = update.callback_query
    await query.answer()
    data = query.data
    suggestion_id = data.split("_", 2)[2]
    target = None
    for sug in suggestion_history:
        if sug["id"] == suggestion_id:
            target = sug
            break
    if not target:
        await query.edit_message_text("❌ پیشنهاد مورد نظر یافت نشد.", reply_markup=kb_back_main())
        return

    if data.startswith("apply_suggestion_"):
        _apply_suggestion_params(target)
        target["status"] = "applied"
        target["applied_at"] = time.time()
        target["result"] = "تنظیمات با موفقیت اعمال شد."
        save_state()
        text = "✅ *تنظیمات اعمال شد.*\n" + DIVIDER + "\n"
        text += build_suggestion_detail_text(target)
        text += f"\n{DIVIDER}\n💡 در صورت نیاز، هر زمان از همین صفحه یا «پیشنهادات فعال» می‌توانید رد کنید."
        await query.edit_message_text(text, reply_markup=kb_suggestion_actions(target["id"]), parse_mode="Markdown")
    elif data.startswith("reject_suggestion_"):
        was_applied = target["status"] == "applied"
        if was_applied:
            _revert_suggestion_params(target)
        target["status"] = "rejected"
        target["rejected_at"] = time.time()
        save_state()
        text = "❌ *پیشنهاد رد شد.*\n" + DIVIDER + "\n"
        if was_applied:
            text += "⚠️ این پیشنهاد قبلاً اعمال شده بود؛ پارامترها به مقدار قبلی بازگردانده شدند.\n" + DIVIDER + "\n"
        text += build_suggestion_detail_text(target)
        text += f"\n{DIVIDER}\n💡 در صورت نیاز، هر زمان از همین صفحه یا «پیشنهادات فعال» می‌توانید دوباره اعمال کنید."
        await query.edit_message_text(text, reply_markup=kb_suggestion_actions(target["id"]), parse_mode="Markdown")
    elif data.startswith("details_suggestion_"):
        status_fa = {
            "pending": "⏳ در انتظار پاسخ",
            "applied": "✅ اعمال شده",
            "rejected": "❌ رد شده",
            "expired": "⌛ منقضی‌شده",
        }.get(target["status"], target["status"])
        text = build_suggestion_detail_text(target)
        text += f"\n{DIVIDER}\n📌 وضعیت: {status_fa}"
        await query.edit_message_text(text, reply_markup=kb_suggestion_actions(target["id"]), parse_mode="Markdown")

# ---------- رویدادها ----------
def fetch_upcoming_events():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/events?upcoming=true", timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
        events = []
        for ev in data:
            name = ev.get("title") or ev.get("name", "رویداد")
            date_str = ev.get("date", "")
            if not date_str:
                continue
            try:
                event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                continue
            importance = "medium"
            if "hard fork" in name.lower() or "upgrade" in name.lower() or "ethereum" in name.lower():
                importance = "high"
            description = ev.get("description", "")[:200]
            events.append({
                "name": escape_markdown(name),
                "time": event_time,
                "importance": importance,
                "description": escape_markdown(description),
                "impact": "مشخص نیست"
            })
        return events
    except Exception as e:
        logger.warning("Events fetch failed: %s", e)
        return []

async def get_upcoming_events(force=False):
    now = time.time()
    if not force and upcoming_events_cache["events"] and now - upcoming_events_cache["ts"] < EVENTS_CHECK_SECONDS:
        return upcoming_events_cache["events"]
    events = fetch_upcoming_events()
    if events:
        upcoming_events_cache.update(events=events, ts=now)
    return events

# ---------- توابع تحلیل لایه‌ها ----------
async def analyze_layers(code, direction, ind, mode, cache_obj, order_flow=None):
    config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    df = cache_obj.ohlcv.get(config["main_tf"], {}).get(code)
    results = {}
    if df is not None and len(df) > 30:
        high = df["high"].iloc[-20:]
        low = df["low"].iloc[-20:]
        price = float(df["close"].iloc[-1])
        prev_high = float(high.max())
        prev_low = float(low.min())
        if direction == "LONG":
            structure_ok = price > prev_low * 0.999
            last = df.iloc[-1]
            if not structure_ok and last["close"] > last["open"] and (last["close"] - last["low"]) > 2 * (last["high"] - last["close"]):
                structure_ok = True
            if not structure_ok and price <= (prev_high + prev_low) / 2:
                structure_ok = True
        else:
            structure_ok = price < prev_high * 1.001
            last = df.iloc[-1]
            if not structure_ok and last["close"] < last["open"] and (last["high"] - last["close"]) > 2 * (last["close"] - last["low"]):
                structure_ok = True
            if not structure_ok and price >= (prev_high + prev_low) / 2:
                structure_ok = True
        results["structure"] = structure_ok
    else:
        results["structure"] = False

    main_tf = config["main_tf"]
    confirm_tfs = config["confirm_tfs"]
    mtf_count = 0
    df_main = cache_obj.ohlcv.get(main_tf, {}).get(code)
    if df_main is not None and len(df_main) > 50:
        price = float(df_main["close"].iloc[-1])
        ema200 = EMAIndicator(df_main["close"], window=200).ema_indicator().iloc[-1]
        if direction == "LONG" and price > ema200:
            mtf_count += 1
        elif direction == "SHORT" and price < ema200:
            mtf_count += 1
    for tf in confirm_tfs:
        df_tf = cache_obj.ohlcv.get(tf, {}).get(code)
        if df_tf is not None and len(df_tf) > 50:
            price = float(df_tf["close"].iloc[-1])
            ema200 = EMAIndicator(df_tf["close"], window=200).ema_indicator().iloc[-1]
            if direction == "LONG" and price > ema200:
                mtf_count += 1
            elif direction == "SHORT" and price < ema200:
                mtf_count += 1
    results["mtf"] = mtf_count >= 1

    momentum_score = 0
    if direction == "LONG":
        if ind["macd_hist"] > 0: momentum_score += 1
        if ind["rsi"] > 50: momentum_score += 1
        if ind["roc"] > 0: momentum_score += 1
        if ind["bullish_div"] or ind["macd_bullish_div"]: momentum_score += 1
    else:
        if ind["macd_hist"] < 0: momentum_score += 1
        if ind["rsi"] < 50: momentum_score += 1
        if ind["roc"] < 0: momentum_score += 1
        if ind["bearish_div"] or ind["macd_bearish_div"]: momentum_score += 1
    results["momentum"] = momentum_score >= 1

    results["volume"] = ind["volume_ratio"] >= 0.8 or ind["volume_spike"] or ind["volume_trend_up"]

    sentiment_score = await cache_obj._calculate_sentiment_score(code, ind)
    if direction == "LONG":
        results["sentiment"] = sentiment_score > -0.2
    else:
        results["sentiment"] = sentiment_score < 0.2

    results["trend"] = ind["price_above_ema200"] if direction == "LONG" else not ind["price_above_ema200"]

    if order_flow is None:
        order_flow = await cache_obj._get_order_flow(code)
    if order_flow == 0 or (0.9 <= order_flow <= 1.1):
        results["order_flow"] = True
    else:
        if direction == "LONG":
            results["order_flow"] = order_flow > 1.1
        else:
            results["order_flow"] = order_flow < 0.9

    breadth = cache_obj._get_market_breadth()
    sample_count = getattr(cache_obj, "_breadth_sample_count", 0)
    if direction == "LONG":
        results["breadth"] = (breadth >= 45) if sample_count >= 5 else True
    else:
        results["breadth"] = (breadth <= 55) if sample_count >= 5 else True

    bb_percent = ind.get("bb_percent", 0.5)
    results["smart_vol"] = 0.1 <= bb_percent <= 0.9

    if direction == "LONG":
        results["comp_trend"] = ind["plus_di"] > ind["minus_di"]
    else:
        results["comp_trend"] = ind["minus_di"] > ind["plus_di"]

    return results

# ---------- تولید سیگنال جدید ----------
async def generate_trade_plan_v2(code, mode="standard", send_to_channel=False,
                                  min_confidence=None, min_gap=None,
                                  min_confirmations_bonus=0, adx_min_override=None):
    """
    اگر send_to_channel=True باشد، می‌توان از طریق پارامترهای min_confidence/min_gap/
    min_confirmations_bonus/adx_min_override سخت‌گیری بیشتری نسبت به تحلیل شخصی کاربر
    اعمال کرد (برای کاهش سیگنال‌های کاذب کانال) بدون این‌که رفتار حالت‌های شخصی تغییر کند.
    """
    global app
    try:
        # جلوگیری از باز کردن فوری یک سیگنال جدید کانال بلافاصله بعد از بسته‌شدن سیگنال قبلی همان ارز
        if send_to_channel:
            has_open_record = any(
                r["symbol"] == code and r["mode"] == mode and r["status"] == "open"
                for r in signal_history
            )
            if not has_open_record:
                last_close = last_channel_signal_close_time.get(code, 0)
                if time.time() - last_close < CHANNEL_REOPEN_COOLDOWN_SECONDS:
                    logger.debug(f"Channel cooldown active for {code}, skipping")
                    return None

        await cache.update_prices(force=True, codes=[code])
        ind = await cache.get_indicators(code, mode)
        if not ind:
            logger.info(f"No indicators for {code}")
            return None
        config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
        effective_min_confidence = min_confidence if min_confidence is not None else MIN_SIGNAL_CONFIDENCE
        effective_min_gap = min_gap if min_gap is not None else MIN_DIRECTION_GAP
        effective_min_confirmations = config["min_confirmations"] + max(0, min_confirmations_bonus)
        effective_adx_min = adx_min_override if adx_min_override is not None else config["adx_min"]
        order_flow = await cache._get_order_flow(code)
        long_layers = await analyze_layers(code, "LONG", ind, mode, cache, order_flow)
        short_layers = await analyze_layers(code, "SHORT", ind, mode, cache, order_flow)

        long_score = 0
        short_score = 0
        long_confirmed = 0
        short_confirmed = 0
        for layer, weight in LAYER_WEIGHTS.items():
            if long_layers.get(layer, False):
                long_score += weight
                long_confirmed += 1
            if short_layers.get(layer, False):
                short_score += weight
                short_confirmed += 1

        direction = None
        confidence = 0
        layers = {}

        if send_to_channel:
            # برای سیگنال کانال، فقط حالتی که خیلی واضح یک جهت را تایید می‌کند پذیرفته می‌شود
            # (بدون حالت میانی/ضعیف‌تر «else» که در نسخه قبل باعث سیگنال‌های کم‌اطمینان می‌شد)
            if long_confirmed >= effective_min_confirmations and long_score >= short_score + effective_min_gap:
                direction = "LONG"
                confidence = long_score
                layers = long_layers
            elif short_confirmed >= effective_min_confirmations and short_score >= long_score + effective_min_gap:
                direction = "SHORT"
                confidence = short_score
                layers = short_layers
            else:
                logger.info(f"No clear channel-grade direction for {code}: long_conf={long_confirmed}, short_conf={short_confirmed}, gap={abs(long_score-short_score)}")
                return None
        elif long_confirmed >= config["min_confirmations"] and long_score >= short_score + effective_min_gap:
            direction = "LONG"
            confidence = long_score
            layers = long_layers
        elif short_confirmed >= config["min_confirmations"] and short_score >= long_score + effective_min_gap:
            direction = "SHORT"
            confidence = short_score
            layers = short_layers
        else:
            # اصلاح: قبلاً یک مسیر جایگزین ضعیف‌تر اینجا بود که حتی وقتی اختلاف امتیاز
            # لانگ/شورت تقریباً صفر بود هم سیگنال صادر می‌کرد (فقط برای مصرف شخصی).
            # این باعث سیگنال‌های کم‌اطمینان می‌شد؛ حذف شد تا حتی حالت شخصی هم به همان
            # حداقل فاصله اطمینان (effective_min_gap) پایبند باشد.
            logger.info(f"No clear direction for {code}: long_conf={long_confirmed}, short_conf={short_confirmed}, gap={abs(long_score-short_score)}")
            return None

        if confidence < effective_min_confidence:
            logger.info(f"Confidence too low for {code}: {confidence:.1f} < {effective_min_confidence}")
            return None

        if send_to_channel and ind.get("adx", 0) < effective_adx_min:
            logger.info(f"ADX too low for channel signal {code}: {ind.get('adx', 0):.1f} < {effective_adx_min}")
            return None

        levels = build_ladder_weighted(ind, direction, mode)
        if levels["rr"] < config["min_rr"]:
            logger.info(f"RR too low for {code}: {levels['rr']:.2f} < {config['min_rr']}")
            return None

        funding = 0.0
        fg_value, _ = await get_fear_greed()
        if fg_value is not None:
            if direction == "LONG" and fg_value > 80:
                confidence -= 5
            elif direction == "SHORT" and fg_value < 20:
                confidence -= 5
        confidence = max(0, min(100, confidence))
        confidence = float(confidence)

        max_lev = config["max_leverage"]
        if confidence >= 90:
            leverage = max_lev
        elif confidence >= 80:
            leverage = max(1, max_lev - 1)
        elif confidence >= 70:
            leverage = max(1, max_lev - 2)
        elif confidence >= 60:
            leverage = max(1, max_lev - 3)
        else:
            leverage = 1

        win_rate_est = get_win_rate_estimate()
        entry_avg = levels["avg_entry"]
        liq = calc_liquidation_price(direction, entry_avg, leverage)
        reasons, warnings = signal_reasons(direction, ind, mode)
        grade = signal_grade(confidence)

        plan = TradePlan(
            symbol=code,
            direction=direction,
            trend=ind["trend_label"],
            rsi=float(ind["rsi"]),
            current_price=float(ind["price"]),
            confidence=confidence,
            win_rate_estimate=win_rate_est,
            entries=levels["entries"],
            stop_losses=levels["stop_losses"],
            take_profits=levels["take_profits"],
            funding_rate=funding,
            leverage=leverage,
            liquidation_price=liq,
            scores={},
            reasons=reasons,
            warnings=warnings,
            support=ind["support"],
            resistance=ind["resistance"],
            breakout_up=ind["breakout_up"],
            breakout_down=ind["breakout_down"],
            bullish_div=ind["bullish_div"],
            bearish_div=ind["bearish_div"],
            macd_bullish_div=ind["macd_bullish_div"],
            macd_bearish_div=ind["macd_bearish_div"],
            entry_price=entry_avg,
            sl_price=levels["stop_losses"][0],
            tp_prices=levels["take_profits"],
            timestamp=time.time(),
            mode=mode,
            layer_results=layers,
            signal_grade=grade,
            adx_at_time=ind["adx"],
            rsi_at_time=ind["rsi"],
            market_condition="trending" if ind["adx"] >= 25 else "ranging",
            rr=levels["rr"]
        )
        async with signal_history_lock:
            existing_signal = next((r for r in signal_history if r["symbol"] == code and r["mode"] == mode and r["status"] == "open"), None)
            if existing_signal:
                same_direction = existing_signal["direction"] == direction
                entry_close = abs(existing_signal["entry_price"] - entry_avg) / entry_avg < 0.002 if entry_avg else False
                sl0 = levels["stop_losses"][0]
                sl_close = abs(existing_signal["sl_price"] - sl0) / sl0 < 0.002 if sl0 else False
                if same_direction and entry_close and sl_close:
                    # بدون تغییر واقعی؛ فقط تازه‌سازی timestamp، پیام کانال دوباره ارسال نمی‌شود
                    existing_signal["timestamp"] = time.time()
                    signal_id = existing_signal["signal_id"]
                elif same_direction:
                    # همان جهت اما ورود/اهداف تغییر کرده: همان سیگنال اصلاح می‌شود (پیام «سیگنال اصلاح شد»)
                    existing_signal.update({
                        "entry_price": entry_avg,
                        "sl_price": levels["stop_losses"][0],
                        "tp_prices": levels["take_profits"],
                        "confidence": confidence,
                        "timestamp": time.time(),
                        "win_rate_estimate": win_rate_est,
                        "signal_grade": grade,
                        "rr": levels["rr"],
                        "adx_at_time": ind["adx"],
                        "rsi_at_time": ind["rsi"],
                        "market_condition": "trending" if ind["adx"] >= 25 else "ranging",
                    })
                    signal_id = existing_signal["signal_id"]
                else:
                    # جهت کاملاً برعکس شده: سیگنال قبلی نامعتبر می‌شود (از آمار موفق/ناموفق حذف می‌شود)
                    # و یک سیگنال کاملاً تازه با شناسه جدید ثبت می‌شود
                    existing_signal["status"] = "invalidated"
                    existing_signal["invalidated_at"] = time.time()
                    signal_id = record_signal(plan)
            else:
                signal_id = record_signal(plan)

        if send_to_channel:
            await send_signal_to_channel(plan, signal_id)
        return plan
    except Exception as e:
        logger.exception(f"generate_trade_plan_v2 error for {code}: {e}")
        return None

def build_ladder_weighted(ind, direction, mode):
    config = MODE_CONFIGS[mode]
    price = float(ind["price"])
    atr = float(ind["atr"])
    if atr <= 0: atr = price * 0.01
    entries = [price - atr * m if direction == "LONG" else price + atr * m for m in config["entry_ladder_atr"]]
    avg_entry = sum(e * w for e, w in zip(entries, ENTRY_WEIGHTS))
    min_pcts = MIN_TP_PERCENTAGES.get(mode, [0.5, 1.0, 2.0])
    if direction == "LONG":
        take_profits = [
            max(avg_entry + atr * m, avg_entry * (1 + min_pct/100))
            for m, min_pct in zip(config["tp_multipliers"], min_pcts)
        ]
        initial_stop = min(avg_entry - config["sl_atr_mult"] * atr, ind["support"] * 0.995)
    else:
        take_profits = [
            min(avg_entry - atr * m, avg_entry * (1 - min_pct/100))
            for m, min_pct in zip(config["tp_multipliers"], min_pcts)
        ]
        initial_stop = max(avg_entry + config["sl_atr_mult"] * atr, ind["resistance"] * 1.005)
    risk = abs(avg_entry - initial_stop)
    reward = abs(take_profits[-1] - avg_entry)
    rr = reward / risk if risk > 0 else 0
    return {
        "entries": entries,
        "stop_losses": [initial_stop],
        "take_profits": take_profits,
        "avg_entry": avg_entry,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "entry_to_sl_pct": (risk / avg_entry * 100) if avg_entry > 0 else 0,
        "entry_to_tp_pct": (reward / avg_entry * 100) if avg_entry > 0 else 0,
        "sl_atr": risk / atr if atr > 0 else 0,
        "tp_atr": reward / atr if atr > 0 else 0,
    }

def calc_liquidation_price(direction, entry, leverage):
    maint_margin = 0.005
    if direction == "LONG":
        return entry * (1 - 1/leverage + maint_margin)
    return entry * (1 + 1/leverage - maint_margin)

def signal_reasons(direction, ind, mode):
    reasons, warnings = [], []
    if direction == "LONG":
        if ind.get("price_above_ema200", False): reasons.append("قیمت بالای EMA200")
        if ind.get("ema20_above_ema50", False): reasons.append("EMA20 بالای EMA50")
        if ind.get("ema20_bullish_cross", False): reasons.append("کراس صعودی EMA20/EMA50")
        if ind.get("macd_hist", 0) > 0: reasons.append("MACD مثبت")
        if ind.get("plus_di", 0) > ind.get("minus_di", 0): reasons.append("+DI > -DI")
        if ind.get("adx", 0) >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind.get("volume_ratio", 1) >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind.get("volume_ratio", 1) >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind.get("higher_tf_trend_up", False): reasons.append("تأیید تایم‌فریم بالاتر")
        if ind.get("price_above_vwap", False): reasons.append("قیمت بالای VWAP")
        if ind.get("roc", 0) > 0: reasons.append("ROC مثبت")
        if ind.get("cci", 0) > 0: reasons.append("CCI مثبت")
        if ind.get("breakout_up", False): reasons.append("شکست مقاومت")
        if ind.get("bullish_div", False): reasons.append("واگرایی مثبت RSI")
        if ind.get("macd_bullish_div", False): reasons.append("واگرایی مثبت MACD")
        if ind.get("rsi", 0) >= 68: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع خرید")
        if ind.get("williams_r", 0) > -20: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع خرید")
    else:
        if not ind.get("price_above_ema200", True): reasons.append("قیمت زیر EMA200")
        if not ind.get("ema20_above_ema50", True): reasons.append("EMA20 زیر EMA50")
        if ind.get("ema20_bearish_cross", False): reasons.append("کراس نزولی EMA20/EMA50")
        if ind.get("macd_hist", 0) < 0: reasons.append("MACD منفی")
        if ind.get("minus_di", 0) > ind.get("plus_di", 0): reasons.append("-DI > +DI")
        if ind.get("adx", 0) >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind.get("volume_ratio", 1) >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind.get("volume_ratio", 1) >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind.get("higher_tf_trend_down", False): reasons.append("تأیید تایم‌فریم بالاتر")
        if not ind.get("price_above_vwap", True): reasons.append("قیمت زیر VWAP")
        if ind.get("roc", 0) < 0: reasons.append("ROC منفی")
        if ind.get("cci", 0) < 0: reasons.append("CCI منفی")
        if ind.get("breakout_down", False): reasons.append("شکست حمایت")
        if ind.get("bearish_div", False): reasons.append("واگرایی منفی RSI")
        if ind.get("macd_bearish_div", False): reasons.append("واگرایی منفی MACD")
        if ind.get("rsi", 0) <= 32: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع فروش")
        if ind.get("williams_r", 0) < -80: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع فروش")
    return reasons, warnings

def record_signal(plan):
    global TOTAL_SIGNALS_GENERATED, LAST_REPORT_TIME
    signal_id = uuid.uuid4().hex[:10]
    record = {
        "signal_id": signal_id,
        "symbol": plan.symbol,
        "direction": plan.direction,
        "entry_price": plan.entry_price,
        "sl_price": plan.sl_price,
        "tp_prices": plan.tp_prices,
        "confidence": plan.confidence,
        "timestamp": plan.timestamp,
        "opened_at": plan.timestamp,  # زمان واقعی باز شدن؛ برخلاف timestamp هرگز با اصلاحیه‌ها بازنویسی نمی‌شود
        "leverage": plan.leverage,
        "status": "open",
        "mode": plan.mode,
        "win_rate_estimate": plan.win_rate_estimate,
        "signal_grade": plan.signal_grade,
        "rr": plan.rr,
        "adx_at_time": plan.adx_at_time,
        "rsi_at_time": plan.rsi_at_time,
        "market_condition": plan.market_condition,
    }
    signal_history.append(record)
    if len(signal_history) > 200:
        signal_history.pop(0)
    TOTAL_SIGNALS_GENERATED += 1
    LAST_REPORT_TIME = time.time()
    return signal_id

CLOSED_STATUSES = ("tp3_hit", "sl_hit", "invalidated")
_STAGE_RANK = {"open": 0, "tp1_hit": 1, "tp2_hit": 2}

def update_signal_status(symbol, current_price):
    """
    بروزرسانی وضعیت سیگنال‌های باز یک ارز بر اساس قیمت لحظه‌ای.
    رفع باگ نسخه قبل: قبلاً فقط رکوردهایی با status == "open" بررسی می‌شدند،
    یعنی به محض رسیدن به TP1، سیگنال دیگر هرگز برای TP2/TP3/برخورد حد ضرر
    پیگیری نمی‌شد. اکنون تا رسیدن به یکی از وضعیت‌های نهایی (TP3، SL، یا
    نامعتبر شدن) پیگیری ادامه دارد و حد ضرر هم به‌صورت پویا (Trailing) جابه‌جا می‌شود:
    بعد از TP1 → حد ضرر به نقطه ورود، بعد از TP2 → حد ضرر به TP1.
    """
    changed = []
    for rec in signal_history:
        if rec["symbol"] != symbol or rec["status"] in CLOSED_STATUSES:
            continue
        direction = rec["direction"]
        old_status = rec["status"]
        tp = rec["tp_prices"]

        hit_sl = (current_price <= rec["sl_price"]) if direction == "LONG" else (current_price >= rec["sl_price"])
        if hit_sl:
            rec["status"] = "sl_hit"
        else:
            stage = _STAGE_RANK.get(old_status, 0)
            if direction == "LONG":
                if stage < 3 and current_price >= tp[2]:
                    stage = 3
                elif stage < 2 and current_price >= tp[1]:
                    stage = 2
                elif stage < 1 and current_price >= tp[0]:
                    stage = 1
            else:
                if stage < 3 and current_price <= tp[2]:
                    stage = 3
                elif stage < 2 and current_price <= tp[1]:
                    stage = 2
                elif stage < 1 and current_price <= tp[0]:
                    stage = 1

            if stage == 1 and old_status == "open":
                rec["status"] = "tp1_hit"
                rec["sl_price"] = rec["entry_price"]
            elif stage == 2 and old_status in ("open", "tp1_hit"):
                rec["status"] = "tp2_hit"
                rec["sl_price"] = tp[0]
            elif stage == 3:
                rec["status"] = "tp3_hit"

        if rec["status"] != old_status:
            changed.append(rec["signal_id"])
    return changed

# ---------- فرمت‌سازی ----------
def format_main_signal_v2(plan, code, chat_id):
    direction = "لانگ 🟢" if plan.direction == "LONG" else "شورت 🔴"
    mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
    layers_text = ""
    for layer, ok in plan.layer_results.items():
        emoji = "✅" if ok else "❌"
        layers_text += f"{emoji} {LAYER_NAMES.get(layer, layer)}\n"
    grade_emoji = {"A": "🔥", "B": "⚡", "C": "📊", "D": "💤"}.get(plan.signal_grade[:1], "📊")
    text = (
        f"{grade_emoji} *سیگنال نهادی* | {code}/USDT | {direction}\n"
        f"🕒 {shamsi_now()}\n"
        f"🛠️ حالت: {mode_label} | درجه: {plan.signal_grade}\n"
        f"{DIVIDER}\n"
        f"🧩 *تحلیل ۱۰ لایه‌ای:*\n{layers_text}\n"
        f"🎯 *اطمینان:* {plan.confidence:.0f}٪ ({confidence_badge(plan.confidence)})\n"
        f"📊 *نرخ موفقیت:* {plan.win_rate_estimate:.1f}٪\n"
        f"📐 *نسبت ریسک به بازده:* 1:{plan.rr:.2f}\n"
        f"{DIVIDER}\n"
        f"📥 *ورود پله‌ای:*\n"
        f"1️⃣ {fmt_amount(plan.entries[0], chat_id)}\n"
        f"2️⃣ {fmt_amount(plan.entries[1], chat_id)}\n"
        f"3️⃣ {fmt_amount(plan.entries[2], chat_id)}\n"
        f"🎯 *حد سود هوشمند:*\n"
        f"1️⃣ {fmt_amount(plan.take_profits[0], chat_id)}\n"
        f"2️⃣ {fmt_amount(plan.take_profits[1], chat_id)}\n"
        f"3️⃣ {fmt_amount(plan.take_profits[2], chat_id)}\n"
        f"🛑 *حد ضرر پویا:* {fmt_amount(plan.sl_price, chat_id)}\n"
        f"{DIVIDER}\n"
        f"⚡ *اهرم پیشنهادی:* {plan.leverage}x\n"
        f"💰 *مدیریت ریسک:* حداکثر ۱.۲٪ سرمایه\n"
        f"🔔 *نکته:* پس از رسیدن به TP1، حد ضرر را به Entry منتقل کنید.\n"
        f"{DIVIDER}\n"
        f"⚠️ تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست."
    )
    return rtl_lines(text)

def format_status_dashboard(code, ind, plan, chat_id, mode, long_layers=None, short_layers=None):
    mode_label = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])["label"]
    config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    price = ind['price']
    df_daily = cache.ohlcv.get("1d", {}).get(code)
    change_24h = 0
    high_24h = price
    low_24h = price
    if df_daily is not None and len(df_daily) >= 2:
        close_prev = float(df_daily["close"].iloc[-2])
        if close_prev > 0:
            change_24h = ((price - close_prev) / close_prev) * 100
        high_24h = float(df_daily["high"].iloc[-1]) if pd.notna(df_daily["high"].iloc[-1]) else price
        low_24h = float(df_daily["low"].iloc[-1]) if pd.notna(df_daily["low"].iloc[-1]) else price
    ema20_pos = "بالای 📈" if ind['price_above_ema20'] else "زیر 📉"
    ema50_pos = "بالای 📈" if ind['price_above_ema50'] else "زیر 📉"
    macd_status = "مثبت 📈" if ind['macd_hist'] > 0 else "منفی 📉"
    support = ind['support']
    resistance = ind['resistance']
    support_2 = ind['support'] * 0.99
    resistance_2 = ind['resistance'] * 1.01
    if plan and plan.layer_results:
        confirmed = sum(1 for v in plan.layer_results.values() if v)
        total_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in plan.layer_results.items() if ok)
        layers_summary = "📋 *خلاصه تحلیل لایه‌ها (۱۰ لایه):*\n"
        for layer, ok in plan.layer_results.items():
            emoji = "✅" if ok else "❌"
            weight = LAYER_WEIGHTS.get(layer, 0)
            layers_summary += f"{emoji} {LAYER_NAMES.get(layer, layer)} (وزن: {weight}%)\n"
        layers_summary += f"\n💡 *جمع‌بندی:* {confirmed} از ۱۰ لایه تأیید شد | امتیاز وزنی: {total_weight}%"
    else:
        if long_layers is not None and short_layers is not None:
            long_confirmed = sum(1 for v in long_layers.values() if v)
            short_confirmed = sum(1 for v in short_layers.values() if v)
            long_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in long_layers.items() if ok)
            short_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in short_layers.items() if ok)
            layers_summary = (
                f"📋 *خلاصه تحلیل لایه‌ها:*\n"
                f"🟢 لانگ: {long_confirmed} لایه تأیید | امتیاز: {long_weight}%\n"
                f"🔴 شورت: {short_confirmed} لایه تأیید | امتیاز: {short_weight}%\n"
                f"📊 اختلاف: {abs(long_weight - short_weight):.0f}%\n"
            )
            reasons_no_signal = []
            if ind['adx'] < config['adx_min']:
                reasons_no_signal.append(f"⚠️ ADX پایین است ({ind['adx']:.1f} < {config['adx_min']})")
            if long_confirmed < config['min_confirmations'] and short_confirmed < config['min_confirmations']:
                reasons_no_signal.append(f"⚠️ تعداد لایه‌ها کمتر از حد نیاز ({config['min_confirmations']}) است")
            if abs(long_weight - short_weight) < MIN_DIRECTION_GAP:
                reasons_no_signal.append(f"⚠️ اختلاف امتیاز دو جهت کمتر از {MIN_DIRECTION_GAP} است")
            if reasons_no_signal:
                layers_summary += f"\n💡 *دلایل عدم سیگنال:*\n" + "\n".join(reasons_no_signal)
            else:
                layers_summary += f"\n💡 *وضعیت:* شرایط برای سیگنال‌دهی مناسب نیست"
        else:
            layers_summary = "📋 در حال تحلیل لایه‌ها..."
    header = f"🧭 *وضعیت لحظه‌ای* {code}/USDT\n🕒 {shamsi_now()}\n🛠️ حالت: {mode_label}\n{DIVIDER}\n"
    price_text = (
        f"💰 قیمت: {fmt_amount(price, chat_id)}\n"
        f"📊 تغییرات ۲۴h: {change_24h:+.2f}%\n"
        f"📈 بالا: {fmt_amount(high_24h, chat_id)} | 📉 پایین: {fmt_amount(low_24h, chat_id)}\n"
        f"{DIVIDER}\n"
        f"📈 روند: {ind['trend_label']}\n"
        f"📊 قیمت نسبت به EMA20: {ema20_pos} | EMA50: {ema50_pos}\n"
        f"🎯 RSI: {ind['rsi']:.1f}\n"
        f"💪 ADX: {ind['adx']:.1f}\n"
        f"📊 MACD: {macd_status}\n"
        f"📊 حجم: {ind['volume_ratio']:.2f}× میانگین {' 🔊' if ind['volume_spike'] else ''}\n"
        f"{DIVIDER}\n"
        f"📊 حمایت: {fmt_amount(support, chat_id)} | مقاومت: {fmt_amount(resistance, chat_id)}\n"
    )
    if plan and plan.confidence >= MIN_SIGNAL_CONFIDENCE:
        footer = (
            f"\n{DIVIDER}\n"
            f"🎯 اطمینان: {plan.confidence:.0f}٪\n"
            f"⚡ اهرم: {plan.leverage}x\n"
            f"📐 RR: 1:{plan.rr:.2f}\n"
            f"📊 نرخ موفقیت: {plan.win_rate_estimate:.1f}٪\n"
            f"{DIVIDER}\n"
            f"⚠️ حد ضرر: {fmt_amount(plan.sl_price, chat_id)}"
        )
    else:
        footer = f"\n{DIVIDER}\n💤 در حال حاضر سیگنال نهایی وجود ندارد."
    return rtl_lines(header + price_text + layers_summary + footer + f"\n{DIVIDER}\n⚠️ تحلیل تکنیکال است و تضمین سود نیست.")

# ---------- توابع اصلی ----------
async def generate_trade_plan(code, mode="standard"):
    return await generate_trade_plan_v2(code, mode)

async def generate_status_text_async(code, chat_id, mode="standard"):
    await cache.update_prices(force=True, codes=[code])
    ind = await cache.get_indicators(code, mode)
    if not ind:
        return rtl_lines(f"{code}\n\n⚠️ داده کافی برای تحلیل این ارز دریافت نشد.")
    order_flow = await cache._get_order_flow(code)
    long_layers = await analyze_layers(code, "LONG", ind, mode, cache, order_flow)
    short_layers = await analyze_layers(code, "SHORT", ind, mode, cache, order_flow)
    plan = await generate_trade_plan_v2(code, mode)
    return format_status_dashboard(code, ind, plan, chat_id, mode, long_layers, short_layers)

async def generate_weekly_summary_async(code, chat_id):
    await cache.update_prices(force=True, codes=[code])
    week_df = await cache.get_weekly_data(code)
    if week_df is None or len(week_df) < 2:
        return rtl_lines(f"{code}\n\n⚠️ حداقل داده لازم برای تحلیل ۷ روزه دریافت نشد.")
    week_df = week_df.sort_values("timestamp").reset_index(drop=True)
    close = week_df["close"]
    first_price = float(close.iloc[0]); current_price = float(close.iloc[-1])
    if first_price <= 0: return "⚠️ قیمت تاریخی نامعتبر است."
    cumulative_return = ((current_price / first_price) - 1) * 100
    returns = close.pct_change() * 100
    positive_days = int((returns > 0).sum()); negative_days = int((returns < 0).sum())
    best_day = float(returns.max()); worst_day = float(returns.min())
    best_idx = returns.idxmax(); worst_idx = returns.idxmin()
    highest = float(week_df["high"].max()); lowest = float(week_df["low"].min())
    range_pct = ((highest - lowest) / first_price * 100)
    high_row = week_df.loc[week_df["high"].idxmax()]; low_row = week_df.loc[week_df["low"].idxmin()]
    running_max = close.cummax(); drawdown = (close / running_max - 1) * 100; max_drawdown = fl
