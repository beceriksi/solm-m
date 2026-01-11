import requests
import os
import time
from google import genai

# --- AYARLAR ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# SDK yapılandırması
client = genai.Client(api_key=GEMINI_KEY)
PROCESSED_TOKENS = set()

def get_ai_narrative_analysis(name, symbol, socials):
    social_text = "Sosyal medya mevcut." if socials else "Sosyal medya yok."
    prompt = (f"Solana meme coin analizi:\n"
              f"İsim: {name} ({symbol})\n"
              f"Sosyal: {social_text}\n"
              f"Bu token viral olur mu? Yanıtına 'KARAR: POZİTİF' veya 'KARAR: NEGATİF' ile başla, "
              f"ardından Türkçe 1 cümle açıklama yap.")
    
    for attempt in range(2):
        try:
            # ÖNEMLİ: Kota hatası almamak için her sorgu öncesi 15 saniye mola
            time.sleep(15) 
            
            # MODEL İSMİ: 'gemini-2.0-flash' kütüphanenin beklediği standart formattır
            response = client.models.generate_content(
                model='gemini-2.0-flash', 
                contents=prompt
            )
            
            if response and response.text:
                return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"🛑 Kota doldu, 60 sn bekleniyor...", flush=True)
                time.sleep(60)
            else:
                print(f"⚠️ AI Hatası: {e}", flush=True)
                break
    return "KARAR: NEGATİF"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"✅ Telegram mesajı iletildi.", flush=True)
    except:
        pass

def scan():
    print(f"\n📡 [{time.strftime('%H:%M:%S')}] Piyasayı Tara ve Analiz Et...", flush=True)
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return
        profiles = res.json()
        
        # En yeni 10 profili inceleyelim
        addr_list = [p['tokenAddress'] for p in profiles[:10]]
        detail_res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addr_list)}")
        pairs = detail_res.json().get('pairs', [])

        for pair in pairs:
            addr = pair['baseToken']['address']
            if addr in PROCESSED_TOKENS: continue

            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            txs = pair.get('txns', {}).get('m5', {})
            total_tx = txs.get('buys', 0) + txs.get('sells', 0)
            
            # 20k MCAP, 5k Liq, %10 Oran, 15+ İşlem
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15 and (liq/mcap >= 0.10):
                name = pair['baseToken']['name']
                symbol = pair['baseToken']['symbol']
                has_socials = pair.get('info', {}).get('socials', [])
                
                print(f"🔍 Kriterlere Uygun: {name}. AI yorumu alınıyor...", flush=True)
                ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                
                if "POZİTİF" in ai_comment.upper():
                    clean_comment = ai_comment.replace("KARAR: POZİTİF", "").strip()
                    msg = (
                        f"🚀 *AI ONAYLI SOLANA GEM*\n\n"
                        f"📊 *Token:* {name} ({symbol})\n"
                        f"💰 *MCAP:* ${mcap:,.0f}\n"
                        f"💧 *Likidite:* ${liq:,.0f}\n"
                        f"🔄 *5dk İşlem:* {total_tx}\n\n"
                        f"🧠 *AI Yorumu:* {clean_comment}\n\n"
                        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                    )
                    send_telegram(msg)
                    print(f"✅ SİNYAL GÖNDERİLDİ: {name}")
                
                PROCESSED_TOKENS.add(addr)
    except Exception as e:
        print(f"🚨 Hata: {e}")

if __name__ == "__main__":
    send_telegram("🛡️ *Müfettiş Bot Yayında!* \nModel: Gemini 2.0 Flash")
    while True:
        scan()
        time.sleep(60) # Her tarama arası 1 dakika
