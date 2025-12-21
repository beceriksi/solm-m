import os
import json
import time
import math
import requests
from datetime import datetime, timezone, timedelta

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Tarama ağları (GeckoTerminal network isimleri)
NETWORKS = ["solana", "base"]

# Günlük maksimum alarm
DAILY_ALERT_LIMIT = int(os.getenv("DAILY_ALERT_LIMIT", "3"))

# Aynı token'ı tekrar uyarma süresi (saat)
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "24"))

# Filtre aralıkları (USD)
LIQ_MIN = float(os.getenv("LIQ_MIN", "15000"))
LIQ_MAX = float(os.getenv("LIQ_MAX", "80000"))

FDV_MIN = float(os.getenv("FDV_MIN", "200000"))
FDV_MAX = float(os.getenv("FDV_MAX", "3000000"))

# Hacim / Likidite minimum oranı (24h)
VOL_LIQ_MIN = float(os.getenv("VOL_LIQ_MIN", "0.40"))

# 24h işlem sayısı (txns) minimum
TXNS24_MIN = int(os.getenv("TXNS24_MIN", "120"))

# 1h price change limitleri (çok pump'ı ele)
PCHG1H_MIN = float(os.getenv("PCHG1H_MIN", "5"))
PCHG1H_MAX = float(os.getenv("PCHG1H_MAX", "120"))

# Botun kaç tane aday göndereceği (tek taramada)
TOP_N = int(os.getenv("TOP_N", "2"))

# State dosyası (Actions cache ile saklanacak)
STATE_PATH = os.getenv("STATE_PATH", ".cache/state.json")

# GeckoTerminal API (public)
GT_BASE = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "meme-scout-bot/1.0"}

# ===================== YARDIMCILAR =====================
def now_utc():
    return datetime.now(timezone.utc)

def ts():
    return now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"day": "", "daily_count": 0, "last_alert": {}}

def save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def reset_daily_if_needed(st):
    today = now_utc().strftime("%Y-%m-%d")
    if st.get("day") != today:
        st["day"] = today
        st["daily_count"] = 0
    return st

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("\n[UYARI] TELEGRAM_TOKEN veya CHAT_ID yok -> mesaj aşağıda:\n")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code != 200:
            print("[HATA] Telegram gönderilemedi:", r.text)
    except Exception as e:
        print("[HATA] Telegram hatası:", e)

def gt_get(path, params=None, retries=4, timeout=15):
    url = f"{GT_BASE}{path}"
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            time.sleep(1.2)
        except Exception:
            time.sleep(1.2)
    return None

def safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def safe_int(x):
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None

# ===================== VERİ ÇEKME =====================
def fetch_candidates(network: str):
    """
    GeckoTerminal'dan trending + new pools çekip aday havuzu oluşturur.
    """
    out = []

    # Trending pools
    j1 = gt_get(f"/networks/{network}/trending_pools")
    if j1 and "data" in j1:
        out.extend(j1["data"])

    # New pools
    j2 = gt_get(f"/networks/{network}/new_pools")
    if j2 and "data" in j2:
        out.extend(j2["data"])

    return out

