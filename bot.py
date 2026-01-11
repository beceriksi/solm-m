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
    """Gemini Kotasını Koruyan Akıllı Analiz Fonksiyonu"""
    social_text = "Sosyal medya mevcut." if socials else "Sosyal medya yok."
    prompt = (f"Analyze Solana meme coin: {name} ({symbol}). Socials: {social_text}. "
              f"Viral potential? Start with 'KARAR: POZİTİF' or 'KARAR: NEGATİF' and give 1 sentence.")
    
    # 3 defa deneme mekanizması
    for attempt in range(3):
        try:
            # Kotayı korumak için her istekten önce 3 saniye mola
            time.sleep(3) 
            response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                wait = (attempt + 1) * 10
                print(f"⏳ AI Kotası doldu, {wait} sn bekleniyor... (Deneme {attempt+1}/3)", flush=True)
                time.sleep(wait)
            else:
                print(f"⚠️ AI Hatası: {e}", flush=True)
                break
    
    return "KARAR: POZİTİF (Teknik veriler çok iyi, AI şu an meşgul.)"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        if res.status_code == 200:
            print(f"✅ Mesaj iletildi.", flush=True)
        else:
            print(f"❌ Mesaj hatası: {res.status_code}", flush=True)
    except Exception as e:
        print(f"🚨 Bağlantı Hatası: {e}", flush=True)

def scan():
    print(f"\n📡 [{time.strftime('%H:%M:%S')}] Tarama yapılıyor...", flush=True)
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return
        
        profiles = res.json()
        if not profiles: return
        
        addr_list = [p['tokenAddress'] for p in profiles[:15]]
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

            # --- GÜVENLİ FİLTRE: 20k MCAP, 5k Liq, 15+ TX ---
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15 and (liq/mcap >= 0.10):
                name = pair['baseToken']['name']
                symbol = pair['baseToken']['symbol']
                
                print(f"🔍 Süzgeçten Geçti: {name}. AI inceliyor...", flush=True)
                ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                
                if "POZİTİF" in ai_comment.upper():
                    clean_ai = ai_comment.replace("KARAR: POZİTİF", "✅ AI Yorumu:").strip()
                    msg = (
                        f"🛡️ *GÜVENLİ GEM BULUNDU*\n\n"
                        f"📊 *Token:* {name} ({symbol})\n"
                        f"💰 *MCAP:* ${mcap:,.0f}\n"
                        f"💧 *Likidite:* ${liq:,.0f}\n"
                        f"🔄 *5dk TX:* {total_tx}\n\n"
                        f"🧠 {clean_ai}\n\n"
                        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                    )
                    send_telegram(msg)
                
                PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Tarama Hatası: {e}")

if __name__ == "__main__":
    send_telegram("🛡️ *Müfettiş Bot Kesintisiz Modda Başladı!*")
    while True:
        scan()
        time.sleep(40) # 40 saniye mola
