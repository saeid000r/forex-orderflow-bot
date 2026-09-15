import os
import json
import requests
import sys
from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, TcpProtocol

# لود کردن ماژول‌ها با آدرس‌دهی مستقیم و اصلاح شده
try:
    from ctrader_open_api.messages.ProtoOAApplicationAuthReq_pb2 import ProtoOAApplicationAuthReq
    from ctrader_open_api.messages.ProtoOAAccountAuthReq_pb2 import ProtoOAAccountAuthReq
    from ctrader_open_api.messages.ProtoOASymbolsListReq_pb2 import ProtoOASymbolsListReq
    from ctrader_open_api.messages.ProtoOAGetDepthQuotesReq_pb2 import ProtoOAGetDepthQuotesReq
except:
    print("Error: Library path issues. Please check requirements.")
    sys.exit(1)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))

JOURNAL_FILE = "journal.json"
TARGET_SYMBOLS = ["XAUUSD", "US30", "BRENT", "USNDAQ100", "EURUSD"]

# اصلاح نام هاست طبق پیشنهاد سیستم (DEMO بجای SANDBOX)
HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT

client = Client(HOST, PORT, TcpProtocol)
symbol_map, symbol_names, depth_results = {}, {}, {}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try: requests.post(url, data=payload, timeout=10)
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
        # قیمت لحظه‌ای از لول ۲
        p_bid = bids[0].price / 100000.0 if bids[0].price > 100000 else bids[0].price
        p_ask = asks[0].price / 100000.0 if asks[0].price > 100000 else asks[0].price
        price = (p_bid + p_ask) / 2.0
        current_prices[sym_name] = price
        
        imbalance = (v_bid - v_ask) / (v_bid + v_ask)
        
        signal = None
        if imbalance >= 0.40: signal = "BUY"
        elif imbalance <= -0.40: signal = "SELL"
        
        if signal:
            is_dup = any(s["symbol"] == sym_name for s in journal["active"])
            if not is_dup:
                tp = price + (price*0.002) if signal=="BUY" else price - (price*0.002)
                sl = price - (price*0.001) if signal=="BUY" else price + (price*0.001)
                journal["active"].append({"symbol": sym_name, "type": signal, "tp": round(tp,5), "sl": round(sl,5)})
                journal["total"] += 1
                msg = f"<b>{'🔥 Golden' if abs(imbalance)>0.6 else '🟢 Normal'} {signal}</b>\n"
                msg += f"Symbol: {sym_name}\nImbalance: {round(imbalance*100)}%\nPrice: {round(price,5)}"
                send_telegram(msg)

    # بررسی TP/SL
    for s in journal["active"]:
        if s["symbol"] in current_prices:
            cp = current_prices[s["symbol"]]
            if (s["type"]=="BUY" and cp>=s["tp"]) or (s["type"]=="SELL" and cp<=s["tp"]):
                journal["tp"]+=1
                send_telegram(f"✅ TP HIT: {s['symbol']}")
            elif (s["type"]=="BUY" and cp<=s["sl"]) or (s["type"]=="SELL" and cp>=s["sl"]):
                journal["sl"]+=1
                send_telegram(f"❌ SL HIT: {s['symbol']}")
            else: active_signals.append(s)
    
    journal["active"] = active_signals
    with open(JOURNAL_FILE, "w") as f: json.dump(journal, f, indent=4)
    if reactor.running: reactor.stop()

def on_connected(client):
    req = ProtoOAApplicationAuthReq(); req.clientId = CLIENT_ID; req.clientSecret = CLIENT_SECRET
    client.send(req).addCallback(lambda r: authenticate_account())

def authenticate_account():
    req = ProtoOAAccountAuthReq(); req.accessToken = ACCESS_TOKEN; req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(lambda r: get_symbols())

def get_symbols():
    req = ProtoOASymbolsListReq(); req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(on_symbols_list)

def on_symbols_list(res):
    for s in res.symbol:
        name = s.symbolName.replace("#", "")
        for t in TARGET_SYMBOLS:
            if t in name: symbol_map[t]=s.symbolId; symbol_names[s.symbolId]=s.symbolName
    fetch_depths(list(symbol_map.values()))

def fetch_depths(ids):
    if not ids: process_and_finish(); return
    sid = ids.pop(0)
    req = ProtoOAGetDepthQuotesReq(); req.ctidTraderAccountId = ACCOUNT_ID; req.symbolId = sid
    client.send(req).addCallback(lambda r: (depth_results.update({sid: r}), fetch_depths(ids))).addErrback(lambda e: fetch_depths(ids))

client.setConnectedCallback(on_connected)
client.startService()
reactor.run()
