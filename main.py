import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

NETWORKS = ["solana", "base"]

# ---- ERKEN GEM PARAMETRELERİ ----
LIQ_MIN = 8000
LIQ_MAX = 35000

FDV_MIN = 80000
FDV_MAX = 400000

VOL_LIQ_MIN = 0.5
TXNS24_MIN = 40

PCHG1H_MIN = 2
PCHG1H_MAX = 60

SCORE_MIN = 60

DAILY_ALERT_LIMIT = 2
COOLDOWN_HOURS = 24
STATE_PATH = ".cache/state.json"

GT_BASE = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "early-gem-meme-bot/1.0"}

# ===================== YARDIMCILAR =====================
def now():
    return datetime.now(timezone.utc)

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

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
        return {"day": "", "count": 0, "sent": {}}

def save_state(s):
    os.makedirs(".cache", exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(s, f)

def score(c):
    liq_score = max(0, 1 - abs(c["liq"] - 20000) / 20000)
    fdv_score = max(0, 1 - abs(c["fdv"] - 150000) / 150000)
    vol_score = min(1, (c["vol"] / c["liq"]) / 1.5)
    tx_score = min(1, c["tx"] / 120)

    momentum = 1 if 5 <= c["p1"] <= 40 else 0.5

    return round(
        30 * liq_score +
        30 * fdv_score +
        20 * vol_score +
        10 * tx_score +
        10 * momentum, 1
    )

# ===================== MAIN =====================
def main():
    print("[INFO] Başladı:", now())

    state = load_state()
    today = now().strftime("%Y-%m-%d")
    if state["day"] != today:
        state["day"] = today
        state["count"] = 0

    if state["count"] >= DAILY_ALERT_LIMIT:
        print("[INFO] Günlük limit dolu.")
        return

    found = []

    for net in NETWORKS:
        pools = gt_get(f"/networks/{net}/new_pools")
        for p in pools:
            a = p["attributes"]

            liq = float(a.get("reserve_in_usd") or 0)
            fdv = float(a.get("fdv_usd") or 0)
            vol = float(a.get("volume_usd", {}).get("h24") or 0)
            p1 = float(a.get("price_change_percentage", {}).get("h1") or 0)

            tx = sum(a.get("transactions", {}).get("h24", {}).values())

            if not (LIQ_MIN <= liq <= LIQ_MAX): continue
            if not (FDV_MIN <= fdv <= FDV_MAX): continue
            if liq == 0 or vol / liq < VOL_LIQ_MIN: continue
            if tx < TXNS24_MIN: continue
            if not (PCHG1H_MIN <= p1 <= PCHG1H_MAX): continue

            sym = a.get("name", "UNKNOWN").split("/")[0].strip()
            pool = a.get("address")
            key = f"{net}:{pool}"

            last = state["sent"].get(key)
            if last and now() - datetime.fromisoformat(last) < timedelta(hours=COOLDOWN_HOURS):
                continue

            sc = score({"liq": liq, "fdv": fdv, "vol": vol, "tx": tx, "p1": p1})
            if sc < SCORE_MIN: continue

            found.append((sc, net, sym, liq, fdv, vol, tx, p1, pool, key))

    found.sort(reverse=True)

    for f in found[:2]:
        sc, net, sym, liq, fdv, vol, tx, p1, pool, key = f

        msg = (
            f"🚀 ERKEN GEM ADAYI\n"
            f"🌐 Ağ: {net.upper()}\n"
            f"🪙 {sym}\n"
            f"⭐ Skor: {sc}/100\n\n"
            f"💧 Likidite: ${liq:,.0f}\n"
            f"🏷 FDV: ${fdv:,.0f}\n"
            f"📊 Hacim 24h: ${vol:,.0f}\n"
            f"🔁 Tx 24h: {tx}\n"
            f"⏱ 1h Değişim: %{p1:.1f}\n\n"
            f"https://www.geckoterminal.com/{net}/pools/{pool}\n\n"
            f"🧪 Manuel kontrol: LP kilit / mint / holder / deployer"
        )

        send_telegram(msg)
        state["sent"][key] = now().isoformat()
        state["count"] += 1

        if state["count"] >= DAILY_ALERT_LIMIT:
            break

    save_state(state)

    if not found:
        print("[INFO] Uygun erken gem yok.")

if __name__ == "__main__":
    main()
