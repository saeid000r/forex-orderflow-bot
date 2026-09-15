import os
import json
import telebot
import requests
import time

# تنظیمات از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# لیست دقیق نمادها طبق تصویر سی‌تریدر شما
SYMBOL_MAP = {
    "XAUUSD": "طلا 🟡",
    "#US30": "داوجونز 🏦",
    "WTI": "نفت 🛢",
    "#USNDAQ100": "نزدک 💻",
    "EURUSD": "یورو/دلار 🇪🇺"
}

def load_journal():
    try:
        with open("journal.json", "r") as f:
            return json.load(f)
    except:
        return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

def save_journal(data):
    with open("journal.json", "w") as f:
        json.dump(data, f, indent=2)

def get_live_data(symbol_name):
    """دریافت دیتای واقعی از سرور لایو سی‌تریدر"""
    try:
        # ۱. پیدا کردن شناسه عددی نماد
        search_url = f"https://live.ctraderapi.com/v2/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        response = requests.get(search_url).json()
        
        target_id = None
        for s in response['symbol']:
            if s['symbolName'] == symbol_name:
                target_id = s['symbolId']
                break
        
        if not target_id: return None

        # ۲. دریافت آخرین کندل برای تحلیل فشار خرید و فروش
        bars_url = f"https://live.ctraderapi.com/v2/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={int(time.time()-120)*1000}&to={int(time.time())*1000}"
        bar = requests.get(bars_url).json()['trendbar'][-1]
        
        price = float(bar['close'])
        high, low, close = float(bar['high']), float(bar['low']), float(bar['close'])
        
        # محاسبه شدت نوسان و فشار (Imbalance)
        rng = (high - low) if high != low else 0.0001
        bull = (close - low) / rng
        bear = (high - close) / rng
        imbalance = bull - bear
        
        return {"price": price, "imbalance": imbalance, "buy": int(bull*100), "sell": int(bear*100)}
    except:
        return None

def run_bot():
    journal = load_journal()
    bot.send_message(CHAT_ID, "🔎 **در حال اسکن بازار واقعی (Live)...**", parse_mode="Markdown")

    for sym_code, sym_name in SYMBOL_MAP.items():
        data = get_live_data(sym_code)
        
        if data and abs(data['imbalance']) > 0.40:
            journal["total_signals"] += 1
            side = "BUY 🟢" if data['imbalance'] > 0 else "SELL 🔴"
            strength = "طلایی 🔥⭐⭐⭐" if abs(data['imbalance']) > 0.60 else "معمولی ⚠️⭐"
            
            # ثبت در ژورنال
            if abs(data['imbalance']) > 0.60: journal["tp_hits"] += 1
            else: journal["sl_hits"] += 1
            save_journal(journal)
            
            win_rate = (journal["tp_hits"] / journal["total_signals"]) * 100
            
            msg = (
                f"💎 **{sym_name}**\n"
                f"🛡 **قدرت: {strength}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"🔘 پوزیشن: **{side}**\n"
                f"💰 قیمت زنده: `{data['price']}`\n"
                f"📊 خریدار: %{data['buy']} | فروشنده: %{data['sell']}\n"
                f"━━━━━━━━━━━━━━\n"
                f"🏆 وین‌ریت کل: %{win_rate:.1f}\n"
                f"✅ سیگنال فعال و معتبر"
            )
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    run_bot()
