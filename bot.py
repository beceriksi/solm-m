import requests
import os
import time
from google import genai

# --- AYARLAR ---
# GitHub Secrets kısmından bu isimleri kontrol etmeyi unutma!
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# AI İstemcisi
client = genai.Client(api_key=GEMINI_KEY)
PROCESSED_TOKENS = set()

def get_ai_narrative_analysis(name, symbol, socials):
    """Gemini 2.0 ile Token Hikayesi ve Viral Potansiyel Analizi"""
    social_text = "Sosyal medya linkleri (X/TG) mevcut." if socials else "Sosyal medya linki bulunmuyor."
    
    prompt = (f"Sen bir Solana meme coin uzmanısın.\n"
              f"Token Adı: {name} ({symbol})\n"
              f"Sosyal Medya Durumu: {social_text}\n"
              f"Bu token isminde viral bir potansiyel veya popüler bir akım (meme, AI, kedi vb.) var mı? "
              f"Yanıtın çok kısa ve öz olsun. Önce 'KARAR: POZİTİF' veya 'KARAR: NEGATİF' yaz, "
              f"ardından 1 cümleyle nedenini açıkla.")
    try:
        response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
        return response.text
    except Exception as e:
        print(f"⚠️ AI Hatası: {e}")
        return "KARAR: POZİTİF (Teknik veriler iyi olduğu için AI hatasına rağmen gönderildi.)"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"❌ Telegram mesajı gönderilemedi: {e}")

def scan():
    print(f"📡 [{time.strftime('%H:%M:%S')}] Pusuya Yatıldı: Güvenli Gem taranıyor...", flush=True)
    
    # token-profiles: Sadece DexScreener'da onaylı/profilli ciddi coinleri getirir
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return
        
        profiles = res.json()
        if not profiles: return
        
        # En yeni 15 adresi alıp detaylarını sorgula
        addr_list = [p['tokenAddress'] for p in profiles[:15]]
        detail_url = f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addr_list)}"
        detail_res = requests.get(detail_url)
        pairs = detail_res.json().get('pairs', [])

        for pair in pairs:
            addr = pair['baseToken']['address']
            if addr in PROCESSED_TOKENS: continue

            # --- TEKNİK VERİLER ---
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            txs = pair.get('txns', {}).get('m5', {})
            total_tx = txs.get('buys', 0) + txs.get('sells', 0)
            has_socials = pair.get('info', {}).get('socials', [])

            # --- GÜVENLİ VE EARLY KRİTERLER ---
            # 1. MCAP en az 20.000$
            # 2. Likidite en az 5.000$
            # 3. Son 5 dakikada en az 15 işlem (Canlılık testi)
            # 4. Likidite/MCAP oranı %10'dan büyük (Rug-pull koruması)
            
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15:
                if (liq / mcap) >= 0.10:
                    name = pair['baseToken']['name']
                    symbol = pair['baseToken']['symbol']
                    
                    print(f"🔍 Teknik Süzgeçten Geçti: {name}. AI inceliyor...", flush=True)
                    
                    # AI Kararı
                    ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                    
                    if "POZİTİF" in ai_comment.upper():
                        # AI yorumunu temizleyip mesaj oluşturma
                        clean_ai = ai_comment.replace("KARAR: POZİTİF", "✅ AI Gözüyle:").strip()
                        
                        msg = (
                            f"🛡️ *GÜVENLİ EARLY GEM BULUNDU*\n\n"
                            f"📊 *Token:* {name} ({symbol})\n"
                            f"💰 *MCAP:* ${mcap:,.0f}\n"
                            f"💧 *Likidite:* ${liq:,.0f}\n"
                            f"🔄 *5dk TX:* {total_tx} işlem\n\n"
                            f"🧠 {clean_ai}\n\n"
                            f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                        )
                        send_telegram(msg)
                        print(f"🚀 SİNYAL GÖNDERİLDİ: {name}")
                    else:
                        print(f"❌ AI RED: {name} (Narrative zayıf bulundu)")

                    PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Hata oluştu: {e}")

if __name__ == "__main__":
    print("🤖 Bot Aktif! Güvenli mod ve AI analizi devrede.", flush=True)
    send_telegram("🛡️ *Solana Müfettişi Göreve Başladı!*\n\nKriter: 20k+ MCAP, 5k+ Liq, AI Onayı.")
    while True:
        scan()
        time.sleep(45) # 45 saniye bekleme
