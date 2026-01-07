import requests
import os
import time
from google import genai

# --- AYARLAR ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# AI Client Kurulumu
client = genai.Client(api_key=GEMINI_KEY)

# Aynı coini defalarca atmaması için hafıza
PROCESSED_TOKENS = set()

def get_ai_opinion(name, desc, socials):
    """Gemini AI ile anlatı (narrative) analizi yapar (Kota korumalı)."""
    prompt = (f"Sen bir Solana meme coin uzmanısın. Şu coini analiz et:\n"
              f"İsim: {name}\nAçıklama: {desc}\nSosyal Medya: {socials}\n"
              f"Bu coin bir trend (narrative) yakalayabilir mi? "
              f"Yanıtın sadece 'POZİTİF: [Analiz]' veya 'NEGATİF' olsun.")
    
    # 429 Hataları için 3 kez deneme mekanizması
    for attempt in range(3):
        try:
            # Ücretsiz kota için her istek öncesi kısa bir nefes al
            time.sleep(2)
            response = client.models.generate_content(
                model='gemini-2.0-flash-001', 
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e):
                wait_time = 15 * (attempt + 1)
                print(f"⏳ AI Kotası doldu, {wait_time} saniye bekleniyor...")
                time.sleep(wait_time)
                continue
            print(f"⚠️ AI Hatası: {e}")
            return "NEGATİF"
    return "NEGATİF"

def scan():
    """Solana ağındaki en yeni token profillerini tarar."""
    print("\n🔎 Tarama başlatılıyor...")
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            print(f"❌ Dexscreener Hatası: {res.status_code}")
            return

        profiles = res.json()
        if not profiles: return

        # En yeni 15 profili kontrol et
        for profile in profiles[:15]:
            addr = profile.get('tokenAddress')
            chain = profile.get('chainId')

            if chain != 'solana' or addr in PROCESSED_TOKENS:
                continue

            # Token detaylarını çek
            pair_url = f"https://api.dexscreener.com/latest/dex/tokens/{addr}"
            try:
                pair_res = requests.get(pair_url, timeout=15).json()
                pairs = pair_res.get('pairs', [])
            except:
                continue

            if not pairs: continue
            
            # En yüksek likiditeli Solana çiftini seç
            pair = max(pairs, key=lambda x: x.get('liquidity', {}).get('usd', 0))
            
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            vol_5m = pair.get('volume', {}).get('m5', 0)
            
            # --- FİLTRE: MCAP (15k-850k), Liq (>3k), Vol (>500$) ---
            if 15000 <= mcap <= 850000 and liq >= 3000 and vol_5m > 500:
                name = pair['baseToken']['name']
                desc = profile.get('description', 'Açıklama yok.')
                socials = " | ".join([s.get('type', '') for s in profile.get('links', [])])
                
                print(f"🎯 Kriterlere Uygun: {name} (MCAP: ${mcap:,.0f}). AI'ya soruluyor...")
                
                ai_decision = get_ai_opinion(name, desc, socials)
                
                if "POZİTİF" in ai_decision:
                    send_alert(pair, ai_decision, mcap, liq, vol_5m, addr)
                    PROCESSED_TOKENS.add(addr)
                    print(f"✅ ONAYLANDI: {name} -> Telegram'a gönderildi.")
                else:
                    PROCESSED_TOKENS.add(addr)
                    print(f"❌ AI REDDETTİ: {name}")
            else:
                # Kriter dışı kalanları da hafızaya alalım ki tekrar bakmasın
                if mcap > 0: PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Genel Hata: {e}")

def send_alert(pair, ai_decision, mcap, liq, vol, addr):
    """Telegram bildirimi gönderir."""
    # Markdown hatalarını önlemek için temizlik
    clean_ai = ai_decision.replace("POZİTİF:", "✅").replace("_", " ").replace("*", "")
    name = pair['baseToken']['name'].replace("_", " ").replace("*", "")
    
    msg = (
        f"🌟 *MEME RADAR SİNYALİ* 🌟\n\n"
        f"💎 *Asset:* {name}\n"
        f"💰 *MCAP:* ${mcap:,.0f}\n"
        f"💧 *Liq:* ${liq:,.0f}\n"
        f"📊 *5m Vol:* ${vol:,.0f}\n\n"
        f"🧠 *AI Analizi:* {clean_ai[:250]}...\n\n"
        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})\n"
        f"🚀 [BullX](https://neo.bullx.io/terminal?chain=solana&address={addr})"
    )
    
    try:
        send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(send_url, data={
            "chat_id": CHAT_ID, 
            "text": msg, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": "false"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

if __name__ == "__main__":
    print("🚀 90 Puanlık Solana Sniper Aktif!")
    print("-----------------------------------")
    while True:
        scan()
        time.sleep(45) # Rate limit yememek için 45 saniye bekle
