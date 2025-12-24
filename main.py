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

# Likidite bandı
LIQ_MIN = 8000
LIQ_MAX = 35000

# FDV bandı (MCAP proxy)
FDV_MIN = 100000
FDV_MAX = 500000

# Genel filtreler
VOL_LIQ_MIN = 0.5
TXNS24_MIN = 40
PCHG1H_MIN = 2
PCHG1H_MAX = 60
SCORE_MIN = 60

# Yaş filtresi: 24 saatten eskiyi alma
MAX_AGE_HOURS = 24

# Mint açıksa ekstra filtreler (kontrollü risk)
MINT_OPEN_FDV_MIN = 140000
MINT_OPEN_TX_MIN = 70
MINT_OPEN_VOL_LIQ_MIN = 0.8

# Günlük limit / tekrar spam önleme
DAILY_ALERT_LIMIT = 2
COOLDOWN_HOURS = 24
STATE_PATH = ".cache/state.json"

# Tema raporu (Türkiye saati)
TR_UTC_OFFSET = 3
THEME_REPORT_HOUR_TR = 12  # 12:00 TR civarı

GT_BASE = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "solana-meme-wave-bot/1.1"}

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")


# ===================== YARDIMCILAR =====================
def now_utc():
    return datetime.now(timezone.utc)


def now_tr():
    # Türkiye saati UTC+3
    return now_utc() + timedelta(hours=TR_UTC_OFFSET)


def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        print("[TG HATA]", e)


def gt_get(path: str):
    try:
        r = requests.get(GT_BASE + path, headers=UA, timeout=15)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception:
        pass
    return []


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
            s.setdefault("day", "")
            s.setdefault("count", 0)
            s.setdefault("sent", {})
            s.setdefault("seen", {})
            s.setdefault("theme_sent_day", "")
            return s
    except:
        return {"day": "", "count": 0, "sent": {}, "seen": {}, "theme_sent_day": ""}


def save_state(s):
    os.makedirs(".cache", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)


def parse_dt_any(x):
    if not x:
        return None
    try:
        if isinstance(x, str):
            return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(timezone.utc)
        if isinstance(x, (int, float)) and x > 10_000_000:
            return datetime.fromtimestamp(float(x), tz=timezone.utc)
    except:
        return None
    return None


def score(c):
    # basit ve stabil puan: hedefe yakınlık + aktivite
    liq_score = max(0, 1 - abs(c["liq"] - 20000) / 20000)
    fdv_score = max(0, 1 - abs(c["fdv"] - 250000) / 250000)
    vol_score = min(1, (c["vol"] / c["liq"]) / 1.5) if c["liq"] > 0 else 0
    tx_score = min(1, c["tx"] / 120)

    momentum = 1 if 5 <= c["p1"] <= 40 else 0.5

    return round(
        30 * liq_score +
        30 * fdv_score +
        20 * vol_score +
        10 * tx_score +
        10 * momentum, 1
    )


def extract_token_ca(pool_obj):
    rel = (pool_obj or {}).get("relationships", {}) or {}
    base = (rel.get("base_token", {}) or {}).get("data", {}) or {}
    token_id = base.get("id")

    if not token_id:
        token_id = ((rel.get("token", {}) or {}).get("data", {}) or {}).get("id")

    if not token_id:
        return None

    if isinstance(token_id, str) and "_" in token_id:
        return token_id.split("_", 1)[1].strip()
    return str(token_id).strip()


# ===================== SOLANA RPC =====================
def sol_rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC_URL, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def sol_mint_security(mint_addr):
    """
    Mint authority / freeze authority kontrolü.
    """
    try:
        j = sol_rpc("getAccountInfo", [mint_addr, {"encoding": "jsonParsed"}])
        val = (j.get("result", {}) or {}).get("value")
        if not val:
            return None

        data = (val.get("data", {}) or {})
        parsed = (data.get("parsed", {}) or {})
        info = (parsed.get("info", {}) or {})

        mint_auth = info.get("mintAuthority", None)
        freeze_auth = info.get("freezeAuthority", None)

        return {
            "mint_open": mint_auth is not None,
            "freeze_open": freeze_auth is not None,
            "mint_authority": mint_auth,
            "freeze_authority": freeze_auth,
        }
    except:
        return None


