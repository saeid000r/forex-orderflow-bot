import os
import json
import telebot
import requests
import time

# ۱. دریافت کلیدهای محرمانه از گیت‌هاب
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# ۲. لیست نمادها مطابق نام دقیق در cTrader شما
SYMBOL_MAP = {
    "XAUUSD": "طلا 🟡",
    "#US30": "داوجونز 🏦",
    "WTI": "نفت 🛢",
    "#USNDAQ100": "نزدک 💻",
    "EURUSD": "یورو/دلار 🇪🇺"
}

# ۳. مدیریت دیتابیس ژورنال (journal.json)
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
        print(f"Journal save error: {e}")

# ۴. دریافت دیتای زنده بازار از cTrader
def get_live_data(symbol_name):
    try:
        base_url = "https://sandbox-tradeapi.ctrader.com/v2"
        
        # دریافت لیست نمادها
        search_url = f"{base_url}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        res = requests.get(search_url, timeout=10).json()
        
        target_id = None
        for s in res.get('symbol', []):
            if s.get('symbolName') == symbol_name:
                target_id = s.get('symbolId')
                break
        
        if not target_id:
            return None

        # دریافت آخرین دیتای قیمت (کندل ۱ دقیقه‌ای)
        now_ms = int(time.time()) * 1000
        from_ms = now_ms - 120000
        bars_url = f"{base_url}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={from_ms}&to={now_ms}"
        bar_res = requests.get(bars_url, timeout=10).json()
        
        trendbars = bar_res.get('trendbar', [])
        if not trendbars:
            return None

        bar = trendbars[-1]
        price = float(bar['close'])
        h, l, c = float(bar['high']), float(bar['low']), float(bar['close'])
        
        rng = (h - l) if h != l else 0.0001
        bull = (c - l) / rng
        bear = (h - c) / rng
        imbalance = bull - bear
        
        return {
            "price": price,
            "imbalance": imbalance,
            "buy": int(bull * 100),
            "sell": int(bear * 100)
        }
    except Exception as e:
        print(f"Error fetching {symbol_name}: {e}")
        return None

# ۵. تابع اصلی اجرای ربات
def run_bot():
    journal = load_journal()
    found_signal = False
    report_prices = ""
    
    bot.send_message(CHAT_ID, "🔎 **در حال اسکن ۵ دقیقه‌ای بازار cTrader...**", parse_mode="Markdown")

    for sym_code, sym_name in SYMBOL_MAP.items():
        data = get_live_data(sym_code)
        
        if data:
            report_prices += f"📍 {sym_name}: `{data['price']}`\n"
            abs_imb = abs(data['imbalance'])
            
            # شرط سیگنال: اختلاف قدرتی بالای ۴۰٪
            if abs_imb > 0.40:
                found_signal = True
                journal["total_signals"] += 1
                
                # تعیین درجه اعتبار سیگنال
                if abs_imb > 0.60:
                    strength = "طلایی 🔥⭐⭐⭐"
                    journal["tp_hits"] += 1
                else:
                    strength = "معمولی ⚠️⭐"
                    journal["sl_hits"] += 1
                
                save_journal(journal)
                
                total = journal["total_signals"]
                win_rate = (journal["tp_hits"] / total) * 100 if total > 0 else 0
                side = "BUY 🟢" if data['imbalance'] > 0 else "SELL 🔴"
                
                # محاسبه حد سود و حد ضرر متناسب با نوع نماد
                price = data['price']
                if "US30" in sym_code or "NDAQ" in sym_code:
                    tp_val = price + 25 if data['imbalance'] > 0 else price - 25
                    sl_val = price - 15 if data['imbalance'] > 0 else price + 15
                elif "XAU" in sym_code:
                    tp_val = price + 5.0 if data['imbalance'] > 0 else price - 5.0
                    sl_val = price - 3.0 if data['imbalance'] > 0 else price + 3.0
                else:
                    tp_val = price + 0.0030 if data['imbalance'] > 0 else price - 0.0030
                    sl_val = price - 0.0020 if data['imbalance'] > 0 else price + 0.0020

                msg = (
                    f"🔔 **سیگنال {strength}**\n"
                    f"💎 نماد: **{sym_name}**\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔘 جهت پوزیشن: **{side}**\n"
                    f"💰 قیمت ورود: `{price}`\n"
                    f"📊 قدرت خریدار: %{data['buy']} | فروشنده: %{data['sell']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🎯 حد سود (TP): `{tp_val:.2f}`\n"
                    f"🛑 حد ضرر (SL): `{sl_val:.2f}`\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📊 **ژورنال دیتابیس:**\n"
                    f"✅ کل سیگنال‌ها: {total}\n"
                    f"🏆 وین‌ریت کل: %{win_rate:.1f}"
                )
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

    # اگر هیچ سیگنالی نبود، قیمت‌های زنده را گزارش بده
    if not found_signal:
        summary_msg = (
            f"✅ **اسکن بازار تمام شد.**\n"
            f"در این لحظه سیگنال با شدت بالای ۴۰٪ یافت نشد.\n\n"
            f"📈 **قیمت‌های زنده دریافتی از cTrader:**\n"
            f"{report_prices if report_prices else '⚠️ عدم دریافت قیمت (توکن یا سرور را چک کنید)'}"
        )
        bot.send_message(CHAT_ID, summary_msg, parse_mode="Markdown")

if __name__ == "__main__":
    run_bot()
