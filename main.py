import os
import json
import requests
import sys
from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, TcpProtocol

# سیستم هوشمند برای پیدا کردن ماژول‌های گم‌شده cTrader
def get_ctrader_msg(name):
    import importlib
    variations = [
        f"ctrader_open_api.messages.{name}_pb2",
        f"ctrader_open_api.messages.{name}",
        f"messages.{name}_pb2",
        f"{name}_pb2"
    ]
    for var in variations:
        try:
            mod = importlib.import_module(var)
            return getattr(mod, name)
        except:
            continue
    return None

# لود کردن ماژول‌ها
ProtoOAApplicationAuthReq = get_ctrader_msg("ProtoOAApplicationAuthReq")
ProtoOAAccountAuthReq = get_ctrader_msg("ProtoOAAccountAuthReq")
ProtoOASymbolsListReq = get_ctrader_msg("ProtoOASymbolsListReq")
ProtoOAGetDepthQuotesReq = get_ctrader_msg("ProtoOAGetDepthQuotesReq")

# بررسی نهایی برای جلوگیری از کرش
if not ProtoOAApplicationAuthReq:
    print("Error: Could not load cTrader message modules. Package structure is incompatible.")
    sys.exit(1)

# تنظیمات اصلی
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))
JOURNAL_FILE = "journal.json"
TARGET_SYMBOLS = ["XAUUSD", "US30", "BRENT", "USNDAQ100", "EURUSD"]

client = Client(EndPoints.PROTOBUF_SANDBOX_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
symbol_map, symbol_names, depth_results = {}, {}, {}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, "r") as f: return json.load(f)
    return {"total": 0, "tp": 0, "sl": 0, "active": []}

def process_and_finish():
    journal = load_journal()
    active_signals, current_prices = [], {}

    for sym_id, depth in depth_results.items():
        sym_name = symbol_names.get(sym_id, "")
        bids, asks = depth.bids, depth.asks
        if not bids or not asks: continue

        v_bid = sum(b.volume for b in bids)
        v_ask = sum(a.volume for a in asks)
        price = (bids[0].price + asks[0].price) / 200000.0 if bids[0].price > 1000 else (bids[0].price + asks[0].price) / 2.0
        current_prices[sym_name] = price
        
        imbalance = (v_bid - v_ask) / (v_bid + v_ask)
        signal = "BUY" if imbalance > 0.4 else "SELL" if imbalance < -0.4 else None
        
        if signal:
            is_dup = any(s["symbol"] == sym_name for s in journal["active"])
            if not is_dup:
                tp = price + (price*0.002) if signal=="BUY" else price - (price*0.002)
                sl = price - (price*0.001) if signal=="BUY" else price + (price*0.001)
                new_sig = {"symbol": sym_name, "type": signal, "entry": round(price,4), "tp": round(tp,4), "sl": round(sl,4)}
                journal["active"].append(new_sig)
                journal["total"] += 1
                send_telegram(f"<b>L2 {signal}</b>\nSym: {sym_name}\nPrice: {price}\nImb: {round(imbalance*100)}%")

    # چک کردن TP/SL
    for s in journal["active"]:
        if s["symbol"] in current_prices:
            cp = current_prices[s["symbol"]]
            if (s["type"]=="BUY" and cp>=s["tp"]) or (s["type"]=="SELL" and cp<=s["tp"]):
                journal["tp"]+=1
                send_telegram(f"✅ TP: {s['symbol']}")
            elif (s["type"]=="BUY" and cp<=s["sl"]) or (s["type"]=="SELL" and cp>=s["sl"]):
                journal["sl"]+=1
                send_telegram(f"❌ SL: {s['symbol']}")
            else: active_signals.append(s)
    
    journal["active"] = active_signals
    with open(JOURNAL_FILE, "w") as f: json.dump(journal, f, indent=4)
    if reactor.running: reactor.stop()

def on_connected(client):
    req = ProtoOAApplicationAuthReq(); req.clientId = CLIENT_ID; req.clientSecret = CLIENT_SECRET
    client.send(req).addCallback(on_app_auth)

def on_app_auth(res):
    req = ProtoOAAccountAuthReq(); req.accessToken = ACCESS_TOKEN; req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(on_account_auth)

def on_account_auth(res):
    req = ProtoOASymbolsListReq(); req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(on_symbols_list)

def on_symbols_list(res):
    for s in res.symbol:
        name = s.symbolName.replace("#", "")
        for t in TARGET_SYMBOLS:
            if t in name: symbol_map[t]=s.symbolId; symbol_names[s.symbolId]=s.symbolName
    fetch_all_depth(list(symbol_map.values()))

def fetch_all_depth(ids):
    if not ids: process_and_finish(); return
    sid = ids.pop(0)
    req = ProtoOAGetDepthQuotesReq(); req.ctidTraderAccountId = ACCOUNT_ID; req.symbolId = sid
    client.send(req).addCallback(lambda r: (depth_results.update({sid: r}), fetch_all_depth(ids)))

client.setConnectedCallback(on_connected)
client.startService()
reactor.run()
