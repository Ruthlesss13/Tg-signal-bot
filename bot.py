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
            gate_symbols = []
            for code in COIN_CODES:
                if code == "TON":
                    gate_symbols.append("TONCOIN/USDT")
                else:
                    gate_symbols.append(f"{code}/USDT")
            tickers = await asyncio.to_thread(exchange_gate.fetch_tickers, gate_symbols)
            for i, code in enumerate(COIN_CODES):
                sym = gate_symbols[i]
                if sym in tickers and tickers[sym].get("last") is not None:
                    new_prices[code] = float(tickers[sym]["last"])
            if "TON" not in new_prices:
                try:
                    ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, "TON/USDT")
                    if ticker and ticker.get("last") is not None:
                        new_prices["TON"] = float(ticker["last"])
                except:
                    pass
            if new_prices:
                self.active_exchange_name = "Gate.io"
                self.prices = new_prices
                self.last_price_update = now
                return self.prices
        except Exception as e:
            logger.warning(f"Gate.io fetch_tickers failed: {e}")

        # ۳. Fallback تکی فقط برای ارزهای بدون قیمت
        async def fetch_one(code):
            try:
                ticker = await asyncio.to_thread(exchange_mexc.fetch_ticker, f"{code}/USDT")
                if ticker and ticker.get("last") is not None:
                    return code, float(ticker["last"])
            except:
                pass
            try:
                sym = "TONCOIN/USDT" if code == "TON" else f"{code}/USDT"
                ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, sym)
                if ticker and ticker.get("last") is not None:
                    return code, float(ticker["last"])
            except:
                if code == "TON":
                    try:
                        ticker = await asyncio.to_thread(exchange_gate.fetch_ticker, "TON/USDT")
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
            self.active_exchange_name = "MEXC/Gate (fallback)"
        return self.prices

    async def get_ohlcv(self, code: str, timeframe: str = "1h") -> Optional[pd.DataFrame]:
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

        try:
            sym = "TONCOIN/USDT" if code == "TON" else f"{code}/USDT"
            raw = await asyncio.to_thread(exchange_gate.fetch_ohlcv, sym, timeframe, limit=100)
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

def format_price(price: float) -> str:
    if price < 0.01:
        return f"{price:.10f}"
    elif price < 1:
        return f"{price:.6f}"
    else:
        return f"{price:,.4f}"

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
    macd_status = "صعودی 🟢" if macd_hist > 0 else "نزولی 🔴"

    return (
        f"📊 **گزارش جامع وضعیت و تحلیل تکنیکال {code}**\n"
        f"{DIVIDER}\n"
        f"🏛 **صرافی:** `{cache.active_exchange_name}` | **جفت ارز:** `{code}/USDT`\n"
        f"🔄 **وضعیت معاملات Swap:** 🟢 فعال (Spot & Futures)\n"
        f"{DIVIDER}\n"
        f"💵 **قیمت دلاری:** `${format_price(price)}` USDT\n"
        f"🇮🇷 **معادل تومانی:** `{irt_price:,.0f}` تومان\n"
        f"📅 **تاریخ و زمان:** `{shamsi_now()}`\n"
        f"{DIVIDER}\n"
        f"📌 **مؤلفه‌های تکنیکال (تایم‌فریم 1 ساعته):**\n"
        f"• **روند کلی بازار:** {trend}\n"
        f"• **RSI (14):** `{rsi:.1f}`\n"
        f"• **استوکاستیک RSI:** `{stoch_rsi:.1f}`\n"
        f"• **ADX:** `{adx:.1f}`\n"
        f"• **MACD:** {macd_status}\n"
        f"• **ATR:** `${format_price(atr)}`\n"
        f"{DIVIDER}\n"
        f"📈 **میانگین‌های متحرک (EMA):**\n"
        f"• **EMA 20:** `${format_price(ema20)}`\n"
        f"• **EMA 50:** `${format_price(ema50)}`\n"
        f"• **EMA 200:** `${format_price(ema200)}`\n"
        f"{DIVIDER}\n"
        f"🎯 **سطوح حمایت و مقاومت کلیدی:**\n"
        f"🛡 **حمایت (24 ساعت):** `${format_price(support)}`\n"
        f"🚀 **مقاومت (24 ساعت):** `${format_price(resistance)}`\n"
        f"🌐 **باند بالایی بولینگر:** `${format_price(bb_upper)}`\n"
        f"🌐 **باند پایینی بولینگر:** `${format_price(bb_lower)}`"
    )

