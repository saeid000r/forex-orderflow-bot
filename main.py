import os
import json
import telebot
import requests
import time

# دریافت اطلاعات از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# نام نمادها
SYMBOL_MAP = {
    "XAUUSD": "GOLD",
    "#US30": "Dow Jones",
    "WTI": "WTI Oil",
    "#USNDAQ100": "Nasdaq",
    "EURUSD": "EUR/USD"
}

def load_journal():
    try:
        with open("journal.json", "r") as f: return json.load(f)
    except: return {"total": 0, "tp": 0, "sl": 0}

def save_journal(data):
    with open("journal.json", "w") as f: json.dump(data, f)

def get_data(sym_name):
    try:
        base = "https://sandbox-tradeapi.ctrader.com/v2"
        # پیدا کردن ID
        r = requests.get(f"{base}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}", timeout=10).json()
        sid = next((s['symbolId'] for s in r.get('symbol', []) if s['symbolName'] == sym_name), None)
        if not sid: return None
        
        # دریافت قیمت
        b = requests.get(f"{base}/symbols/{sid}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={int(time.time()-120)*1000}&to={int(time.time())*1000}", timeout=10).json()
        bar = b['trendbar'][-1]
        c, h, l = float(bar['close']), float(bar['high']), float(bar['low'])
        rng = (h - l) if h != l else 0.0001
        imb = ((c - l) / rng) - ((h - c) / rng)
        return {"p": c, "imb": imb}
    except: return None

def run():
    j = load_journal()
    found = False
    report = "SCAN REPORT:\n"
    
    for code, name in SYMBOL_MAP.items():
        d = get_data(code)
        if d:
            report += f"- {name}: {d['p']}\n"
            if abs(d['imb']) > 0.40:
                found = True
                j["total"] += 1
                side = "BUY" if d['imb'] > 0 else "SELL"
                if abs(d['imb']) > 0.60: j["tp"] += 1
                else: j["sl"] += 1
                save_journal(j)
                
                wr = (j["tp"] / j["total"]) * 100
                msg = (f"SIGNAL: {name}\nTYPE: {side}\nPRICE: {d['p']}\n"
                       f"WINRATE: {wr:.1f}%\nTOTAL: {j['total']}")
                bot.send_message(CHAT_ID, msg) # بدون Markdown برای جلوگیری از ارور
                
    if not found:
        bot.send_message(CHAT_ID, report + "\nNo Signal Found.")

if __name__ == "__main__":
    run()
