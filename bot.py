import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict

import ccxt
import jdatetime
import pandas as pd
import requests
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator, ROCIndicator, WilliamsRIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator, CCIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import VolumeWeightedAveragePrice
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

# ---------- لیست ارزها ----------
COIN_ICONS = {
    "BTC": "₿", "ETH": "Ξ", "SOL": "☀️", "BNB": "🔶", "XRP": "✕",
    "ADA": "₳", "DOGE": "Ɖ", "AVAX": "🔺", "LINK": "🔗", "DOT": "●",
    "NEAR": "Ⓝ", "SUI": "💧", "APT": "🔹", "ARB": "🔵", "OP": "🔴",
    "MATIC": "💜", "TON": "💎", "LTC": "Ł", "BCH": "₿", "ATOM": "⚛️"
}
COIN_CODES = sorted(list(COIN_ICONS.keys()))

TIMEFRAMES = ("15m", "1h", "4h", "1d")
IRT_RATE_TTL_SECONDS = 60
OHLCV_TTL_SECONDS = 180
PRICE_TTL_SECONDS = 30

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "───────────────"
RLM = "\u200f"

# ---------- اتصال به صرافی ----------
exchange_gate = ccxt.gate({"enableRateLimit": True, "options": {"defaultType": "spot"}})
exchange_kucoin = ccxt.kucoin({"enableRateLimit": True})

# ========== متغیرهای سراسری ==========
signal_history: List[Dict] = []
TOTAL_SIGNALS_GENERATED = 0
LAST_REPORT_TIME = None
_irt_rate_cache = {"value": None, "ts": 0.0}

# ---------- ابزارهای تاریخ و قیمت ----------
def shamsi_now():
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M:%S")