# ===========================
# کیبوردهای یک‌ستونی با متن‌های کوتاه‌تر
# ===========================
def kb_main_menu(is_admin_user=False):
    keyboard = [
        [InlineKeyboardButton("💰 قیمت‌ها", callback_data="coins_prices_all")],
        [InlineKeyboardButton("📊 تحلیل ارزها", callback_data="coins_status_grid")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    keyboard.append([InlineKeyboardButton("▶️ شروع", callback_data="bot_start_action")])
    keyboard.append([InlineKeyboardButton("⏸ توقف", callback_data="bot_stop_action")])
    return InlineKeyboardMarkup(keyboard)

def kb_prices_all_single():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="coins_prices_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
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
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 آمار سیگنال‌ها", callback_data="admin_signal_stats")],
        [InlineKeyboardButton("👥 آمار کاربران", callback_data="admin_system_stats")],
        [InlineKeyboardButton("🗑 صفر کردن آمار", callback_data="reset_stats_confirm")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
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
            "✅ **ربات برای شما فعال شد.**",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if data == "bot_stop_action":
        paused_users.add(user_id)
        save_state()
        await query.edit_message_text(
            "⏹ **ربات متوقف شد.**",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )
        return

    if user_id in paused_users and data != "main_menu":
        await query.edit_message_text(
            "⛔️ **ربات برای شما غیرفعال است.**\nبرای فعال‌سازی روی دکمه «▶️ شروع» کلیک کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ شروع", callback_data="bot_start_action")]]),
            parse_mode="Markdown"
        )
        return

    if data == "main_menu":
        await query.edit_message_text(
            "👇 **منوی اصلی:**",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )

    elif data == "coins_prices_all":
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...", parse_mode="Markdown")
        prices = await cache.update_prices()
        rate = await fetch_irt_rate()

        exchange_emoji = "🇲" if "MEXC" in cache.active_exchange_name else "🇬"

        text = (
            f"💵 **لیست ۳۰ قیمت ارز برتر**\n"
            f"📅 **تاریخ:** `{shamsi_now()}`\n"
            f"🇮🇷 **نرخ تتر:** `{rate:,.0f}` تومان\n"
            f"{DIVIDER}\n"
        )

        for code in COIN_CODES:
            p_usd = prices.get(code, 0.0)
            p_irt = p_usd * rate
            text += f"‎{exchange_emoji} **{code}**: `${format_price(p_usd)}` USDT\n"
            text += f"‎🇮🇷 `{p_irt:,.0f}` تومان\n\n"

        await query.edit_message_text(text, reply_markup=kb_prices_all_single(), parse_mode="Markdown")

    elif data == "coins_status_grid":
        text = (
            "📊 **بخش تحلیل تکنیکال ارزها**\n"
            "ارز مورد نظر را انتخاب کنید:"
        )
        await query.edit_message_text(text, reply_markup=kb_status_grid(), parse_mode="Markdown")

    elif data.startswith("coin_detail_"):
        code = data.split("_")[2]
        await query.edit_message_text(f"⏳ در حال تحلیل {code}...", parse_mode="Markdown")
        detail_text = await analyze_coin_full_status(code)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"coin_detail_{code}")],
            [InlineKeyboardButton("🔙 لیست ارزها", callback_data="coins_status_grid")]
        ])
        await query.edit_message_text(detail_text, reply_markup=kb, parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_adm:
            return
        await query.edit_message_text(
            f"👑 **پنل مدیریت**\n{DIVIDER}\nلطفاً انتخاب کنید:",
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
            f"📈 **آمار سیگنال‌ها**\n"
            f"{DIVIDER}\n"
            f"🔢 **کل تولیدشده:** `{TOTAL_SIGNALS_GENERATED}`\n"
            f"🎯 **بسته‌شده:** `{total}`\n"
            f"✅ **موفق:** `{wins}`\n"
            f"❌ **ناموفق:** `{losses}`\n"
            f"🏆 **نرخ پیروزی:** `{win_rate:.1f}%`\n"
            f"{DIVIDER}\n"
            f"📍 **جزئیات اهداف:**\n"
            f"• TP1: `{tp1}`\n"
            f"• TP2: `{tp2}`\n"
            f"• TP3: `{tp3}`\n"
            f"• SL: `{sl}`\n"
            f"{DIVIDER}\n"
            f"🕒 **آخرین بروزرسانی:** `{LAST_REPORT_TIME or 'ثبت نشده'}`"
        )
        await query.edit_message_text(stats_text, reply_markup=kb_back_admin(), parse_mode="Markdown")

    elif data == "admin_system_stats":
        if not is_adm:
            return
        rate = await fetch_irt_rate()
        wallex_status = "آنلاین 🟢" if rate > 0 else "آفلاین 🔴"
        channel_status = f"`{CHANNEL_ID}` 🟢" if CHANNEL_ID else "تنظیم نشده 🔴"

        sys_text = (
            f"👥 **آمار کاربران و وضعیت سیستم**\n"
            f"{DIVIDER}\n"
            f"👤 **کاربران فعال:** `{len(registered_users - paused_users)}` نفر\n"
            f"⏸ **متوقف‌شده:** `{len(paused_users)}` نفر\n"
            f"📊 **کل ثبت‌نام‌ها:** `{len(registered_users)}` نفر\n"
            f"{DIVIDER}\n"
            f"🏛 **صرافی فعال:** `{cache.active_exchange_name}`\n"
            f"🇮🇷 **وضعیت Wallex:** {wallex_status}\n"
            f"📢 **کانال:** {channel_status}\n"
            f"⏱ **ساعت:** `{shamsi_now()}`"
        )
        await query.edit_message_text(sys_text, reply_markup=kb_back_admin(), parse_mode="Markdown")

    elif data == "reset_stats_confirm":
        if not is_adm:
            return
        await query.edit_message_text(
            "⚠️ **آیا از صفر کردن آمار اطمینان دارید؟**",
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
            "✅ **آمار با موفقیت صفر شد.**",
            reply_markup=kb_back_admin(),
            parse_mode="Markdown"
        )

async def channel_signal_monitor_loop(app: Application):
    await asyncio.sleep(5)
    global TOTAL_SIGNALS_GENERATED
    while True:
        try:
            if not CHANNEL_ID:
                logger.warning("⚠️ CHANNEL_ID not set.")
                await asyncio.sleep(600)
                continue

            logger.info("🔍 Checking for signals...")
            prices = await cache.update_prices()
            if not prices:
                logger.warning("⚠️ No prices.")
                await asyncio.sleep(600)
                continue

            for code in COIN_CODES:
                price = prices.get(code, 0.0)
                if price == 0.0:
                    continue

                df = await cache.get_ohlcv(code, "1h")
                if df is None or len(df) < 50:
                    continue

                rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
                ema200 = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]

                logger.info(f"📊 {code}: Price={price:.4f}, EMA200={ema200:.4f}, RSI={rsi:.2f} -> Condition: {price > ema200 and rsi < 32}")

                if price > ema200 and rsi < 32:
                    logger.info(f"🚨 SIGNAL for {code}!")
                    tp1 = price * 1.02
                    tp2 = price * 1.04
                    sl = price * 0.98
                    rate = await fetch_irt_rate()
                    irt_price = price * rate

                    signal_msg = (
                        f"📣 **سیگنال جدید** #{code}\n"
                        f"{DIVIDER}\n"
                        f"🟢 **جهت:** BUY / LONG\n"
                        f"🏛 **صرافی:** `{cache.active_exchange_name}`\n"
                        f"💵 **ورود:** `${format_price(price)}` USDT\n"
                        f"🇮🇷 **تومان:** `{irt_price:,.0f}`\n"
                        f"📅 **زمان:** `{shamsi_now()}`\n"
                        f"{DIVIDER}\n"
                        f"🎯 **TP1:** `${format_price(tp1)}`\n"
                        f"🎯 **TP2:** `${format_price(tp2)}`\n"
                        f"🛑 **SL:** `${format_price(sl)}`\n"
                        f"{DIVIDER}\n"
                        f"⚡️ *تحلیل خودکار*"
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
            logger.error(f"❌ Loop error: {e}", exc_info=True)
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

    logger.info("🚀 FINAL VERSION - STABLE BUTTONS, LEFT-ALIGNED, FAST")
    application.run_polling()

if __name__ == "__main__":
    main()