def lp_lock_hint_from_gecko(attrs):
    """
    GeckoTerminal bazen lock yüzdesi/işareti taşıyabiliyor. Varsa okuruz.
    Yoksa (None, 'bilinmiyor').
    """
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
                    return True, "kilitli"
                if v is False:
                    return False, "kilitli değil"
                return None, "bilinmiyor"

    return None, "bilinmiyor"


# ===================== RİSK / FİLTRE =====================
def passes_filters(liq, fdv, vol, tx, p1):
    if not (LIQ_MIN <= liq <= LIQ_MAX):
        return False, "liq"
    if not (FDV_MIN <= fdv <= FDV_MAX):
        return False, "fdv"
    if liq <= 0:
        return False, "liq0"
    if (vol / liq) < VOL_LIQ_MIN:
        return False, "volliq"
    if tx < TXNS24_MIN:
        return False, "tx"
    if not (PCHG1H_MIN <= p1 <= PCHG1H_MAX):
        return False, "p1"
    return True, ""


def mint_open_extra_ok(fdv, vol, liq, tx, lp_locked_flag):
    # Mint açıksa: FDV>=140k, tx>=70, vol/liq>=0.8, LP çekilebilir değil
    if fdv < MINT_OPEN_FDV_MIN:
        return False, "mint_fdv"
    if tx < MINT_OPEN_TX_MIN:
        return False, "mint_tx"
    if liq <= 0 or (vol / liq) < MINT_OPEN_VOL_LIQ_MIN:
        return False, "mint_volliq"
    if lp_locked_flag is False:
        return False, "mint_lp"
    return True, ""


def risk_label(mint_sec, lp_locked_flag):
    """
    Düşük/Orta. Yüksek risk zaten elenecek.
    """
    notes = []

    if not mint_sec:
        notes.append("Mint/Freeze doğrulaması alınamadı (RPC)")
        # doğrulama yoksa temkinli: orta risk
        if lp_locked_flag is False:
            notes.append("LP kilitli görünmüyor")
        elif lp_locked_flag is None:
            notes.append("LP kilit durumu bilinmiyor")
        return "MID", "🟡 ORTA", notes

    if mint_sec["mint_open"]:
        notes.append("Mint authority AÇIK (supply artabilir)")
    else:
        notes.append("Mint authority KAPALI")

    if mint_sec["freeze_open"]:
        notes.append("Freeze authority AÇIK (kilitleme riski)")
    else:
        notes.append("Freeze authority KAPALI")

    if lp_locked_flag is False:
        notes.append("LP kilitli görünmüyor")
        return "MID", "🟡 ORTA", notes
    if lp_locked_flag is None:
        notes.append("LP kilit durumu bilinmiyor")
        return "MID", "🟡 ORTA", notes

    # buraya kadar LP iyi
    if mint_sec["mint_open"] or mint_sec["freeze_open"]:
        return "MID", "🟡 ORTA", notes

    return "LOW", "🟢 DÜŞÜK", notes


# ===================== TEMA / DALGA ALGILAMA =====================
def normalize_name(sym: str) -> str:
    s = (sym or "").strip().lower()
    # sadece harf/rakam bırak (basit)
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
    return "".join(out)


def age_bucket(age_hours: float) -> str:
    if age_hours < 2:
        return "0-2h"
    if age_hours < 6:
        return "2-6h"
    if age_hours < 12:
        return "6-12h"
    return "12-24h"


def fdv_bucket(fdv: float) -> str:
    if fdv < 140000:
        return "100-140k"
    if fdv < 200000:
        return "140-200k"
    if fdv < 300000:
        return "200-300k"
    return "300-500k"


