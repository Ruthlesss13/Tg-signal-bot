import logging
import asyncio
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import ccxt.async_support as ccxt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

# ۱. تنظیمات Logging و Error Handler
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("signal_bot")

# دیکشنری حافظه موقت برای جلوگیری از ارسال سیگنال تکراری (Cooldown)
sent_signals_cooldown = {}

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        return
    logger.error("Exception while handling an update:", exc_info=context.error)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            text="اطلاعات به‌روزرسانی شد.",
            reply_markup=query.message.reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e

# ۲. استخراج اندیکاتورها و فیلتر حجم با Pandas
def fetch_indicators(ohlcv_data):
    df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # محاسبه EMA 200
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # محاسبه RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # محاسبه ATR (14)
    tr1 = df['high'] - df['low']
    tr2 = np.abs(df['high'] - df['close'].shift())
    tr3 = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()

    # محاسبه میانگین حجم ۲۰ کندل اخیر (Volume SMA 20)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean()

    last_row = df.iloc[-1]
    
    # فیلتر حجم: آیا حجم کندل جاری بیشتر از میانگین حجم ۲۰ کندل اخیر است؟
    is_volume_high = last_row['volume'] > last_row['vol_sma20']

    return (
        float(last_row['close']),
        float(last_row['ema200']),
        float(last_row['rsi']),
        float(last_row['atr']),
        is_volume_high
    )

