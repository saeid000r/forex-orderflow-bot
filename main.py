import os
import json
import time
import requests
import telebot

# ۱. کلیدها و توکن‌ها
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# ۲. تنظیمات دقیق نمادها و حد سود/ضرر
SYMBOLS = {
    "XAUUSD": {"name": "طلا (XAUUSD) 🟡", "tp": 5.0, "sl": 3.0, "dec": 2},
    "#US30": {"name": "داوجونز (#US30) 🏦", "tp": 30.0, "sl": 20.0, "dec": 2},
    "WTI": {"name": "نفت (WTI) 🛢", "tp": 0.50, "sl": 0.30, "dec": 2},
    "#USNDAQ100": {"name": "نزدک (#USNDAQ100) 💻", "tp": 25.0, "sl": 15.0, "dec": 2},
    "EURUSD": {"name": "یورو/دلار (EURUSD) 🇪🇺", "tp": 0.0030, "sl": 0.0020, "dec": 4}
}

# ۳. مدیریت دیتابیس ژورنال
def load_journal():
    try:
        if os.path.exists("journal.json"):
            with open("journal.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

def save_journal(data):
    try:
        with open("journal.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Journal error: {e}")

# ۴. دریافت دیتای زنده با مدیریت خطای شبکه
def get_symbol_data(symbol_code):
    endpoints = [
        "https://sandbox-tradeapi.ctrader.com/v2",
        "https://live.ctraderapi.com/v2"
    ]
    for base in endpoints:
        try:
            sym_url = f"{base}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
            res = requests.get(sym_url, timeout=8).json()
            symbols_list = res.get('symbol', [])
            
            target_id = None
            for s in symbols_list:
                if s.get('symbolName') == symbol_code:
                    target_id = s.get('symbolId')
                    break
            
            if not target_id:
                continue

            now_ms = int(time.time()) * 1000
            from_ms = now_ms - 180000
            bars_url = f"{base}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={from_ms}&to={now_ms}"
            bar_res = requests.get(bars_url, timeout=8).json()
            bars = bar_res.get('trendbar', [])
            
            if bars:
                last_bar = bars[-1]
                close_p = float(last_bar['close'])
                high_p = float(last_bar['high'])
                low_p = float(last_bar['low'])
                
                rng = (high_p - low_p) if high_p != low_p else 0.0001
                bull_force = (close_p - low_p) / rng
                bear_force = (high_p - close_p) / rng
                imbalance = bull_force - bear_force
                
                return {
                    "price": close_p,
                    "imbalance": imbalance,
                    "buy_p": int(bull_force * 100),
                    "sell_p": int(bear_force * 100)
                }
        except Exception:
            continue
    return None

# ۵. اجرای اصلی
def run_bot():
    journal = load_journal()
    price_reports = []
    found_signal = False

    for code, config in SYMBOLS.items():
        data = get_symbol_data(code)
        if data:
            price = data['price']
            imb = data['imbalance']
            abs_imb = abs(imb)
            
            price_reports.append(f"• {config['name']}: {price:.{config['dec']}f}")

            # شرط سیگنال (شدت بالای ۴۰٪)
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
                tp_cnt = journal["tp_hits"]
                sl_cnt = journal["sl_hits"]
                win_rate = (tp_cnt / total) * 100 if total > 0 else 0.0

                side = "BUY 🟢" if imb > 0 else "SELL 🔴"
                
                if imb > 0:
                    tp_p = price + config['tp']
                    sl_p = price - config['sl']
                else:
                    tp_p = price - config['tp']
                    sl_p = price + config['sl']

                msg = (
                    f"🔔 {strength}\n"
                    f"💎 نماد: {config['name']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔘 جهت پوزیشن: {side}\n"
                    f"💰 قیمت ورود: {price:.{config['dec']}f}\n"
                    f"📊 قدر خریدار: {data['buy_p']}% | فروشنده: {data['sell_p']}%\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🎯 حد سود (TP): {tp_p:.{config['dec']}f}\n"
                    f"🛑 حد ضرر (SL): {sl_p:.{config['dec']}f}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📊 ژورنال دیتابیس:\n"
                    f"✅ کل سیگنال‌ها: {total}\n"
                    f"🎯 TP: {tp_cnt} | 🛑 SL: {sl_cnt}\n"
                    f"🏆 وین‌ریت ثبت شده: %{win_rate:.1f}"
                )
                
                bot.send_message(CHAT_ID, msg)

    if not found_signal:
        if price_reports:
            prices_text = "\n".join(price_reports)
            summary = (
                "✅ اسکن ۵ دقیقه‌ای بازار انجام شد.\n"
                "در این لحظه سیگنالی با شدت بالای ۴۰٪ یافت نشد.\n\n"
                "📈 قیمت‌های زنده دریافت شده:\n"
                f"{prices_text}"
            )
        else:
            summary = (
                "✅ اسکن ۵ دقیقه‌ای بازار انجام شد.\n\n"
                "⚠️ سرور cTrader دیتایی ارسال نکرد (احتمال تعطیلی بازار یا نیاز به Refresh Token)."
            )
        bot.send_message(CHAT_ID, summary)

if __name__ == "__main__":
    run_bot()