def build_wave_keys(items):
    """
    Tamamen dinamik: sabit tema listesi yok.
    - İsimlerde ortak prefix/suffix (4 karakter) kümelenmesi
    - Yoksa yaş+fdv bucket kümelenmesi
    """
    # prefix/suffix adaylarını say
    pref_count = {}
    suff_count = {}

    for it in items:
        nm = normalize_name(it["sym"])
        if len(nm) >= 4:
            pref = nm[:4]
            suff = nm[-4:]
            pref_count[pref] = pref_count.get(pref, 0) + 1
            suff_count[suff] = suff_count.get(suff, 0) + 1

    # en az 2 tekrar edenleri tema adayı say
    hot_pref = {k for k, v in pref_count.items() if v >= 2}
    hot_suff = {k for k, v in suff_count.items() if v >= 2}

    for it in items:
        nm = normalize_name(it["sym"])
        wave = None
        if len(nm) >= 4:
            pref = nm[:4]
            suff = nm[-4:]
            if pref in hot_pref:
                wave = f"NAME:PREF:{pref}"
            elif suff in hot_suff:
                wave = f"NAME:SUFF:{suff}"

        if not wave:
            wave = f"BIN:{it['age_bucket']}:{it['fdv_bucket']}"

        it["wave_key"] = wave

    return items


def wave_stats(items):
    """
    Dalga puanı: coin sayısı + ağırlıklı hacim + tx
    """
    groups = {}
    for it in items:
        k = it.get("wave_key", "UNK")
        g = groups.setdefault(k, {"n": 0, "vol": 0.0, "tx": 0, "samples": []})
        g["n"] += 1
        g["vol"] += float(it["vol"])
        g["tx"] += int(it["tx"])
        if len(g["samples"]) < 3:
            g["samples"].append(it["sym"])

    # skor
    for k, g in groups.items():
        g["score"] = (g["n"] * 1.0) + (g["vol"] / 100000.0) + (g["tx"] / 200.0)

    # sırala
    ranked = sorted(groups.items(), key=lambda kv: kv[1]["score"], reverse=True)
    return ranked


def pretty_wave_name(wave_key: str) -> str:
    if wave_key.startswith("NAME:PREF:"):
        return f"İsim prefix dalgası: {wave_key.split(':')[-1].upper()}*"
    if wave_key.startswith("NAME:SUFF:"):
        return f"İsim suffix dalgası: *{wave_key.split(':')[-1].upper()}"
    # BIN:age:fdv
    try:
        _, a, f = wave_key.split(":")
        return f"Momentum bandı: {a} & {f}"
    except:
        return "Dalga"


# ===================== MAIN =====================
def main():
    print("[INFO] Başladı:", now_utc().isoformat())

    state = load_state()

    # günlük reset (TR gününe göre)
    today_tr = now_tr().strftime("%Y-%m-%d")
    if state.get("day") != today_tr:
        state["day"] = today_tr
        state["count"] = 0

    found = []
    eligible_for_wave = []

    for net in NETWORKS:
        pools = gt_get(f"/networks/{net}/new_pools")
