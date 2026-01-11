import requests
import os
import time
from google import genai

# --- AYARLAR ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_KEY)
PROCESSED_TOKENS = set()

def get_ai_narrative_analysis(name, symbol, socials):
    """Gemini 1.5 Flash ile daha stabil ve kota dostu analiz"""
    social_text = "Sosyal medya linkleri mevcut." if socials else "Sosyal medya linki yok."
    
    prompt = (f"Bir Solana meme coin uzmanı gibi davran.\n"
              f"Token Adı: {name} ({symbol})\n"
              f"Sosyal Medya: {social_text}\n"
              f"Bu tokenın temasını ve viral olma potansiyelini analiz et.\n"
              f"Yanıtına mutlaka 'KARAR: POZİTİF' veya 'KARAR: NEGATİF' ile başla. "
              f"Ardından nedenini 1 kısa cümleyle Türkçe açıkla.")
    
    for attempt in range(2):
        try:
            # İstek öncesi 10 saniye mola (Google'ı sakinleştirir)
            time.sleep(10) 
            # Daha yüksek kotalı 1.5 modelini kullanıyoruz
            response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
            if response and response.text:
                return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"🛑 Google Blokladı. 60 saniye TAM SESSİZLİK moduna geçiliyor...", flush=True)
                time.sleep(60)
            else:
                print(f"⚠️ AI Hatası: {e}", flush=True)
                break
    
    return "KARAR: NEGATİF"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        if res.status_code == 200:
            print(f"✅ Mesaj iletildi.", flush=True)
    except Exception as e:
        print(f"🚨 Telegram Hatası: {e}")

def scan():
    print(f"\n📡 [{time.strftime('%H:%M:%S')}] Stabil AI Taraması Başladı...", flush=True)
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return
        
        profiles = res.json()
        if not profiles: return
        
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
            has_socials = pair.get('info', {}).get('socials', [])

            # Sert Kriterler: 20k MCAP, 5k Liq, 15+ TX
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15 and (liq/mcap >= 0.10):
                name = pair['baseToken']['name']
                symbol = pair['baseToken']['symbol']
                
                print(f"🔍 Süzgeçten Geçti: {name}. AI yorumu bekleniyor...", flush=True)
                ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                
                if "POZİTİF" in ai_comment.upper():
                    clean_comment = ai_comment.replace("KARAR: POZİTİF", "").strip()
                    msg = (
                        f"🌟 *AI ONAYLI NARRATIVE (1.5 Flash)*\n\n"
                        f"📊 *Token:* {name} ({symbol})\n"
                        f"💰 *MCAP:* ${mcap:,.0f}\n"
                        f"💧 *Likidite:* ${liq:,.0f}\n"
                        f"🔄 *5dk TX:* {total_tx}\n\n"
                        f"🧠 *AI Yorumu:* {clean_comment}\n\n"
                        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                    )
                    send_telegram(msg)
                    print(f"🚀 SİNYAL GÖNDERİLDİ: {name}")
                
                PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Tarama Hatası: {e}")

if __name__ == "__main__":
    send_telegram("🤖 *Stabil AI Modu (1.5 Flash) Aktif!*")
    while True:
        scan()
        time.sleep(120) # Tarama arasını 2 dakikaya çıkardık
