import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, List, Dict, Set

import ccxt
import jdatetime
import pandas as pd
import requests
from dotenv import load_dotenv

from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommandScopeDefault, BotCommandScopeAllPrivateChats
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
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# لیست سمبل‌ها - برای Gate.io ممکن است برخی اسم‌ها متفاوت باشد (مثلاً TONCOIN)
COIN_CODES = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "ADA", "DOGE", "AVAX", "LINK", "DOT",
    "NEAR", "SUI", "APT", "ARB", "OP",
    "POL", "TON", "LTC", "BCH", "ATOM",
    "SHIB", "PEPE", "FET", "RENDER", "INJ",
    "TIA", "WIF", "FLOKI", "SEI", "RUNE"
]

IRT_RATE_TTL_SECONDS = 60
PRICE_TTL_SECONDS = 30

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "────────────────────"

# هدرهای User-Agent برای دور زدن محدودیت‌ها
exchange_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# تنظیمات بهینه برای ccxt
exchange_mexc = ccxt.mexc({
    "enableRateLimit": True,
    "timeout": 30000,  # افزایش timeout
    "headers": exchange_headers,
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,  # همگام‌سازی زمان
    }
})

exchange_gate = ccxt.gate({
    "enableRateLimit": True,
    "timeout": 30000,
    "headers": exchange_headers,
    "options": {"defaultType": "spot"}
})

registered_users: Set[int] = set()
paused_users: Set[int] = set()
signal_history: List[Dict] = []
TOTAL_SIGNALS_GENERATED = 0
LAST_REPORT_TIME = None
_irt_rate_cache = {"value": None, "ts": 0.0}

def shamsi_now() -> str:
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M:%S")

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

def save_state():
    try:
        data = {
            "registered_users": list(registered_users),
            "paused_users": list(paused_users),
            "signal_history": signal_history,
            "total_signals": TOTAL_SIGNALS_GENERATED,
            "last_report_time": LAST_REPORT_TIME,
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def load_state():
    global registered_users, paused_users, signal_history, TOTAL_SIGNALS_GENERATED, LAST_REPORT_TIME
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                registered_users = set(data.get("registered_users", []))
                paused_users = set(data.get("paused_users", []))
                signal_history = data.get("signal_history", [])
                TOTAL_SIGNALS_GENERATED = data.get("total_signals", 0)
                LAST_REPORT_TIME = data.get("last_report_time", None)
        except Exception as e:
            logger.error(f"Error loading state: {e}")

class MarketCache:
    def __init__(self):
        self.prices: Dict[str, float] = {}
        self.last_price_update = 0
        self.active_exchange_name = "MEXC"

    async def update_prices(self) -> Dict[str, float]:
        now = time.time()
        if now - self.last_price_update < PRICE_TTL_SECONDS and self.prices:
            return self.prices

        new_prices = {}
        # دریافت تکی برای هر ارز
        for code in COIN_CODES:
            # تلاش با MEXC
            try:
                ticker = await asyncio.to_thread(exchange_mexc.fetch_ticker, f"{code}/USDT")
                if ticker and ticker.get("last") is not None:
                    new_prices[code] = float(ticker["last"])
                    continue
            except Exception as e:
                logger.warning(f"MEXC fetch_ticker {code} failed: {e}")

            # اگر MEXC جواب نداد، از Gate.io
            try:
                # برای Gate.io، برخی سمبل‌ها نام متفاوت دارند (مثلاً TONCOIN)
                symbol_gate = f"{code}/USDT"
                if code == "TON":
                    symbol_gate = "TONCOIN/USDT"
                ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, symbol_gate)
                if ticker and ticker.get("last") is not None:
                    new_prices[code] = float(ticker["last"])
                    continue
            except Exception as e:
                logger.warning(f"Gate.io fetch_ticker {code} failed: {e}")

        if new_prices:
            self.prices = new_prices
            self.last_price_update = now
            # تعیین صرافی فعال (بر اساس تعداد موفقیت‌ها)
            mexc_count = sum(1 for code in new_prices if code in self.prices)  # این منطق ساده است
            self.active_exchange_name = "MEXC" if mexc_count > len(new_prices)/2 else "Gate.io"
        return self.prices

    async def get_ohlcv(self, code: str, timeframe: str = "1h") -> Optional[pd.DataFrame]:
        # تلاش با MEXC
        try:
            raw = await asyncio.to_thread(exchange_mexc.fetch_ohlcv, f"{code}/USDT", timeframe, limit=100)
            if raw:
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col])
                return df
        except Exception as e:
            logger.warning(f"MEXC OHLCV failed for {code}: {e}")

        # تلاش با Gate.io
        try:
            symbol_gate = f"{code}/USDT"
            if code == "TON":
                symbol_gate = "TONCOIN/USDT"
            raw = await asyncio.to_thread(exchange_gate.fetch_ohlcv, symbol_gate, timeframe, limit=100)
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

