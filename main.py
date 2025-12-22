import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Solana-only
NETWORKS = ["solana"]

# ---- ERKEN/ERKEN-STAGE PARAMETRELERİ ----
LIQ_MIN = 8000
LIQ_MAX = 35000

# Hedef bandın: 100k - 500k
FDV_MIN = 100000
FDV_MAX = 500000

VOL_LIQ_MIN = 0.5
TXNS24_MIN = 40

PCHG1H_MIN = 2
PCHG1H_MAX = 60

SCORE_MIN = 60

# "İlk gün" filtresi: 24 saatten eskiyse alma
MAX_AGE_HOURS = 24

DAILY_ALERT_LIMIT = 2
COOLDOWN_HOURS = 24
STATE_PATH = ".cache/state.json"

GT_BASE = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "early-gem-solana-bot/1.0"}

# Solana RPC (public default; istersen GitHub Secrets ile SOLANA_RPC_URL ekleyebilirsin)
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")


# ===================== YARDIMCILAR =====================
def now():
    return datetime.now(timezone.utc)


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True}, timeout=10)
    except Exception as e:
        print("[TG HATA]", e)


def gt_get(path):
    try:
        r = requests.get(GT_BASE + path, headers=UA, timeout=15)
        if r.status_code == 200:
            # GeckoTerminal v2 "data" döndürür
            return r.json().get("data", [])
    except Exception:
        pass
    return []


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
            # geriye dönük uyum
            if "seen" not in s:
                s["seen"] = {}
            return s
    except:
        return {"day": "", "count": 0, "sent": {}, "seen": {}}


def save_state(s):
    os.makedirs(".cache", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)


def score(c):
    liq_score = max(0, 1 - abs(c["liq"] - 20000) / 20000)
    fdv_score = max(0, 1 - abs(c["fdv"] - 250000) / 250000)  # 100k-500k ortası
    vol_score = min(1, (c["vol"] / c["liq"]) / 1.5)
    tx_score = min(1, c["tx"] / 120)

    # momentum: çok aşırı değil, canlı
    momentum = 1 if 5 <= c["p1"] <= 40 else 0.5

    return round(
        30 * liq_score +
        30 * fdv_score +
        20 * vol_score +
        10 * tx_score +
        10 * momentum, 1
    )


def parse_dt_any(x):
    """
    GeckoTerminal alanları format olarak değişebiliyor.
    Bu fonksiyon mümkün olanları dener.
    """
    if not x:
        return None
    try:
        # ISO: "2025-12-23T12:34:56Z"
        if isinstance(x, str):
            return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(timezone.utc)
        # unix seconds
        if isinstance(x, (int, float)) and x > 10_000_000:
            return datetime.fromtimestamp(float(x), tz=timezone.utc)
    except:
        return None
    return None


def extract_token_ca(pool_obj):
    """
    GeckoTerminal pool objesinden base token CA (mint) çıkarmaya çalışır.
    Başarısız olursa None döner.
    """
    rel = (pool_obj or {}).get("relationships", {}) or {}
    base = (rel.get("base_token", {}) or {}).get("data", {}) or {}
    token_id = base.get("id")
    if not token_id:
        # bazı cevaplarda "token" gibi gelebiliyor
        token_id = ((rel.get("token", {}) or {}).get("data", {}) or {}).get("id")

    if not token_id:
        return None

    # çoğunlukla "solana_<MINT>" gibi gelir
    if isinstance(token_id, str) and "_" in token_id:
        return token_id.split("_", 1)[1].strip()
    return str(token_id).strip()


# ===================== SOLANA DOĞRULAMA =====================
def sol_rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC_URL, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def sol_mint_security(mint_addr):
    """
    Mint authority / freeze authority kontrolü (jsonParsed).
    Çıktı:
      {
        "mint_open": bool,
        "freeze_open": bool,
        "mint_authority": str|None,
        "freeze_authority": str|None
      }
    """
    try:
        j = sol_rpc("getAccountInfo", [mint_addr, {"encoding": "jsonParsed"}])
        val = (j.get("result", {}) or {}).get("value")
        if not val:
            return None  # bulamadı
        data = (val.get("data", {}) or {})
        parsed = (data.get("parsed", {}) or {})
        info = (parsed.get("info", {}) or {})

        mint_auth = info.get("mintAuthority", None)
        freeze_auth = info.get("freezeAuthority", None)

        mint_open = mint_auth is not None
        freeze_open = freeze_auth is not None

        return {
            "mint_open": mint_open,
            "freeze_open": freeze_open,
            "mint_authority": mint_auth,
            "freeze_authority": freeze_auth
        }
    except Exception:
        return None