def normalize_pool_item(item, network: str):
    """
    GeckoTerminal pool item -> tek format sözlük
    """
    attr = item.get("attributes", {}) if isinstance(item, dict) else {}
    rel = item.get("relationships", {}) if isinstance(item, dict) else {}

    base_token = None
    quote_token = None

    # relationships -> base_token / quote_token id'leri bazen gelir
    try:
        base_token = rel.get("base_token", {}).get("data", {}).get("id")
        quote_token = rel.get("quote_token", {}).get("data", {}).get("id")
    except Exception:
        pass

    # Token adresini çıkarma: genelde base token üzerinden gideriz
    # ID formatı çoğu zaman "{network}_{address}" gibi.
    token_addr = None
    if base_token and "_" in base_token:
        token_addr = base_token.split("_", 1)[1]

    name = attr.get("name") or ""
    symbol = ""
    # name bazen "TOKEN / SOL" gibi => sol tarafı yakala
    if " / " in name:
        symbol = name.split(" / ", 1)[0].strip()

    liq = safe_float(attr.get("reserve_in_usd"))
    fdv = safe_float(attr.get("fdv_usd"))
    price_usd = safe_float(attr.get("base_token_price_usd") or attr.get("price_in_usd"))

    vol24 = safe_float(attr.get("volume_usd", {}).get("h24") if isinstance(attr.get("volume_usd"), dict) else None)
    txns24 = safe_int(attr.get("transactions", {}).get("h24", {}).get("buys", 0) if isinstance(attr.get("transactions"), dict) else None)
    txns24_sells = safe_int(attr.get("transactions", {}).get("h24", {}).get("sells", 0) if isinstance(attr.get("transactions"), dict) else None)
    if txns24 is not None and txns24_sells is not None:
        txns24 = txns24 + txns24_sells

    pchg1h = safe_float(attr.get("price_change_percentage", {}).get("h1") if isinstance(attr.get("price_change_percentage"), dict) else None)
    pchg24 = safe_float(attr.get("price_change_percentage", {}).get("h24") if isinstance(attr.get("price_change_percentage"), dict) else None)

    pool_address = attr.get("address")  # pool address
    dex_id = attr.get("dex_id")

    # GeckoTerminal sayfa linki (pool)
    # Örn: https://www.geckoterminal.com/solana/pools/<pool_address>
    link = None
    if pool_address:
        link = f"https://www.geckoterminal.com/{network}/pools/{pool_address}"

    return {
        "network": network,
        "symbol": symbol or name[:20],
        "name": name,
        "token_addr": token_addr,
        "pool": pool_address,
        "dex": dex_id,
        "liq": liq,
        "fdv": fdv,
        "vol24": vol24,
        "txns24": txns24,
        "pchg1h": pchg1h,
        "pchg24": pchg24,
        "price_usd": price_usd,
        "link": link
    }

# ===================== SKORLAMA / FİLTRE =====================
def in_range(x, a, b):
    return x is not None and a <= x <= b

def score_candidate(c):
    """
    Basit ama işe yarayan "2x-3x aday" skoru.
    """
    liq = c["liq"] or 0
    fdv = c["fdv"] or 0
    vol24 = c["vol24"] or 0
    txns24 = c["txns24"] or 0
    p1 = c["pchg1h"] if c["pchg1h"] is not None else 0
    p24 = c["pchg24"] if c["pchg24"] is not None else 0

    # Likidite ideal ~50k: uzaklaştıkça ceza
    liq_target = 50000.0
    liq_score = max(0.0, 1.0 - abs(liq - liq_target) / liq_target)  # 0..1

    # FDV ideal ~1.2M: uzaklaştıkça ceza
    fdv_target = 1200000.0
    fdv_score = max(0.0, 1.0 - abs(fdv - fdv_target) / fdv_target) if fdv > 0 else 0.0

    # Volume/Liq
    vl = (vol24 / liq) if liq > 0 else 0.0
    vl_score = min(1.0, vl / 1.5)  # 1.5x üstü full

    # Txns
    tx_score = min(1.0, txns24 / 400.0)

    # Momentum: 1h pozitif ama çok abartı değil
    mom = 0.0
    if c["pchg1h"] is not None:
        if 5 <= p1 <= 40:
            mom = 1.0
        elif 40 < p1 <= 120:
            mom = 0.6
        elif p1 < 5:
            mom = 0.2
        else:
            mom = 0.1

    # 24h çok negatifse kırp
    draw = 1.0
    if c["pchg24"] is not None and p24 < -25:
        draw = 0.6

    # Final skor 0..100
    s = (
        25 * liq_score +
        25 * fdv_score +
        20 * vl_score +
        20 * tx_score +
        10 * mom
    ) * draw

    return round(s, 1)

