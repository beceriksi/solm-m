import requests
import os
import time
import sys
import functools
from google import genai

# Çıktıların GitHub loglarında anında görünmesi için
print = functools.partial(print, flush=True)

# --- AYARLAR ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_KEY)
PROCESSED_TOKENS = set()

def get_ai_opinion(name, desc):
    """Gemini AI Analizi (Kota Korumalı)"""
    prompt = (f"Sen bir Solana meme coin uzmanısın. Şu coini analiz et:\n"
              f"İsim: {name}\nBilgi: {desc}\n"
              f"Bu coin bir trend yakalayabilir mi? Yanıtın sadece 'POZİTİF: [Neden]' veya 'NEGATİF' olsun.")
    try:
        time.sleep(2) # Kotayı koru
        response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
        return response.text
    except Exception as e:
        if "429" in str(e):
            print("⏳ AI Kotası doldu, beklemede...")
            time.sleep(20)
        return "NEGATİF"

def scan():
    print(f"\n🔎 [{time.strftime('%H:%M:%S')}] Tarama yapılıyor...")
    
    # DAHA GENİŞ TARAMA: Latest Pairs API (Yeni çıkan tüm çiftler)
    url = "https://api.dexscreener.com/latest/dex/search?q=solana"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            print(f"❌ API Hatası: {res.status_code}")
            return

        data = res.json()
        pairs = data.get('pairs', [])
        
        if not pairs:
            print("📭 Yeni çift bulunamadı.")
            return

        count = 0
        for pair in pairs[:30]: # En yeni 30 çifti incele
            addr = pair['baseToken']['address']
            
            if addr in PROCESSED_TOKENS:
                continue

            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            buys = pair.get('txns', {}).get('m5', {}).get('buys', 0)

            # --- ESNETİLMİŞ FİLTRELER (Sinyal gelmesi için) ---
            # MCAP: 20k - 750k | Liq: > 2500 | 5dk alım: > 3
            if 20000 <= mcap <= 750000 and liq >= 2500 and buys >= 3:
                name = pair['baseToken']['name']
                print(f"🎯 Kriterlere Uygun: {name} (MCAP: ${mcap:,.0f})")
                
                # AI'ya sor (Açıklama yoksa ismi üzerinden analiz yapar)
                desc = pair.get('info', {}).get('description', 'Yeni token, henüz açıklama girilmemiş.')
                ai_decision = get_ai_opinion(name, desc)
                
                if "POZİTİF" in ai_decision:
                    send_alert(pair, ai_decision, mcap, liq, addr)
                    print(f"✅ ONAY: {name} Telegram'a uçtu!")
                else:
                    print(f"❌ RED: {name}")
                
                PROCESSED_TOKENS.add(addr)
                count += 1
            
        if count == 0:
            print("😴 Kriterlere uygun yeni coin yok, pusuda bekleniyor...")

    except Exception as e:
        print(f"🚨 Hata: {e}")

def send_alert(pair, ai_decision, mcap, liq, addr):
    """Telegram Mesaj Gönderimi"""
    clean_ai = ai_decision.replace("POZİTİF:", "✅").replace("_", " ")
    msg = (
        f"🚀 *YENİ SOLANA SİNYALİ*\n\n"
        f"💎 *Token:* {pair['baseToken']['name']}\n"
        f"💰 *MCAP:* ${mcap:,.0f}\n"
        f"💧 *Likidite:* ${liq:,.0f}\n\n"
        f"🧠 *AI:* {clean_ai[:200]}\n\n"
        f"🔗 [Grafik]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
    )
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                     data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except:
        print("❌ Telegram mesajı başarısız.")

if __name__ == "__main__":
    print("🤖 Bot başlatıldı... Sinyal bekleniyor.")
    while True:
        scan()
        # GitHub Actions'ta çok sık istek atmamak ve logları görmek için 60 sn ideal
        time.sleep(60)
