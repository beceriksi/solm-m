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
    """AI yorumunu alana kadar dener ve kotayı zorlamaz"""
    social_text = "Sosyal medya linkleri mevcut." if socials else "Sosyal medya linki yok."
    
    # AI'ya daha net bir 'narrative' analizi yaptıralım
    prompt = (f"Bir Solana meme coin uzmanı gibi davran.\n"
              f"Token Adı: {name} ({symbol})\n"
              f"Sosyal Medya: {social_text}\n"
              f"Bu tokenın temasını ve ismini analiz et. Viral olma potansiyeli var mı?\n"
              f"Yanıtına mutlaka 'KARAR: POZİTİF' veya 'KARAR: NEGATİF' ile başla. "
              f"Ardından nedenini 1 cümleyle Türkçe açıkla.")
    
    # 3 Deneme hakkı veriyoruz
    for attempt in range(3):
        try:
            # ÖNEMLİ: Kota dostu olması için her istekten önce 6 saniye bekle
            time.sleep(6) 
            response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
            if response and response.text:
                return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"⏳ Kota aşımı, {name} için bekleniyor...", flush=True)
                time.sleep(15) # Hata alınca 15 saniye komple dur
            else:
                print(f"⚠️ AI Hatası: {e}", flush=True)
                break
    
    return "KARAR: NEGATİF (AI şu an yorum yapamıyor)"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        if res.status_code == 200:
            print(f"✅ Mesaj iletildi.", flush=True)
    except Exception as e:
        print(f"🚨 Telegram Hatası: {e}")

def scan():
    print(f"\n📡 [{time.strftime('%H:%M:%S')}] AI Odaklı Tarama Başladı...", flush=True)
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return
        
        profiles = res.json()
        if not profiles: return
        
        addr_list = [p['tokenAddress'] for p in profiles[:10]] # Listeyi daraltıp kaliteyi artıralım
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

            # --- SERT KRİTERLER (Sadece kaliteli olanlar AI'ya gitsin) ---
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15 and (liq/mcap >= 0.10):
                name = pair['baseToken']['name']
                symbol = pair['baseToken']['symbol']
                
                print(f"🔍 Süzgeçten Geçti: {name}. AI yorumu bekleniyor...", flush=True)
                
                # AI Analizi
                ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                
                # Sadece AI "POZİTİF" derse gönderiyoruz
                if "POZİTİF" in ai_comment.upper():
                    clean_comment = ai_comment.replace("KARAR: POZİTİF", "").strip()
                    msg = (
                        f"🌟 *AI ONAYLI NARRATIVE*\n\n"
                        f"📊 *Token:* {name} ({symbol})\n"
                        f"💰 *MCAP:* ${mcap:,.0f}\n"
                        f"💧 *Likidite:* ${liq:,.0f}\n"
                        f"🔄 *5dk TX:* {total_tx}\n\n"
                        f"🧠 *AI Yorumu:* {clean_comment}\n\n"
                        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                    )
                    send_telegram(msg)
                    print(f"🚀 SİNYAL GÖNDERİLDİ: {name}")
                else:
                    print(f"⏭️ AI Pas Geçti: {name}")
                
                PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Tarama Hatası: {e}")

if __name__ == "__main__":
    send_telegram("🤖 *AI Yorum Odaklı Mod Aktif!*\n\nArtık her sinyalde AI yorumu bulunacak.")
    while True:
        scan()
        time.sleep(90) # Tarama arasını 1.5 dakikaya çıkardık ki kota dolmasın
