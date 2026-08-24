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

--- اصلاحات دور بعدی (این نسخه) ---
15) رفع سه باگ بحرانی که باعث «کار نکردن اکثر دکمه‌های ربات» شده بود:
    - format_main_signal_v2 (نمایش کارت سیگنال) به یک متغیر fg_value/fg_class ارجاع
      می‌داد که هرگز در آن تابع محاسبه نشده بود → با NameError کرش می‌کرد (۱۰۰٪ قابل
      تکرار، هر بار که سیگنالی نمایش داده می‌شد).
    - داخل button_handler، بلوک «if fg_value is not None» مربوط به دکمه‌ی «داشبورد
      تحلیلی» به‌اشتباه هم‌سطح با «if data == "dashboard":» بود، نه داخل آن؛ یعنی این
      بلوک (و return پایانش) برای *هر* callback دیگری هم که به این نقطه از کد می‌رسید
      اجرا و باعث NameError می‌شد — یعنی هر دکمه‌ای که هندلرش در فایل بعد از این نقطه
      قرار داشت (لیست ارزها، برگشت‌ها، دریافت قیمت و ده‌ها دکمه‌ی دیگر) اصلاً هرگز به
      کد خودش نمی‌رسید.
    - همین دقیقاً همین باگ (تورفتگی اشتباه) برای دکمه‌ی «پنل مدیریت» هم تکرار شده بود.
    این سه مورد با هم توضیح می‌دهند چرا تقریباً همه‌ی دکمه‌های ربات از کار افتاده بودند.
16) طبق درخواست، ارسال خبر/هشدار نهنگ به کانال کاملاً غیرفعال شد (send_high_importance_
    news_to_channel اکنون بلافاصله return می‌کند). اخبار همچنان در تاریخچه‌ی داخلی ربات
    («📰 اخبار و هشدارها» برای کاربران خصوصی) ذخیره می‌شود؛ فقط دیگر به کانال ارسال
    نمی‌شود.
17) طبق درخواست، دیگر هیچ پیامی در کانال حذف نمی‌شود. هم send_signal_to_channel (سیگنال
    جدید/اصلاح‌شده) و هم update_channel_signal_message (TP1/TP2/TP3/SL) به‌جای
    delete_message + send_message مستقل، پیام تازه را با reply_to_message_id روی
    *آخرین* پیام مربوط به همان سیگنال ارسال می‌کنند. نتیجه یک رشته‌ی ریپلای کامل در
    کانال است (باز شدن → اصلاح‌ها → TP/SL) که همیشه مشخص می‌کند هر پیام ادامه‌ی کدام
    سیگنال است، بدون از دست رفتن هیچ پیامی از تاریخچه‌ی کانال.
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
WHALE_MIN_AMOUNT_BTC = 1000        # آستانه برای Whale Alert API (در صورت داشتن کلید پولی)
WHALE_MIN_AMOUNT_BTC_FREE = 150    # آستانه برای حالت رایگان (blockchain.info) — اصلاح باگ:
# قبلاً همان آستانه‌ی ۱۰۰۰ BTC برای حالت رایگان هم استفاده می‌شد؛ تراکنش‌های بیت‌کوینی
# بالای ۱۰۰۰ BTC (حدود ۱۰۰+ میلیون دلار) در مواقع خیلی نادر اتفاق می‌افتن، یعنی عملاً
# هیچ‌وقت هیچ هشدار نهنگی از منبع رایگان نمی‌رسید. این یکی از دلایل اصلی «اخبار نمیاد» بود.
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
STATE_BACKUP_DIR = os.path.join(DATA_DIR, "backups")
STATE_BACKUP_KEEP = 5  # چند نسخه‌ی پشتیبان آخر نگه‌داشته شود

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"
MENU_PROMPT = "👇 یکی از گزینه‌ها را انتخاب کن:"

# ---------- صرافی‌ها ----------
# اصلاح باگ (علت اصلی «بات استارت نمیشه» با نسخه‌های جدید ccxt):
# در ccxt نسخه ۴ به بعد، نام کلاس صرافی Gate.io از gateio به gate تغییر کرده.
_GateExchangeClass = getattr(ccxt, "gate", None) or getattr(ccxt, "gateio", None)
if _GateExchangeClass is None:
    raise RuntimeError(
        "کتابخانه ccxt نصب‌شده هیچ‌کدام از کلاس‌های 'gate' یا 'gateio' را ندارد. "
        "لطفاً با «pip install --upgrade ccxt» نسخه ccxt را بروزرسانی کنید."
    )