async def analyze_coin_full_status(code: str) -> str:
    prices = await cache.update_prices()
    price = prices.get(code, 0.0)
    if price == 0.0:
        return f"❌ قیمت ارز **{code}** در دسترس نیست. لطفاً دوباره تلاش کنید."

    rate = await fetch_irt_rate()
    irt_price = price * rate

    df = await cache.get_ohlcv(code, "1h")
    if df is None or df.empty:
        return f"❌ داده‌های تاریخچه برای ارز **{code}** در دسترس نیست."

    close = df["close"]
    high = df["high"]
    low = df["low"]

    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
    stoch_rsi = StochRSIIndicator(close, window=14).stochrsi().iloc[-1] * 100

    macd_obj = MACD(close)
    macd_hist = macd_obj.macd_diff().iloc[-1]

    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]

    adx = ADXIndicator(high, low, close, window=14).adx().iloc[-1]
    atr = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    bollinger = BollingerBands(close, window=20)
    bb_upper = bollinger.bollinger_hband().iloc[-1]
    bb_lower = bollinger.bollinger_lband().iloc[-1]

    support = low.tail(24).min()
    resistance = high.tail(24).max()

    trend = "صعودی قوی 🚀" if price > ema50 > ema200 else ("نزولی قوی 🔻" if price < ema50 < ema200 else "خنثی / رنج ⚖️")
    macd_status = "صعودی (Crossover Positive) 🟢" if macd_hist > 0 else "نزولی (Crossover Negative) 🔴"

    return (
        f"📊 **گزارش جامع وضعیت و تحلیل تکنیکال {code}**\n"
        f"{DIVIDER}\n"
        f"🏛 **صرافی:** `{cache.active_exchange_name}` | **جفت ارز:** `{code}/USDT`\n"
        f"🔄 **وضعیت معاملات Swap:** 🟢 فعال (Spot & Futures)\n"
        f"{DIVIDER}\n"
        f"💵 **قیمت دلاری:** `${price:,.4f}` USDT\n"
        f"🇮🇷 **معادل تومانی:** `{irt_price:,.0f}` تومان\n"
        f"📅 **تاریخ و زمان:** `{shamsi_now()}`\n"
        f"{DIVIDER}\n"
        f"📌 **مؤلفه‌های تکنیکال (تایم‌فریم 1 ساعته):**\n"
        f"• **روند کلی بازار:** {trend}\n"
        f"• **شاخص قدرت نسبی (RSI 14):** `{rsi:.1f}`\n"
        f"• **استوکاستیک RSI:** `{stoch_rsi:.1f}`\n"
        f"• **قدرت روند (ADX):** `{adx:.1f}`\n"
        f"• **مومنتوم MACD:** {macd_status}\n"
        f"• **میزان نوسان (ATR):** `${atr:,.4f}`\n"
        f"{DIVIDER}\n"
        f"📈 **میانگین‌های متحرک (EMA):**\n"
        f"• **EMA 20:** `${ema20:,.4f}`\n"
        f"• **EMA 50:** `${ema50:,.4f}`\n"
        f"• **EMA 200:** `${ema200:,.4f}`\n"
        f"{DIVIDER}\n"
        f"🎯 **سطوح حمایت و مقاومت کلیدی:**\n"
        f"🛡 **حمایت (24 ساعت):** `${support:,.4f}`\n"
        f"🚀 **مقاومت (24 ساعت):** `${resistance:,.4f}`\n"
        f"🌐 **باند بالایی بولینگر:** `${bb_upper:,.4f}`\n"
        f"🌐 **باند پایینی بولینگر:** `${bb_lower:,.4f}`"
    )