def lp_lock_hint_from_gecko(attrs):
    """
    GeckoTerminal bazı durumlarda lock yüzdesi / lock bilgisi taşıyabiliyor.
    Burada "varsa" okuruz. Yoksa None.
    """
    # olası alanlar (varsa)
    candidates = [
        ("locked_liquidity_percentage", "pct"),
        ("lockedLiquidityPercentage", "pct"),
        ("lp_locked_percent", "pct"),
        ("lpLockedPercent", "pct"),
        ("liquidity_locked_percent", "pct"),
        ("liquidityLockedPercent", "pct"),
        ("lp_locked", "bool"),
        ("lpLocked", "bool"),
        ("liquidity_locked", "bool"),
        ("liquidityLocked", "bool"),
    ]

    for k, typ in candidates:
        if k in attrs:
            v = attrs.get(k)
            if typ == "pct":
                try:
                    pct = float(v)
                    if pct >= 95:
                        return True, f"%{pct:.0f} kilitli"
                    if pct <= 5:
                        return False, f"%{pct:.0f} kilitli"
                    return None, f"%{pct:.0f} kilitli (belirsiz)"
                except:
                    return None, "bilinmiyor"
            if typ == "bool":
                if v is True:
                    return True, "kilitli (bool)"
                if v is False:
                    return False, "kilitli değil (bool)"
                return None, "bilinmiyor"

    return None, "bilinmiyor"


def risk_label(mint_sec, lp_locked_flag):
    """
    İstenen davranış:
    - YÜKSEK RİSK (🔴): Telegram'a GİTMEYECEK
    - ORTA (🟡): GİDECEK (uyarı)
    - DÜŞÜK (🟢): GİDECEK

    Kurallar:
    - Mint açık (mintAuthority var) => 🔴 (gönderme)
    - Freeze açık ama mint kapalı => 🟡 (gönder + uyar)
    - Mint kapalı & freeze kapalı => 🟢 (lp kilit bilinmiyorsa bile genelde 🟢/🟡 arası)
    - LP kilit açıkça "değil" ise => 🟡 (uyarı) (🔴 yapmıyoruz çünkü Solana'da lock her zaman olmayabiliyor)
    """
    if not mint_sec:
        # doğrulama yapılamadıysa: temkinli
        # high-risk göndermeyelim demedin; ama doğrulama yoksa “🟡” yapıp yine göndermek daha iyi.
        return "MID", "🟡 ORTA", ["Mint/Freeze doğrulaması alınamadı (RPC)"]

    notes = []
    if mint_sec["mint_open"]:
        return "HIGH", "🔴 YÜKSEK", ["Mint authority açık (yeni token basılabilir)"]

    # mint kapalı
    if mint_sec["freeze_open"]:
        notes.append("Freeze authority açık (kilitleme riski)")

    # LP lock ipucu
    if lp_locked_flag is False:
        notes.append("LP kilitli görünmüyor (dikkat)")
    elif lp_locked_flag is None:
        notes.append("LP kilit durumu bilinmiyor")

    # Düşük/Orta karar
    if mint_sec["freeze_open"] or (lp_locked_flag is False) or (lp_locked_flag is None):
        return "MID", "🟡 ORTA", notes

    return "LOW", "🟢 DÜŞÜK", notes