def fetch_irt_rate():
    now = time.time()
    if _irt_rate_cache["value"] and (now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS):
        return _irt_rate_cache["value"]
    try:
        r = requests.get("https://api.wallex.ir/v1/markets", timeout=5)
        if r.status_code == 200:
            rate = float(r.json()["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])
            _irt_rate_cache.update(value=rate, ts=now)
            return rate
    except Exception as e:
        logger.warning(f"Error fetching IRT rate: {e}")
    return _irt_rate_cache["value"] or 60000.0  # مقدار پشتیبان

def format_price_full(usdt_value: float) -> str:
    rate = fetch_irt_rate()
    irt_value = usdt_value * rate
    return (
        f"💵 **قیمت دلاری:** `${usdt_value:,.4f}` USDT\n"
        f"🇮🇷 **معادل تومانی:** `{irt_value:,.0f}` تومان\n"
        f"📅 **تاریخ و زمان:** `{shamsi_now()}`"
    )

# ---------- ذخیره و بازیابی وضعیت ----------
def save_state():
    try:
        data = {
            "signal_history": signal_history,
            "total_signals": TOTAL_SIGNALS_GENERATED,
            "last_report_time": LAST_REPORT_TIME,
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def load_state():
    global signal_history, TOTAL_SIGNALS_GENERATED, LAST_REPORT_TIME
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                signal_history = data.get("signal_history", [])
                TOTAL_SIGNALS_GENERATED = data.get("total_signals", 0)
                LAST_REPORT_TIME = data.get("last_report_time", None)
        except Exception as e:
            logger.error(f"Error loading state: {e}")

# ---------- مدیریت داده‌های بازار ----------
class MarketCache:
    def __init__(self):
        self.prices: Dict[str, float] = {}
        self.ohlcv: Dict[str, Dict[str, pd.DataFrame]] = {tf: {} for tf in TIMEFRAMES}
        self.last_price_update = 0

    async def update_prices(self):
        now = time.time()
        if now - self.last_price_update < PRICE_TTL_SECONDS and self.prices:
            return self.prices
        try:
            symbols = [f"{code}/USDT" for code in COIN_CODES]
            tickers = await asyncio.to_thread(exchange_gate.fetch_tickers, symbols)
            for code in COIN_CODES:
                sym = f"{code}/USDT"
                if sym in tickers and tickers[sym].get("last"):
                    self.prices[code] = float(tickers[sym]["last"])
            self.last_price_update = now
        except Exception as e:
            logger.warning(f"Error fetching prices: {e}")
        return self.prices

    async def get_ohlcv(self, code: str, timeframe: str) -> Optional[pd.DataFrame]:
        symbol = f"{code}/USDT"
        try:
            raw = await asyncio.to_thread(exchange_gate.fetch_ohlcv, symbol, timeframe, limit=100)
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            return df
        except Exception as e:
            logger.error(f"OHLCV fetch error for {code} {timeframe}: {e}")
            return None

cache = MarketCache()

# ---------- تحلیل تکنیکال ارزها ----------
async def analyze_coin_details(code: str) -> str:
    price = (await cache.update_prices()).get(code, 0.0)
    df_1h = await cache.get_ohlcv(code, "1h")
    
    if df_1h is None or df_1h.empty:
        return f"❌ دریافت اطلاعات برای ارز {code} با خطا مواجه شد."

    close = df_1h["close"]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]
    macd = MACD(close).macd_diff().iloc[-1]
    atr = AverageTrueRange(df_1h["high"], df_1h["low"], close, window=14).average_true_range().iloc[-1]
    
    support = df_1h["low"].tail(20).min()
    resistance = df_1h["high"].tail(20).max()
    trend = "صعودی 📈" if price > ema200 else "نزولی 📉"

    text = (
        f"📊 **تحلیل و وضعیت لحظه‌ای {COIN_ICONS.get(code, '')} {code}**\n"
        f"{DIVIDER}\n"
        f"{format_price_full(price)}\n"
        f"{DIVIDER}\n"
        f"📌 **مؤلفه‌های تکنیکال (تایم‌فریم 1H):**\n"
        f"• **روند کلی:** {trend}\n"
        f"• **شاخص RSI:** `{rsi:.1f}`\n"
        f"• **مومنتوم MACD:** `{'مثبت +' if macd > 0 else 'منفی -'}` (`{macd:.4f}`)\n"
        f"• **میانگین EMA 20:** `${ema20:,.4f}`\n"
        f"• **میانگین EMA 200:** `${ema200:,.4f}`\n"
        f"• **دامنه نوسان (ATR):** `${atr:,.4f}`\n"
        f"{DIVIDER}\n"
        f"🎯 **سطوح کلیدی:**\n"
        f"🛡 **حمایت نزدیک:** `${support:,.4f}`\n"
        f"🚀 **مقاومت نزدیک:** `${resistance:,.4f}`"
    )
    return text

# ---------- کیبوردهای شیشه‌ای (Inline Keyboards) ----------
def kb_main_menu(is_admin_user=False):
    keyboard = [
        [InlineKeyboardButton("📊 آمار کامل سیگنال‌ها", callback_data="stats_detailed")],
        [InlineKeyboardButton("📈 قیمت و وضعیت لحظه‌ای ارزها", callback_data="coins_list_1")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def kb_coins_grid(page=1):
    items_per_page = 8
    total_pages = (len(COIN_CODES) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = start + items_per_page
    
    buttons = []
    row = []
    for code in COIN_CODES[start:end]:
        icon = COIN_ICONS.get(code, "")
        row.append(InlineKeyboardButton(f"{icon} {code}", callback_data=f"coin_detail_{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
        
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"coins_list_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"coins_list_{page+1}"))
    
    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_back_main():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")]])

def kb_stats_menu(is_admin_user=False):
    btns = []
    if is_admin_user:
        btns.append([InlineKeyboardButton("🗑 پاک‌سازی و صفر کردن آمار", callback_data="reset_stats_confirm")])
    btns.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(btns)

def kb_reset_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، تمام آمار پاک شود", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ انصراف", callback_data="stats_detailed")]
    ])

# ---------- هندلرهای ربات ----------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_adm = user_id in ADMIN_USER_IDS
    text = (
        f"🤖 **به ربات تحلیل و سیگنال‌دهی خوش آمدید.**\n\n"
        f"این ربات به‌صورت خودکار بازار کریپتو را پایش کرده و سیگنال‌های با دقت بالا را به کانال ارسال می‌کند.\n\n"
        f"👇 **از دکمه‌های زیر جهت مشاهده آمار و قیمت ارزها استفاده کنید:**"
    )
    await update.message.reply_text(text, reply_markup=kb_main_menu(is_adm), parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_adm = user_id in ADMIN_USER_IDS

    if data == "main_menu":
        await query.edit_message_text(
            "👇 **منوی اصلی ربات:**",
            reply_markup=kb_main_menu(is_adm),
            parse_mode="Markdown"
        )

    elif data == "stats_detailed":
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
            f"📊 **آمار و عملکرد دقیق سیگنال‌های کانال**\n"
            f"{DIVIDER}\n"
            f"🔢 **کل سیگنال‌های ثبت‌شده:** `{TOTAL_SIGNALS_GENERATED}`\n"
            f"🎯 **سیگنال‌های بسته‌شده:** `{total}`\n"
            f"✅ **موفق (سود):** `{wins}`\n"
            f"❌ **ناموفق (حد ضرر):** `{losses}`\n"
            f"🏆 **نرخ پیروزی (Win Rate):** `{win_rate:.1f}%`\n"
            f"{DIVIDER}\n"
            f"📍 **جزئیات اهداف:**\n"
            f"• برخورد با TP1: `{tp1}`\n"
            f"• برخورد با TP2: `{tp2}`\n"
            f"• برخورد با TP3: `{tp3}`\n"
            f"• برخورد با حد ضرر (SL): `{sl}`\n"
            f"{DIVIDER}\n"
            f"🕒 **آخرین بازنویسی آمار:** `{LAST_REPORT_TIME or 'ثبت نشده'}`"
        )
        await query.edit_message_text(stats_text, reply_markup=kb_stats_menu(is_adm), parse_mode="Markdown")

    elif data == "reset_stats_confirm":
        if not is_adm:
            return
        await query.edit_message_text(
            "⚠️ **آیا از صفر کردن تمامی آمار و تاریخچه سیگنال‌ها اطمینان دارید؟**\nاین عمل غیرقابل بازگشت است.",
            reply_markup=kb_reset_confirm(),
            parse_mode="Markdown"
        )

    elif data == "reset_stats_do":
        if not is_adm:
            return
        global signal_history, TOTAL_SIGNALS_GENERATED, LAST_REPORT_TIME
        signal_history.clear()
        TOTAL_SIGNALS_GENERATED = 0
        LAST_REPORT_TIME = shamsi_now()
        save_state()
        await query.edit_message_text(
            "✅ **تمامی آمار با موفقیت صفر شد.**",
            reply_markup=kb_back_main(),
            parse_mode="Markdown"
        )

    elif data.startswith("coins_list_"):
        page = int(data.split("_")[2])
        prices = await cache.update_prices()
        rate = fetch_irt_rate()
        
        text = f"📈 **قیمت لحظه‌ای ارزها (دلار / تومان)**\n📅 `{shamsi_now()}`\n{DIVIDER}\n"
        for code in COIN_CODES[(page-1)*8 : page*8]:
            p_usd = prices.get(code, 0.0)
            p_irt = p_usd * rate
            icon = COIN_ICONS.get(code, "")
            text += f"{icon} **{code}:** `${p_usd:,.4f}` ≈ `{p_irt:,.0f}` تومان\n"
            
        text += f"\n💡 *برای مشاهده وضعیت دقیق تکنیکال، روی ارز مورد نظر کلیک کنید.*"
        await query.edit_message_text(text, reply_markup=kb_coins_grid(page), parse_mode="Markdown")

    elif data.startswith("coin_detail_"):
        code = data.split("_")[2]
        await query.edit_message_text("⏳ در حال دریافت و تحلیل اطلاعات بازار...", parse_mode="Markdown")
        detail_text = await analyze_coin_details(code)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"coin_detail_{code}")],
            [InlineKeyboardButton("🔙 لیست ارزها", callback_data="coins_list_1")]
        ])
        await query.edit_message_text(detail_text, reply_markup=kb, parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_adm:
            return
        text = (
            f"👑 **پنل مدیریت ادمین**\n"
            f"{DIVIDER}\n"
            f"🆔 **شناسه کانال فعال:** `{CHANNEL_ID or 'تنظیم نشده'}`\n"
            f"🤖 **وضعیت ربات:** آنلاین و فعال\n"
            f"💾 **ذخیره‌سازی:** فعال (بدون بک‌آپ اضافی)"
        )
        await query.edit_message_text(text, reply_markup=kb_back_main(), parse_mode="Markdown")

# ---------- چرخه‌ی خودکار ارسال سیگنال به کانال ----------
async def channel_signal_monitor_loop(app: Application):
    await asyncio.sleep(5)
    global TOTAL_SIGNALS_GENERATED
    while True:
        try:
            if CHANNEL_ID:
                prices = await cache.update_prices()
                for code in COIN_CODES:
                    df = await cache.get_ohlcv(code, "1h")
                    if df is None or len(df) < 50:
                        continue
                    
                    price = prices.get(code, 0.0)
                    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
                    ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
                    ema200 = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]

                    # نمونه منطق ساده سیگنال‌دهی برای کانال
                    if price > ema200 and rsi < 35:
                        tp1 = price * 1.02
                        tp2 = price * 1.04
                        sl = price * 0.98
                        
                        signal_msg = (
                            f"📣 **سیگنال جدید کانال** {COIN_ICONS.get(code, '')} #{code}\n"
                            f"{DIVIDER}\n"
                            f"🟢 **جهت معامله:** BUY / LONG\n"
                            f"{format_price_full(price)}\n"
                            f"{DIVIDER}\n"
                            f"🎯 **هدف اول (TP1):** `${tp1:,.4f}`\n"
                            f"🎯 **هدف دوم (TP2):** `${tp2:,.4f}`\n"
                            f"🛑 **حد ضرر (SL):** `${sl:,.4f}`\n"
                            f"{DIVIDER}\n"
                            f"⚡️ *سیگنال بر اساس پایش خودکار ربات صادر شده است.*"
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
                        await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Channel monitor loop error: {e}")
        await asyncio.sleep(600)  # بررسی هر ۱۰ دقیقه

# ---------- راه‌اندازی اصلی ----------
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN یافت نشد!")
        return

    load_state()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    # شروع حلقه پس‌زمینه
    loop = asyncio.get_event_loop()
    loop.create_task(channel_signal_monitor_loop(application))

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