exchange_gateio = _GateExchangeClass({
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
CHANNEL_MIN_DIRECTION_GAP = 20                 # قبلاً 18 — اختلاف امتیاز لانگ/شورت باید کاملاً واضح باشد
CHANNEL_MIN_CONFIRMATIONS_BONUS = 2            # لایه تاییدی اضافه نسبت به حداقل حالت پایه (متناسب با ۲۰ لایه، قبلاً 1 بود روی مبنای ۱۰ لایه)
CHANNEL_ADX_MIN = 18                           # قبلاً 20 — فقط در بازار با روند نسبتاً قوی سیگنال کانال صادر شود

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
        "min_confirmations": 9,  # قبلاً 5 از ۱۰ لایه؛ حالا از ۲۰ لایه (تناسب حفظ شد)
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
        "min_confirmations": 11,  # قبلاً 6 از ۱۰ لایه؛ حالا از ۲۰ لایه
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
        "min_confirmations": 13,  # قبلاً 7 از ۱۰ لایه؛ حالا از ۲۰ لایه
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
        "min_confirmations": 15,  # قبلاً 8 از ۱۰ لایه؛ حالا از ۲۰ لایه
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
    # --- ۱۰ لایه‌ی اصلی قبلی (وزن‌ها کمی کاهش یافت تا جا برای لایه‌های جدید باز شود) ---
    "structure": 10,
    "mtf": 10,
    "momentum": 10,
    "volume": 6,
    "sentiment": 6,
    "trend": 6,
    "order_flow": 6,
    "breadth": 4,
    "smart_vol": 4,
    "comp_trend": 6,
    # --- ۱۰ لایه‌ی جدید (طبق درخواست: افزایش از ۱۰ به ۲۰، مبتنی بر اندیکاتورهای مهم) ---
    "rsi_zone": 5,          # RSI در محدوده‌ی سالم روند (نه در اشباع خرید/فروش)
    "stoch_rsi": 3,         # تایید مومنتوم کوتاه‌مدت با StochRSI
    "cci_confirm": 3,       # هم‌جهتی CCI
    "williams_r": 3,        # هم‌جهتی Williams %R
    "ema_stack": 5,         # آرایش کامل EMA20/50/200 (مهم‌ترین لایه‌ی جدید)
    "vwap_confirm": 4,      # قیمت نسبت به VWAP (معیار نهادی)
    "breakout_confirm": 3,  # شکست واقعی سقف/کف اخیر
    "bb_position": 3,       # موقعیت در باند بولینگر
    "volatility_sane": 2,   # نوسان غیرعادی/بیش‌ازحد نباشد
    "no_counter_div": 1,    # واگرایی خلاف جهت سیگنال شکل نگرفته باشد
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
    "rsi_zone": "محدوده RSI",
    "stoch_rsi": "StochRSI",
    "cci_confirm": "CCI",
    "williams_r": "Williams %R",
    "ema_stack": "آرایش EMA",
    "vwap_confirm": "موقعیت نسبت به VWAP",
    "breakout_confirm": "شکست قیمتی",
    "bb_position": "موقعیت باند بولینگر",
    "volatility_sane": "نوسان منطقی (ATR)",
    "no_counter_div": "نبود واگرایی مخالف",
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
    early_entry: bool = False
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
def detect_early_entry(df):
    """Detect an EMA(fast/slow) or MACD/signal cross within the last 3 closed candles.
    Returns 'LONG', 'SHORT', or None."""
    try:
        if df is None or len(df) < 4:
            return None
        recent = df.iloc[-4:]
        e_fast = recent['ema20'].values
        e_slow = recent['ema50'].values
        m = recent['macd'].values
        s = recent['macd_signal'].values
        long_cross = short_cross = False
        for i in range(1, len(recent)):
            if e_fast[i-1] <= e_slow[i-1] and e_fast[i] > e_slow[i]:
                long_cross = True
            if e_fast[i-1] >= e_slow[i-1] and e_fast[i] < e_slow[i]:
                short_cross = True
            if m[i-1] <= s[i-1] and m[i] > s[i]:
                long_cross = True
            if m[i-1] >= s[i-1] and m[i] < s[i]:
                short_cross = True
        if long_cross and not short_cross:
            return 'LONG'
        if short_cross and not long_cross:
            return 'SHORT'
        return None
    except Exception:
        return None



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
    """
    اصلاح باگ: نسخه‌ی قبل نرخ موفقیت را از روی «همه‌ی» رکوردهای signal_history (از جمله
    سیگنال‌های هنوز باز/در حال اجرا) حساب می‌کرد که عدد را به‌شدت و نادرست پایین نشان
    می‌داد. الان فقط سیگنال‌های واقعاً بسته‌شده (TP یا SL) را در نظر می‌گیرد.
    """
    closed = [s for s in signal_history if s["status"] in ("tp1_hit", "tp2_hit", "tp3_hit", "sl_hit")]
    if not closed:
        return 50.0
    wins = sum(1 for s in closed if s["status"].startswith("tp"))
    return wins / len(closed) * 100

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
            # اصلاح باگ: قبلاً یک فیلتر دوم و اشتباه این‌جا بود که فقط اخباری رو قبول
            # می‌کرد که کلمه‌ی «important» یا «high» توی برچسب‌هاشون باشه. اما درخواست
            # بالا از قبل با &filter=important فقط اخبار مهم رو از سمت خود CryptoPanic
            # گرفته؛ برچسب‌های واقعی هرگز حاوی کلمه‌ی «important» نیستن (مثلاً
            # «Bitcoin», «Regulation» و...)، پس این شرط تقریباً همیشه False می‌شد و
            # لیست خبر همیشه خالی برمی‌گشت — این اصلی‌ترین دلیل «اخبار نمیاد» بود.
            news_list.append({
                "title": escape_markdown(title[:100]),
                "impact": impact,
                "source": "CryptoPanic",
                "url": item.get("url", "") if isinstance(item.get("url", ""), str) and item.get("url", "").strip().startswith("http") else "",
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
                    flow_type = "خروج از صرافی"
                elif not from_is_exchange and to_is_exchange:
                    flow_type = "ورود به صرافی"
                elif from_is_exchange and to_is_exchange:
                    flow_type = "انتقال بین صرافی‌ها"
                else:
                    flow_type = "انتقال بین کیف‌پول‌ها"
                impact = "خنثی"
                # اصلاح باگ (رگرسیون تکراری): قبلاً flow_type رشته‌ای شامل پسوند
                # "(احتمال فروش)" بود، در حالی که این مقایسه‌ها دقیقاً با رشته‌ی بدون
                # پسوند مقایسه می‌شدند و همیشه False می‌شدند — یعنی این دو حالت هرگز به
                # عنوان impact محاسبه نمی‌شدند و اکثر هشدارها به‌اشتباه «خنثی» می‌ماندند
                # و توسط فیلتر پایین‌دستی (که فقط نزولی/صعودی رو نشون می‌ده) حذف می‌شدند.
                if flow_type == "ورود به صرافی" and amount_btc > 500:
                    impact = "نزولی 📉 (احتمال فروش)"
                elif flow_type == "خروج از صرافی" and amount_btc > 500:
                    impact = "صعودی 📈 (احتمال انباشت/نگهداری)"
                elif amount_btc > 2000:
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
                if total_out >= WHALE_MIN_AMOUNT_BTC_FREE:
                    alerts.append({
                        "amount_btc": total_out,
                        "symbol": "BTC",
                        "timestamp": time.time(),
                        "from_address": "مشخص نیست",
                        "to_address": "مشخص نیست",
                        "from_owner": "ناشناس",
                        "to_owner": "ناشناس",
                        "flow_type": "نامشخص",
                        "impact": "🔍 نیاز به بررسی (حرکت بزرگ، جهت دقیق نامشخص)",
                        "value_usd": total_out * cache.prices.get("BTC", 0)
                    })
            return alerts[:5]
    except Exception as e:
        logger.warning("Whale alert fetch failed: %s", e)
        return []

async def fetch_important_news():
    # اصلاح باگ: قبلاً این تابع هم (از طریق news_monitor_loop) و هم whale_monitor_loop
    # به‌صورت جداگانه fetch_whale_alerts() رو صدا می‌زدن و به news_history اضافه
    # می‌کردن — یعنی هر هشدار نهنگ دوبار پردازش و دوبار به کانال ارسال می‌شد. الان
    # مسئولیت نهنگ‌ها فقط با whale_monitor_loop هست و این تابع فقط اخبار CryptoPanic
    # رو برمی‌گردونه.
    all_news = []
    crypto_news = await fetch_cryptopanic_news()
    for item in crypto_news:
        text = f"📰 *{item['title']}*\n📈 تأثیر: {item['impact']}\n📌 منبع: {item['source']}"
        news_url = item.get("url", "")
        if isinstance(news_url, str) and news_url.strip().startswith("http"):
            text += f"\n🔗 لینک: {news_url.strip()}"
        all_news.append({
            "text": text,
            "importance": "high",
            "impact": item["impact"],
            "source": "crypto",
            "url": news_url.strip() if isinstance(news_url, str) and news_url.strip().startswith("http") else "",
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
        [InlineKeyboardButton("🔙 بازگشت", callback_data="optimization_center")],
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
    """
    اصلاح مهم (علت اصلی «بیشتر سیگنال‌ها اشتباه دارد»): با اینکه سیستم «۱۰ لایه تاییدی»
    نامیده می‌شد، اکثر لایه‌ها با شرط‌های بسیار سهل‌گیرانه تقریباً همیشه True برمی‌گشتند
    (مثلاً momentum فقط با ۱ از ۴ شرط تایید می‌شد، order_flow/breadth وقتی داده کافی
    نداشتند به‌طور خودکار True می‌شدند، volume با حجم زیر میانگین هم قبول می‌شد). نتیجه
    این بود که هم سیگنال لانگ و هم شورت یک نماد هم‌زمان امتیاز بالا می‌گرفتند و انتخاب
    جهت نهایی عملاً به یک اختلاف امتیاز کوچک و نه‌چندان معنادار وابسته می‌شد. هر لایه
    اکنون واقعاً باید چیزی را تایید کند، نه اینکه پیش‌فرض تایید باشد:
    - structure: فقط نیمه‌ی درست رنج ۲۰ کندلی (نه هر قیمتی بالاتر از کف).
    - mtf: اکثریت تایم‌فریم‌ها (۲ از ۳) هم‌جهت باشند، نه فقط ۱ مورد.
    - momentum: حداقل ۳ از ۴ شرط (نه فقط ۱).
    - volume: حجم واقعاً هم‌سطح یا بالاتر از میانگین (۱.۰x به‌جای ۰.۸x).
    - sentiment: باید واقعاً هم‌جهت باشد (نه فقط «خیلی منفی نباشد»).
    - order_flow / breadth: نبود داده دیگر به‌معنای تایید خودکار نیست؛ یعنی «نامشخص»
      همان «تاییدنشده» است، نه «تاییدشده».
    """
    config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    df = cache_obj.ohlcv.get(config["main_tf"], {}).get(code)
    results = {}
    if df is not None and len(df) > 30:
        high = df["high"].iloc[-20:]
        low = df["low"].iloc[-20:]
        price = float(df["close"].iloc[-1])
        prev_high = float(high.max())
        prev_low = float(low.min())
        midpoint = (prev_high + prev_low) / 2
        if direction == "LONG":
            # ساختار فقط وقتی تایید می‌شود که قیمت واقعاً در نیمه‌ی پایینی رنج اخیر باشد
            # (خرید نزدیک حمایت) — نه صرفاً «بالاتر از کف».
            results["structure"] = price <= midpoint
        else:
            results["structure"] = price >= midpoint
    else:
        results["structure"] = False

    main_tf = config["main_tf"]
    confirm_tfs = config["confirm_tfs"]
    mtf_total = 0
    mtf_count = 0
    df_main = cache_obj.ohlcv.get(main_tf, {}).get(code)
    if df_main is not None and len(df_main) > 50:
        mtf_total += 1
        price = float(df_main["close"].iloc[-1])
        ema200 = EMAIndicator(df_main["close"], window=200).ema_indicator().iloc[-1]
        if direction == "LONG" and price > ema200:
            mtf_count += 1
        elif direction == "SHORT" and price < ema200:
            mtf_count += 1
    for tf in confirm_tfs:
        df_tf = cache_obj.ohlcv.get(tf, {}).get(code)
        if df_tf is not None and len(df_tf) > 50:
            mtf_total += 1
            price = float(df_tf["close"].iloc[-1])
            ema200 = EMAIndicator(df_tf["close"], window=200).ema_indicator().iloc[-1]
            if direction == "LONG" and price > ema200:
                mtf_count += 1
            elif direction == "SHORT" and price < ema200:
                mtf_count += 1
    # اکثریت واقعی لازم است (حداقل ۲ تایم‌فریم هم‌جهت)، نه فقط یکی از سه‌تا.
    results["mtf"] = mtf_total >= 2 and mtf_count >= 2

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
    results["momentum"] = momentum_score >= 3

    results["volume"] = ind["volume_ratio"] >= 1.0 or ind["volume_spike"] or ind["volume_trend_up"]

    sentiment_score = await cache_obj._calculate_sentiment_score(code, ind)
    if direction == "LONG":
        results["sentiment"] = sentiment_score > 0.05
    else:
        results["sentiment"] = sentiment_score < -0.05

    results["trend"] = ind["price_above_ema200"] if direction == "LONG" else not ind["price_above_ema200"]

    if order_flow is None:
        order_flow = await cache_obj._get_order_flow(code)
    if order_flow == 0:
        # داده جریان سفارشات در دسترس نبود؛ «نامشخص» دیگر به‌معنای تایید خودکار نیست.
        results["order_flow"] = False
    elif 0.95 <= order_flow <= 1.05:
        # جریان سفارشات واقعاً متعادل است — نه به‌نفع لانگ نه شورت، هر دو جهت را می‌پذیرد.
        results["order_flow"] = True
    else:
        if direction == "LONG":
            results["order_flow"] = order_flow > 1.05
        else:
            results["order_flow"] = order_flow < 0.95

    breadth = cache_obj._get_market_breadth()
    sample_count = getattr(cache_obj, "_breadth_sample_count", 0)
    if sample_count < 5:
        # نمونه کافی برای قضاوت در مورد کل بازار نداریم؛ «نامشخص» تایید محسوب نمی‌شود.
        results["breadth"] = False
    elif direction == "LONG":
        results["breadth"] = breadth >= 50
    else:
        results["breadth"] = breadth <= 50

    bb_percent = ind.get("bb_percent", 0.5)
    results["smart_vol"] = 0.15 <= bb_percent <= 0.85

    if direction == "LONG":
        results["comp_trend"] = ind["plus_di"] > ind["minus_di"]
    else:
        results["comp_trend"] = ind["minus_di"] > ind["plus_di"]

    # ==================== ۱۰ لایه‌ی جدید (تا رسیدن به ۲۰ لایه) ====================
    # طبق درخواست: مبتنی بر اندیکاتورهای مهمی که از قبل محاسبه می‌شدند ولی هیچ‌کدام
    # به‌عنوان یک لایه‌ی مستقل امتیازدهی نمی‌شدند (RSI، EMA stack، VWAP، CCI،
    # Williams %R، StochRSI، شکست قیمتی، موقعیت باند بولینگر، نوسان، واگرایی).

    rsi_val = ind["rsi"]
    if direction == "LONG":
        # روند سالم صعودی: RSI بالای ۵۰ ولی هنوز در اشباع خرید افراطی نیست
        results["rsi_zone"] = 50 < rsi_val < 75
    else:
        results["rsi_zone"] = 25 < rsi_val < 50

    stoch_k = ind.get("stoch_k", 50)
    results["stoch_rsi"] = stoch_k > 50 if direction == "LONG" else stoch_k < 50

    cci_val = ind.get("cci", 0)
    results["cci_confirm"] = cci_val > 0 if direction == "LONG" else cci_val < 0

    williams_val = ind.get("williams_r", -50)
    # محدوده‌ی Williams %R بین ۰ و ۱۰۰-‌ است؛ بالای ۵۰- یعنی مومنتوم رو به بالا
    results["williams_r"] = williams_val > -50 if direction == "LONG" else williams_val < -50

    # آرایش کامل میانگین‌های متحرک — مهم‌ترین لایه‌ی جدید؛ فقط وقتی هر سه EMA
    # به ترتیب درست چیده شده باشند تایید می‌شود (نه صرفاً یکی دو تا).
    price = ind["price"]
    ema20, ema50, ema200 = ind["ema20"], ind["ema50"], ind["ema200"]
    if direction == "LONG":
        results["ema_stack"] = price > ema20 > ema50 > ema200
    else:
        results["ema_stack"] = price < ema20 < ema50 < ema200

    results["vwap_confirm"] = ind["price_above_vwap"] if direction == "LONG" else not ind["price_above_vwap"]

    results["breakout_confirm"] = ind["breakout_up"] if direction == "LONG" else ind["breakout_down"]

    bb_pct = ind.get("bb_percent", 0.5)
    # موقعیت در باند بولینگر: برای لانگ باید در نیمه‌ی بالایی (نه در سقف کامل باند)،
    # برای شورت در نیمه‌ی پایینی باشد (نه در کف کامل باند که ممکن است برگشت بخورد).
    if direction == "LONG":
        results["bb_position"] = 0.45 <= bb_pct <= 0.95
    else:
        results["bb_position"] = 0.05 <= bb_pct <= 0.55

    atr_pct = ind.get("atr_pct", 1.0)
    # نوسان خیلی پایین (بازار خواب) یا خیلی بالا (نامنظم/خطرناک برای حد ضرر) رد می‌شود.
    results["volatility_sane"] = 0.15 <= atr_pct <= 8.0

    # واگرایی خلاف جهت سیگنال نباید شکل گرفته باشد (هشدار برگشت روند زودهنگام)
    if direction == "LONG":
        results["no_counter_div"] = not (ind.get("bearish_div") or ind.get("macd_bearish_div"))
    else:
        results["no_counter_div"] = not (ind.get("bullish_div") or ind.get("macd_bullish_div"))

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
        # اصلاح باگ اصلی «همه سیگنال‌ها دارند برعکس می‌شوند»: قبلاً این تابع (هم اینجا برای
        # کول‌داون، هم پایین‌تر برای تشخیص اصلاح/نامعتبرشدن) فقط status=="open" را «سیگنال
        # فعال» می‌دانست. به‌محض برخورد قیمت به TP1، وضعیت به "tp1_hit" تغییر می‌کرد و از
        # دید این تابع انگار اصلاً سیگنالی برای آن ارز وجود نداشت. پس در چرخه‌ی بعدی —
        # درست وقتی که بعد از یک حرکت قیمتی بزرگ، تحلیل تکنیکال غالباً جهت مخالف را نشان
        # می‌دهد — بلافاصله یک سیگنال کاملاً تازه و اغلب در جهت عکس ساخته و در کانال
        # جایگزین سیگنال قبلی (که هنوز واقعاً باز و در سود بود!) می‌شد. همین رفتار دقیقاً
        # همان چیزی بود که به‌نظر می‌رسید «هر سیگنالی خیلی سریع برعکس می‌شود».
        # اصلاح: تا وقتی سیگنال قبلی به‌طور کامل بسته نشده (TP3/SL/نامعتبر)، برای همان
        # ارز+حالت سیگنال تازه‌ای ساخته/جایگزین نمی‌شود؛ اگر سیگنال از قبل TP1/TP2 را زده
        # (یعنی در سود است)، دیگر دست نمی‌خورد — احتمال تغییر روند از طریق هشدار جداگانه‌ی
        # «تغییر روند» (send_trend_reversal_warning) به کاربران اطلاع داده می‌شود، نه با
        # جایگزین کردن کل سیگنال با یک سیگنال جدید و متضاد.
        existing_active = next(
            (r for r in signal_history if r["symbol"] == code and r["mode"] == mode and r["status"] not in CLOSED_STATUSES),
            None
        )
        if existing_active and existing_active["status"] in ("tp1_hit", "tp2_hit"):
            logger.debug(f"{code}/{mode} already has an in-profit signal ({existing_active['status']}); skipping re-analysis.")
            return None

        if send_to_channel and not existing_active:
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

        # اصلاح مهم (بخشی از بررسی سخت‌گیری هر ۴ حالت): با ۲۰ لایه، از نظر ریاضی ممکن
        # بود یک سیگنال فقط با تجمیع تعداد زیادی لایه‌ی «کم‌اهمیت» (وزن ۱ تا ۴، مثل
        # StochRSI/CCI/Williams %R/شکست/باند بولینگر) هم به حداقل تعداد لایه (min_confirmations)
        # و هم به حداقل اطمینان وزنی (MIN_SIGNAL_CONFIDENCE) برسد، بدون این‌که حتی یکی از
        # مهم‌ترین لایه‌های «بنیادین» (ساختار بازار، هم‌گرایی تایم‌فریم، مومنتوم، آرایش EMA)
        # تایید شده باشد. چنین سیگنالی از نظر آماری موجه است ولی از نظر تحلیلی ضعیف و
        # مصداق «سیگنال کاذب» است. الان حداقل ۲ مورد از این ۴ لایه‌ی بنیادین باید تایید
        # شده باشند، وگرنه سیگنال (چه شخصی چه کانال) صادر نمی‌شود.
        # Early-entry detection uses the same main-timeframe cache entry as analyze_layers.
        early_entry = False
        try:
            df_early = cache.ohlcv.get(config["main_tf"], {}).get(code)
            if df_early is not None:
                df_early = df_early.copy()
                close_early = df_early["close"]
                df_early["ema20"] = EMAIndicator(close_early, window=20).ema_indicator()
                df_early["ema50"] = EMAIndicator(close_early, window=50).ema_indicator()
                macd_early = MACD(close_early, window_slow=26, window_fast=12, window_sign=9)
                df_early["macd"] = macd_early.macd()
                df_early["macd_signal"] = macd_early.macd_signal()
                early_dir = detect_early_entry(df_early)
                early_entry = (early_dir == direction)
        except Exception as e:
            logger.debug(f"Early-entry detection unavailable for {code}: {e}")
            early_entry = False

        CORE_LAYERS = ("structure", "mtf", "momentum", "ema_stack")
        core_confirmed = sum(1 for l in CORE_LAYERS if layers.get(l, False))
        if core_confirmed < (2 - (1 if early_entry else 0)):
            logger.info(f"Core layers insufficient for {code}: only {core_confirmed}/4 ({CORE_LAYERS}) confirmed")
            return None

        adx_floor = effective_adx_min - (3 if early_entry else 0)
        if send_to_channel and ind.get("adx", 0) < adx_floor:
            logger.info(f"ADX too low for channel signal {code}: {ind.get('adx', 0):.1f} < {adx_floor}")
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
            early_entry=early_entry,
            signal_grade=grade,
            adx_at_time=ind["adx"],
            rsi_at_time=ind["rsi"],
            market_condition="trending" if ind["adx"] >= 25 else "ranging",
            rr=levels["rr"]
        )
        async with signal_history_lock:
            existing_signal = next((r for r in signal_history if r["symbol"] == code and r["mode"] == mode and r["status"] not in CLOSED_STATUSES), None)
            if existing_signal and existing_signal["status"] in ("tp1_hit", "tp2_hit"):
                # رقابت زمانی نادر: بین شروع تحلیل (بالا) و رسیدن به اینجا، سیگنال به
                # TP1/TP2 رسیده. مثل حالت بالا، دست‌نخورده رهایش می‌کنیم.
                logger.debug(f"{code}/{mode} advanced to {existing_signal['status']} mid-analysis; skipping.")
                return None
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
        f"🧩 *تحلیل ۲۰ لایه‌ای:*\n{layers_text}\n"
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
        layers_summary = "📋 *خلاصه تحلیل لایه‌ها (۲۰ لایه):*\n"
        for layer, ok in plan.layer_results.items():
            emoji = "✅" if ok else "❌"
            weight = LAYER_WEIGHTS.get(layer, 0)
            layers_summary += f"{emoji} {LAYER_NAMES.get(layer, layer)} (وزن: {weight}%)\n"
        layers_summary += f"\n💡 *جمع‌بندی:* {confirmed} از ۲۰ لایه تأیید شد | امتیاز وزنی: {total_weight}%"
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
    running_max = close.cummax(); drawdown = (close / running_max - 1) * 100; max_drawdown = float(drawdown.min())
    running_min = close.cummin(); runup = (close / running_min - 1) * 100; max_runup = float(runup.max())
    volatility = float(returns.dropna().std() or 0)
    atr_series = AverageTrueRange(week_df["high"], week_df["low"], close, window=min(14, max(2, len(week_df)-1))).average_true_range()
    atr_daily = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
    atr_pct = (atr_daily / current_price * 100) if current_price > 0 else 0
    avg_volume = float(week_df["volume"].mean()); first_volume = float(week_df["volume"].iloc[0]); last_volume = float(week_df["volume"].iloc[-1])
    volume_trend_pct = ((last_volume / first_volume) - 1) * 100 if first_volume > 0 else 0
    volume_trend = "افزایشی 🔊" if volume_trend_pct > 10 else "کاهشی 🔇" if volume_trend_pct < -10 else "خنثی"
    daily_all = cache.ohlcv.get("1d", {}).get(code)
    daily_rsi = daily_ema20 = daily_ema50 = daily_macd = daily_adx = bb_position = bb_width = None
    if daily_all is not None and len(daily_all) >= 50:
        d_close = daily_all["close"]
        rsi = RSIIndicator(d_close, window=14).rsi()
        ema20 = EMAIndicator(d_close, window=20).ema_indicator(); ema50 = EMAIndicator(d_close, window=50).ema_indicator()
        macd = MACD(d_close, window_slow=26, window_fast=12, window_sign=9)
        adx_ind = ADXIndicator(daily_all["high"], daily_all["low"], d_close, window=14)
        bb = BollingerBands(d_close, window=20, window_dev=2)
        daily_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None
        daily_ema20 = float(ema20.iloc[-1]) if pd.notna(ema20.iloc[-1]) else None
        daily_ema50 = float(ema50.iloc[-1]) if pd.notna(ema50.iloc[-1]) else None
        daily_macd = float(macd.macd_diff().iloc[-1]) if pd.notna(macd.macd_diff().iloc[-1]) else None
        daily_adx = float(adx_ind.adx().iloc[-1]) if pd.notna(adx_ind.adx().iloc[-1]) else None
        bb_position = float(bb.bollinger_pband().iloc[-1]) if pd.notna(bb.bollinger_pband().iloc[-1]) else None
        bb_width = float(bb.bollinger_wband().iloc[-1]) if pd.notna(bb.bollinger_wband().iloc[-1]) else None
    if daily_ema20 is not None and daily_ema50 is not None:
        if current_price > daily_ema20 and daily_ema20 > daily_ema50: trend = "صعودی قوی 📈"
        elif current_price > daily_ema50: trend = "صعودی ملایم 📈"
        elif current_price < daily_ema20 and daily_ema20 < daily_ema50: trend = "نزولی قوی 📉"
        else: trend = "نزولی ملایم 📉"
    else: trend = "نامشخص"
    returns_vals = returns.dropna().tolist(); consecutive_up = 0
    for v in reversed(returns_vals):
        if v > 0: consecutive_up += 1
        else: break
    consecutive_down = 0
    for v in reversed(returns_vals):
        if v < 0: consecutive_down += 1
        else: break
    if daily_macd is not None and daily_macd > 0 and volume_trend_pct > 0: momentum_volume = "مومنتوم با حجم تأیید می‌شود 🟢"
    elif daily_macd is not None and daily_macd < 0 and volume_trend_pct < 0: momentum_volume = "ضعف مومنتوم با کاهش حجم 🔴"
    else: momentum_volume = "تأیید کامل وجود ندارد ⚠️"
    ret_3d = ((current_price / float(close.iloc[max(0, len(close)-4)])) - 1) * 100 if len(close) >= 4 else 0
    ret_24h = float(returns.iloc[-1]) if not returns.empty else 0
    best_date = shamsi_date(week_df.loc[best_idx, "timestamp"]) if best_idx in week_df.index else "-"
    worst_date = shamsi_date(week_df.loc[worst_idx, "timestamp"]) if worst_idx in week_df.index else "-"
    funding = 0.0
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📊 *تحلیل جامع ارز* {code}\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 بازده ۷ روزه: *{cumulative_return:+.2f}%*\n"
        f"📈 بازده ۳ روزه: *{ret_3d:+.2f}%*\n"
        f"📈 بازده ۲۴h: *{ret_24h:+.2f}%*\n"
        f"{DIVIDER}\n"
        f"📈 بالاترین: {fmt_amount(highest, chat_id)} 📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 پایین‌ترین: {fmt_amount(lowest, chat_id)} 📅 {shamsi_date(low_row['timestamp'])}\n"
        f"📏 محدوده ۷ روزه: *{range_pct:.2f}%*\n"
        f"🚀 بیشینه رشد: *{max_runup:+.2f}%*\n"
        f"🛑 بیشینه کاهش: *{max_drawdown:.2f}%*\n"
        f"⚡ ATR روزانه: *{atr_pct:.2f}%*\n"
        f"📐 نوسان‌پذیری: *{volatility:.2f}%*\n"
        f"{DIVIDER}\n"
        f"🟢 روز مثبت: {positive_days} | 🔴 روز منفی: {negative_days}\n"
        f"🔥 بهترین روز: *{best_day:+.2f}%* ({best_date})\n"
        f"💥 بدترین روز: *{worst_day:+.2f}%* ({worst_date})\n"
        f"📈 پشت‌سرهم صعودی: {consecutive_up} روز\n"
        f"📉 پشت‌سرهم نزولی: {consecutive_down} روز\n"
        f"{DIVIDER}\n"
        f"📊 میانگین حجم: `{avg_volume:,.0f}`\n"
        f"🔊 روند حجم: {volume_trend} ({volume_trend_pct:+.1f}%)\n"
        f"🧠 {momentum_volume}\n"
        f"{DIVIDER}\n"
        f"📈 *روند روزانه:* {trend}\n"
        f"📐 قیمت نسبت به EMA20: {'بالای 📈' if daily_ema20 is not None and current_price > daily_ema20 else 'زیر 📉' if daily_ema20 is not None else 'نامشخص'}\n"
        f"📐 قیمت نسبت به EMA50: {'بالای 📈' if daily_ema50 is not None and current_price > daily_ema50 else 'زیر 📉' if daily_ema50 is not None else 'نامشخص'}\n"
        f"📈 MACD روزانه: {'مثبت 📈' if daily_macd is not None and daily_macd > 0 else 'منفی 📉' if daily_macd is not None else '-'}\n"
        f"💪 ADX روزانه: {daily_adx:.1f}" if daily_adx is not None else "💪 ADX روزانه: -"
    )
    text += f"\n🎯 RSI روزانه: {daily_rsi:.1f}" if daily_rsi is not None else "\n🎯 RSI روزانه: -"
    text += f"\n📏 موقعیت بولینگر: {bb_position*100:.1f}%" if bb_position is not None else "\n📏 موقعیت بولینگر: -"
    text += f"\n📐 پهنای بولینگر: {bb_width:.2f}" if bb_width is not None else "\n📐 پهنای بولینگر: -"
    if macro_data:
        text += f"\n{DIVIDER}\n📊 *داده‌های کلان بازار:*\n"
        text += f"• سلطه بیت‌کوین: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += f"• حجم کل بازار: {macro_data.get('total_volume', 0):.0f}\n"
    text += (
        f"\n{DIVIDER}\n"
        f"{DIVIDER}\nℹ️ داده‌ها از Gate.io (اصلی)، کوکوین اسپات و CoinGecko (پشتیبان) محاسبه شده‌اند."
    )
    return rtl_lines(text)

def format_prices_pretty(prices, chat_id):
    lines = ["💰 قیمت لحظه‌ای", f"🕒 {shamsi_now()}", DIVIDER]
    for code in COIN_CODES:
        price = prices.get(code)
        if price is not None and price > 0:
            source = price_sources.get(code, "G")
            if source == "G":
                source_emoji = "🅶"
            elif source == "K":
                source_emoji = "🅺"
            elif source == "C":
                source_emoji = "🅲"
            else:
                source_emoji = "❓"
            price_display = fmt_amount(price, chat_id)
            lines.append(f"{code} {source_emoji} → {price_display}")
        else:
            lines.append(f"{code} ⚠️ قیمت در دسترس نیست")
    return rtl_lines("\n".join(lines))

def split_long_message(text, limit=TELEGRAM_MSG_LIMIT):
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(block) > limit:
            if current:
                parts.append(current.strip()); current = ""
            for i in range(0, len(block), limit):
                parts.append(block[i:i + limit])
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            parts.append(current.strip()); current = block
        else:
            current = candidate
    if current:
        parts.append(current.strip())
    return parts

# ---------- توابع ارسال به کانال ----------
def calculate_signal_hash(symbol, mode, direction, entry, sl, tps):
    return f"{symbol}|{mode}|{direction}|{entry:.6f}|{sl:.6f}|{tps[0]:.6f}|{tps[1]:.6f}|{tps[2]:.6f}"

async def send_signal_to_channel(plan, signal_id):
    """
    برای هر ارز فقط یک «رشته» سیگنال در کانال دنبال می‌شود (کلید = نماد ارز). طبق درخواست،
    پیام‌های قبلی دیگر حذف نمی‌شوند — هر پیام تازه (اصلاح، تارگت خورده، بسته‌شده و...) به‌صورت
    ریپلای روی آخرین پیام مربوط به همان سیگنال ارسال می‌شود تا در کانال کاملاً مشخص باشد
    این پیام ادامه‌ی کدام سیگنال است، بدون اینکه چیزی از تاریخچه‌ی کانال پاک شود.
    """
    if not CHANNEL_ID:
        return
    key = plan.symbol
    new_hash = calculate_signal_hash(plan.symbol, plan.mode, plan.direction, plan.entry_price, plan.sl_price, plan.tp_prices)

    async with channel_lock:
        existing = channel_message_map.get(key)
        if existing and existing.get("hash") == new_hash:
            logger.debug(f"No change for {key}, skipping channel message")
            return

        is_correction = bool(existing) and existing.get("signal_id") == signal_id
        reply_to_id = existing.get("message_id") if existing else None

        direction_emoji = "🟢" if plan.direction == "LONG" else "🔴"
        if is_correction:
            header = "🔄🔄🔄 *سیگنال اصلاح شد* 🔄🔄🔄"
            footer_note = ""
        elif existing:
            # سیگنال قبلی همین ارز به‌خاطر برعکس شدن کامل جهت بازار نامعتبر شد (نه TP/SL)؛
            # این خودش یک سیگنال کاملاً تازه است، فقط یک خط کوتاه توضیح اضافه می‌شود.
            header = "🔔 *سیگنال جدید*"
            footer_note = "\n\nℹ️ سیگنال قبلی این ارز به‌دلیل تغییر جهت بازار بسته شد."
        else:
            header = "🔔 *سیگنال جدید*"
            footer_note = ""
        mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
        text = (
            f"{header} | {plan.symbol}/USDT\n"
            f"🛠️ حالت معاملاتی: {mode_label}\n"
            f"📈 جهت: {plan.direction} {direction_emoji}\n"
            f"🎯 اطمینان: {plan.confidence:.0f}٪ ({confidence_badge(plan.confidence)})\n"
            f"📐 نسبت ریسک به بازده: 1:{plan.rr:.2f}\n\n"
            f"📥 ورود: {format_channel_price(plan.entry_price)}\n"
            f"🛑 حد ضرر: {format_channel_price(plan.sl_price)}\n"
            f"🎯 اهداف:\n"
            f"1️⃣ {format_channel_price(plan.tp_prices[0])}\n"
            f"2️⃣ {format_channel_price(plan.tp_prices[1])}\n"
            f"3️⃣ {format_channel_price(plan.tp_prices[2])}\n\n"
            f"⚡ اهرم پیشنهادی: {plan.leverage}x\n"
            f"🕒 {shamsi_now()}"
            f"{footer_note}"
        )
        if getattr(plan, "early_entry", False):
            text += "\n⚡️ ورود زودهنگام (Early Entry)"
        try:
            try:
                msg = await app.bot.send_message(
                    chat_id=CHANNEL_ID, text=rtl_lines(text), parse_mode="Markdown",
                    reply_to_message_id=reply_to_id,
                )
            except Exception as reply_err:
                if reply_to_id:
                    logger.warning(f"Reply to previous channel message failed ({reply_err}); sending without reply.")
                    msg = await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(text), parse_mode="Markdown")
                else:
                    raise
            old_signal_id = existing.get("signal_id") if existing else None
            if old_signal_id and old_signal_id != signal_id:
                channel_signal_messages.pop(old_signal_id, None)
            channel_message_map[key] = {
                "signal_id": signal_id,
                "message_id": msg.message_id,
                "hash": new_hash
            }
            channel_signal_messages[signal_id] = msg.message_id
            save_state()
            logger.info(f"Channel message {'corrected' if is_correction else 'sent'} for {key} (signal_id {signal_id})")
        except Exception as e:
            logger.error(f"Failed to send channel message for {key}: {e}")

def _format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} روز و {hours} ساعت"
    if hours > 0:
        return f"{hours} ساعت و {minutes} دقیقه"
    return f"{minutes} دقیقه"

def build_signal_update_text_from_record(rec):
    """
    برای TP1/TP2 (وضعیت‌های میانی) یک بروزرسانی مختصر با اهداف باقی‌مانده کافی است.
    اما برای بسته‌شدن نهایی سیگنال (TP3 یا SL) طبق درخواست، پیام باید شامل *اطلاعات
    کامل* معامله باشد (نه فقط یک خط وضعیت) — حالت معاملاتی، جهت، تمام ورودها/اهداف،
    اهرم، اطمینان اولیه، RR، زمان باز شدن و مدت زمانی که سیگنال باز بوده.
    """
    direction_emoji = "🟢" if rec["direction"] == "LONG" else "🔴"
    mode_label = MODE_CONFIGS.get(rec.get("mode"), MODE_CONFIGS["standard"])["label"]

    if rec["status"] == "tp1_hit":
        lines = [
            f"🔔 بروزرسانی سیگنال | {rec['symbol']}/USDT",
            f"🛠️ حالت: {mode_label} | جهت: {rec['direction']} {direction_emoji}",
            "",
            "✅ *TP1 زده شد*",
            f"🛑 حد ضرر به نقطه ورود منتقل شد (معامله از این پس بدون ریسک): {format_channel_price(rec['entry_price'])}",
            "🎯 اهداف بعدی:",
            f"2️⃣ {format_channel_price(rec['tp_prices'][1])}",
            f"3️⃣ {format_channel_price(rec['tp_prices'][2])}",
            f"🕒 بروزرسانی: {shamsi_now()}",
        ]
        return "\n".join(lines)

    if rec["status"] == "tp2_hit":
        lines = [
            f"🔔 بروزرسانی سیگنال | {rec['symbol']}/USDT",
            f"🛠️ حالت: {mode_label} | جهت: {rec['direction']} {direction_emoji}",
            "",
            "✅ *TP2 زده شد*",
            f"🛑 حد ضرر به TP1 منتقل شد: {format_channel_price(rec['sl_price'])}",
            "🎯 هدف بعدی:",
            f"3️⃣ {format_channel_price(rec['tp_prices'][2])}",
            f"🕒 بروزرسانی: {shamsi_now()}",
        ]
        return "\n".join(lines)

    if rec["status"] in ("tp3_hit", "sl_hit"):
        opened_at = rec.get("opened_at", rec.get("timestamp", time.time()))
        duration_txt = _format_duration(time.time() - opened_at)
        is_win = rec["status"] == "tp3_hit"
        # ایموجی سبز (برد) یا قرمز (باخت) دقیقاً در ابتدا و انتهای پیام، تا در نگاه اول و
        # حتی در پیش‌نمایش/نوتیفیکیشن تلگرام کاملاً مشخص باشد که این پیام یک «سیگنال زنده»
        # نیست بلکه گزارش نهایی بسته‌شدن یک سیگنال قبلی است.
        edge_emoji = "🟢" if is_win else "🔴"
        if is_win:
            result_header = "🏆 *سیگنال با موفقیت بسته شد — TP3 زده شد*"
            result_price = rec["tp_prices"][2]
            pct = (
                ((result_price - rec["entry_price"]) / rec["entry_price"] * 100)
                if rec["direction"] == "LONG"
                else ((rec["entry_price"] - result_price) / rec["entry_price"] * 100)
            )
            result_line = f"📈 نتیجه: +{pct:.2f}% (تا سطح TP3)"
        else:
            result_header = "❌ *سیگنال بسته شد — حد ضرر فعال شد*"
            result_price = rec["sl_price"]
            pct = (
                ((result_price - rec["entry_price"]) / rec["entry_price"] * 100)
                if rec["direction"] == "LONG"
                else ((rec["entry_price"] - result_price) / rec["entry_price"] * 100)
            )
            result_line = f"📉 نتیجه: {pct:.2f}%"

        lines = [
            f"{edge_emoji} {edge_emoji} {edge_emoji} بسته‌شدن سیگنال | {rec['symbol']}/USDT {edge_emoji} {edge_emoji} {edge_emoji}",
            f"🛠️ حالت معاملاتی: {mode_label}",
            f"📈 جهت: {rec['direction']} {direction_emoji}",
            DIVIDER,
            result_header,
            result_line,
            f"⏱️ مدت زمان باز بودن: {duration_txt}",
            DIVIDER,
            "📋 *جزئیات کامل معامله:*",
            f"📥 ورود: {format_channel_price(rec['entry_price'])}",
            f"🛑 حد ضرر نهایی: {format_channel_price(rec['sl_price'])}",
            "🎯 اهداف:",
            f"1️⃣ {format_channel_price(rec['tp_prices'][0])}",
            f"2️⃣ {format_channel_price(rec['tp_prices'][1])}",
            f"3️⃣ {format_channel_price(rec['tp_prices'][2])}",
            f"🎯 اطمینان اولیه: {rec.get('confidence', 0):.0f}٪ (درجه {rec.get('signal_grade', '-')})",
            f"📐 نسبت ریسک به بازده هدف: 1:{rec.get('rr', 0):.2f}",
            f"⚡ اهرم پیشنهادی: {rec.get('leverage', 1)}x",
            f"🕒 زمان باز شدن: {shamsi_date(datetime.fromtimestamp(opened_at))}",
            f"🕒 زمان بسته‌شدن: {shamsi_now()}",
            DIVIDER,
            f"{edge_emoji} {edge_emoji} {edge_emoji} این سیگنال دیگر فعال نیست {edge_emoji} {edge_emoji} {edge_emoji}",
        ]
        return "\n".join(lines)

    return ""

async def update_channel_signal_message(signal_id):
    """
    وضعیت تازه‌ی یک سیگنال (TP1/TP2/TP3/SL) را به‌صورت یک پیام *جدید* که روی آخرین پیام
    مربوط به همان سیگنال ریپلای شده ارسال می‌کند — طبق درخواست، دیگر هیچ پیامی در کانال
    حذف نمی‌شود؛ به این ترتیب کل تاریخچه‌ی یک سیگنال (باز شدن → اصلاح‌ها → TP/SL) به‌صورت
    یک رشته‌ی ریپلای در کانال باقی می‌ماند و همیشه مشخص است هر پیام مربوط به کدام سیگنال
    است. فقط وقتی سیگنال به‌طور نهایی بسته می‌شود (TP3 یا SL) رهگیری آن متوقف و امکان
    صدور سیگنال جدید (با رشته‌ی تازه) برای همان ارز، پس از کول‌داون، باز می‌شود.

    از همان channel_lock که send_signal_to_channel استفاده می‌کند بهره می‌برد تا این دو
    تابع هرگز هم‌زمان روی وضعیت کانال یک ارز کار نکنند (جلوگیری از race condition).
    """
    async with channel_lock:
        if signal_id not in channel_signal_messages:
            return
        rec = next((r for r in signal_history if r.get("signal_id") == signal_id), None)
        if not rec:
            return
        new_text = build_signal_update_text_from_record(rec)
        if not new_text:
            return
        reply_to_id = channel_signal_messages[signal_id]
        try:
            try:
                new_msg = await app.bot.send_message(
                    chat_id=CHANNEL_ID, text=rtl_lines(new_text), parse_mode="Markdown",
                    reply_to_message_id=reply_to_id,
                )
            except Exception as reply_err:
                logger.warning(f"Reply to previous channel message failed ({reply_err}); sending without reply.")
                new_msg = await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(new_text), parse_mode="Markdown")
            channel_signal_messages[signal_id] = new_msg.message_id
            key = rec["symbol"]
            if channel_message_map.get(key, {}).get("signal_id") == signal_id:
                channel_message_map[key]["message_id"] = new_msg.message_id
        except Exception as e:
            logger.error(f"Failed to send updated channel message for signal {signal_id}: {e}")
            return
        if rec["status"] in ("tp3_hit", "sl_hit"):
            last_channel_signal_close_time[rec["symbol"]] = time.time()
            key = rec["symbol"]
            if channel_message_map.get(key, {}).get("signal_id") == signal_id:
                del channel_message_map[key]
            channel_signal_messages.pop(signal_id, None)
        save_state()

async def send_high_importance_news_to_channel(news_text):
    """
    طبق درخواست: دیگر هیچ خبر/هشدار نهنگی به کانال ارسال نمی‌شود — کانال فقط برای
    سیگنال‌های معاملاتی است. اخبار همچنان در تاریخچه‌ی داخلی ربات («📰 اخبار و هشدارها»
    برای کاربران خصوصی، از طریق add_news_alert) ذخیره و قابل مشاهده می‌ماند؛ فقط ارسال
    آن به کانال تلگرام غیرفعال شد. برای فعال‌سازی دوباره در آینده، کافیست خط
    "return  # ..." زیر را حذف کنید.
    """
    return  # ارسال خبر/نهنگ به کانال عمداً غیرفعال شده — طبق درخواست کاربر
    if not CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(news_text), parse_mode="Markdown")
        logger.info("High importance news sent to channel")
    except Exception as e:
        logger.error(f"Failed to send news to channel: {e}")