# ===================== MAIN =====================
def main():
    print("[INFO] Başladı:", now())

    state = load_state()
    today = now().strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["count"] = 0

    if state["count"] >= DAILY_ALERT_LIMIT:
        print("[INFO] Günlük limit dolu.")
        return

    found = []

    for net in NETWORKS:
        pools = gt_get(f"/networks/{net}/new_pools")
        for p in pools:
            a = (p.get("attributes") or {})

            liq = float(a.get("reserve_in_usd") or 0)
            fdv = float(a.get("fdv_usd") or 0)
            vol = float((a.get("volume_usd") or {}).get("h24") or 0)
            p1 = float((a.get("price_change_percentage") or {}).get("h1") or 0)

            tx = sum((a.get("transactions") or {}).get("h24", {}).values()) if (a.get("transactions") and a["transactions"].get("h24")) else 0

            # yaş filtresi (<= 24h)
            created_at = None
            for key in ("pool_created_at", "created_at", "createdAt", "timestamp", "pool_created_at_timestamp"):
                if key in a:
                    created_at = parse_dt_any(a.get(key))
                    if created_at:
                        break

            # new_pools zaten yeni olur ama yine de 24h üstünü ele
            if created_at:
                age = now() - created_at
                if age > timedelta(hours=MAX_AGE_HOURS):
                    continue
            else:
                # created_at yoksa yine devam et (new_pools genelde zaten taze)
                age = None

            # temel filtreler
            if not (LIQ_MIN <= liq <= LIQ_MAX):
                continue
            if not (FDV_MIN <= fdv <= FDV_MAX):
                continue
            if liq == 0 or (vol / liq) < VOL_LIQ_MIN:
                continue
            if tx < TXNS24_MIN:
                continue
            if not (PCHG1H_MIN <= p1 <= PCHG1H_MAX):
                continue

            sym = (a.get("name", "UNKNOWN").split("/")[0].strip()) if a.get("name") else "UNKNOWN"
            pool = a.get("address")
            key = f"{net}:{pool}"

            # token CA (mint)
            ca = extract_token_ca(p)
            if not ca:
                # CA yoksa doğrulama yapılamaz; ama yine de notla orta risk gönderilebilir
                ca = "UNKNOWN"

            # cooldown sadece "gönderilenler" için
            last_sent = state["sent"].get(key)
            if last_sent:
                try:
                    if now() - datetime.fromisoformat(last_sent) < timedelta(hours=COOLDOWN_HOURS):
                        continue
                except:
                    pass

            # skor
            sc = score({"liq": liq, "fdv": fdv, "vol": vol, "tx": tx, "p1": p1})
            if sc < SCORE_MIN:
                continue

            # güvenlik doğrulama
            mint_sec = None
            if ca != "UNKNOWN":
                mint_sec = sol_mint_security(ca)

            lp_locked_flag, lp_locked_note = lp_lock_hint_from_gecko(a)

            rcode, rlabel, rnotes = risk_label(mint_sec, lp_locked_flag)

            # 🔴 riskli coinler hiç gelmesin
            if rcode == "HIGH":
                # "seen" güncelle (sonradan düzelirse haber verebilmek için)
                state["seen"][key] = {
                    "risk": "HIGH",
                    "ts": now().isoformat(),
                    "ca": ca
                }
                continue

            # Önceden HIGH iken şimdi MID/LOW oldu mu?
            prev_seen = state.get("seen", {}).get(key)
            became_safer = False
            if prev_seen and prev_seen.get("risk") == "HIGH" and rcode in ("MID", "LOW"):
                became_safer = True

            # listede tut
            found.append({
                "sc": sc,
                "net": net,
                "sym": sym,
                "liq": liq,
                "fdv": fdv,
                "vol": vol,
                "tx": tx,
                "p1": p1,
                "pool": pool,
                "key": key,
                "ca": ca,
                "age": age,
                "risk_code": rcode,
                "risk_label": rlabel,
                "risk_notes": rnotes,
                "lp_note": lp_locked_note,
                "became_safer": became_safer,
                "mint_sec": mint_sec
            })

            # seen güncelle
            state["seen"][key] = {
                "risk": rcode,
                "ts": now().isoformat(),
                "ca": ca
            }

    # en iyiler önce
    found.sort(key=lambda x: x["sc"], reverse=True)

    sent_any = False

    # Günlük limit kadar gönder
    for f in found:
        if state["count"] >= DAILY_ALERT_LIMIT:
            break

        age_text = "bilinmiyor"
        if f["age"] is not None:
            hours = f["age"].total_seconds() / 3600
            if hours < 1:
                age_text = f"~{int(hours * 60)} dk"
            else:
                age_text = f"~{hours:.1f} saat"

        # Mint/Freeze satırları
        if f["mint_sec"] is None and f["ca"] != "UNKNOWN":
            mint_line = "Mint Authority: bilinmiyor (RPC)"
            freeze_line = "Freeze Authority: bilinmiyor (RPC)"
        elif f["mint_sec"] is None:
            mint_line = "Mint Authority: bilinmiyor (CA yok)"
            freeze_line = "Freeze Authority: bilinmiyor (CA yok)"
        else:
            mint_line = "Mint Authority: " + ("Kapalı ✅" if not f["mint_sec"]["mint_open"] else "Açık ❌")
            freeze_line = "Freeze Authority: " + ("Kapalı ✅" if not f["mint_sec"]["freeze_open"] else "Açık ⚠️")

        # LP satırı
        lp_line = f"LP: {f['lp_note']}"

        extra = ""
        if f["became_safer"]:
            extra = "🆕 Önceden riskliydi, artık daha güvenli görünüyor.\n\n"

        # Mesaj
        msg = (
            f"🚀 SOLANA EARLY STAGE\n\n"
            f"🪙 {f['sym']}\n"
            f"📜 CA: {f['ca']}\n"
            f"⭐ Skor: {f['sc']}/100\n\n"
            f"💰 FDV: ${f['fdv']:,.0f}\n"
            f"💧 Likidite: ${f['liq']:,.0f}\n"
            f"📊 Hacim 24h: ${f['vol']:,.0f}\n"
            f"🔁 Tx 24h: {f['tx']}\n"
            f"⏱ Yaş: {age_text}\n"
            f"⏱ 1h Değişim: %{f['p1']:.1f}\n\n"
            f"{extra}"
            f"🔐 Güvenlik\n"
            f"• {mint_line}\n"
            f"• {freeze_line}\n"
            f"• {lp_line}\n\n"
            f"⚠️ RİSK: {f['risk_label']}\n"
        )

        # Orta risk notları
        if f["risk_notes"]:
            # çok uzamasın diye 2 maddeyle sınırla
            notes = f["risk_notes"][:2]
            msg += "👀 Not: " + " | ".join(notes) + "\n\n"
        else:
            msg += "\n"

        msg += (
            f"🔗 https://www.geckoterminal.com/solana/pools/{f['pool']}\n\n"
            f"🧪 Manuel kontrol: holder dağılımı / deployer geçmişi"
        )

        send_telegram(msg)
        state["sent"][f["key"]] = now().isoformat()
        state["count"] += 1
        sent_any = True

        # küçük nefes
        time.sleep(0.8)

    save_state(state)

    if not sent_any:
        print("[INFO] Uygun coin yok (riskli elendi / filtre yok).")


if __name__ == "__main__":
    main()