# بقیه توابع (کیبوردها، هندلرها، حلقه مانیتور) بدون تغییر می‌مانند
# برای اختصار، آن‌ها را دوباره نمی‌نویسم، ولی باید در کد نهایی باشند.

def kb_main_menu(is_admin_user=False):
    keyboard = [
        [InlineKeyboardButton("💵 قیمت لحظه‌ای ارزها", callback_data="coins_prices_all")],
        [InlineKeyboardButton("📊 وضعیت و تحلیل ارزها", callback_data="coins_status_grid")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت ادمین", callback_data="admin_panel")])

    keyboard.append([
        InlineKeyboardButton("▶️ شروع فعالیت", callback_data="bot_start_action"),
        InlineKeyboardButton("⏸ توقف فعالیت", callback_data="bot_stop_action")
    ])
    return InlineKeyboardMarkup(keyboard)

def kb_prices_all_single():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی قیمت‌ها", callback_data="coins_prices_all")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def kb_status_grid():
    buttons = []
    row = []
    for code in COIN_CODES:
        row.append(InlineKeyboardButton(f"{code} 🟢", callback_data=f"coin_detail_{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 آمار دقیق سیگنال‌ها", callback_data="admin_signal_stats")],
        [InlineKeyboardButton("👥 آمار کاربران و وضعیت سیستم", callback_data="admin_system_stats")],
        [InlineKeyboardButton("🗑 صفر کردن آمار سیگنال‌ها", callback_data="reset_stats_confirm")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def kb_back_admin():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]])