# ۳. تحلیل رژیم بازار و تولید متن سیگنال به همراه محاسبات R:R
def analyze_market_regime(symbol: str, price: float, ema200: float, rsi: float, atr: float, is_volume_high: bool):
    if price <= 0 or ema200 <= 0 or atr <= 0:
        return False, None, None

    # فیلتر حجم: عدم صدور سیگنال در صورت پایین بودن حجم معاملات
    if not is_volume_high:
        return False, None, None

    price_ema_diff_pct = abs(price - ema200) / ema200 * 100

    signal_type = None
    is_long = None
    confidence = 0
    leverage = "1x"
    condition_met = False

    # الف) بازار رنج (Sideways)
    if price_ema_diff_pct <= 2.0:
        if rsi <= 30:
            signal_type = "BUY / LONG (Range Low)"
            is_long = True
            confidence = 78
            leverage = "2x - 4x"
            condition_met = True
        elif rsi >= 70:
            signal_type = "SELL / SHORT (Range High)"
            is_long = False
            confidence = 78
            leverage = "2x - 4x"
            condition_met = True

    # ب) بازار صعودی (Bullish Trend)
    elif price > ema200:
        if rsi <= 35:
            signal_type = "BUY / LONG (Strong Dip)"
            is_long = True
            confidence = 92
            leverage = "5x - 10x"
            condition_met = True
        elif 40 <= rsi <= 48:
            signal_type = "BUY / LONG (Trend Continuation)"
            is_long = True
            confidence = 85
            leverage = "3x - 5x"
            condition_met = True

    # ج) بازار نزولی (Bearish Trend)
    elif price < ema200:
        if rsi >= 68:
            signal_type = "SELL / SHORT (Strong Rejection)"
            is_long = False
            confidence = 90
            leverage = "5x - 10x"
            condition_met = True
        elif 52 <= rsi <= 60:
            signal_type = "SELL / SHORT (Trend Continuation)"
            is_long = False
            confidence = 82
            leverage = "3x - 5x"
            condition_met = True

    if condition_met:
        # محاسبه قیمت TP/SL
        if is_long:
            sl = price - (1.5 * atr)
            tp1 = price + (1.5 * atr)
            tp2 = price + (3.0 * atr)
        else:
            sl = price + (1.5 * atr)
            tp1 = price - (1.5 * atr)
            tp2 = price - (3.0 * atr)

        # محاسبه درصدهای تغییر
        tp1_pct = abs(tp1 - price) / price * 100
        tp2_pct = abs(tp2 - price) / price * 100
        sl_pct = abs(price - sl) / price * 100
        rr_ratio = round(tp2_pct / sl_pct, 2) if sl_pct > 0 else 2.0

        fmt = lambda val: f"{val:.8f}" if price < 0.01 else f"{val:.4f}"
        
        signal_message = (
            f"🚨 **سیگنال جدید دریافت شد** 🚨\n\n"
            f"جفت ارز: #{symbol}\n"
            f"نوع سیگنال: {signal_type}\n"
            f"قیمت ورود: {fmt(price)}\n"
            f"شاخص RSI: {rsi:.2f}\n\n"
            f"🎯 **حد سود اول (TP1):** {fmt(tp1)} (`+{tp1_pct:.2f}%`)\n"
            f"🚀 **حد سود دوم (TP2):** {fmt(tp2)} (`+{tp2_pct:.2f}%`)\n"
            f"🛑 **حد ضرر (SL):** {fmt(sl)} (`-{sl_pct:.2f}%`)\n\n"
            f"⚖️ **نسبت ریسک به ریوارد:** 1:{rr_ratio}\n"
            f"📊 **ضریب اطمینان:** %{confidence}\n"
            f"⚡ **اهرم پیشنهادی:** {leverage}"
        )

        # دکمه‌های شیشه‌ای لینک مستقیم به نمودار و معامله
        clean_pair = symbol.replace("/", "")
        keyboard = [
            [
                InlineKeyboardButton("📈 مشاهده در TradingView", url=f"https://www.tradingview.com/symbols/{clean_pair}/"),
                InlineKeyboardButton("📊 معامله در MEXC", url=f"https://www.mexc.com/exchange/{symbol.replace('/', '_')}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        return True, signal_message, reply_markup

    return False, None, None

# ۴. حلقه اصلی پایش بازار همراه با فیلتر اسپم (Cooldown)
async def channel_signal_monitor_loop(app: Application):
    exchange = ccxt.mexc({'enableRateLimit': True})
    symbols = ['BTC/USDT', 'ETH/USDT', 'PEPE/USDT', 'SHIB/USDT', 'SOL/USDT']
    timeframe = '1h'
    cooldown_hours = 2  # مدت زمان عدم ارسال سیگنال تکراری برای یک نماد (ساعت)

    while True:
        try:
            logger.info("🔍 Checking market data and volume filters...")
            now = datetime.now()

            for symbol in symbols:
                # بررسی Cooldown
                if symbol in sent_signals_cooldown:
                    last_sent = sent_signals_cooldown[symbol]
                    if now < last_sent + timedelta(hours=cooldown_hours):
                        continue

                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=210)
                if not ohlcv or len(ohlcv) < 200:
                    continue

                price, ema200, rsi, atr, is_vol_high = fetch_indicators(ohlcv)
                clean_symbol = symbol.replace("/", "")

                condition, signal_msg, reply_markup = analyze_market_regime(
                    clean_symbol, price, ema200, rsi, atr, is_vol_high
                )

                p_fmt = f"{price:.8f}" if price < 0.01 else f"{price:.4f}"
                logger.info(
                    f"📊 {clean_symbol}: Price={p_fmt}, VolHigh={is_vol_high} -> Signal: {condition}"
                )

                if condition and signal_msg:
                    # ارسال پیام به کانال (آیدی کانال خود را جایگزین کنید)
                    # await app.bot.send_message(
                    #     chat_id="@your_channel",
                    #     text=signal_msg,
                    #     parse_mode="Markdown",
                    #     reply_markup=reply_markup
                    # )
                    
                    # ثبت زمان ارسال جهت جلوگیری از سیگنال تکراری
                    sent_signals_cooldown[symbol] = now
                    logger.info(f"📣 Signal Sent for {clean_symbol} with UI buttons")

        except asyncio.CancelledError:
            logger.info("Signal monitor loop cancelled.")
            await exchange.close()
            break
        except Exception as e:
            logger.error(f"Error fetching data from exchange: {e}")

        await asyncio.sleep(60)

# ۵. اجرای برنامه
def main():
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(global_error_handler)
    app.add_handler(CallbackQueryHandler(callback_handler))

    loop = asyncio.get_event_loop()
    loop.create_task(channel_signal_monitor_loop(app))

    logger.info("🚀 Advanced Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()
