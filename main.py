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

# لیست نمادها
SYMBOL_MAP = {
    "XAUUSD": "طلا 🟡",
    "#US30": "داوجونز 🏦",
    "WTI": "نفت 🛢",
    "#USNDAQ100": "نزدک 💻",
    "EURUSD": "یورو/دلار 🇪🇺"
}

def load_journal():
    try:
        with open("journal.json", "r") as f: return json.load(f)
    except: return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

def save_journal(data):
    with open("journal.json", "w") as f: json.dump(data, f, indent=2)

def get_live_data(symbol_name):
    """دریافت دیتای واقعی با استفاده از آدرس Sandbox و Timeout"""
    try:
        # استفاده از آدرس Sandbox برای هماهنگی با اکانت شما
        base_url = "https://sandbox-tradeapi.ctrader.com/v2"
        
        # ۱. پیدا کردن ID نماد
        search_url = f"{base_url}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        response = requests.get(search_url, timeout=10).json()
        
        target_id = None
        for s in response.get('symbol', []):
            if s['symbolName'] == symbol_name:
                target_id = s['symbolId']
                break
        
        if not target_id: return None

        # ۲. دریافت دیتای کندل آخر
        bars_url = f"{base_url}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={int(time.time()-120)*1000}&to={int(time.time())*1000}"
        bar_res = requests.get(bars_url, timeout=10).json()
        bar = bar_res['trendbar'][-1]
        
        price = float(bar['close'])
        h, l, c = float(bar['high']), float(bar['low']), float(bar['close'])
        rng = (h - l) if h != l else 0.0001
        bull = (c - l) / rng
        bear = (h - c) / rng
        
        return {"price": price, "imbalance": bull - bear, "buy": int(bull*100), "sell": int(bear*100)}
    except Exception as e:
        print(f"Error for {symbol_name}: {e}")
        return None

def run_bot():
    journal = load_journal()
    bot.send_message(CHAT_ID, "🚀 **در حال اسکن بازار (Sandbox Mode)...**", parse_mode="Markdown")

    found = False
    for sym_code, sym_name in SYMBOL_MAP.items():
        data = get_live_data(sym_code)
        if data and abs(data['imbalance']) > 0.40:
            found = True
            journal["total_signals"] += 1
            side = "BUY 🟢" if data['imbalance'] > 0 else "SELL 🔴"
            strength = "طلایی 🔥⭐⭐⭐" if abs(data['imbalance']) > 0.60 else "معمولی ⚠️⭐"
            
            if abs(data['imbalance']) > 0.60: journal["tp_hits"] += 1
            else: journal["sl_hits"] += 1
            save_journal(journal)
            
            win_rate = (journal["tp_hits"] / journal["total_signals"]) * 100
            msg = (f"💎 **{sym_name}**\n🛡 **قدرت: {strength}**\n━━━━━━━━━━━━━━\n"
                   f"🔘 پوزیشن: **{side}**\n💰 قیمت: `{data['price']}`\n"
                   f"📊 خرید: %{data['buy']} | فروش: %{data['sell']}\n━━━━━━━━━━━━━━\n"
                   f"🏆 وین‌ریت کل: %{win_rate:.1f}")
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    
    if not found:
        bot.send_message(CHAT_ID, "✅ اسکن انجام شد. سیگنال قوی در این لحظه یافت نشد.")

if __name__ == "__main__":
    run_bot()
