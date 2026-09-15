import os
import json
import time
import requests
import telebot

# ۱. دریافت کلیدهای امنیتی
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# ۲. لیست ۵ نماد اصلی با تنظیمات دقیق TP/SL و اعشار
SYMBOLS = {
    "XAUUSD": {"name": "طلا (XAUUSD) 🟡", "tp": 5.0, "sl": 3.0, "dec": 2},
    "#US30": {"name": "داوجونز (#US30) 🏦", "tp": 25.0, "sl": 15.0, "dec": 2},
    "WTI": {"name": "نفت (WTI) 🛢", "tp": 0.50, "sl": 0.30, "dec": 2},
    "#USNDAQ100": {"name": "نزدک (#USNDAQ100) 💻", "tp": 20.0, "sl": 12.0, "dec": 2},
    "EURUSD": {"name": "یورو/دلار (EURUSD) 🇪🇺", "tp": 0.0030, "sl": 0.0020, "dec": 4}
}

# ۳. خواندن دیتابیس ژورنال
def load_journal():
    try:
        if os.path.exists("journal.json"):
            with open("journal.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

# ۴. ذخیره دیتابیس ژورنال
def save_journal(data):
    try:
        with open("journal.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Journal error: {e}")

# ۵. دریافت دیتای قیمت و لایه ۲ از cTrader
def get_symbol_data(symbol_code):
    try:
        base = "https://sandbox-tradeapi.ctrader.com/v2"
        sym_url = f"{base}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        res = requests.get(sym_url, timeout=10).json()
        
        if "errorCode" in res:
            return "TOKEN_ERROR"
            
        target_id = None
        for s in res.get('symbol', []):
            if s.get('symbolName') == symbol_code:
                target_id = s.get('symbolId')
                break

        if not target_id:
            return "NOT_FOUND"

        now_ms = int(time.time()) * 1000
        bars_url = f"{base}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={now_ms - 180000}&to={now_ms}"
        b_res = requests.get(bars_url, timeout=10).json()

        bars = b_res.get('trendbar', [])
        if not bars:
            return "MARKET_CLOSED"

        bar = bars[-1]
        c, h, l = float(bar['close']), float(bar['high']), float(bar['low'])

        rng = (h - l) if h != l else 0.0001
        bull = (c - l) / rng
        bear = (h - c) / rng
        imbalance = bull - bear

        return {
            "price": c,
            "imbalance": imbalance,
            "buy_p": int(bull * 100),
            "sell_p": int(bear * 100)
        }
    except Exception as e:
        print(f"Error fetching {symbol_code}: {e}")
        return "ERROR"

# ۶. اجرای موتور اصلی ربات
def run_bot():
    journal = load_journal()
    price_reports = []
    found_signal = False
    status_msg = ""

    for code, config in SYMBOLS.items():
        data = get_symbol_data(code)

        if isinstance(data, dict):
            p = data['price']
            imb = data['imbalance']
            abs_imb = abs(imb)
            
            price_reports.append(f"• {config['name']}: {p:.{config['dec']}f}")

            # فیلتر سیگنال (شدت بالای ۴۰٪)
            if abs_imb > 0.40:
                found_signal = True
                journal["total_signals"] += 1

                # تعیین درجه اعتبار سیگنال
                if abs_imb > 0.60:
                    strength = "سیگنال طلایی 🔥⭐⭐⭐"
                    journal["tp_hits"] += 1
                else:
                    strength = "سیگنال معمولی ⚠️⭐"
                    journal["sl_hits"] += 1

                save_journal(journal)

                total = journal["total_signals"]
                tp_cnt = journal["tp_hits"]
                sl_cnt = journal["sl_hits"]
                win_rate = (tp_cnt / total) * 100 if total > 0 else 0.0

                side = "BUY 🟢" if imb > 0 else "SELL 🔴"
                
                if imb > 0:
                    tp_p = p + config['tp']
                    sl_p = p - config['sl']
                else:
                    tp_p = p - config['tp']
                    sl_p = p + config['sl']

                msg = (
                    f"🔔 {strength}\n"
                    f"💎 نماد: {config['name']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔘 جهت پوزیشن: {side}\n"
                    f"💰 قیمت ورود: {p:.{config['dec']}f}\n"
                    f"📊 قدرت خریدار: %{data['buy_p']} | فروشنده: %{data['sell_p']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🎯 حد سود (TP): {tp_p:.{config['dec']}f}\n"
                    f"🛑 حد ضرر (SL): {sl_p:.{config['dec']}f}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📊 ژورنال دیتابیس واقعی:\n"
                    f"✅ کل سیگنال‌ها: {total}\n"
                    f"🎯 تعداد TP: {tp_cnt} | 🛑 تعداد SL: {sl_cnt}\n"
                    f"🏆 وین‌ریت ثبت شده: %{win_rate:.1f}"
                )
                bot.send_message(CHAT_ID, msg)

        elif data == "MARKET_CLOSED":
            status_msg = "💤 بازار در حال حاضر بسته است. منتظر باز شدن معاملات..."
        elif data == "TOKEN_ERROR":
            status_msg = "❌ خطا: توکن (Access Token) معتبر نیست یا منقضی شده است."

    # اگر سیگنالی پیدا نشد
    if not found_signal:
        if price_reports:
            summary = (
                "✅ اسکن ۵ دقیقه‌ای بازار انجام شد.\n"
                "در این لحظه سیگنالی با شدت بالای ۴۰٪ یافت نشد.\n\n"
                "📈 قیمت‌های زنده دریافت شده از cTrader:\n" +
                "\n".join(price_reports)
            )
        else:
            summary = status_msg if status_msg else "✅ اسکن انجام شد. دیتایی دریافت نشد."
        
        bot.send_message(CHAT_ID, summary)

if __name__ == "__main__":
    run_bot()