print(f"[DEBUG] {net} new_pools sayısı:", len(pools))

        for p in pools:
            a = (p.get("attributes") or {})

            liq = float(a.get("reserve_in_usd") or 0)
            fdv = float(a.get("fdv_usd") or 0)
            vol = float((a.get("volume_usd") or {}).get("h24") or 0)
            p1 = float((a.get("price_change_percentage") or {}).get("h1") or 0)

            tx = 0
            try:
                tx = sum((a.get("transactions") or {}).get("h24", {}).values())
            except:
                tx = 0

            # yaş filtresi
            created_at = None
            for key in ("pool_created_at", "created_at", "createdAt", "timestamp", "pool_created_at_timestamp"):
                if key in a:
                    created_at = parse_dt_any(a.get(key))
                    if created_at:
                        break

            if created_at:
                age = now_utc() - created_at
                if age > timedelta(hours=MAX_AGE_HOURS):
                    continue
                age_hours = age.total_seconds() / 3600.0
            else:
                # created_at yoksa "taze" varsay (new_pools zaten yeni)
                age = None
                age_hours = 6.0  # orta değer; tema bucket için

            ok, why = passes_filters(liq, fdv, vol, tx, p1)
            if not ok:
                continue

            sym = (a.get("name", "UNKNOWN").split("/")[0].strip()) if a.get("name") else "UNKNOWN"
            pool = a.get("address")
            key = f"{net}:{pool}"

            # cooldown (sadece gönderilenlere)
            last_sent = state["sent"].get(key)
            if last_sent:
                try:
                    if now_utc() - datetime.fromisoformat(last_sent) < timedelta(hours=COOLDOWN_HOURS):
                        continue
                except:
                    pass

            # CA
            ca = extract_token_ca(p) or "UNKNOWN"

            # mint/freeze
            mint_sec = sol_mint_security(ca) if ca != "UNKNOWN" else None

            # LP ipucu
            lp_locked_flag, lp_note = lp_lock_hint_from_gecko(a)

            # skor
            sc = score({"liq": liq, "fdv": fdv, "vol": vol, "tx": tx, "p1": p1})
            if sc < SCORE_MIN:
                continue

            # MINT açıksa ekstra güvenlik şartları
            mint_open = (mint_sec["mint_open"] if mint_sec else False)

            if mint_open:
                ok2, why2 = mint_open_extra_ok(fdv, vol, liq, tx, lp_locked_flag)
                if not ok2:
                    # yüksek risk gibi davran: sessiz ele (senin istediğin)
                    state["seen"][key] = {"risk": "HIGH", "ts": now_utc().isoformat(), "ca": ca}
                    continue

            # risk label (LOW/MID)
            rcode, rlabel, rnotes = risk_label(mint_sec, lp_locked_flag)

            # Önceden HIGH iken şimdi MID/LOW oldu mu? (düzeldiyse not)
            prev_seen = state.get("seen", {}).get(key)
            became_safer = False
            if prev_seen and prev_seen.get("risk") == "HIGH" and rcode in ("MID", "LOW"):
                became_safer = True

            item = {
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
                "age_hours": age_hours,
                "age_bucket": age_bucket(age_hours),
                "fdv_bucket": fdv_bucket(fdv),
                "risk_code": rcode,
                "risk_label": rlabel,
                "risk_notes": rnotes,
                "lp_note": lp_note,
                "became_safer": became_safer,
                "mint_sec": mint_sec,
                "mint_open": mint_open,
            }

            found.append(item)
            eligible_for_wave.append(item)

            # seen güncelle
            state["seen"][key] = {"risk": rcode, "ts": now_utc().isoformat(), "ca": ca}

    # ===================== TEMA / DALGA HESAPLA =====================
    if eligible_for_wave:
        eligible_for_wave = build_wave_keys(eligible_for_wave)
        ranked = wave_stats(eligible_for_wave)
        top_wave_keys = [k for k, g in ranked[:2]]  # en güçlü 2 dalga
    else:
        ranked = []
        top_wave_keys = []

    # found içine wave_key yaz (önceliklendirme için)
    wave_map = {it["key"]: it.get("wave_key") for it in eligible_for_wave}
    for it in found:
        it["wave_key"] = wave_map.get(it["key"], f"BIN:{it['age_bucket']}:{it['fdv_bucket']}")
        it["in_top_wave"] = it["wave_key"] in top_wave_keys

    # ===================== GÜNLÜK TEMA RAPORU (TR 12:00) =====================
    # Saatlik workflow ile çalıştığı için: 12:00 TR saatinde (±1) bir kere atsın.
    hour_tr = now_tr().hour
    if ranked and state.get("theme_sent_day") != today_tr and hour_tr == THEME_REPORT_HOUR_TR:
        lines = []
        lines.append("📊 BUGÜNÜN SOLANA MEME DALGALARI\n")

        for idx, (k, g) in enumerate(ranked[:3], start=1):
            nm = pretty_wave_name(k)
            samples = ", ".join(g["samples"]) if g["samples"] else "-"
            lines.append(
                f"#{idx} — {nm}\n"
                f"• Coin: {g['n']} | Hacim ağırlık: ${g['vol']:,.0f} | Tx: {g['tx']}\n"
                f"• Örnek: {samples}\n"
            )

        lines.append("Not: Dalga raporu sadece öncelik içindir; tema dışı coinler de gönderilir.")
        send_telegram("\n".join(lines))
        state["theme_sent_day"] = today_tr

    # ===================== ÖNCELİKLENDİR ve GÖNDER =====================
    # Öncelik: top wave -> skor -> daha düşük risk (LOW önce)
    def sort_key(it):
        risk_rank = 0 if it["risk_code"] == "LOW" else 1
        return (1 if it["in_top_wave"] else 0, -risk_rank, it["sc"])

    found.sort(key=sort_key, reverse=True)

    sent_any = False
    for f in found:
        if state["count"] >= DAILY_ALERT_LIMIT:
            break

        # yaş yazısı
        if f["age"] is None:
            age_text = "bilinmiyor"
        else:
            h = f["age"].total_seconds() / 3600
            if h < 1:
                age_text = f"~{int(h * 60)} dk"
            else:
                age_text = f"~{h:.1f} saat"

        # mint/freeze satırı
        if f["mint_sec"] is None and f["ca"] != "UNKNOWN":
            mint_line = "Mint Authority: bilinmiyor (RPC)"
            freeze_line = "Freeze Authority: bilinmiyor (RPC)"
            mint_open_txt = "bilinmiyor"
        elif f["mint_sec"] is None:
            mint_line = "Mint Authority: bilinmiyor (CA yok)"
            freeze_line = "Freeze Authority: bilinmiyor (CA yok)"
            mint_open_txt = "bilinmiyor"
        else:
            mint_line = "Mint Authority: " + ("AÇIK ⚠️" if f["mint_sec"]["mint_open"] else "KAPALI ✅")
            freeze_line = "Freeze Authority: " + ("AÇIK ⚠️" if f["mint_sec"]["freeze_open"] else "KAPALI ✅")
            mint_open_txt = "AÇIK" if f["mint_sec"]["mint_open"] else "KAPALI"

        # dalga notu
        wave_note = ""
        if f["in_top_wave"]:
            wave_note = "📈 Bu coin bugün ağda birlikte hareket eden dalganın parçası (öncelikli).\n"
        else:
            wave_note = "ℹ️ Bu coin tema dışı olabilir ama kriterleri karşılıyor.\n"

        extra = ""
        if f["became_safer"]:
            extra = "🆕 Önceden riskliydi, artık daha güvenli görünüyor.\n\n"

        msg = (
            f"🚀 SOLANA MEME (FİLTRELİ)\n\n"
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
            f"{wave_note}\n"
            f"🔐 Güvenlik\n"
            f"• {mint_line}\n"
            f"• {freeze_line}\n"
            f"• LP: {f['lp_note']}\n\n"
            f"⚠️ RİSK: {f['risk_label']}\n"
        )

        # notları kısa tut
        if f["risk_notes"]:
            msg += "👀 Not: " + " | ".join(f["risk_notes"][:2]) + "\n\n"
        else:
            msg += "\n"

        # Mint açık özel hatırlatma (kontrollü)
        if mint_open_txt == "AÇIK":
            msg += (
                f"🧩 Mint AÇIK modu: FDV≥{MINT_OPEN_FDV_MIN//1000}k, Tx≥{MINT_OPEN_TX_MIN}, vol/liq≥{MINT_OPEN_VOL_LIQ_MIN}\n\n"
            )

        msg += (
            f"🔗 https://www.geckoterminal.com/solana/pools/{f['pool']}\n\n"
            f"🧪 Manuel kontrol: holder dağılımı / deployer geçmişi"
        )

        send_telegram(msg)
        state["sent"][f["key"]] = now_utc().isoformat()
        state["count"] += 1
        sent_any = True
        time.sleep(0.8)

    save_state(state)

    if not sent_any:
        print("[INFO] Uygun coin yok (filtre/risk).")


if __name__ == "__main__":
    main()