# ---------- حلقه مستقل کانال (پویا) ----------
# نکته مهم (اصلاح‌شده): دیگر به‌ازای هر «حالت معاملاتی» (fast/semi_fast/standard/conservative)
# سیگنال جدا برای یک ارز تولید و ارسال نمی‌شود. برای هر ارز فقط یک تحلیل واحد (CHANNEL_SIGNAL_MODE)
# با آستانه‌های سخت‌گیرانه‌تر (CHANNEL_MIN_* ) بررسی می‌شود تا تعداد سیگنال‌ها کم و اعتبار آن‌ها بالا بماند.
async def channel_broadcast_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            if not CHANNEL_ID:
                await asyncio.sleep(60)
                continue

            now = time.time()
            last_time = last_mode_broadcast_time.get(CHANNEL_SIGNAL_MODE, 0)
            if now - last_time >= CHANNEL_CHECK_INTERVAL_SECONDS:
                logger.info("Channel broadcast cycle started (یک تحلیل واحد برای هر ارز)")
                await cache.update_prices(force=False)
                await cache.update_ohlcv(force=False)
                for code in cache.valid_codes:
                    try:
                        plan = await generate_trade_plan_v2(
                            code,
                            CHANNEL_SIGNAL_MODE,
                            send_to_channel=True,
                            min_confidence=CHANNEL_MIN_SIGNAL_CONFIDENCE,
                            min_gap=CHANNEL_MIN_DIRECTION_GAP,
                            min_confirmations_bonus=CHANNEL_MIN_CONFIRMATIONS_BONUS,
                            adx_min_override=CHANNEL_ADX_MIN,
                        )
                        if plan:
                            logger.info(f"Channel signal generated: {plan.symbol} {plan.direction} conf={plan.confidence:.0f}")
                    except Exception as e:
                        logger.debug(f"Error generating channel signal for {code}: {e}")
                    await asyncio.sleep(0.05)
                last_mode_broadcast_time[CHANNEL_SIGNAL_MODE] = now
                logger.info("Channel broadcast cycle completed")
        except Exception as e:
            logger.exception("Channel broadcast error: %s", e)
        await asyncio.sleep(60)

# ---------- حلقه پایش سیگنال‌های کانال (جایگزین trigger_scanner_loop قدیمی) ----------
# نسخه قبل این حلقه به‌جای «پایش» سیگنال‌های باز، برای هر نوسان کوچک قیمت (۰.۵٪) سیگنال
# تازه تولید می‌کرد که باعث سیل سیگنال و تناقض با حلقه اصلی کانال می‌شد؛ این باگ حذف شده.
# کار این حلقه اکنون فقط این است: با فاصله کوتاه، قیمت لحظه‌ای هر ارزی که یک سیگنال باز و
# فعال در کانال دارد را می‌خواند و در صورت برخورد به TP/SL پیام کانال را بروزرسانی می‌کند.
# این کار دیگر به «سیگنال‌های شخصی کاربران» (active_signals) وابسته نیست، بنابراین سیگنال‌های
# کانال حتی وقتی هیچ کاربری آن‌ها را شخصاً دنبال نکرده باشد هم به‌درستی بسته/بروزرسانی می‌شوند.
CHANNEL_MONITOR_INTERVAL_SECONDS = int(os.getenv("CHANNEL_MONITOR_INTERVAL_SECONDS", "90"))