def passes_filters(c):
    if not in_range(c["liq"], LIQ_MIN, LIQ_MAX):
        return False
    if not in_range(c["fdv"], FDV_MIN, FDV_MAX):
        return False

    # Volume/Liq şartı
    liq = c["liq"] or 0
    vol24 = c["vol24"] or 0
    if liq <= 0:
        return False
    if (vol24 / liq) < VOL_LIQ_MIN:
        return False

    # Txns24
    if (c["txns24"] or 0) < TXNS24_MIN:
        return False

    # 1h değişim çok düşük ya da aşırı pump
    p1 = c["pchg1h"]
    if p1 is None:
        return False
    if not (PCHG1H_MIN <= p1 <= PCHG1H_MAX):
        return False

    # token adresi yoksa (bazı havuzlarda) ele
    if not c["token_addr"]:
        return False

    return True

# ===================== ALERT DEDUPE =====================
def can_alert(st, token_key):
    last = st.get("last_alert", {}).get(token_key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (now_utc() - last_dt) > timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return True

def mark_alert(st, token_key):
    st.setdefault("last_alert", {})[token_key] = now_utc().isoformat()

# ===================== FORMAT =====================
def fmt_money(x):
    if x is None:
        return "-"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x/1_000:.1f}K"
    return f"{x:.0f}"

def fmt_pct(x):
    if x is None:
        return "-"
    return f"{x:.1f}%"

def build_message(c, sc):
    net = c["network"].upper()
    sym = c["symbol"]
    liq = fmt_money(c["liq"])
    fdv = fmt_money(c["fdv"])
    vol = fmt_money(c["vol24"])
    tx = c["txns24"] or 0

    # hızlı “neden seçildi” özeti
    vl = (c["vol24"] / c["liq"]) if (c["vol24"] and c["liq"]) else 0.0

    lines = []
    lines.append("🚀 MEME FIRSATI (Filtreyi geçti)")
    lines.append(f"🌐 Ağ: {net}")
    lines.append(f"🪙 {sym}")
    lines.append(f"⭐ Skor: {sc}/100")
    lines.append("")
    lines.append(f"💧 Likidite: ${liq}")
    lines.append(f"📈 Hacim 24h: ${vol}  (Vol/Liq: {vl:.2f}x)")
    lines.append(f"🏷️ FDV: ${fdv}")
    lines.append(f"🔁 İşlem 24h: {tx}")
    lines.append(f"⏱️ 1h: {fmt_pct(c['pchg1h'])} | 24h: {fmt_pct(c['pchg24'])}")
    if c["link"]:
        lines.append("")
        lines.append(f"🔗 {c['link']}")
    lines.append("")
    lines.append("🧪 Manuel kontrol: LP kilit / mint authority / top holders / deployer geçmişi / sosyal hype")
    return "\n".join(lines)

# ===================== MAIN =====================
def main():
    print("[INFO] Başladı:", ts())

    st = load_state()
    st = reset_daily_if_needed(st)

    if st["daily_count"] >= DAILY_ALERT_LIMIT:
        print(f"[INFO] Günlük limit dolu ({st['daily_count']}/{DAILY_ALERT_LIMIT}).")
        return

    candidates = []
    for net in NETWORKS:
        raw = fetch_candidates(net)
        for item in raw:
            c = normalize_pool_item(item, net)
            if passes_filters(c):
                sc = score_candidate(c)
                c["score"] = sc
                candidates.append(c)

    # Skora göre sırala
    candidates.sort(key=lambda x: x["score"], reverse=True)

    sent = 0
    for c in candidates[:50]:
        if st["daily_count"] >= DAILY_ALERT_LIMIT:
            break

        token_key = f"{c['network']}:{c['token_addr']}"
        if not can_alert(st, token_key):
            continue

        # Çok düşük skoru ele (filtre geçti ama zayıf olabilir)
        if c["score"] < 65:
            continue

        msg = build_message(c, c["score"])
        send_telegram(msg)
        mark_alert(st, token_key)
        st["daily_count"] += 1
        sent += 1

        # Tek çalışmada TOP_N kadar gönder
        if sent >= TOP_N:
            break

    save_state(st)

    if sent == 0:
        print("[INFO] Uygun meme yok (veya cooldown/limit).")
    else:
        print(f"[INFO] Gönderilen fırsat: {sent} | Günlük: {st['daily_count']}/{DAILY_ALERT_LIMIT}")

if __name__ == "__main__":
    main()
