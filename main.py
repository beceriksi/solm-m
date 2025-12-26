import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

NETWORKS = ["solana"]

# Likidite
LIQ_MIN = 8000
LIQ_MAX = 35000

# FDV segmentleri
FDV_EARLY_MIN = 50000
FDV_CORE_MIN = 100000
FDV_SAFE_MIN = 150000
FDV_MAX = 500000

# Sabit (DEĞİŞMEDİ)
TXNS24_MIN = 40

VOL_LIQ_MIN_CORE = 0.5
VOL_LIQ_MIN_EARLY = 0.8

MAX_AGE_HOURS = 24

STATE_PATH = ".cache/state.json"
GT_BASE = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "solana-meme-bot/FINAL"}

TR_OFFSET = 3

# ===================== YARDIMCILAR =====================
def now_utc():
    return datetime.now(timezone.utc)

def now_tr():
    return now_utc() + timedelta(hours=TR_OFFSET)

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True})

def gt_get(path):
    try:
        r = requests.get(GT_BASE + path, headers=UA, timeout=15)
        if r.status_code == 200:
            return r.json().get("data", [])
    except:
        pass
    return []

def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except:
        return {
            "sent": {},
            "pending": {},
            "hb": {}
        }

def save_state(s):
    os.makedirs(".cache", exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(s, f)

# ===================== SOLANA RPC =====================
def sol_rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC_URL, json=payload, timeout=15)
    return r.json()

def mint_security(ca):
    try:
        j = sol_rpc("getAccountInfo", [ca, {"encoding": "jsonParsed"}])
        info = j["result"]["value"]["data"]["parsed"]["info"]
        return {
            "mint_open": info.get("mintAuthority") is not None,
            "freeze_open": info.get("freezeAuthority") is not None
        }
    except:
        return None

def lp_hint(attrs):
    for k in ["locked_liquidity_percentage", "lp_locked_percent"]:
        if k in attrs:
            try:
                return float(attrs[k]) >= 95
            except:
                pass
    return None

# ===================== MAIN =====================
def main():
    state = load_state()
    found = []

    pools = gt_get("/networks/solana/new_pools")
    print("[DEBUG] solana new_pools:", len(pools))

    for p in pools:
        a = p.get("attributes", {})
        liq = float(a.get("reserve_in_usd") or 0)
        fdv = float(a.get("fdv_usd") or 0)
        vol = float(a.get("volume_usd", {}).get("h24") or 0)
        tx = sum(a.get("transactions", {}).get("h24", {}).values())

        if not (LIQ_MIN <= liq <= LIQ_MAX): continue
        if not (FDV_EARLY_MIN <= fdv <= FDV_MAX): continue
        if tx < TXNS24_MIN: continue

        vol_liq = vol / liq if liq else 0

        ca = p.get("relationships", {}).get("base_token", {}).get("data", {}).get("id", "")
        ca = ca.split("_")[-1] if "_" in ca else ca

        sec = mint_security(ca)
        if not sec or sec["mint_open"] or sec["freeze_open"]:
            continue

        lp_locked = lp_hint(a)
        key = p["id"]

        if lp_locked is None:
            state["pending"][key] = {"ca": ca, "fdv": fdv}
            continue
        if lp_locked is False:
            continue

        # KATEGORİ
        if fdv < FDV_CORE_MIN:
            if vol_liq < VOL_LIQ_MIN_EARLY:
                continue
            category = "ERKEN (YÜKSEK RİSK)"
            risk = "🔴"
        elif fdv < FDV_SAFE_MIN:
            if vol_liq < VOL_LIQ_MIN_CORE:
                continue
            category = "CORE (ORTA RİSK)"
            risk = "🟡"
        else:
            if vol_liq < VOL_LIQ_MIN_CORE:
                continue
            category = "CORE (DAHA GÜVENLİ)"
            risk = "🟢"

        found.append({
            "sym": a.get("name", "UNKNOWN").split("/")[0],
            "ca": ca,
            "fdv": fdv,
            "liq": liq,
            "tx": tx,
            "vol": vol,
            "cat": category,
            "risk": risk,
            "pool": p["id"]
        })

    for f in found[:2]:
        msg = (
            f"🚀 SOLANA MEME\n\n"
            f"🪙 {f['sym']}\n"
            f"📜 CA: {f['ca']}\n"
            f"{f['risk']} {f['cat']}\n\n"
            f"FDV: ${f['fdv']:,.0f}\n"
            f"Likidite: ${f['liq']:,.0f}\n"
            f"Tx: {f['tx']}\n"
            f"Hacim: ${f['vol']:,.0f}\n\n"
            f"https://www.geckoterminal.com/solana/pools/{f['pool']}\n\n"
            f"⚠️ Not: ERKEN coinlerde küçük pozisyon önerilir."
        )
        send_telegram(msg)
        time.sleep(1)

    # HEARTBEAT
    hour = now_tr().hour
    day = now_tr().strftime("%Y-%m-%d")
    slot = f"{day}-{hour}"

    if hour in (9, 21) and slot not in state["hb"]:
        send_telegram(
            f"🧭 SOLANA MEME DURUM\n\n"
            f"• Yeni pool: {len(pools)}\n"
            f"• Pending (LP belirsiz): {len(state['pending'])}\n"
            f"• Gönderilen: {len(found)}"
        )
        state["hb"][slot] = True

    save_state(state)

if __name__ == "__main__":
    main()