# ---------- هشدار تغییر روند برای سیگنال‌های در حال سود (بعد از TP1/TP2) ----------
last_known_direction = {}

def check_trend_reversed(ind, original_direction):
    """
    بررسی محافظه‌کارانه‌ی «تغییر روند»: وقتی حداقل دو شاخص از سه شاخص اصلیِ روند
    (قیمت نسبت به EMA200)، مومنتوم (MACD Histogram) و جهت‌ حرکت (DI+/DI-) برخلاف جهت
    اولیه‌ی سیگنال شده باشند، تغییر روند تایید می‌شود.
    """
    price_above_ema200 = ind.get("price_above_ema200", True)
    macd_bullish = ind.get("macd_hist", 0) > 0
    di_bullish = ind.get("plus_di", 0) > ind.get("minus_di", 0)
    conditions = [
        not price_above_ema200 if original_direction == "LONG" else price_above_ema200,
        not macd_bullish if original_direction == "LONG" else macd_bullish,
        not di_bullish if original_direction == "LONG" else di_bullish,
    ]
    return sum(conditions) >= 2

def build_trend_reversal_text(rec):
    direction_fa = "لانگ 🟢" if rec["direction"] == "LONG" else "شورت 🔴"
    mode_label = MODE_CONFIGS.get(rec.get("mode"), MODE_CONFIGS["standard"])["label"]
    hit_label = "TP1" if rec["status"] == "tp1_hit" else "TP2"
    next_target = "TP2 و TP3" if rec["status"] == "tp1_hit" else "TP3"
    protect_hint = (
        "زیر سطح حمایت اخیر" if rec["direction"] == "LONG" else "بالای سطح مقاومت اخیر"
    )
    lines = [
        "🚨🔀🚨 *هشدار تغییر روند* 🚨🔀🚨",
        f"{rec['symbol']}/USDT | {direction_fa} | {mode_label}",
        DIVIDER,
        f"✅ این سیگنال قبلاً به {hit_label} رسیده، اما روند بازار در حال حاضر برخلاف جهت "
        f"اولیه‌ی این معامله برگشته است.",
        f"🎯 با این تغییر، احتمال رسیدن به {next_target} کاهش یافته است.",
        DIVIDER,
        "💡 *پیشنهاد:*",
        "• در صورت تمایل، بخشی یا کل سود فعلی را همین‌جا ذخیره کنید.",
        "• حد ضرر را نزدیک‌تر به قیمت فعلی بیاورید تا سود به‌دست‌آمده حفظ شود.",
        f"• اگر شکست واقعی {protect_hint} رخ داد، از ادامه‌ی این معامله صرف‌نظر کنید.",
        DIVIDER,
        f"🕒 {shamsi_now()}",
        "⚠️ این هشدار تکنیکال است، نه توصیه مالی؛ تصمیم نهایی با شماست.",
    ]
    return "\n".join(lines)

async def send_trend_reversal_warning(rec):
    """
    هشدار را به‌صورت ریپلای روی همان پیام سیگنال اصلی در کانال ارسال می‌کند (اگر پیام
    اصلی هنوز موجود باشد) تا برای اعضای کانال کاملاً مشخص باشد این هشدار مربوط به کدام
    سیگنال است. اگر ریپلای به هر دلیلی (مثلاً پیام اصلی حذف شده) شکست بخورد، پیام به‌طور
    عادی (بدون ریپلای) ارسال می‌شود تا هشدار در هر صورت به دست کاربران برسد.
    """
    if not CHANNEL_ID:
        return
    signal_id = rec.get("signal_id")
    original_message_id = channel_signal_messages.get(signal_id)
    symbol = rec.get("symbol")
    direction = rec.get("direction")
    if last_known_direction.get(symbol) == direction:
        rec["reversal_warned"] = True
        return
    text = build_trend_reversal_text(rec)
    try:
        try:
            await app.bot.send_message(
                chat_id=CHANNEL_ID,
                text=rtl_lines(text),
                parse_mode="Markdown",
                reply_to_message_id=original_message_id,
            )
        except Exception as reply_err:
            if original_message_id:
                logger.warning(f"Reply to original signal message failed ({reply_err}); sending without reply.")
                await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(text), parse_mode="Markdown")
            else:
                raise
        rec["reversal_warned"] = True
        last_known_direction[symbol] = direction
        save_state()
        logger.info(f"Trend reversal warning sent for {rec.get('symbol')} (signal_id {signal_id})")
    except Exception as e:
        logger.error(f"Failed to send trend reversal warning for {rec.get('symbol')}: {e}")

async def channel_signal_monitor_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            if not CHANNEL_ID or not channel_message_map:
                await asyncio.sleep(CHANNEL_MONITOR_INTERVAL_SECONDS)
                continue

            symbols_to_check = list(channel_message_map.keys())
            await cache.update_prices(force=True, codes=symbols_to_check)

            for code in symbols_to_check:
                current_price = cache.prices.get(code)
                if not current_price:
                    continue
                try:
                    entry = channel_message_map.get(code)
                    rec = next((r for r in signal_history if r.get("signal_id") == entry.get("signal_id")), None) if entry else None
                    rec_status_before_update = rec.get("status") if rec else None
                    rec_reversal_warned = bool(rec.get("reversal_warned")) if rec else False
                    changed = update_signal_status(code, current_price)
                    for sid in changed:
                        await update_channel_signal_message(sid)
                except Exception as e:
                    logger.debug(f"Error monitoring channel signal for {code}: {e}")

                # هشدار تغییر روند: مستقل از بروزرسانی وضعیت همین چرخه، برای سیگنال‌هایی که
                # هنوز به TP1/TP2 رسیده بودند بررسی می‌شود تا اگر هم‌زمان به TP3/SL رفتند،
                # هشدار از دست نرود.
                try:
                    if not rec or rec_status_before_update not in ("tp1_hit", "tp2_hit") or rec_reversal_warned:
                        continue
                    ind = await cache.get_indicators(code, rec.get("mode", "standard"))
                    if not ind:
                        continue
                    if check_trend_reversed(ind, rec["direction"]):
                        await send_trend_reversal_warning(rec)
                except Exception as e:
                    logger.debug(f"Error checking trend reversal for {code}: {e}")

        except Exception as e:
            logger.exception("Channel signal monitor error: %s", e)
        await asyncio.sleep(CHANNEL_MONITOR_INTERVAL_SECONDS)

# ---------- توابع آمار سیگنال‌ها ----------
def format_signal_history_page(filter_type: str, page: int = 0, per_page: int = 20, chat_id: int = None):
    if filter_type == "success":
        records = [r for r in signal_history if r["status"].startswith("tp")]
        title = "✅ *تاریخچه سیگنال‌های موفق*"
    else:
        records = [r for r in signal_history if r["status"] == "sl_hit"]
        title = "❌ *تاریخچه سیگنال‌های ناموفق*"

    records = sorted(records, key=lambda x: x["timestamp"], reverse=True)
    total = len(records)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_records = records[start:end]

    if not page_records:
        text = f"{title}\n\nهیچ سیگنالی ثبت نشده است."
    else:
        text = f"{title}\n{DIVIDER}\n"
        for rec in page_records:
            date_str = shamsi_date(datetime.fromtimestamp(rec["timestamp"]))
            symbol = rec["symbol"]
            direction = "لانگ 🟢" if rec["direction"] == "LONG" else "شورت 🔴"
            status = "TP1" if rec["status"] == "tp1_hit" else "TP2" if rec["status"] == "tp2_hit" else "TP3" if rec["status"] == "tp3_hit" else "SL"
            mode_label = MODE_CONFIGS.get(rec["mode"], MODE_CONFIGS["standard"])["label"]
            if rec["status"].startswith("tp"):
                if rec["status"] == "tp1_hit":
                    price_hit = rec["tp_prices"][0]
                elif rec["status"] == "tp2_hit":
                    price_hit = rec["tp_prices"][1]
                else:
                    price_hit = rec["tp_prices"][2]
                price_text = fmt_amount(price_hit, chat_id) if chat_id else format_channel_price(price_hit)
            else:
                price_text = fmt_amount(rec["sl_price"], chat_id) if chat_id else format_channel_price(rec["sl_price"])
            text += (
                f"{symbol} | {direction} | {mode_label}\n"
                f"   تاریخ: {date_str}\n"
                f"   وضعیت: {status} @ {price_text}\n"
                f"{DIVIDER}\n"
            )

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"stats_{filter_type}_page_{page-1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"stats_{filter_type}_page_{page+1}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="stats_history_menu")])
    keyboard = InlineKeyboardMarkup(rows)
    return text, keyboard

def format_coin_ranking(success: bool = True, top_n: int = 20):
    if success:
        records = [r for r in signal_history if r["status"].startswith("tp")]
        title = "🏆 *بیشترین ارزهای موفق*"
    else:
        records = [r for r in signal_history if r["status"] == "sl_hit"]
        title = "💔 *بیشترین ارزهای ناموفق*"

    counts = {}
    for rec in records:
        sym = rec["symbol"]
        counts[sym] = counts.get(sym, 0) + 1

    sorted_coins = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    if not sorted_coins:
        text = f"{title}\n\nهیچ داده‌ای موجود نیست."
    else:
        text = f"{title}\n{DIVIDER}\n"
        for i, (sym, cnt) in enumerate(sorted_coins, 1):
            text += f"{i}. {sym} — {cnt} سیگنال\n"
        text += f"{DIVIDER}\n"

    keyboard = InlineKeyboardMarkup([
        # اصلاح: قبلاً به‌جای منوی بلافصل قبلی (بیشترین ارزها) مستقیم به «آمار سیگنال‌ها»
        # می‌پرید و یک لایه از مسیر برگشت را حذف می‌کرد.
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stats_top_coins_menu")]
    ])
    return text, keyboard

