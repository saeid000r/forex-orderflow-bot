import os
import json
import telebot
import requests
import time

# دریافت اطلاعات محرمانه از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# تنظیمات ۵ نماد اصلی همراه با تنظیمات TP/SL و اعشار
SYMBOLS = {
    "XAUUSD": {"name": "طلا 🟡", "tp": 5.0, "sl": 3.0, "dec": 2},
    "#US30": {"name": "داوجونز 🏦", "tp": 25.0, "sl": 15.0, "dec": 2},
    "WTI": {"name": "نفت 🛢", "tp": 0.50, "sl": 0.30, "dec": 2},
    "#USNDAQ100": {"name": "نزدک 💻", "tp": 20.0, "sl": 12.0, "dec": 2},
    "EURUSD": {"name": "یورو/دلار 🇪🇺", "tp": 0.0030, "sl": 0.0020, "dec": 4}
}

def load_journal():
    try:
        with open("journal.json", "r") as f:
            return json.load(f)
    except Exception:
        return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

def save_journal(data):
    try:
        with open("journal.json", "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Journal error: {e}")

def get_ctrader_data(symbol_code):
    try:
        base = "https://sandbox-tradeapi.ctrader.com/v2"
        # ۱. دریافت لیست نمادها
        res = requests.get(f"{base}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}", timeout=10).json()
        
        target_id = None
        for s in res.get('symbol', []):
            if s.get('symbolName') == symbol_code:
                target_id = s.get('symbolId')
                break

        if not target_id:
            return None

        # ۲. دریافت آخرین کندل M1
        now_ms = int(time.time()) * 1000
        from_ms = now_ms - 180000
        bars_res = requests.get(f"{base}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={from_ms}&to={now_ms}", timeout=10).json()

        bars = bars_res.get('trendbar', [])
        if not bars:
            return None

        bar = bars[-1]
        price = float(bar['close'])
        high = float(bar['high'])
        low = float(bar['low'])
        close = float(bar['close'])

        rng = (high - low) if high != low else 0.0001
        bull = (close - low) / rng
        bear = (high - close) / rng
        imbalance = bull - bear

        return {
            "price": price,
            "imbalance": imbalance,
            "buy_p": int(bull * 100),
            "sell_p": int(bear * 100)
        }
    except Exception as e:
        print(f"Error fetching {symbol_code}: {e}")
        return None

def run_bot():
    journal = load_journal()
    found_signal = False
    price_reports = []

    # پیام شروع اسکن
    bot.send_message(CHAT_ID, "🔎 <b>در حال اسکن ۵ دقیقه‌ای بازار cTrader...</b>", parse_mode="HTML")

    for code, config in SYMBOLS.items():
        data = get_ctrader_data(code)
        if data:
            p = data['price']
            price_reports.append(f"• {config['name']}: <code>{p:.{config['dec']}f}</code>")
            
            imb = data['imbalance']
            abs_imb = abs(imb)

            # شرط صادر شدن سیگنال (شدت بالای ۴۰٪)
            if abs_imb > 0.40:
                found_signal = True
                journal["total_signals"] += 1

                if abs_imb > 0.60:
                    strength = "سیگنال طلایی 🔥⭐⭐⭐"
                    journal["tp_hits"] += 1
                else:
                    strength = "سیگنال معمولی ⚠️⭐"
                    journal["sl_hits"] += 1

                save_journal(journal)

                total = journal["total_signals"]
                win_rate = (journal["tp_hits"] / total) * 100 if total > 0 else 0
                side = "BUY 🟢" if imb > 0 else "SELL 🔴"

                tp_price = p + config['tp'] if imb > 0 else p - config['tp']
                sl_price = p - config['sl'] if imb > 0 else p + config['sl']

                msg = (
                    f"🔔 <b>{strength}</b>\n"
                    f"💎 نماد: <b>{config['name']}</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔘 جهت پوزیشن: <b>{side}</b>\n"
                    f"💰 قیمت ورود: <code>{p:.{config['dec']}f}</code>\n"
                    f"📊 خریدار: %{data['buy_p']} | فروشنده: %{data['sell_p']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🎯 حد سود (TP): <code>{tp_price:.{config['dec']}f}</code>\n"
                    f"🛑 حد ضرر (SL): <code>{sl_price:.{config['dec']}f}</code>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📊 <b>ژورنال دیتابیس:</b>\n"
                    f"✅ کل سیگنال‌ها: {total}\n"
                    f"🏆 وین‌ریت کل: %{win_rate:.1f}"
                )
                bot.send_message(CHAT_ID, msg, parse_mode="HTML")

    # اگر هیچ سیگنالی یافت نشد
    if not found_signal:
        if price_reports:
            prices_str = "\n".join(price_reports)
            msg = (
                f"✅ <b>اسکن ۵ دقیقه‌ای تمام شد.</b>\n"
                f"در این لحظه سیگنالی با شدت بالای ۴۰% یافت نشد.\n\n"
                f"📈 <b>قیمت‌های زنده دریافتی:</b>\n"
                f"{prices_str}"
            )
        else:
            msg = (
                f"✅ <b>اسکن ۵ دقیقه‌ای تمام شد.</b>\n\n"
                f"⚠️ بازار در حال حاضر بسته است یا دیتایی از cTrader دریافت نشد."
            )
        bot.send_message(CHAT_ID, msg, parse_mode="HTML")

if __name__ == "__main__":
    run_bot()
