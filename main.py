import os
import json
import requests
from tradingview_ta import TA_Handler, Interval

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
JOURNAL_FILE = "journal.json"

# تنظیمات دقیق نمادهای زنده بازار در TradingView
SYMBOLS_CONFIG = [
    {"symbol": "XAUUSD", "screener": "forex", "exchange": "OANDA", "display": "XAUUSD"},
    {"symbol": "US30", "screener": "america", "exchange": "CAPITALCOM", "display": "#US30"},
    {"symbol": "UKOIL", "screener": "cfd", "exchange": "TVC", "display": "BRENT"},
    {"symbol": "US100", "screener": "america", "exchange": "CAPITALCOM", "display": "#USNDAQ100"},
    {"symbol": "EURUSD", "screener": "forex", "exchange": "FX_IDC", "display": "EURUSD"}
]

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"total": 0, "tp": 0, "sl": 0, "active": []}

def save_journal(data):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=4)

def main():
    journal = load_journal()
    new_signals = []
    active_signals = []
    current_prices = {}

    # ۱. دریافت قیمت زنده از TradingView و محاسبه اوردر فلو
    for item in SYMBOLS_CONFIG:
        display_name = item["display"]
        try:
            handler = TA_Handler(
                symbol=item["symbol"],
                screener=item["screener"],
                exchange=item["exchange"],
                interval=Interval.INTERVAL_5_MINUTES
            )
            analysis = handler.get_analysis()
            indicators = analysis.indicators

            close = indicators["close"]
            high = indicators["high"]
            low = indicators["low"]

            current_prices[display_name] = close

            range_hl = high - low
            if range_hl == 0:
                continue

            # محاسبه میزان عدم تعادل عرضه و تقاضا (Order Flow Imbalance)
            bull_power = close - low
            bear_power = high - close
            imbalance = (bull_power / range_hl) - (bear_power / range_hl)

            signal_type = None
            strength = ""

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
                entry = close
                atr = range_hl if range_hl > 0 else entry * 0.001

                if signal_type == "BUY":
                    tp = entry + (atr * 2.0)
                    sl = entry - (atr * 1.0)
                else:
                    tp = entry - (atr * 2.0)
                    sl = entry + (atr * 1.0)

                new_signals.append({
                    "symbol": display_name,
                    "type": signal_type,
                    "strength": strength,
                    "entry": round(entry, 4),
                    "tp": round(tp, 4),
                    "sl": round(sl, 4)
                })
        except Exception as e:
            print(f"Error fetching {display_name}: {e}")

    # ۲. بررسی سیگنال‌های باز و ثبت سود/ضرر
    for sig in journal.get("active", []):
        sym = sig["symbol"]
        if sym not in current_prices:
            active_signals.append(sig)
            continue

        cp = current_prices[sym]
        if sig["type"] == "BUY":
            if cp >= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT! (سود شد)</b>\nSymbol: <b>{sym}</b>\nExit Price: {cp}")
            elif cp <= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT! (ضرر شد)</b>\nSymbol: <b>{sym}</b>\nExit Price: {cp}")
            else:
                active_signals.append(sig)
        else:  # SELL
            if cp <= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT! (سود شد)</b>\nSymbol: <b>{sym}</b>\nExit Price: {cp}")
            elif cp >= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT! (ضرر شد)</b>\nSymbol: <b>{sym}</b>\nExit Price: {cp}")
            else:
                active_signals.append(sig)

    # ۳. ارسال سیگنال جدید به تلگرام
    for sig in new_signals:
        is_duplicate = any(s["symbol"] == sig["symbol"] for s in active_signals)
        if is_duplicate:
            continue

        active_signals.append(sig)
        journal["total"] += 1

        closed_trades = journal["tp"] + journal["sl"]
        wr = (journal["tp"] / closed_trades * 100) if closed_trades > 0 else 0.0

        msg = f"{sig['strength']} SIGNAL\n\n"
        msg += f"Symbol: <b>{sig['symbol']}</b>\n"
        msg += f"Action: <b>{sig['type']}</b>\n"
        msg += f"Entry: <code>{sig['entry']}</code>\n"
        msg += f"TP: <code>{sig['tp']}</code>\n"
        msg += f"SL: <code>{sig['sl']}</code>\n\n"
        msg += f"📊 Win Rate: <b>{wr:.1f}%</b> (Trades: {closed_trades})"

        send_telegram(msg)

    journal["active"] = active_signals
    save_journal(journal)
    print("Scan finished successfully.")

if __name__ == "__main__":
    main()
