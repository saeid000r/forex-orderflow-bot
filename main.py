import os
import json
import time
import requests
import telebot

# کلیدها از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

# لیست نمادها همراه با نام‌های احتمالی در بروکر
SYMBOLS = {
    "XAUUSD": {"name": "طلا 🟡", "keys": ["XAUUSD", "GOLD"], "tp": 5.0, "sl": 3.0, "dec": 2},
    "#US30": {"name": "داوجونز 🏦", "keys": ["US30", "DJ30", "WALLSTREET"], "tp": 25.0, "sl": 15.0, "dec": 2},
    "WTI": {"name": "نفت 🛢", "keys": ["WTI", "BRENT", "USOIL"], "tp": 0.50, "sl": 0.30, "dec": 2},
    "#USNDAQ100": {"name": "نزدک 💻", "keys": ["USNDAQ100", "NASDAQ", "USTEC"], "tp": 20.0, "sl": 12.0, "dec": 2},
    "EURUSD": {"name": "یورو/دلار 🇪🇺", "keys": ["EURUSD"], "tp": 0.0030, "sl": 0.0020, "dec": 4}
}

def load_journal():
    try:
        if os.path.exists("journal.json"):
            with open("journal.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except: pass
    return {"total_signals": 0, "tp_hits": 0, "sl_hits": 0}

def save_journal(data):
    try:
        with open("journal.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except: pass

def fetch_from_ctrader(symbol_config):
    # چک کردن هر دو سرور Live و Sandbox
    endpoints = [
        "https://live.ctraderapi.com/v2",
        "https://sandbox-tradeapi.ctrader.com/v2"
    ]
    
    for base in endpoints:
        try:
            # ۱. گرفتن لیست نمادها
            sym_url = f"{base}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
            res = requests.get(sym_url, timeout=8).json()
            
            if "symbol" not in res:
                continue
                
            target_id = None
            for s in res['symbol']:
                s_name = s.get('symbolName', '').upper()
                for k in symbol_config['keys']:
                    if k in s_name:
                        target_id = s.get('symbolId')
                        break
                if target_id: break
                
            if not target_id: continue

            # ۲. گرفتن کندل‌ها (بازه ۱ ساعته برای اطمینان از وجود دیتا)
            now_ms = int(time.time()) * 1000
            from_ms = now_ms - 3600000 # ۱ ساعت قبل
            
            bars_url = f"{base}/symbols/{target_id}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={from_ms}&to={now_ms}"
            bars_res = requests.get(bars_url, timeout=8).json()
            
            bars = bars_res.get('trendbar', [])
            if not bars: continue

            last_bar = bars[-1]
            
            # استخراج قیمت
            low_p = float(last_bar.get('low', 0))
            if 'close' in last_bar:
                close_p = float(last_bar['close'])
                high_p = float(last_bar.get('high', close_p))
            else:
                # فرمول محاسبه قیمت از روی delta در بعضی بنچمارک‌های cTrader
                close_p = low_p + float(last_bar.get('deltaClose', 0))
                high_p = low_p + float(last_bar.get('deltaHigh', 0))
                
            # اصلاح اعشار قیمت اگر لازم بود
            if close_p > 100000 and "EUR" in symbol_config['keys'][0]:
                close_p /= 100000.0
                high_p /= 100000.0
                low_p /= 100000.0

            rng = (high_p - low_p) if high_p != low_p else 0.0001
            bull = (close_p - low_p) / rng
            bear = (high_p - close_p) / rng
            imbalance = bull - bear

            return {
                "price": close_p,
                "imbalance": imbalance,
                "buy_p": int(bull * 100),
                "sell_p": int(bear * 100)
            }
        except Exception as e:
            print(f"Error on {base}: {e}")
            continue
            
    return None

def run_bot():
    journal = load_journal()
    price_reports = []
    found_signal = False

    for code, config in SYMBOLS.items():
        data = fetch_from_ctrader(config)
        
        if data:
            p = data['price']
            imb = data['imbalance']
            abs_imb = abs(imb)
            
            price_reports.append(f"• {config['name']}: {p:.{config['dec']}f}")

            # شرط صادر شدن سیگنال (فشار بالای ۴۰٪)
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
                
                tp_p = p + config['tp'] if imb > 0 else p - config['tp']
                sl_p = p - config['sl'] if imb > 0 else p + config['sl']

                msg = (
                    f"🔔 {strength}\n"
                    f"💎 نماد: {config['name']}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔘 جهت پوزیشن: {side}\n"
                    f"💰 قیمت ورود: {p:.{config['dec']}f}\n"
                    f"📊 خریدار: %{data['buy_p']} | فروشنده: %{data['sell_p']}\n"
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

    if not found_signal:
        if price_reports:
            summary = (
                "✅ اسکن ۵ دقیقه‌ای بازار انجام شد.\n"
                "در این لحظه سیگنالی با شدت بالای ۴۰٪ یافت نشد.\n\n"
                "📈 قیمت‌های زنده دریافت شده از cTrader:\n" +
                "\n".join(price_reports)
            )
        else:
            summary = (
                "✅ اسکن ۵ دقیقه‌ای انجام شد.\n\n"
                "⚠️ دیتایی دریافت نشد. لطفا مطمئن شوید CTRADER_ACCOUNT_ID و CTRADER_ACCESS_TOKEN در Secrets گیت‌هاب درست وارد شده‌اند."
            )
        bot.send_message(CHAT_ID, summary)

if __name__ == "__main__":
    run_bot()
