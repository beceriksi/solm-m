import requests
import os
import time
from google import genai

# --- AYARLAR ---
# Environment Variable (Ortam Değişkeni) olarak tanımladığından emin ol
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# AI Client Kurulumu
client = genai.Client(api_key=GEMINI_KEY)

# Aynı coini defalarca atmaması için hafıza
PROCESSED_TOKENS = set()

def get_ai_opinion(name, desc, socials):
    """Gemini AI ile anlatı (narrative) analizi yapar."""
    prompt = (f"Sen bir Solana meme coin uzmanısın. Şu coini analiz et:\n"
              f"İsim: {name}\nAçıklama: {desc}\nSosyal Medya: {socials}\n"
              f"Bu coin bir trend (narrative) yakalayabilir mi? "
              f"Yanıtın sadece 'POZİTİF: [Analiz]' veya 'NEGATİF' olsun.")
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash-001', 
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"⚠️ AI Hatası: {e}")
        return "NEGATİF"

def scan():
    """Solana ağındaki en yeni token profillerini tarar."""
    print("🔎 Tarama başlatılıyor...")
    
    # Token Profiles API: Bilgileri girilmiş ciddi projeleri yakalar
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        # Timeout=15 ekleyerek botun asılı kalmasını engelliyoruz
        res = requests.get(url, timeout=15)
        
        if res.status_code != 200:
            print(f"❌ Dexscreener Hatası: Kod {res.status_code}")
            return

        profiles = res.json()
        if not profiles:
            print("📭 Yeni profil bulunamadı.")
            return

        for profile in profiles[:15]:  # Her seferinde en yeni 15 taneye bak
            addr = profile.get('tokenAddress')
            chain = profile.get('chainId')

            if chain != 'solana' or addr in PROCESSED_TOKENS:
                continue

            # Token verilerini detaylı çek
            pair_url = f"https://api.dexscreener.com/latest/dex/tokens/{addr}"
            pair_res = requests.get(pair_url, timeout=15).json()
            pairs = pair_res.get('pairs', [])

            if not pairs: continue
            
            # En yüksek likiditeli Solana çiftini al
            pair = max(pairs, key=lambda x: x.get('liquidity', {}).get('usd', 0))
            
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            vol_5m = pair.get('volume', {}).get('m5', 0)
            
            print(f"📊 İnceleniyor: {pair['baseToken']['symbol']} - MCAP: ${mcap:,.0f}")

            # --- 90 PUANLIK FİLTRE (MCAP ve Hacim Odaklı) ---
            if 15000 <= mcap <= 850000 and liq >= 3000 and vol_5m > 500:
                
                name = pair['baseToken']['name']
                desc = profile.get('description', 'Açıklama yok.')
                socials = " | ".join([s.get('type', '') for s in profile.get('links', [])])
                
                print(f"🎯 Kriterlere uygun: {name}. AI'ya soruluyor...")
                
                ai_decision = get_ai_opinion(name, desc, socials)
                
                if "POZİTİF" in ai_decision:
                    send_alert(pair, ai_decision, mcap, liq, vol_5m, addr)
                    PROCESSED_TOKENS.add(addr)
                    print(f"✅ Sinyal gönderildi: {name}")
                else:
                    print(f"❌ AI Onaylamadı: {name}")
                    # Bir kez reddedilen coini bir daha sormayalım
                    PROCESSED_TOKENS.add(addr)

    except requests.exceptions.Timeout:
        print("🕒 İstek zaman aşımına uğradı (Timeout). Bir sonraki tur denenecek.")
    except Exception as e:
        print(f"🚨 Beklenmedik Hata: {e}")

def send_alert(pair, ai_decision, mcap, liq, vol, addr):
    """Telegram üzerinden formatlı bildirim gönderir."""
    clean_ai = ai_decision.replace("POZİTİF:", "✅").replace("_", " ")
    name = pair['baseToken']['name'].replace("_", " ")
    
    msg = (
        f"🌟 *MEME RADAR SİNYALİ* 🌟\n\n"
        f"💎 *Asset:* {name}\n"
        f"💰 *MCAP:* ${mcap:,.0f}\n"
        f"💧 *Liq:* ${liq:,.0f}\n"
        f"📊 *5m Vol:* ${vol:,.0f}\n\n"
        f"🧠 *AI Analizi:* {clean_ai[:200]}...\n\n"
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
    except:
        print("Telegram mesajı gönderilemedi.")

if __name__ == "__main__":
    print("🚀 Solana Sniper Bot Aktif! (Durdurmak için Ctrl+C)")
    while True:
        scan()
        print("😴 60 saniye bekleniyor...")
        time.sleep(60)
