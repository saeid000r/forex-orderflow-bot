import os
import json
import requests
import yfinance as yf

# دریافت توکن‌های تلگرام از سکرت‌های گیت‌هاب
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
JOURNAL_FILE = "journal.json"

# اتصال دیتای جهانی به نام‌های دقیق بروکر cTrader شما
SYMBOLS = {
    "XAUUSD=X": "XAUUSD",
    "^DJI": "#US30",
    "BZ=F": "BRENT",
    "^NDX": "#USNDAQ100",
    "EURUSD=X": "EURUSD"
}

def send_telegram(text):
    """ارسال پیام به تلگرام با فرمت HTML برای جلوگیری از ارور هشتگ"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    return {"total": 0, "tp": 0, "sl": 0, "active": []}

def save_journal(data):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=4)

def main():
    journal = load_journal()
    new_signals = []
    active_signals = []
    current_prices = {}

    # ۱. دریافت دیتای لحظه‌ای و محاسبه استراتژی
    for ticker, ctrader_name in SYMBOLS.items():
        try:
            # دریافت کندل‌های 5 دقیقه‌ای
            df = yf.Ticker(ticker).history(period="1d", interval="5m")
            if df.empty or len(df) < 2: 
                continue
            
            last_closed = df.iloc[-2] # آخرین کندل کامل بسته شده
            current_price = df.iloc[-1]['Close'] # قیمت دقیق همین لحظه
            
            high = last_closed['High']
            low = last_closed['Low']
            close = last_closed['Close']
            
            current_prices[ctrader_name] = current_price
            
            if high - low == 0: continue
            
            # محاسبه فرمول Order Flow Imbalance (اوردر فلو)
            bull_power = close - low
            bear_power = high - close
            range_hl = high - low
            imbalance = (bull_power / range_hl) - (bear_power / range_hl)
            
            signal_type = None
            strength = ""
            
            # شرایط سیگنال (40% نرمال - 60% طلایی)
            if imbalance >= 0.60:
                signal_type = "BUY"
                strength = "🔥 <b>Golden</b> 🔥"
            elif imbalance >= 0.40:
                signal_type = "BUY"
                strength = "🟢 <b>Normal</b>"
            elif imbalance <= -0.60:
                signal_type = "SELL"
                strength = "🔥 <b>Golden</b> 🔥"
            elif imbalance <= -0.40:
                signal_type = "SELL"
                strength = "🔴 <b>Normal</b>"

            if signal_type:
                # محاسبه حد سود و ضرر بر اساس نوسان کندل
                atr = range_hl
                if atr == 0: atr = current_price * 0.001
                
                entry = current_price
                if signal_type == "BUY":
                    tp = entry + (atr * 2.5)
                    sl = entry - (atr * 1.5)
                else:
                    tp = entry - (atr * 2.5)
                    sl = entry + (atr * 1.5)
                    
                new_signals.append({
                    "symbol": ctrader_name,
                    "type": signal_type,
                    "strength": strength,
                    "entry": round(entry, 4),
                    "tp": round(tp, 4),
                    "sl": round(sl, 4)
                })

        except Exception as e:
            print(f"Error on {ctrader_name}: {e}")

    # ۲. بررسی سیگنال‌های باز قبلی (آیا تی‌پی یا استاپ خورده‌اند؟)
    for sig in journal["active"]:
        sym = sig["symbol"]
        if sym not in current_prices:
            active_signals.append(sig)
            continue
            
        cp = current_prices[sym]
        if sig["type"] == "BUY":
            if cp >= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT! (سود شد)</b>\nSymbol: {sym} (BUY)\nPrice: {cp}")
            elif cp <= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT! (ضرر شد)</b>\nSymbol: {sym} (BUY)\nPrice: {cp}")
            else:
                active_signals.append(sig)
        else: # SELL
            if cp <= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT! (سود شد)</b>\nSymbol: {sym} (SELL)\nPrice: {cp}")
            elif cp >= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT! (ضرر شد)</b>\nSymbol: {sym} (SELL)\nPrice: {cp}")
            else:
                active_signals.append(sig)

    # ۳. ارسال سیگنال‌های جدید و محاسبه وین‌ریت
    for sig in new_signals:
        # جلوگیری از ارسال سیگنال تکراری برای یک ارز
        is_duplicate = any(s["symbol"] == sig["symbol"] for s in active_signals)
        if is_duplicate: continue

        active_signals.append(sig)
        journal["total"] += 1
        
        # محاسبه دقیق وین ریت
        wr = 0
        closed_trades = journal["tp"] + journal["sl"]
        if closed_trades > 0:
            wr = (journal["tp"] / closed_trades) * 100
            
        msg = f"{sig['strength']} SIGNAL\n\n"
        msg += f"Symbol: <b>{sig['symbol']}</b>\n"
        msg += f"Action: <b>{sig['type']}</b>\n"
        msg += f"Entry: <code>{sig['entry']}</code>\n"
        msg += f"TP: <code>{sig['tp']}</code>\n"
        msg += f"SL: <code>{sig['sl']}</code>\n\n"
        msg += f"📊 Win Rate: <b>{wr:.1f}%</b> (Trades: {closed_trades})"
        
        send_telegram(msg)

    # ۴. ذخیره وضعیت جدید در فایل
    journal["active"] = active_signals
    save_journal(journal)
    print("Scan completed successfully.")

if __name__ == "__main__":
    main()