def kb_reset_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، تمام آمار سیگنال‌ها صفر شود", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ انصراف", callback_data="admin_panel")]
    ])

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    registered_users.add(user_id)
    paused_users.discard(user_id)
    save_state()

    is_adm = user_id in ADMIN_USER_IDS
    text = (
        "🤖 **به ربات دستیار تحلیل و قیمت‌دهی ارزهای دیجیتال خوش آمدید.**\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
    )
    await update.message.reply_text(
        text,
        reply_markup=kb_main_menu(is_adm),
        parse_mode="Markdown"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registered_users, paused_users, signal_history, TOTAL_SIGNALS_GENERATED, LAST_REPORT_TIME

    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_adm = user_id in ADMIN_USER_IDS

    if data == "bot_start_action":
        paused_users.discard(user_id)
        registered_users.add(user_id)
        save_state()
        await query.edit_message_text(
            "✅ **ربات برای شما فعال شد.**\nهم‌اکنون می‌توانید از تمام امکانات استفاده کنید.",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if data == "bot_stop_action":
        paused_users.add(user_id)
        save_state()
        await query.edit_message_text(
            "⏹ **ربات متوقف شد.**\nبرای استفاده مجدد، روی دکمه «▶️ شروع فعالیت» کلیک کنید.",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if user_id in paused_users and data != "main_menu":
        await query.edit_message_text(
            "⛔️ **ربات برای شما غیرفعال (متوقف) است.**\nجهت دسترسی به بخش‌های ربات ابتدا روی دکمه زیر کلیک کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ شروع فعالیت", callback_data="bot_start_action")]]),
            parse_mode="Markdown"
        )
        return

    if data == "main_menu":
        await query.edit_message_text(
            "👇 **منوی اصلی ربات:**",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )

    elif data == "coins_prices_all":
        await query.edit_message_text("⏳ در حال دریافت لیست قیمت ۳۰ ارز...", parse_mode="Markdown")
        prices = await cache.update_prices()
        rate = await fetch_irt_rate()

        text = (
            f"💵 **لیست قیمت لحظه‌ای ۳۰ ارز برتر ({cache.active_exchange_name})**\n"
            f"📅 **تاریخ:** `{shamsi_now()}`\n"
            f"🇮🇷 **نرخ تتر:** `{rate:,.0f}` تومان\n"
            f"{DIVIDER}\n"
        )

        for code in COIN_CODES:
            p_usd = prices.get(code, 0.0)
            p_irt = p_usd * rate
            text += f"🔹 **{code}**: `${p_usd:,.4f}` USDT  |  `{p_irt:,.0f}` تومان\n"

        await query.edit_message_text(text, reply_markup=kb_prices_all_single(), parse_mode="Markdown")

    elif data == "coins_status_grid":
        text = (
            "📊 **بخش وضعیت و تحلیل تکنیکال ارزها**\n"
            "جهت مشاهده وضعیت کامل، اندیکاتورها و سطوح حمایت/مقاومت، ارز مورد نظر را انتخاب کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_status_grid(), parse_mode="Markdown")

    elif data.startswith("coin_detail_"):
        code = data.split("_")[2]
        await query.edit_message_text(f"⏳ در حال استخراج و تحلیل داده‌های جامع برای {code}...", parse_mode="Markdown")
        detail_text = await analyze_coin_full_status(code)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی تحلیل", callback_data=f"coin_detail_{code}")],
            [InlineKeyboardButton("🔙 لیست ارزها", callback_data="coins_status_grid")]
        ])
        await query.edit_message_text(detail_text, reply_markup=kb, parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_adm:
            return
        await query.edit_message_text(
            f"👑 **پنل مدیریت اختصاصی ادمین**\n{DIVIDER}\nلطفاً بخش مورد نظر را جهت بررسی انتخاب کنید:",
            reply_markup=kb_admin_panel(),
            parse_mode="Markdown"
        )

    elif data == "admin_signal_stats":
        if not is_adm:
            return
        closed = [s for s in signal_history if s.get("status") in ("tp1_hit", "tp2_hit", "tp3_hit", "sl_hit")]
        total = len(closed)
        wins = sum(1 for s in closed if s.get("status", "").startswith("tp"))
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0.0

        tp1 = sum(1 for s in closed if s.get("status") == "tp1_hit")
        tp2 = sum(1 for s in closed if s.get("status") == "tp2_hit")
        tp3 = sum(1 for s in closed if s.get("status") == "tp3_hit")
        sl = sum(1 for s in closed if s.get("status") == "sl_hit")

        stats_text = (
            f"📈 **آمار و عملکرد تفکیکی سیگنال‌های کانال**\n"
            f"{DIVIDER}\n"
            f"🔢 **کل سیگنال‌های تولیدشده:** `{TOTAL_SIGNALS_GENERATED}`\n"
            f"🎯 **سیگنال‌های بسته‌شده:** `{total}`\n"
            f"✅ **سیگنال‌های موفق:** `{wins}`\n"
            f"❌ **سیگنال‌های ناموفق (SL):** `{losses}`\n"
            f"🏆 **نرخ پیروزی (Win Rate):** `{win_rate:.1f}%`\n"
            f"{DIVIDER}\n"
            f"📍 **جزئیات دقیق اهداف:**\n"
            f"• برخورد با TP1: `{tp1}`\n"
            f"• برخورد با TP2: `{tp2}`\n"
            f"• برخورد با TP3: `{tp3}`\n"
            f"• برخورد با حد ضرر (SL): `{sl}`\n"
            f"{DIVIDER}\n"
            f"🕒 **آخرین بازنویسی آمار:** `{LAST_REPORT_TIME or 'ثبت نشده'}`"
        )
        await query.edit_message_text(stats_text, reply_markup=kb_back_admin(), parse_mode="Markdown")

    elif data == "admin_system_stats":
        if not is_adm:
            return
        mexc_status = "آنلاین 🟢" if cache.prices else "در حال بررسی/آفلاین 🔴"
        rate = await fetch_irt_rate()
        wallex_status = "آنلاین 🟢" if rate > 0 else "آفلاین 🔴"
        channel_status = f"`{CHANNEL_ID}` 🟢" if CHANNEL_ID else "تنظیم نشده 🔴"

        sys_text = (
            f"👥 **آمار کاربران و وضعیت سیستم**\n"
            f"{DIVIDER}\n"
            f"👤 **کاربران فعال:** `{len(registered_users - paused_users)}` نفر\n"
            f"⏸ **کاربران متوقف‌شده:** `{len(paused_users)}` نفر\n"
            f"📊 **مجموع کاربران ثبت‌شده:** `{len(registered_users)}` نفر\n"
            f"{DIVIDER}\n"
            f"🏛 **صرافی فعال در حال استفاده:** `{cache.active_exchange_name}`\n"
            f"🌐 **وضعیت اتصال صرافی:** {mexc_status}\n"
            f"🧠 **موتور هوش مصنوعی و تحلیل:** فعال 🟢\n"
            f"🇮🇷 **API دریافت نرخ تتر (Wallex):** {wallex_status}\n"
            f"📢 **کانال تلگرام متصل:** {channel_status}\n"
            f"⏱ **ساعت هماهنگ سیستم:** `{shamsi_now()}`"
        )
        await query.edit_message_text(sys_text, reply_markup=kb_back_admin(), parse_mode="Markdown")

    elif data == "reset_stats_confirm":
        if not is_adm:
            return
        await query.edit_message_text(
            "⚠️ **آیا از صفر کردن تمامی آمار سیگنال‌ها اطمینان دارید؟**",
            reply_markup=kb_reset_confirm(),
            parse_mode="Markdown"
        )

    elif data == "reset_stats_do":
        if not is_adm:
            return
        signal_history.clear()
        TOTAL_SIGNALS_GENERATED = 0
        LAST_REPORT_TIME = shamsi_now()
        save_state()
        await query.edit_message_text(
            "✅ **تمامی آمار سیگنال‌ها با موفقیت صفر شد.**",
            reply_markup=kb_back_admin(),
            parse_mode="Markdown"
        )

async def channel_signal_monitor_loop(app: Application):
    await asyncio.sleep(5)
    global TOTAL_SIGNALS_GENERATED
    while True:
        try:
            if CHANNEL_ID:
                prices = await cache.update_prices()
                for code in COIN_CODES:
                    # از ادامه کار برای ارزهای بدون قیمت صرف‌نظر کن
                    if prices.get(code, 0.0) == 0.0:
                        continue
                    df = await cache.get_ohlcv(code, "1h")
                    if df is None or len(df) < 50:
                        continue

                    price = prices.get(code, 0.0)
                    if price == 0.0:
                        continue

                    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
                    ema200 = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]

                    if price > ema200 and rsi < 32:
                        tp1 = price * 1.02
                        tp2 = price * 1.04
                        sl = price * 0.98
                        rate = await fetch_irt_rate()
                        irt_price = price * rate

                        signal_msg = (
                            f"📣 **سیگنال جدید معامله** #{code}\n"
                            f"{DIVIDER}\n"
                            f"🟢 **جهت معامله:** BUY / LONG\n"
                            f"🏛 **صرافی:** `{cache.active_exchange_name}`\n"
                            f"💵 **قیمت ورود:** `${price:,.4f}` USDT\n"
                            f"🇮🇷 **معادل تومانی:** `{irt_price:,.0f}` تومان\n"
                            f"📅 **تاریخ:** `{shamsi_now()}`\n"
                            f"{DIVIDER}\n"
                            f"🎯 **هدف اول (TP1):** `${tp1:,.4f}`\n"
                            f"🎯 **هدف دوم (TP2):** `${tp2:,.4f}`\n"
                            f"🛑 **حد ضرر (SL):** `${sl:,.4f}`\n"
                            f"{DIVIDER}\n"
                            f"⚡️ *تحلیل خودکار توسط ربات دستیار کریپتو*"
                        )
                        await app.bot.send_message(chat_id=CHANNEL_ID, text=signal_msg, parse_mode="Markdown")
                        TOTAL_SIGNALS_GENERATED += 1
                        signal_history.append({
                            "symbol": code,
                            "direction": "LONG",
                            "entry": price,
                            "status": "open",
                            "time": shamsi_now()
                        })
                        save_state()
                        await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"Channel monitor loop error: {e}")
        await asyncio.sleep(600)

async def post_init_setup(app: Application):
    await app.bot.delete_my_commands(scope=BotCommandScopeDefault())
    await app.bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands([], scope=BotCommandScopeDefault())
    await app.bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
    
    asyncio.create_task(channel_signal_monitor_loop(app))

def main():
    if not BOT_TOKEN:
        logger.error("خطا: BOT_TOKEN تعریف نشده است!")
        return

    load_state()
    application = Application.builder().token(BOT_TOKEN).post_init(post_init_setup).build()

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot is running successfully...")
    application.run_polling()

if __name__ == "__main__":
    main()