# ---------- توابع منوهای آمار ----------
async def stats_menu(update, context):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    text = "📊 *آمار سیگنال‌ها*\n" + DIVIDER + "\n" + MENU_PROMPT
    rows = [
        [InlineKeyboardButton("🏆 بیشترین ارزها", callback_data="stats_top_coins_menu")],
        [InlineKeyboardButton("📋 آخرین سیگنال‌ها", callback_data="stats_recent_signals_menu")],
        [InlineKeyboardButton("📜 تاریخچه سیگنال‌ها", callback_data="stats_history_menu")],
    ]
    if is_admin_role(chat_id):
        rows.append([InlineKeyboardButton("🗑️ پاک کردن تاریخچه سیگنال‌ها", callback_data="clear_stats_step1")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")])
    keyboard = InlineKeyboardMarkup(rows)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

async def stats_top_coins_menu(update, context):
    query = update.callback_query
    await query.answer()
    text = "🏆 *بیشترین ارزها*\n" + DIVIDER + "\n" + MENU_PROMPT
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 ارزهای موفق", callback_data="stats_success_coins")],
        [InlineKeyboardButton("💔 ارزهای ناموفق", callback_data="stats_failed_coins")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stats_menu")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

async def stats_recent_signals_menu(update, context):
    query = update.callback_query
    await query.answer()
    text = "📋 *آخرین سیگنال‌ها*\n" + DIVIDER + "\n" + MENU_PROMPT
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ سیگنال‌های موفق", callback_data="stats_recent_success_page_0")],
        [InlineKeyboardButton("❌ سیگنال‌های ناموفق", callback_data="stats_recent_failed_page_0")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stats_menu")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

async def stats_history_menu(update, context):
    query = update.callback_query
    await query.answer()
    text = "📜 *تاریخچه سیگنال‌ها*\n" + DIVIDER + "\n" + MENU_PROMPT
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ سیگنال‌های موفق", callback_data="stats_success_page_0")],
        [InlineKeyboardButton("❌ سیگنال‌های ناموفق", callback_data="stats_failed_page_0")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stats_menu")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

async def stats_success_signals(update, context, page=0, recent=False):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    text, keyboard = format_signal_history_page("success", page, chat_id=chat_id)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(chat_id, [query.message.message_id])

async def stats_failed_signals(update, context, page=0, recent=False):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    text, keyboard = format_signal_history_page("failed", page, chat_id=chat_id)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(chat_id, [query.message.message_id])

async def stats_success_coins(update, context):
    query = update.callback_query
    await query.answer()
    text, keyboard = format_coin_ranking(success=True)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

async def stats_failed_coins(update, context):
    query = update.callback_query
    await query.answer()
    text, keyboard = format_coin_ranking(success=False)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    set_interactive_screen(query.message.chat_id, [query.message.message_id])

# ---------- پاک کردن داده‌های ذخیره‌شده (با تایید دو مرحله‌ای) ----------
def kb_clear_confirm(step, target):
    """
    کیبورد تایید دو مرحله‌ای برای پاک‌سازی داده. target: "stats" (تاریخچه سیگنال‌ها) یا
    "opt" (تاریخچه پیشنهادات مرکز هوشمندسازی). هر مرحله باید صریحاً تایید شود؛ در هر
    مرحله «انصراف» کاربر را بدون هیچ تغییری به همان منوی مبدأ برمی‌گرداند.
    """
    if target == "stats":
        cancel_cb = "stats_menu"
    else:
        cancel_cb = "optimization_center"
    yes_cb = f"clear_{target}_step2" if step == 1 else f"clear_{target}_confirmed"
    yes_label = "✅ بله، ادامه بده" if step == 1 else "🗑️ بله، برای همیشه پاک کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(yes_label, callback_data=yes_cb)],
        [InlineKeyboardButton("❌ انصراف", callback_data=cancel_cb)],
    ])

async def handle_clear_stats_step1(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    closed_count = len([r for r in signal_history if r.get("status") in CLOSED_STATUSES])
    text = (
        "⚠️ *پاک کردن تاریخچه سیگنال‌ها — مرحله ۱ از ۲*\n" + DIVIDER + "\n\n"
        f"این کار {closed_count} رکورد سیگنال بسته‌شده (TP/SL/نامعتبر) را برای همیشه حذف "
        "می‌کند. آمار نرخ برد، رتبه‌بندی ارزها و تاریخچه از صفر شروع می‌شوند.\n"
        "ℹ️ سیگنال‌هایی که *همین الان باز و در حال پیگیری* هستند حذف نمی‌شوند.\n\n"
        "آیا مطمئن هستید؟"
    )
    await query.edit_message_text(text, reply_markup=kb_clear_confirm(1, "stats"), parse_mode="Markdown")

async def handle_clear_stats_step2(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    text = (
        "🚨 *تایید نهایی*\n" + DIVIDER + "\n\n"
        "این عملیات *غیرقابل بازگشت* است. پیش از حذف، یک نسخه‌ی پشتیبان تازه از وضعیت "
        "فعلی ذخیره می‌شود (پوشه‌ی backups/ روی سرور)، اما بازیابی آن نیاز به دسترسی "
        "دستی به فایل‌های سرور دارد — از داخل ربات قابل بازگردانی نیست.\n\n"
        "برای پاک کردن نهایی روی دکمه‌ی زیر بزنید."
    )
    await query.edit_message_text(text, reply_markup=kb_clear_confirm(2, "stats"), parse_mode="Markdown")

async def handle_clear_stats_confirmed(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    global signal_history, TOTAL_SIGNALS_GENERATED
    save_state()  # یک نسخه پشتیبان تازه از وضعیت فعلی (درست قبل از حذف) در backups/ ثبت شود
    before = len(signal_history)
    signal_history = [r for r in signal_history if r.get("status") not in CLOSED_STATUSES]
    removed = before - len(signal_history)
    TOTAL_SIGNALS_GENERATED = 0
    save_state()
    text = (
        f"✅ *انجام شد.*\n\n{removed} رکورد سیگنال بسته‌شده پاک شد.\n"
        f"سیگنال‌های باز فعلی (در صورت وجود) دست‌نخورده باقی ماندند.\n\n"
        f"💾 یک نسخه‌ی پشتیبان از وضعیت قبل از حذف در backups/ ذخیره شد."
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="stats_menu")]]),
        parse_mode="Markdown"
    )

async def handle_clear_opt_step1(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    count = len(suggestion_history)
    text = (
        "⚠️ *پاک کردن داده‌های بهینه‌سازی — مرحله ۱ از ۲*\n" + DIVIDER + "\n\n"
        f"این کار تاریخچه‌ی {count} پیشنهاد بهینه‌سازی گذشته را برای همیشه حذف می‌کند.\n"
        "ℹ️ تنظیمات فعلی حالت‌های معاملاتی تغییر نمی‌کند؛ فقط سابقه‌ی پیشنهادها پاک "
        "می‌شود.\n\n"
        "آیا مطمئن هستید؟"
    )
    await query.edit_message_text(text, reply_markup=kb_clear_confirm(1, "opt"), parse_mode="Markdown")

async def handle_clear_opt_step2(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    text = (
        "🚨 *تایید نهایی*\n" + DIVIDER + "\n\n"
        "این عملیات *غیرقابل بازگشت* است. پیش از حذف، یک نسخه‌ی پشتیبان تازه از وضعیت "
        "فعلی ذخیره می‌شود (پوشه‌ی backups/ روی سرور)، اما بازیابی آن نیاز به دسترسی "
        "دستی به فایل‌های سرور دارد.\n\n"
        "برای پاک کردن نهایی روی دکمه‌ی زیر بزنید."
    )
    await query.edit_message_text(text, reply_markup=kb_clear_confirm(2, "opt"), parse_mode="Markdown")

async def handle_clear_opt_confirmed(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    global suggestion_history
    save_state()
    removed = len(suggestion_history)
    suggestion_history = []
    save_state()
    text = (
        f"✅ *انجام شد.*\n\n{removed} رکورد پیشنهاد بهینه‌سازی پاک شد.\n\n"
        f"💾 یک نسخه‌ی پشتیبان از وضعیت قبل از حذف در backups/ ذخیره شد."
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="optimization_center")]]),
        parse_mode="Markdown"
    )

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
    """
    اصلاح: قبلاً این صفحه فقط پیشنهادهایی با status == "pending" را نشان می‌داد؛
    یعنی به‌محض اینکه ادمین روی پیام مستقیم (در چت خصوصی) دکمه‌ی تایید/رد را می‌زد،
    آن پیشنهاد از این صفحه ناپدید می‌شد و اطلاعات کمی نشان داده می‌شد. اکنون این صفحه
    همیشه *آخرین* پیشنهاد را نشان می‌دهد — صرف‌نظر از اینکه روی پیام اصلی چه اتفاقی
    افتاده (اعمال/رد/بدون پاسخ) — با جزئیات کامل، و دکمه‌های اعمال/رد در همین‌جا هم
    همیشه فعال هستند تا تصمیم قابل تغییر باشد.
    """
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    last_sug = suggestion_history[-1] if suggestion_history else None
    if not last_sug:
        total_closed = len([s for s in signal_history if s["status"] in ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit"]])
        text = (
            "📋 *پیشنهادات فعال*\n\n"
            f"📊 *وضعیت جمع‌آوری داده*\n"
            f"{DIVIDER}\n"
            f"• تعداد سیگنال‌های بسته‌شده: {total_closed}\n"
            f"• حداقل نیاز برای تحلیل: ۱۰\n\n"
            f"⏳ در حال جمع‌آوری داده‌های کافی برای ارائه پیشنهادات هوشمند...\n\n"
            f"💡 *نکته:* پس از بسته شدن حداقل ۱۰ سیگنال (TP یا SL)، اولین پیشنهادات در اینجا نمایش داده می‌شوند."
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
        return

    status_fa = {
        "pending": "⏳ در انتظار پاسخ",
        "applied": "✅ اعمال شده",
        "rejected": "❌ رد شده",
        "expired": "⌛ منقضی‌شده (بدون پاسخ)",
    }.get(last_sug["status"], last_sug["status"])

    text = "📋 *آخرین پیشنهاد بهینه‌سازی*\n"
    text += f"📅 تاریخ: {shamsi_date(datetime.fromtimestamp(last_sug['timestamp']))}\n"
    text += f"📌 وضعیت فعلی: {status_fa}\n"
    if last_sug.get("applied_at"):
        text += f"   اعمال‌شده در: {shamsi_date(datetime.fromtimestamp(last_sug['applied_at']))}\n"
    if last_sug.get("rejected_at"):
        text += f"   رد‌شده در: {shamsi_date(datetime.fromtimestamp(last_sug['rejected_at']))}\n"
    text += f"{DIVIDER}\n"
    text += build_suggestion_detail_text(last_sug)
    text += (
        f"\n{DIVIDER}\n"
        f"💡 می‌توانید صرف‌نظر از وضعیت فعلی، دوباره اعمال یا رد کنید — تصمیم همیشه "
        f"قابل تغییر است (رد کردن یعنی بازگشت پارامترها به مقدار قبل از این پیشنهاد)."
    )
    await query.edit_message_text(
        text,
        reply_markup=kb_suggestion_actions(last_sug["id"]),
        parse_mode="Markdown"
    )

def kb_optimization_history_nav(page, total_pages):
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"opt_history_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"opt_history_page_{page + 1}"))
    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="optimization_center")])
    return InlineKeyboardMarkup(rows)

_OPT_HISTORY_PARAM_FA = {
    "min_rr": "حداقل نسبت ریسک به بازده",
    "adx_min": "حداقل ADX",
    "min_confirmations": "حداقل لایه‌های تاییدی",
}
_OPT_HISTORY_STATUS_FA = {
    "pending": "⏳ در انتظار پاسخ",
    "applied": "✅ اعمال شده",
    "rejected": "❌ رد شده",
    "expired": "⌛ منقضی‌شده",
}
_OPT_HISTORY_STATUS_EMOJI = {"applied": "✅", "rejected": "❌", "pending": "⏳", "expired": "⌛"}

async def optimization_history(update, context, page: int = 0):
    """
    اصلاح طبق درخواست: قبلاً فقط ۱۰ مورد آخر و فقط یک خلاصه‌ی یک‌خطی («N پیشنهاد») نمایش
    داده می‌شد. الان تا ۲۰ پیشنهاد آخر نمایش داده می‌شود و برای هر مورد، اطلاعات کامل
    پیشنهادی (حالت معاملاتی، پارامتر، مقدار قبل ← بعد و دلیل) هم نشان داده می‌شود؛ برای
    این‌که پیام خیلی طولانی نشود، صفحه‌بندی (۴ مورد در هر صفحه) اضافه شده است.
    """
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    if not suggestion_history:
        text = (
            "📜 *تاریخچه پیشنهادات*\n\n"
            "هیچ پیشنهادی ثبت نشده است.\n"
            "پس از جمع‌آوری داده‌های کافی، اولین پیشنهادات در اینجا نمایش داده می‌شوند."
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
        return

    recent = list(reversed(suggestion_history[-20:]))  # جدیدترین اول، حداکثر ۲۰ پیشنهاد آخر
    per_page = 4
    total_pages = max(1, (len(recent) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_items = recent[start:start + per_page]

    text = f"📜 *تاریخچه پیشنهادات* — {len(recent)} مورد آخر (صفحه {page + 1}/{total_pages})\n"
    text += f"{DIVIDER}\n\n"
    for sug in page_items:
        status_emoji = _OPT_HISTORY_STATUS_EMOJI.get(sug["status"], "❓")
        status_fa = _OPT_HISTORY_STATUS_FA.get(sug["status"], sug["status"])
        date_str = shamsi_date(datetime.fromtimestamp(sug["timestamp"]))
        a = sug.get("analysis", {})
        text += f"{status_emoji} *{date_str}* — {status_fa}\n"
        text += f"   📊 {a.get('total_signals', 0)} سیگنال بسته‌شده | نرخ برد: {a.get('win_rate', 0):.1f}%\n"
        if not sug["suggestions"]:
            text += "   موردی برای پیشنهاد یافت نشد.\n"
        for s in sug["suggestions"]:
            if s["parameter"] == "mode":
                text += f"   ℹ️ {s['reason']}\n"
                continue
            p_fa = _OPT_HISTORY_PARAM_FA.get(s["parameter"], s["parameter"])
            mode_label = MODE_CONFIGS.get(s["mode"], {}).get("label", s["mode"])
            text += f"   • {mode_label} — {p_fa}: {s['current']} ← {s['suggested']}\n"
            text += f"     📌 {s['reason']}\n"
        if sug["status"] == "applied" and "result" in sug:
            text += f"   📌 {sug['result']}\n"
        elif sug["status"] == "rejected":
            text += "   📌 تنظیمات قبلی حفظ شد\n"
        elif sug["status"] == "expired":
            text += "   📌 عدم پاسخ تا ۲۴ ساعت\n"
        text += f"\n{DIVIDER}\n\n"

    await query.edit_message_text(
        text,
        reply_markup=kb_optimization_history_nav(page, total_pages),
        parse_mode="Markdown"
    )

# ---------- دکمه تحلیل جامع ----------
async def comprehensive_analysis(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    await query.edit_message_text("⏳ در حال تحلیل همه ارزها...")
    try:
        await cache.update_prices(force=True)
        await cache.update_ohlcv(force=True)
        active_signals_list = []
        mode = "standard"
        for code in COIN_CODES:
            try:
                ind = await cache.get_indicators(code, mode)
                if not ind:
                    continue
                plan = await generate_trade_plan_v2(code, mode)
                if plan and plan.confidence >= MIN_SIGNAL_CONFIDENCE:
                    active_signals_list.append({
                        "code": code,
                        "direction": plan.direction,
                        "confidence": plan.confidence,
                        "rr": plan.rr,
                        "mode": plan.mode,
                        "entry": plan.entry_price,
                        "sl": plan.sl_price,
                        "tp1": plan.take_profits[0] if plan.take_profits else 0,
                    })
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(f"Comprehensive analysis error for {code}: {e}")
                continue
        if not active_signals_list:
            await query.edit_message_text(
                "📊 *تحلیل جامع ارزها*\n"
                f"{DIVIDER}\n"
                "💤 هیچ سیگنال فعالی یافت نشد.\n\n"
                "دلایل احتمالی:\n"
                "• ADX پایین (بازار رنج)\n"
                "• تعداد لایه‌های تأییدشده کمتر از حد نیاز\n"
                "• نسبت ریسک به بازده پایین",
                reply_markup=kb_back_to_admin_panel(),
                parse_mode="Markdown"
            )
            return
        text = "📊 *تحلیل جامع ارزها*\n"
        text += f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        long_count = 0
        short_count = 0
        for signal in active_signals_list:
            direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
            direction_text = "لانگ" if signal["direction"] == "LONG" else "شورت"
            mode_label = MODE_CONFIGS.get(signal["mode"], MODE_CONFIGS["standard"])["label"]
            if signal["direction"] == "LONG":
                long_count += 1
            else:
                short_count += 1
            text += (
                f"{direction_emoji} {signal['code']} | {direction_text}\n"
                f"   اطمینان: {signal['confidence']:.0f}% | RR: {signal['rr']:.2f} | {mode_label}\n"
                f"   📥 ورود: {fmt_amount(signal['entry'], chat_id)}\n"
                f"   🛑 حد ضرر: {fmt_amount(signal['sl'], chat_id)}\n"
                f"   🎯 TP1: {fmt_amount(signal['tp1'], chat_id)}\n"
                f"{DIVIDER}\n"
            )
        text += f"📊 جمع‌بندی: {len(active_signals_list)} سیگنال فعال\n"
        text += f"🟢 لانگ: {long_count} | 🔴 شورت: {short_count}"
        chunks = split_long_message(text)
        await query.edit_message_text(chunks[0], reply_markup=kb_back_to_admin_panel(), parse_mode="Markdown")
        for chunk in chunks[1:]:
            # همون باگ «چانک بعدی دکمه‌ی بازگشت نداره» این‌جا هم بود؛ اصلاح شد.
            await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=kb_back_to_admin_panel(), parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Comprehensive analysis error: {e}")
        await query.edit_message_text(f"❌ خطا در تحلیل جامع:\n{str(e)}", reply_markup=kb_back_to_admin_panel())

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
        [InlineKeyboardButton("🗑️ پاک کردن داده‌های بهینه‌سازی", callback_data="clear_opt_step1")],
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

    rows.append([InlineKeyboardButton("📡 دریافت سیگنال‌های فعال", callback_data="active_signals_all")])
    rows.append([InlineKeyboardButton("📊 آمار سیگنال‌ها", callback_data="stats_menu")])
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
    if step == 0:
        return rtl_lines(
            "📖 *شروع کار با ربات*\n"
            f"{DIVIDER}\n"
            "این ربات با تحلیل ۲۰ لایه‌ای، سیگنال‌های معاملاتی فیوچرز تولید می‌کند.\n"
            "پس از شروع، ابتدا واحد پولی را انتخاب کنید.\n"
            "سپس سبک معاملاتی خود را از چهار حالت انتخاب کنید.\n"
            "در نهایت منوی اصلی نمایش داده می‌شود."
        )
    elif step == 1:
        return rtl_lines(
            "💰 *قیمت‌های لحظه‌ای*\n"
            f"{DIVIDER}\n"
            "قیمت‌ها از سه منبع دریافت می‌شوند:\n"
            "🅶 Gate.io (منبع اصلی)\n"
            "🅺 کوکوین اسپات (پشتیبان اول)\n"
            "🅲 CoinGecko (پشتیبان نهایی)\n"
            "در صورت عدم دسترسی به منبع اصلی، به‌طور خودکار از پشتیبان استفاده می‌شود."
        )
    elif step == 2:
        return rtl_lines(
            "🪙 *ارزها و علاقه‌مندی‌ها*\n"
            f"{DIVIDER}\n"
            "از منوی «انتخاب ارز» می‌توانید وارد صفحه هر ارز شوید.\n"
            "در آن‌جا می‌توانید ارز را به علاقه‌مندی‌ها اضافه یا حذف کنید.\n"
            "علاقه‌مندی‌ها برای دریافت خودکار سیگنال استفاده می‌شوند."
        )
    elif step == 3:
        return rtl_lines(
            "📊 *تحلیل‌ها و سیگنال‌ها (۲۰ لایه)*\n"
            f"{DIVIDER}\n"
            "سیگنال‌ها بر اساس ۲۰ لایه تحلیل تولید می‌شوند:\n"
            "۱. ساختار بازار | ۲. هم‌گرایی تایم‌فریم | ۳. مومنتوم\n"
            "۴. حجم معاملات | ۵. احساسات بازار (جایگزین فاندینگ)\n"
            "۶. روند | ۷. جریان سفارشات | ۸. تنوع بازار\n"
            "۹. نوسان‌پذیری هوشمند | ۱۰. قدرت روند مکمل\n"
            "حداقل ۴ تا ۷ لایه (بسته به حالت) باید تأیید شوند.\n"
            "ضریب اطمینان = امتیاز وزنی لایه‌های تأییدشده.\n"
            "نرخ موفقیت تخمینی = درصد موفقیت سیگنال‌های گذشته.\n"
            "نسبت ریسک به بازده = نسبت سود بالقوه به ضرر احتمالی.\n"
            "اهرم پویا = بر اساس قدرت سیگنال و حالت معاملاتی.\n"
            "در بازار راکد (ADX پایین)، سیگنال صادر نمی‌شود."
        )
    elif step == 4:
        return rtl_lines(
            "📈 *داشبورد و گزارش‌ها*\n"
            f"{DIVIDER}\n"
            "داشبورد تحلیلی: نرخ برد، فاکتور سود، Expectancy، Max Drawdown، Sharpe، Risk of Ruin\n"
            "گزارش دوره‌ای: هفتگی/ماهانه"
        )
    elif step == 5:
        return rtl_lines(
            "💡 *اصطلاحات جدید*\n"
            f"{DIVIDER}\n"
            "ساختار بازار: شکست مقاومت یا برگشت از حمایت\n"
            "هم‌گرایی تایم‌فریم: همراستایی حداقل ۲ تایم‌فریم\n"
            "احساسات بازار: ترکیبی از تغییر قیمت، حجم و ترس و طمع\n"
            "جریان سفارشات: نسبت سفارشات خرید به فروش\n"
            "تنوع بازار: درصد ارزهای بالای EMA۲۰\n"
            "نوسان‌پذیری هوشمند: موقعیت قیمت در باند بولینگر\n"
            "قدرت روند مکمل: اختلاف +DI و -DI\n"
            "رژیم بازار: رونددار (ADX بالا) یا رنج (ADX پایین)\n"
            "اهرم پویا: اهرم پیشنهادی بر اساس قدرت سیگنال"
        )
    elif step == 6:
        return rtl_lines(
            "📰 *اخبار و هشدارها*\n"
            f"{DIVIDER}\n"
            "اخبار نهنگ‌ها با ایموجی متحرک ارسال می‌شوند.\n"
            "پیام‌های خبری بعد از ۱ ساعت به‌طور خودکار حذف می‌شوند.\n"
            "تاریخچه اخبار در منوی «اخبار و هشدارها» قابل مشاهده است."
        )
    else:
        return rtl_lines(
            "❓ *پرسش‌های متداول*\n"
            f"{DIVIDER}\n"
            "چطور سیگنال بگیرم؟ → انتخاب ارز → پیشنهاد لحظه‌ای\n"
            "ارسال خودکار چگونه است؟ → فقط برای ارزهای مورد علاقه، رویدادمحور\n"
            "چطور ربات را متوقف کنم؟ → دکمه توقف ربات\n"
            "آیا سیگنال‌ها تضمین سود هستند؟ → خیر، تحلیل تکنیکال است"
        )

def welcome_text():
    return rtl_lines(
        "🌟✨ *به سیگنال‌یار حرفه‌ای خوش آمدید!* ✨🌟\n"
        f"{DIVIDER}\n"
        "🤖 *ربات معاملاتی هوشمند* با تحلیل ۲۰ لایه‌ای\n"
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
        BotCommand("news", "اخبار و رویدادهای پیش رو"),
        BotCommand("report", "گزارش دوره‌ای"),
        BotCommand("stop", "توقف ربات"),
    ] if is_admin(user_id) else [BotCommand("menu", "منوی اصلی")]
    await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    await clear_interactive_screen(context, chat_id)
    msg = await context.bot.send_message(chat_id=chat_id, text=welcome_text(), reply_markup=kb_main(user_id), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

# ---------- Trailing monitor ----------
async def trailing_monitor_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            if active_signals:
                for chat_id, signals in list(active_signals.items()):
                    for code, data in list(signals.items()):
                        plan = data["plan"]; stage = data["stage"]
                        try:
                            source = cache.source_for_code(code)
                            if source == "gateio":
                                ticker = await asyncio.to_thread(exchange_gateio.fetch_ticker, cache.symbol_for_code(code))
                            elif source == "kucoin":
                                ticker = await asyncio.to_thread(exchange_spot_kucoin.fetch_ticker, cache.symbol_for_code(code))
                            else:
                                current = cache.prices.get(code, 0)
                                if current > 0:
                                    changed = update_signal_status(code, current)
                                    for sid in changed:
                                        await update_channel_signal_message(sid)
                                continue
                            current = float(ticker.get("last") or ticker.get("close") or 0)
                        except Exception as e:
                            logger.debug("Trailing price fetch failed | code=%s | error=%s", code, e)
                            continue
                        if current <= 0: continue
                        changed = update_signal_status(code, current)
                        for sid in changed:
                            await update_channel_signal_message(sid)
                        tp1, tp2, tp3 = plan.take_profits[0], plan.take_profits[1], plan.take_profits[2]
                        if plan.direction == "LONG":
                            hit_tp1, hit_tp2, hit_tp3 = current >= tp1, current >= tp2, current >= tp3
                        else:
                            hit_tp1, hit_tp2, hit_tp3 = current <= tp1, current <= tp2, current <= tp3
                        new_stage = stage
                        if hit_tp3 and stage < 3: new_stage = 3
                        elif hit_tp2 and stage < 2: new_stage = 2
                        elif hit_tp1 and stage < 1: new_stage = 1
                        if new_stage > stage:
                            if new_stage == 1: new_sl = plan.entries[0]
                            elif new_stage == 2: new_sl = tp1
                            else: new_sl = tp2
                            data["stage"] = new_stage; data["last_notified"] = new_stage
                            text = (
                                f"🔔 بروزرسانی حد ضرر | {code}/USDT\n"
                                f"🕒 {shamsi_now()}\n{DIVIDER}\n"
                                f"✅ قیمت به TP{new_stage} رسید.\n"
                                f"🛑 حد ضرر به {fmt_amount(new_sl, chat_id)} منتقل شد.\n{DIVIDER}\n"
                                f"⚠️ این یک اطلاع‌رسانی خودکار است."
                            )
                            try:
                                await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                            except Exception as e:
                                logger.warning("Trailing notify failed | chat_id=%s | code=%s | error=%s", chat_id, code, e)
        except Exception as e:
            logger.exception("Trailing loop error | error=%s", e)
        await asyncio.sleep(TRAILING_CHECK_SECONDS)

# ---------- Event/News monitor ----------
async def news_monitor_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            # اصلاح باگ: قبلاً کل این حلقه (از جمله ارسال به کانال) فقط وقتی اجرا
            # می‌شد که حداقل یک subscribed_chat_id وجود داشت. ارسال به کانال هیچ
            # ربطی به وجود یا عدم وجود کاربر خصوصی نداره؛ این شرط حذف شد.
            important_news = await fetch_important_news()
            for news in important_news:
                news_url = news.get("url", "")
                details = {"source": news.get("source", "")}
                if isinstance(news_url, str) and news_url.strip().startswith("http"):
                    details["url"] = news_url.strip()
                add_news_alert(news["text"], importance="high", impact=news["impact"], details=details)
                if news.get("importance") == "high":
                    await send_high_importance_news_to_channel(news["text"])
            await check_and_notify_events(app)
        except Exception as e:
            logger.exception("News monitor error: %s", e)
        await asyncio.sleep(EVENTS_CHECK_SECONDS)

async def check_and_notify_events(app):
    events = await get_upcoming_events(force=True)
    now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    upcoming = []
    for ev in events:
        event_time = ev["time"]
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=TEHRAN_TZ)
        delta = event_time - now_utc
        if timedelta(0) <= delta <= timedelta(hours=24):
            upcoming.append(ev)
    if upcoming:
        for chat_id in subscribed_chat_ids:
            text = "📅 *رویدادهای مهم کریپتو در ۲۴ ساعت آینده:*\n" + DIVIDER + "\n"
            for ev in upcoming[:5]:
                importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} *{ev['name']}*\n"
                text += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
                if ev.get("description"):
                    text += f"📝 {ev['description'][:100]}...\n"
                if ev.get("impact"):
                    text += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
                text += "\n"
            try:
                msg = await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                asyncio.create_task(delete_news_messages_after_delay(app, chat_id, msg.message_id))
            except Exception as e:
                logger.warning("Event notify failed: %s", e)

# ---------- Whale monitor ----------
async def whale_monitor_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            # اصلاح باگ: قبلاً این حلقه فقط وقتی حداقل یک کاربر شخصی subscribe کرده بود
            # اجرا می‌شد، در حالی که ارسال هشدار به کانال هیچ ربطی به تعداد کاربران خصوصی
            # نداره. حالا مستقل از subscribed_chat_ids اجرا می‌شه.
            alerts = fetch_whale_alerts()
            if alerts:
                for alert in alerts[:5]:
                    impact = alert["impact"]
                    # اصلاح باگ: قبلاً فقط هشدارهایی که impact دقیقاً شامل «نزولی» یا
                    # «صعودی» بود رد می‌شدن؛ اما حالت رایگان (بدون کلید Whale Alert)
                    # هیچ‌وقت این کلمه‌ها رو تولید نمی‌کرد، پس تمام هشدارهای رایگان
                    # همیشه فیلتر و حذف می‌شدن. الان هر هشدار «قابل‌بررسی» (بزرگ) هم
                    # قبول می‌شه، نه فقط اون‌هایی که جهت دقیقشون مشخصه.
                    if not ("نزولی" in impact or "صعودی" in impact or "بررسی" in impact):
                        continue
                    amount = alert.get("amount_btc", alert.get("amount"))
                    symbol = alert.get("symbol", "")
                    flow = alert.get("flow_type", alert.get("flow"))
                    value_usd = alert.get("value_usd")
                    whale_emoji = "🐋" if isinstance(amount, (int, float)) and amount > 2000 else "🐳"

                    def _valid(v):
                        if v is None or (isinstance(v, str) and not v.strip()):
                            return False
                        if isinstance(v, (int, float)) and v == 0:
                            return False
                        return str(v).strip().lower() not in {"unknown", "n/a", "none", "ناشناس", "نامشخص"}

                    lines = [f"{whale_emoji} *حرکت نهنگ بزرگ*"]
                    if _valid(amount) and _valid(symbol):
                        lines.append(f"💰 مقدار: **{amount:,.0f} {symbol}**")
                    if _valid(value_usd):
                        lines.append(f"💵 ارزش تقریبی: ~{value_usd:,.0f} دلار")
                    if _valid(symbol):
                        lines.append(f"🔗 شبکه: {symbol}")
                    from_addr = alert.get("from_address", "")
                    to_addr = alert.get("to_address", "")
                    from_owner = alert.get("from_owner", "")
                    to_owner = alert.get("to_owner", "")
                    if _valid(from_addr):
                        lines.append(f"📌 از آدرس: `{escape_markdown(from_addr)}`")
                    if _valid(to_addr):
                        lines.append(f"📌 به آدرس: `{escape_markdown(to_addr)}`")
                    if _valid(from_owner):
                        lines.append(f"🏷️ برچسب مبدأ: {escape_markdown(from_owner)}")
                    if _valid(to_owner):
                        lines.append(f"🏷️ برچسب مقصد: {escape_markdown(to_owner)}")
                    if _valid(flow):
                        lines.append(f"📊 نوع تراکنش: {flow}")
                    if _valid(impact):
                        lines.append(f"📈 تأثیر احتمالی: {impact}")
                    lines.append(f"🕒 {shamsi_now()}")
                    text = "\n".join(lines)
                    add_news_alert(text, importance="high", impact=impact, details=alert)
                    # اصلاح باگ: قبلاً فقط آخرین آیتم news_history به کانال ارسال می‌شد،
                    # یعنی اگه در یک دور چند هشدار جدید اضافه می‌شد، بقیه هیچ‌وقت به
                    # کانال نمی‌رسیدن. الان هر هشدار واجد شرایط جداگانه ارسال می‌شه.
                    await send_high_importance_news_to_channel(text)
        except Exception as e:
            logger.exception("Whale monitor error: %s", e)
        await asyncio.sleep(WHALE_CHECK_SECONDS)

# ---------- Macro event monitor ----------
async def fetch_macro_events():
    return []

async def macro_event_monitor_loop(app):
    await asyncio.sleep(120)
    while True:
        try:
            if subscribed_chat_ids:
                events = await fetch_macro_events()
                for ev in events:
                    text = (
                        f"📰 *رویداد کلان اقتصادی*\n"
                        f"{ev.get('title', 'رویداد')}\n"
                        f"🕒 {shamsi_now()}\n"
                        f"📊 سطح اهمیت: {ev.get('importance', 'medium')}\n"
                        f"📈 تأثیر مورد انتظار: {ev.get('impact', 'نامشخص')}\n"
                        f"📝 {ev.get('description', '')[:200]}"
                    )
                    add_news_alert(text, importance=ev.get('importance', 'medium'), impact=ev.get('impact', ''))
                    for chat_id in subscribed_chat_ids:
                        msg = await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                        asyncio.create_task(delete_news_messages_after_delay(app, chat_id, msg.message_id))
        except Exception as e:
            logger.exception("Macro event monitor error: %s", e)
        await asyncio.sleep(6 * 3600)

# ---------- Macro data loop ----------
async def macro_data_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            await cache.update_macro_data()
        except Exception as e:
            logger.exception(f"Macro data loop error: {e}")
        await asyncio.sleep(MACRO_CHECK_SECONDS)

# ---------- Periodic report ----------
async def send_periodic_report(app, period="weekly"):
    stats = compute_advanced_stats(signal_history)
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📊 *گزارش { 'هفتگی' if period == 'weekly' else 'ماهانه' }*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"🔢 تعداد کل سیگنال‌ها: {stats['total_trades']}\n"
        f"✅ نرخ برد: {stats['win_rate']:.1f}%\n"
        f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
        f"📈 میانگین سود هر معامله (Expectancy): {stats['expectancy']:.2f} USDT\n"
        f"📉 بیشترین افت سرمایه (Max Drawdown): {stats['max_drawdown']:.2f} USDT\n"
        f"📊 نسبت شارپ: {stats['sharpe']:.2f}\n"
        f"⚠️ ریسک ورشکستگی: {stats['risk_of_ruin']:.1f}%\n"
        f"🎯 میانگین اطمینان سیگنال‌ها: {stats['avg_confidence']:.1f}%\n"
    )
    if fg_value is not None:
        text += f"🧭 شاخص ترس و طمع: {fg_value} ({fg_class if fg_class else '-'})\n"
    if macro_data:
        text += f"\n📊 *داده‌های کلان بازار:*\n"
        text += f"• سلطه بیت‌کوین: {macro_data.get('btc_dominance', 0):.1f}%\n"
    for chat_id in subscribed_chat_ids:
        try:
            await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
        except Exception as e:
            logger.warning("Periodic report send failed: %s", e)

# ---------- Advanced Reporting ----------
def compute_advanced_stats(signal_history, mode=None):
    filtered = [r for r in signal_history if mode is None or r.get("mode") == mode]
    if not filtered:
        return {
            "sharpe": 0, "max_drawdown": 0, "expectancy": 0,
            "risk_of_ruin": 0, "total_trades": 0, "win_rate": 0,
            "profit_factor": 0, "avg_confidence": 0,
            "wins": 0, "losses": 0
        }
    returns = []
    wins = 0
    losses = 0
    for rec in filtered:
        if rec["status"] == "tp3_hit":
            returns.append(3 * (rec["tp_prices"][2] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "tp2_hit":
            returns.append(2 * (rec["tp_prices"][1] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "tp1_hit":
            returns.append(1 * (rec["tp_prices"][0] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "sl_hit":
            returns.append(rec["entry_price"] - rec["sl_price"])
            losses += 1
    if not returns:
        return {
            "sharpe": 0, "max_drawdown": 0, "expectancy": 0,
            "risk_of_ruin": 0, "total_trades": 0, "win_rate": 0,
            "profit_factor": 0, "avg_confidence": 0,
            "wins": 0, "losses": 0
        }
    returns = np.array(returns)
    win_rate = wins / len(returns) * 100
    avg_return = np.mean(returns)
    std_return = np.std(returns) if len(returns) > 1 else 1e-9
    sharpe = (avg_return / std_return) * np.sqrt(365) if std_return != 0 else 0
    cumulative = np.cumsum(returns)
    max_dd = 0
    peak = cumulative[0]
    for val in cumulative:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    expectancy = avg_return
    risk_of_ruin = (1 - (wins / len(returns))) ** 10 * 100
    profit_factor = (sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r <= 0))) if losses else 999
    avg_confidence = np.mean([rec["confidence"] for rec in filtered]) if filtered else 0
    return {
        "sharpe": sharpe, "max_drawdown": max_dd, "expectancy": expectancy,
        "risk_of_ruin": risk_of_ruin, "total_trades": len(returns),
        "win_rate": win_rate, "profit_factor": profit_factor,
        "avg_confidence": avg_confidence, "wins": wins, "losses": losses,
    }

# ---------- Auto report loop ----------
async def auto_report_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if subscribed_chat_ids:
                await cache.update_prices(force=True)
                await cache.update_ohlcv(force=True)
                now = time.time()
                for chat_id in list(subscribed_chat_ids):
                    role = user_role.get(chat_id, "user")
                    if role == "admin":
                        continue
                    mode = user_trading_mode.get(chat_id, "standard")
                    interval = MODE_CONFIGS[mode]["check_interval"]
                    last_ts = last_check_time.get(chat_id, 0)
                    if now - last_ts < interval:
                        continue
                    favs = user_favorites.get(chat_id, set())
                    if not favs:
                        continue
                    current_signals = {}
                    for code in favs:
                        # اصلاح باگ: این حلقه فقط برای گزارش خصوصی به همان کاربر است و
                        # نباید send_to_channel=True باشد؛ قبلاً هر کاربر با هر «مورد علاقه» و
                        # هر «حالت معاملاتی» شخصی خودش، پیام‌های اضافی و ناهماهنگ به کانال عمومی
                        # ارسال می‌کرد که یکی از دلایل اصلی سیگنال‌های زیاد/متناقض در کانال بود.
                        plan = await generate_trade_plan_v2(code, mode, send_to_channel=False)
                        if plan:
                            current_signals[code] = plan.direction
                        await asyncio.sleep(0.5)
                    prev_signals = last_sent_signals.get(chat_id, {})
                    for code, direction in current_signals.items():
                        prev = prev_signals.get(code)
                        if prev is None or prev["direction"] != direction:
                            plan = await generate_trade_plan_v2(code, mode, send_to_channel=False)
                            if plan:
                                main_text = format_main_signal_v2(plan, code, chat_id)
                                msg = await app.bot.send_message(chat_id=chat_id, text=main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
                                active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
                                prev_signals[code] = {"direction": direction, "timestamp": time.time()}
                    for code in list(prev_signals.keys()):
                        if code not in current_signals:
                            await app.bot.send_message(chat_id=chat_id, text=f"🔴 سیگنال {code} بسته شد.")
                            del prev_signals[code]
                    last_sent_signals[chat_id] = prev_signals
                    last_check_time[chat_id] = now
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Auto loop failed | error=%s", e)
        await asyncio.sleep(60)

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
    if not await guard(update): return
    ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
    no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
    ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
    uptime_sec = time.time() - START_TIME
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
    last_update_str = shamsi_now()
    if LAST_REPORT_TIME:
        last_update_str = shamsi_date(datetime.fromtimestamp(LAST_REPORT_TIME, TEHRAN_TZ))
    active_trailing_count = sum(len(signals) for signals in active_signals.values())
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📊 *وضعیت سیستم*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"⏳ مدت زمان اجرا: `{uptime_str}`\n"
        f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
        f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
        f"🔁 سیگنال‌های دنبال‌شده (تریلینگ): {active_trailing_count}\n"
        f"📊 کل سیگنال‌های تولیدشده: {TOTAL_SIGNALS_GENERATED}\n"
        f"🕒 آخرین بروزرسانی سیگنال: {last_update_str}\n"
    )
    if fg_value is not None:
        text += f"🧭 شاخص ترس و طمع: {fg_value} ({fg_class if fg_class else '-'})\n"
    if macro_data:
        text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
    text += (
        f"{DIVIDER}\n"
        f"🪙 کل ارزهای تعریف‌شده: {len(COIN_CODES)}\n"
        f"🟢 SWAP OK: {ok}\n"
        f"⚪ NO SWAP: {no_swap}\n"
        f"🟠 TICKER ERROR: {ticker_error}\n"
        f"📊 قیمت‌های لحظه‌ای دریافت‌شده: {len(cache.prices)} ارز\n"
        f"{DIVIDER}\n"
        f"📊 داده‌های ذخیره‌شده:\n"
        f"5m: {len(cache.ohlcv.get('5m', {}))} ارز\n"
        f"15m: {len(cache.ohlcv.get('15m', {}))} ارز\n"
        f"1h: {len(cache.ohlcv.get('1h', {}))} ارز\n"
        f"4h: {len(cache.ohlcv.get('4h', {}))} ارز\n"
        f"1d: {len(cache.ohlcv.get('1d', {}))} ارز\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def dashboard(update, context):
    if not await guard(update): return
    if not is_admin_role(update.effective_chat.id):
        await update.message.reply_text("⛔️ فقط ادمین.")
        return
    stats = compute_advanced_stats(signal_history)
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📈 *داشبورد تحلیلی*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"🔢 کل سیگنال‌ها: {stats['total_trades']}\n"
        f"✅ بردها: {stats['wins']}\n"
        f"❌ باخت‌ها: {stats['losses']}\n"
        f"📊 نرخ برد: {stats['win_rate']:.1f}%\n"
        f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
        f"📈 Expectancy: {stats['expectancy']:.2f} USDT\n"
        f"📉 Max Drawdown: {stats['max_drawdown']:.2f} USDT\n"
        f"📊 Sharpe Ratio: {stats['sharpe']:.2f}\n"
        f"⚠️ Risk of Ruin: {stats['risk_of_ruin']:.1f}%\n"
        f"🎯 میانگین اطمینان: {stats['avg_confidence']:.1f}%\n"
    )
    if fg_value is not None:
        text += f"🧭 شاخص ترس و طمع: {fg_value} ({fg_class if fg_class else '-'})\n"
    if macro_data:
        text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
    text += f"{DIVIDER}\n🕒 آخرین سیگنال‌ها:\n"
    for rec in signal_history[-5:]:
        status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
        text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
    await update.message.reply_text(rtl_lines(text), parse_mode="Markdown")

async def news(update, context):
    if not await guard(update): return
    # اصلاح/بهبود: قبلاً دستور /news فقط رویدادهای تقویمی رو نشون می‌داد و هیچ خبر
    # واقعی (نهنگ‌ها/CryptoPanic که در news_history جمع می‌شن) رو نمایش نمی‌داد —
    # با این‌که اسم دستور «news» بود. الان هر دو بخش با فرمت مرتب‌تر نمایش داده می‌شن.
    parts = []

    if news_history:
        recent = list(reversed(news_history[-5:]))
        news_block = "📰 *آخرین اخبار و هشدارها:*\n" + DIVIDER + "\n\n"
        for item in recent:
            importance_emoji = "🔴" if item.get("importance") == "high" else "🟡" if item.get("importance") == "medium" else "🟢"
            news_block += f"{importance_emoji} 🕒 {item['time']}\n{item['text']}\n\n"
        news_block += "برای مشاهده‌ی ۲۰ مورد آخر: منوی اصلی ← 📰 اخبار و هشدارها\n"
        parts.append(news_block)
    else:
        parts.append("📰 *آخرین اخبار و هشدارها:*\n\nهنوز خبری ثبت نشده است.\n")

    events = await get_upcoming_events(force=True)
    now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    upcoming = [ev for ev in events if ev["time"].tzinfo is None or (ev["time"] - now_utc) >= timedelta(0)]
    if upcoming:
        events_block = "📅 *رویدادهای کریپتویی پیش رو:*\n" + DIVIDER + "\n\n"
        for ev in upcoming[:10]:
            importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
            events_block += f"{importance_emoji} *{ev['name']}*\n"
            events_block += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
            if ev.get("description"):
                events_block += f"📝 {ev['description'][:100]}...\n"
            if ev.get("impact"):
                events_block += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
            events_block += "\n"
        parts.append(events_block)
    else:
        parts.append("📅 *رویدادهای کریپتویی پیش رو:*\n\nرویداد مهمی در آینده نزدیک یافت نشد.\n")

    full_text = f"{DIVIDER}\n".join(parts)
    for chunk in split_long_message(rtl_lines(full_text)):
        await update.message.reply_text(chunk, parse_mode="Markdown")

async def periodic_report_command(update, context):
    if not await guard(update): return
    if not is_admin_role(update.effective_chat.id):
        await update.message.reply_text("⛔️ فقط ادمین.")
        return
    await update.message.reply_text("📊 لطفاً دوره‌ی گزارش را انتخاب کنید:", reply_markup=kb_periodic_report())

# ---------- ذخیره و بارگذاری ----------
def _state_payload():
    return {
        "subscribed_chat_ids": list(subscribed_chat_ids),
        "user_currency": user_currency,
        "user_trading_mode": user_trading_mode,
        "user_favorites": {str(k): list(v) for k, v in user_favorites.items()},
        "user_role": {str(k): v for k, v in user_role.items()},
        "news_history": news_history[-20:],
        "signal_history": signal_history[-200:],
        "suggestion_history": suggestion_history[-20:],
        "channel_signal_messages": {str(k): v for k, v in channel_signal_messages.items()},
        "channel_message_map": {str(k): v for k, v in channel_message_map.items()},
        "last_channel_signal_close_time": last_channel_signal_close_time,
        "last_mode_broadcast_time": last_mode_broadcast_time,
    }

def _prune_old_backups():
    try:
        if not os.path.isdir(STATE_BACKUP_DIR):
            return
        files = sorted(
            (f for f in os.listdir(STATE_BACKUP_DIR) if f.startswith("state_") and f.endswith(".json")),
            reverse=True
        )
        for old_file in files[STATE_BACKUP_KEEP:]:
            try:
                os.remove(os.path.join(STATE_BACKUP_DIR, old_file))
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Backup prune failed: {e}")

def save_state():
    """
    بهبود: علاوه بر فایل اصلی state.json (که همیشه به‌صورت atomic —یعنی نوشتن در یک فایل
    موقت و سپس os.replace— بازنویسی می‌شود تا هرگز نصفه‌کاره ذخیره نشود)، بعد از هر ذخیره‌ی
    موفق یک نسخه‌ی پشتیبان زمان‌دار هم در پوشه‌ی backups/ نگه‌داشته می‌شود (همیشه آخرین
    STATE_BACKUP_KEEP نسخه). اگر فایل اصلی به هر دلیلی (خرابی دیسک/ولوم، حذف تصادفی و...)
    از بین برود یا خراب/ناقص شود، load_state() به‌طور خودکار جدیدترین نسخه‌ی پشتیبان معتبر
    را بازیابی می‌کند به‌جای اینکه همه‌چیز از صفر شروع شود.
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        payload = _state_payload()
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)

        try:
            os.makedirs(STATE_BACKUP_DIR, exist_ok=True)
            backup_name = f"state_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            backup_path = os.path.join(STATE_BACKUP_DIR, backup_name)
            backup_tmp = backup_path + ".tmp"
            with open(backup_tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(backup_tmp, backup_path)
            _prune_old_backups()
        except Exception as e:
            logger.debug(f"Backup save failed (non-fatal, main state file was saved fine): {e}")
    except Exception as e:
        logger.warning("State save failed: %s", e)

def _apply_state_data(data):
    global subscribed_chat_ids, user_currency, user_trading_mode, user_favorites, user_role, news_history, signal_history, suggestion_history, channel_signal_messages, channel_message_map, last_channel_signal_close_time, last_mode_broadcast_time
    subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
    user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
    user_trading_mode = {int(k): v for k, v in data.get("user_trading_mode", {}).items()}
    user_favorites = {int(k): set(v) for k, v in data.get("user_favorites", {}).items()}
    user_role = {int(k): v for k, v in data.get("user_role", {}).items()}
    news_history = data.get("news_history", [])
    signal_history = data.get("signal_history", [])
    suggestion_history = data.get("suggestion_history", [])
    channel_signal_messages = {str(k): int(v) for k, v in data.get("channel_signal_messages", {}).items()}
    raw_map = data.get("channel_message_map", {})
    fixed_map = {}
    for k, v in raw_map.items():
        # سازگاری با فایل state قدیمی که کلیدش به‌صورت "SYMBOL|MODE" بود
        symbol_key = k.split("|")[0] if "|" in k else k
        fixed_map[symbol_key] = v
    channel_message_map = fixed_map
    last_channel_signal_close_time = data.get("last_channel_signal_close_time", {})
    last_mode_broadcast_time = data.get("last_mode_broadcast_time", {})

def _reset_state_to_empty():
    global news_history, signal_history, suggestion_history, channel_signal_messages, channel_message_map, last_channel_signal_close_time, last_mode_broadcast_time
    news_history = []
    signal_history = []
    suggestion_history = []
    channel_signal_messages = {}
    channel_message_map = {}
    last_channel_signal_close_time = {}
    last_mode_broadcast_time = {}

def _list_backups_newest_first():
    try:
        if not os.path.isdir(STATE_BACKUP_DIR):
            return []
        files = sorted(
            (f for f in os.listdir(STATE_BACKUP_DIR) if f.startswith("state_") and f.endswith(".json")),
            reverse=True
        )
        return [os.path.join(STATE_BACKUP_DIR, f) for f in files]
    except Exception:
        return []

def load_state():
    """
    بهبود: اگر فایل اصلی state.json موجود نباشد یا خراب/ناقص باشد، به‌جای شروع کاملاً از
    صفر، به‌طور خودکار جدیدترین نسخه‌ی پشتیبان معتبر از پوشه‌ی backups/ بازیابی می‌شود
    (و بلافاصله به‌عنوان فایل اصلی هم دوباره ذخیره می‌شود). فقط اگر هیچ پشتیبان قابل‌استفاده‌ای
    هم پیدا نشد، با داده‌ی خالی شروع می‌شود.
    """
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _apply_state_data(data)
        logger.info("State restored: %s users, %s signals, %s suggestions, %s channel messages",
                    len(subscribed_chat_ids), len(signal_history), len(suggestion_history), len(channel_signal_messages))
        return
    except FileNotFoundError:
        logger.info("No state file found; checking backups before starting fresh...")
    except Exception as e:
        logger.warning("State load failed (%s); checking backups before starting fresh...", e)

    for backup_path in _list_backups_newest_first():
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _apply_state_data(data)
            logger.warning("State restored from backup file: %s", backup_path)
            save_state()  # بازیابی موفق را فوراً به‌عنوان فایل اصلی state.json هم ذخیره کن
            return
        except Exception as e:
            logger.warning("Backup file %s failed to load (%s); trying an older backup...", backup_path, e)
            continue

    logger.info("No usable state file or backup found; starting fresh.")
    _reset_state_to_empty()

# ---------- Button handler ----------
async def button_handler(update, context):
    if not await guard(update): return
    query = update.callback_query; await query.answer()
    data = query.data; chat_id = update.effective_chat.id; user_id = update.effective_user.id
    if data == "noop": return

    if data == "stats_menu":
        await stats_menu(update, context)
        return
    if data == "stats_top_coins_menu":
        await stats_top_coins_menu(update, context)
        return
    if data == "stats_recent_signals_menu":
        await stats_recent_signals_menu(update, context)
        return
    if data == "stats_history_menu":
        await stats_history_menu(update, context)
        return
    if data.startswith("stats_success_page_"):
        page = int(data.split("_")[-1])
        await stats_success_signals(update, context, page)
        return
    if data.startswith("stats_failed_page_"):
        page = int(data.split("_")[-1])
        await stats_failed_signals(update, context, page)
        return
    if data.startswith("stats_recent_success_page_"):
        page = int(data.split("_")[-1])
        await stats_success_signals(update, context, page, recent=True)
        return
    if data.startswith("stats_recent_failed_page_"):
        page = int(data.split("_")[-1])
        await stats_failed_signals(update, context, page, recent=True)
        return
    if data == "stats_success_coins":
        await stats_success_coins(update, context)
        return
    if data == "stats_failed_coins":
        await stats_failed_coins(update, context)
        return

    if data == "optimization_center":
        await optimization_center(update, context)
        return
    if data == "optimization_active":
        await optimization_active(update, context)
        return
    if data == "optimization_history":
        await optimization_history(update, context, page=0)
        return
    if data.startswith("opt_history_page_"):
        page_num = int(data.rsplit("_", 1)[1])
        await optimization_history(update, context, page=page_num)
        return

    if data == "clear_stats_step1":
        await handle_clear_stats_step1(update, context)
        return
    if data == "clear_stats_step2":
        await handle_clear_stats_step2(update, context)
        return
    if data == "clear_stats_confirmed":
        await handle_clear_stats_confirmed(update, context)
        return
    if data == "clear_opt_step1":
        await handle_clear_opt_step1(update, context)
        return
    if data == "clear_opt_step2":
        await handle_clear_opt_step2(update, context)
        return
    if data == "clear_opt_confirmed":
        await handle_clear_opt_confirmed(update, context)
        return

    if data.startswith("apply_suggestion_") or data.startswith("reject_suggestion_") or data.startswith("details_suggestion_"):
        await handle_suggestion_action(update, context)
        return

    if data == "comprehensive_analysis":
        await comprehensive_analysis(update, context)
        return

    if data == "role_admin":
        # نکته امنیتی: قبلاً هر کاربری (حتی غیرادمین) با ارسال همین callback_data می‌توانست
        # نقش ادمین بگیرد. اکنون فقط شناسه‌های داخل ADMIN_USER_IDS اجازه دارند.
        if not is_admin(user_id):
            await query.answer("⛔️ دسترسی ندارید.", show_alert=True)
            return
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
            text = (
                "📰 *تاریخچه اخبار و هشدارها*\n" + DIVIDER + "\n\n"
                "هنوز خبری ثبت نشده است.\n"
                "این بخش به‌صورت خودکار با هشدارهای حرکت نهنگ‌ها و اخبار مهم بازار پر می‌شود."
            )
        else:
            text = f"📰 *تاریخچه اخبار و هشدارها* (۲۰ مورد آخر)\n" + DIVIDER + "\n\n"
            for item in reversed(news_history[-20:]):
                importance_emoji = "🔴" if item.get("importance") == "high" else "🟡" if item.get("importance") == "medium" else "🟢"
                source = item.get("details", {}).get("source", "")
                source_icon = "🐋" if source == "whale" else "📰" if source == "crypto" else "🔔"
                text += f"{importance_emoji} {source_icon} 🕒 {item['time']}\n{item['text']}\n\n{DIVIDER}\n\n"
        chunks = split_long_message(rtl_lines(text))
        await query.edit_message_text(chunks[0], reply_markup=kb_back_to_events(), parse_mode="Markdown")
        for chunk in chunks[1:]:
            await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=kb_back_to_events(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "dashboard":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        stats = compute_advanced_stats(signal_history)
        fg_value, fg_class = await get_fear_greed()
        macro_data = cache.get_macro_data()
        text = (
            f"📈 *داشبورد تحلیلی*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
            f"🔢 کل سیگنال‌ها: {stats['total_trades']}\n"
            f"✅ بردها: {stats['wins']}\n"
            f"❌ باخت‌ها: {stats['losses']}\n"
            f"📊 نرخ برد: {stats['win_rate']:.1f}%\n"
            f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
            f"📈 Expectancy: {stats['expectancy']:.2f} USDT\n"
            f"📉 Max Drawdown: {stats['max_drawdown']:.2f} USDT\n"
            f"📊 Sharpe Ratio: {stats['sharpe']:.2f}\n"
            f"⚠️ Risk of Ruin: {stats['risk_of_ruin']:.1f}%\n"
            f"🎯 میانگین اطمینان: {stats['avg_confidence']:.1f}%\n"
            )
        if fg_value is not None:
            text += f"🧭 شاخص ترس و طمع: {fg_value} ({fg_class if fg_class else '-'})\n"
        if macro_data:
            text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += f"{DIVIDER}\n🕒 آخرین سیگنال‌ها:\n"
        for rec in signal_history[-5:]:
            status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
            text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "favorites":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        favs = user_favorites.get(chat_id, set())
        if not favs:
            text = "⭐ *علاقه‌مندی‌ها*\n\nشما هنوز ارزی به علاقه‌مندی‌ها اضافه نکرده‌اید."
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        else:
            buttons = []
            for code in favs:
                status = cache.market_status.get(code, {}).get("status")
                if status == "SWAP OK": label = f"{code} 🟢"
                elif status == "TICKER ERROR": label = f"{code} 🟠"
                else: label = f"{code} ⚪"
                buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
            rows = build_grid_keyboard(buttons, 2)
            rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
            await query.edit_message_text(
                rtl_lines(f"⭐ *علاقه‌مندی‌ها*\n{DIVIDER}\n{MENU_PROMPT}"),
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode="Markdown",
            )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("toggle_fav_"):
        code = data.split("toggle_fav_", 1)[1]
        favs = user_favorites.setdefault(chat_id, set())
        if code in favs:
            favs.discard(code)
            await query.answer(f"❌ {code} از علاقه‌مندی‌ها حذف شد.")
        else:
            favs.add(code)
            await query.answer(f"⭐ {code} به علاقه‌مندی‌ها اضافه شد.")
        save_state()
        try:
            await query.edit_message_reply_markup(reply_markup=kb_coin_detail(code, code in favs, is_admin_role=is_admin_role(chat_id)))
        except Exception:
            pass
        return

    if data == "periodic_report":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        await query.edit_message_text("📊 لطفاً دوره‌ی گزارش را انتخاب کنید:", reply_markup=kb_periodic_report())
        return

    if data.startswith("report_period_"):
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        period = data.split("report_period_", 1)[1]
        text = f"📊 *گزارش {'هفتگی' if period == 'weekly' else 'ماهانه'}*\n" + DIVIDER + "\n"
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += (
                f"{config['label']}\n"
                f"تعداد سیگنال‌ها: {stats['total_trades']} | برد: {stats['wins']} | باخت: {stats['losses']} | نرخ برد: {stats['win_rate']:.1f}%\n"
                f"فاکتور سود: {stats['profit_factor']:.2f} | Expectancy: {stats['expectancy']:.2f} | MaxDD: {stats['max_drawdown']:.2f}\n"
                f"Sharpe: {stats['sharpe']:.2f} | میانگین اطمینان: {stats['avg_confidence']:.1f}%\n\n"
            )
        # اصلاح: قبلاً به‌جای بازگشت به صفحه‌ی انتخاب دوره (هفتگی/ماهانه)، مستقیم به منوی
        # اصلی می‌رفت و یک لایه از مسیر برگشت را رد می‌کرد.
        await query.edit_message_text(
            rtl_lines(text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="periodic_report")]]),
            parse_mode="Markdown"
        )
        return

    if data == "admin_compare":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        text = "📊 *گزارش مقایسه‌ای حالت‌های معاملاتی*\n" + DIVIDER + "\n"
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += (
                f"{config['label']}\n"
                f"تعداد سیگنال‌ها: {stats['total_trades']} | برد: {stats['wins']} | باخت: {stats['losses']} | نرخ برد: {stats['win_rate']:.1f}%\n"
                f"فاکتور سود: {stats['profit_factor']:.2f} | Expectancy: {stats['expectancy']:.2f} | MaxDD: {stats['max_drawdown']:.2f}\n"
                f"Sharpe: {stats['sharpe']:.2f} | میانگین اطمینان: {stats['avg_confidence']:.1f}%\n\n"
            )
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        return

    if data.startswith("coins_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_reply_markup(reply_markup=kb_coins(page))
        return

    if data == "menu_prices":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...")
        try:
            prices = await asyncio.wait_for(cache.update_prices(), timeout=90)
            await query.edit_message_text(format_prices_pretty(prices, chat_id), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Prices UI error: %s", e)
            await query.edit_message_text(f"❌ خطا در دریافت قیمت‌ها.\nنوع خطا: `{type(e).__name__}`", reply_markup=kb_back_main(), parse_mode="Markdown")
        return

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
            # اصلاح: قبلاً مستقیم به منوی اصلی می‌رفت (یک لایه را رد می‌کرد)؛ الان مثل حالت
            # موفق، به لیست ارزها برمی‌گردد.
            await query.edit_message_text(
                rtl_lines(text),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست ارزها", callback_data="menu_coins")]]),
                parse_mode="Markdown"
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        return

    # ----- بخش ادمین -----
    if data.startswith("askmode_"):
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        parts = data.split("_", 2)
        action = parts[1]
        code = parts[2]
        if action == "weekly":
            try:
                summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
                await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Weekly UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_to_coin(code))
            return
        else:
            await query.edit_message_text(
                f"🛠️ حالت معاملاتی برای {action} {code} را انتخاب کن:",
                reply_markup=kb_mode_selection_for_action(action, code),
            )
            return

    if data.startswith("run_"):
        parts = data.split("_", 3)
        action = parts[1]
        code = parts[2]
        mode = parts[3]
        if code not in COIN_CODES: return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(f"⚠️ قرارداد {code} در KuCoin در دسترس نیست.\nوضعیت: {status}", reply_markup=kb_back_to_coin(code))
            return
        if action == "suggest":
            try:
                text = await asyncio.wait_for(generate_status_text_async(code, chat_id, mode), timeout=30)
                await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Signal UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        elif action == "instant":
            try:
                plan = await asyncio.wait_for(generate_trade_plan_v2(code, mode), timeout=30)
                if plan is None:
                    await query.edit_message_text(
                        f"💤 فعلاً سیگنال نهایی برای {code} وجود ندارد.\nدلایل احتمالی: ADX پایین، عدم تأیید کافی لایه‌ها، یا نسبت R/R نامناسب.",
                        reply_markup=kb_back_to_coin(code),
                        parse_mode="Markdown"
                    )
                    return
                main_text = format_main_signal_v2(plan, code, chat_id)
                await query.edit_message_text(main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
                active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
            except Exception as e:
                logger.exception("Signal UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        elif action == "weekly":
            try:
                summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
                await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Weekly UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_to_coin(code))
        return

    # ----- کاربر عادی -----
    if data.startswith("suggest_"):
        if is_admin_role(chat_id):
            return
        code = data.split("suggest_", 1)[1]
        if code not in COIN_CODES: return
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            text = await asyncio.wait_for(generate_status_text_async(code, chat_id, mode), timeout=30)
            await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        return

    if data.startswith("instant_"):
        if is_admin_role(chat_id):
            return
        code = data.split("instant_", 1)[1]
        if code not in COIN_CODES: return
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            plan = await asyncio.wait_for(generate_trade_plan_v2(code, mode), timeout=30)
            if plan is None:
                await query.edit_message_text(
                    f"💤 فعلاً سیگنال نهایی برای {code} وجود ندارد.\nدلایل احتمالی: ADX پایین، عدم تأیید کافی لایه‌ها، یا نسبت R/R نامناسب.",
                    reply_markup=kb_back_to_coin(code),
                    parse_mode="Markdown"
                )
                return
            main_text = format_main_signal_v2(plan, code, chat_id)
            await query.edit_message_text(main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
            active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        return

    if data.startswith("weekly_"):
        if is_admin_role(chat_id):
            return
        code = data.split("weekly_", 1)[1]
        if code not in COIN_CODES: return
        try:
            summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
            await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Weekly UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_to_coin(code))
        return

    if data.startswith("details_"):
        code = data.split("_", 1)[1]
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            ind = await cache.get_indicators(code, mode)
            if not ind:
                await query.edit_message_text("⚠️ داده کافی نیست.", reply_markup=kb_back_to_coin(code))
                return
            plan = await generate_trade_plan_v2(code, mode)
            if not plan:
                await query.edit_message_text("💤 سیگنال فعلی موجود نیست.\nدلایل احتمالی: ADX پایین یا عدم تأیید کافی لایه‌ها.", reply_markup=kb_back_to_coin(code))
                return
            details_text = format_technical_details(code, plan, ind, chat_id)
            await query.edit_message_text(split_long_message(details_text)[0], reply_markup=kb_back_to_signal(code), parse_mode="Markdown")
        except Exception as e:
            logger.exception("Details UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در نمایش جزئیات {code}.", reply_markup=kb_back_to_coin(code))
        return

    if data == "admin_panel":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
        no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
        ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
        uptime_sec = time.time() - START_TIME
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        fg_value, fg_class = await get_fear_greed()
        macro_data = cache.get_macro_data()
        text = (
            f"🛠️ *پنل مدیریت*\n{DIVIDER}\n🕒 {shamsi_now()}\n"
            f"⏳ مدت اجرا: `{uptime_str}`\n"
            f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
            f"🔁 سیگنال‌های دنبال‌شده: {sum(len(s) for s in active_signals.values())}\n"
            f"📊 کل سیگنال‌ها: {len(signal_history)}\n"
            )
        if fg_value is not None:
            text += f"🧭 شاخص ترس و طمع: {fg_value} ({fg_class if fg_class else '-'})\n"
        if macro_data:
            text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += (
            f"{DIVIDER}\n"
            f"🪙 کل ارزها: {len(COIN_CODES)}\n"
            f"🟢 SWAP OK: {ok}\n⚪ NO SWAP: {no_swap}\n🟠 TICKER ERROR: {ticker_error}\n"
            f"📊 قیمت‌های دریافت‌شده: {len(cache.prices)} ارز\n"
            f"📦 داده‌ها: 5m={len(cache.ohlcv.get('5m',{}))} 15m={len(cache.ohlcv.get('15m',{}))} 1h={len(cache.ohlcv.get('1h',{}))} 4h={len(cache.ohlcv.get('4h',{}))} 1d={len(cache.ohlcv.get('1d',{}))}\n"
            f"{DIVIDER}\n"
            f"📋 *آمار حالت‌ها:*\n"
        )
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += f"{config['label']}: {stats['total_trades']} سیگنال | برد {stats['wins']} | باخت {stats['losses']} | نرخ برد {stats['win_rate']:.1f}%\n"
        text += f"\n🕒 آخرین سیگنال‌ها:\n"
        for rec in signal_history[-5:]:
            status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
            text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} ({MODE_CONFIGS.get(rec['mode'],{}).get('label','')})\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_admin_panel(), parse_mode="Markdown")
        return

    if data == "menu_all":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        await query.edit_message_text("⏳ در حال تحلیل همه ارزها (برای ادمین)...")
        try:
            mode = "standard"
            plans = {}
            for code in COIN_CODES[:20]:
                plan = await generate_trade_plan_v2(code, mode)
                if plan:
                    plans[code] = plan
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception("menu_all error: %s", e)
            # اصلاح: این صفحه از پنل مدیریت باز می‌شود؛ بازگشت باید به همان‌جا برود نه منوی اصلی.
            await query.edit_message_text(f"❌ خطا: {e}", reply_markup=kb_back_to_admin_panel()); return
        if not plans:
            text = "📋 فعلاً سیگنال نهایی نداریم."
            await query.edit_message_text(text, reply_markup=kb_back_to_admin_panel())
        else:
            sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
            full_text = "📋 *نمایش پیشنهادات*\n\n" + "\n\n".join(format_main_signal_v2(p, p.symbol, chat_id) for p in sorted_plans)
            chunks = split_long_message(full_text)
            new_ids = []
            # اصلاح باگ: این صفحه اصلاً دکمه‌ی بازگشت نداشت (نه روی چانک اول، نه بقیه).
            await query.edit_message_text(chunks[0], reply_markup=kb_back_to_admin_panel(), parse_mode="Markdown")
            new_ids.append(query.message.message_id)
            for chunk in chunks[1:]:
                m = await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=kb_back_to_admin_panel(), parse_mode="Markdown")
                new_ids.append(m.message_id)
            set_interactive_screen(chat_id, new_ids)
        return

    # دکمه جدید: نمایش همه سیگنال‌های فعال
    if data == "active_signals_all":
        # اصلاح باگ: قبلاً signal_history[-10:] بدون فیلتر status نمایش داده می‌شد —
        # یعنی سیگنال‌های بسته‌شده (tp/sl) هم به‌اشتباه زیر عنوان «فعال» می‌آمدند. سپس
        # فیلتر به status == "open" محدود شد که خودش هم باگ داشت: بعد از برخورد به TP1
        # یا TP2، وضعیت رکورد دیگه "open" نیست (می‌شه "tp1_hit"/"tp2_hit") در حالی که
        # معامله هنوز واقعاً باز و در حال پیگیریه — پس این سیگنال‌ها به‌اشتباه از لیست
        # «فعال» حذف می‌شدن. الان هر چیزی که به وضعیت نهایی (TP3/SL/نامعتبر) نرسیده،
        # «فعال» حساب می‌شه. همچنین اطلاعات هر سیگنال کامل‌تر و مرتب‌تر نمایش داده می‌شه:
        # قیمت لحظه‌ای، سود/زیان شناور، فاصله تا هدف بعدی، مرحله‌ی فعلی، و مدت‌زمان باز بودن.
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")]])
        try:
            open_signals = [r for r in signal_history if r.get("status") not in CLOSED_STATUSES]
            open_signals.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
            sent_ids = [query.message.message_id]
            if not open_signals:
                text = "📡 *سیگنال‌های فعال*\n\nدر حال حاضر هیچ سیگنال بازی وجود ندارد."
                await query.edit_message_text(rtl_lines(text), reply_markup=back_kb, parse_mode="Markdown")
            else:
                await cache.update_prices(force=False)
                stage_labels = {
                    "open": "🆕 تازه باز شده",
                    "tp1_hit": "✅ TP1 خورده — در مسیر TP2",
                    "tp2_hit": "✅✅ TP2 خورده — در مسیر TP3",
                }
                text = f"📡 *سیگنال‌های فعال* ({len(open_signals)} مورد)\n" + DIVIDER + "\n\n"
                for rec in open_signals:
                    symbol = rec.get("symbol", "?")
                    direction = rec.get("direction", "?")
                    direction_emoji = "🟢" if direction == "LONG" else "🔴"
                    mode_label = MODE_CONFIGS.get(rec.get("mode"), MODE_CONFIGS["standard"])["label"]
                    tp_prices = rec.get("tp_prices") or [0, 0, 0]
                    entry_price = rec.get("entry_price", 0)
                    sl_price = rec.get("sl_price", 0)
                    status = rec.get("status", "open")
                    stage_txt = stage_labels.get(status, status)

                    current_price = cache.prices.get(symbol)
                    pnl_line = ""
                    target_line = ""
                    if current_price and entry_price:
                        if direction == "LONG":
                            pnl_pct = (current_price - entry_price) / entry_price * 100
                        else:
                            pnl_pct = (entry_price - current_price) / entry_price * 100
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                        pnl_line = f"   💹 وضعیت لحظه‌ای: {fmt_amount(current_price, chat_id)} ({pnl_emoji} {pnl_pct:+.2f}%)\n"

                        # نزدیک‌ترین هدف باقی‌مانده (بسته به مرحله‌ای که سیگنال توش هست)
                        next_idx = {"open": 0, "tp1_hit": 1, "tp2_hit": 2}.get(status, 0)
                        next_tp = tp_prices[next_idx] if next_idx < len(tp_prices) else tp_prices[-1]
                        if next_tp:
                            if direction == "LONG":
                                dist_pct = (next_tp - current_price) / current_price * 100
                            else:
                                dist_pct = (current_price - next_tp) / current_price * 100
                            target_line = f"   🎯 فاصله تا TP{next_idx + 1}: {dist_pct:+.2f}%\n"

                    opened_at = rec.get("opened_at", rec.get("timestamp", time.time()))
                    duration_txt = _format_duration(time.time() - opened_at)

                    text += (
                        f"*{symbol}* | {direction} {direction_emoji} | {mode_label}\n"
                        f"   {stage_txt}\n"
                        f"{pnl_line}"
                        f"{target_line}"
                        f"   ⏱️ مدت باز بودن: {duration_txt}\n"
                        f"   🎯 اطمینان اولیه: {rec.get('confidence', 0):.0f}٪ | RR: {rec.get('rr', 0):.2f}\n"
                        f"   📥 ورود: {fmt_amount(entry_price, chat_id)} | 🛑 حد ضرر: {fmt_amount(sl_price, chat_id)}\n"
                        f"   TP1: {fmt_amount(tp_prices[0], chat_id)} | TP2: {fmt_amount(tp_prices[1], chat_id)} | TP3: {fmt_amount(tp_prices[2], chat_id)}\n"
                        f"{DIVIDER}\n\n"
                    )
                chunks = split_long_message(rtl_lines(text))
                await query.edit_message_text(chunks[0], reply_markup=back_kb, parse_mode="Markdown")
                for chunk in chunks[1:]:
                    # اصلاح باگ: قبلاً فقط chunk اول دکمه‌ی بازگشت داشت؛ وقتی تعداد
                    # سیگنال‌های فعال زیاد بود و پیام به چند تکه تقسیم می‌شد، تکه‌های
                    # بعدی (که کاربر معمولاً همون‌ها رو پایین صفحه می‌بینه) هیچ دکمه‌ای
                    # نداشتن. الان هر تکه دکمه‌ی بازگشت خودش رو داره.
                    sent = await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=back_kb, parse_mode="Markdown")
                    sent_ids.append(sent.message_id)
            set_interactive_screen(chat_id, sent_ids)
        except Exception as e:
            logger.exception("active_signals_all error: %s", e)
            await query.edit_message_text(f"❌ خطا در نمایش سیگنال‌های فعال: {type(e).__name__}", reply_markup=back_kb)
        return

def format_technical_details(code, plan, ind, chat_id):
    direction = "لانگ 🟢" if plan.direction == "LONG" else "شورت 🔴"
    reasons_text = "\n".join(f" ✅ {x}" for x in plan.reasons[:15])
    warnings_text = "\n" + "\n".join(f" ⚠️ {x}" for x in plan.warnings) if plan.warnings else ""
    text = (
        f"📊 *جزئیات فنی* {code}/USDT\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"جهت: {direction}\n"
        f"امتیاز نهایی: {plan.confidence:.0f}٪\n"
        f"{DIVIDER}\n"
        f"📈 *دلایل سیگنال*\n{reasons_text}{warnings_text}\n\n"
        f"📐 *اندیکاتورها*\n"
        f"EMA20: {fmt_amount(ind['ema20'], chat_id)}\n"
        f"EMA50: {fmt_amount(ind['ema50'], chat_id)}\n"
        f"EMA200: {fmt_amount(ind['ema200'], chat_id)}\n"
        f"فاصله EMA50: {ind['price_ema50_pct']:+.2f}%\n"
        f"فاصله EMA200: {ind['price_ema200_pct']:+.2f}%\n"
        f"ADX: {ind['adx']:.1f} (DI+ {ind['plus_di']:.1f} / DI- {ind['minus_di']:.1f})\n"
        f"MACD Hist: {ind['macd_hist']:.4f}\n"
        f"RSI: {ind['rsi']:.1f}\n"
        f"Stoch RSI: {ind['stoch_k']:.1f}\n"
        f"ROC: {ind['roc']:+.2f}%\n"
        f"CCI: {ind['cci']:.1f}\n"
        f"Williams %R: {ind['williams_r']:.1f}\n"
        f"BB %: {ind['bb_percent']:.2f} | BB Width: {ind['bb_width']:.2f}\n"
        f"Volume Ratio: {ind['volume_ratio']:.2f}×\n"
        f"VWAP: {fmt_amount(ind['vwap'], chat_id)}\n"
        f"ATR: {fmt_amount(ind['atr'], chat_id)} ({ind['atr_pct']:.2f}%)\n"
        f"حمایت: {fmt_amount(ind['support'], chat_id)} | مقاومت: {fmt_amount(ind['resistance'], chat_id)}\n"
        f"{DIVIDER}\n"
        f"⚠️ تحلیل تکنیکال است و تضمین سود نیست."
    )
    return rtl_lines(text)

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
        BotCommand("news", "اخبار و رویدادهای پیش رو"),
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
    app.create_task(channel_signal_monitor_loop(app))
    logger.info("Signal Bot V62 (Channel: یک سیگنال معتبر به‌ازای هر ارز + پایش مستقل TP/SL) started")

async def global_error_handler(update, context):
    """
    اصلاح مهم: قبلاً هیچ error handler سراسری ثبت نشده بود. یعنی اگر داخل هر کدام از
    handlerها (مثلاً button_handler) یک استثنای پیش‌بینی‌نشده رخ می‌داد (KeyError روی یک
    رکورد قدیمی، تایم‌اوت شبکه و ...)، کاربر هیچ پیامی نمی‌دید و دکمه از دید او «اصلاً کار
    نمی‌کرد» — دقیقاً همان رفتاری که باعث سردرگمی در باگ «دکمه سیگنال‌های فعال» هم شده بود.
    این تابع (۱) خطا را کامل با traceback لاگ می‌کند تا در آینده مشکل‌یابی ممکن باشد و
    (۲) در صورت امکان یک پیام کوتاه به کاربر نشان می‌دهد تا حداقل بداند خطایی رخ داده،
    نه اینکه فکر کند ربات هنگ کرده.
    """
    logger.error("Unhandled exception while processing update: %s", update, exc_info=context.error)
    try:
        if isinstance(update, object) and getattr(update, "callback_query", None):
            await update.callback_query.answer("❌ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)
        elif isinstance(update, object) and getattr(update, "effective_chat", None):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ خطای غیرمنتظره‌ای رخ داد. لطفاً دوباره تلاش کنید یا از /menu استفاده کنید."
            )
    except Exception:
        # حتی اگر اطلاع‌رسانی به کاربر هم ناموفق بود، دیگر بالاتر از این‌جا نباید propagate شود
        logger.exception("Failed to notify user about the original error.")

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
    app.add_error_handler(global_error_handler)
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
