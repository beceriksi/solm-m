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
    """Gemini Narrative ve Sosyal Medya Analizi"""
    social_text = "Sosyal medya linkleri mevcut." if socials else "Sosyal medya linki yok."
    prompt = (f"Sen bir Solana meme coin uzmanı ve narrative (hikaye) analizörüsün.\n"
              f"Token Adı: {name} ({symbol})\n"
              f"Sosyal Medya: {social_text}\n"
              f"Bu tokenın isminde veya temasında bir 'viral potansiyel' veya popüler bir 'kültür' var mı? "
              f"Yanıtın çok kısa olsun. Önce 'KARAR: POZİTİF' veya 'KARAR: NEGATİF' yaz, "
              f"ardından 1 cümleyle nedenini açıkla.")
    try:
        response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
        return response.text
    except:
        return "KARAR: POZİTİF (AI analiz hatası, teknik veriler sağlam olduğu için gönderiliyor.)"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except:
        pass

def scan():
    print(f"📡 [{time.strftime('%H:%M:%S')}] Güvenli Ağ + AI Taraması...", flush=True)
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    
    try:
        res = requests.get(url, timeout=15)
        profiles = res.json() if res.status_code == 200 else []
        if not profiles: return
        
        # Detaylı veri çekme
        addr_list = [p['tokenAddress'] for p in profiles[:15]]
        detail_res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addr_list)}")
        pairs = detail_res.json().get('pairs', [])

        for pair in pairs:
            addr = pair['baseToken']['address']
            if addr in PROCESSED_TOKENS: continue

            # --- MATEMATİKSEL KRİTERLER ---
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            txs = pair.get('txns', {}).get('m5', {})
            total_tx = txs.get('buys', 0) + txs.get('sells', 0)
            has_socials = pair.get('info', {}).get('socials', [])

            # Filtre: 20k+ MCAP, 5k+ Liq, 15+ TX, Sağlıklı Liq Oranı
            if mcap >= 20000 and liq >= 5000 and total_tx >= 15 and (liq/mcap >= 0.10):
                
                name = pair['baseToken']['name']
                symbol = pair['baseToken']['symbol']
                
                print(f"🔍 Teknik Onay: {name}. AI Analizine gidiliyor...", flush=True)
                
                # --- AI NARRATIVE ANALİZİ ---
                ai_comment = get_ai_narrative_analysis(name, symbol, has_socials)
                
                if "POZİTİF" in ai_result := ai_comment.upper():
                    msg = (
                        f"🚀 *AI ONAYLI GEM BULUNDU*\n\n"
                        f"💎 *Token:* {name} ({symbol})\n"
                        f"💰 *MCAP:* ${mcap:,.0f}\n"
                        f"💧 *Liq:* ${liq:,.0f}\n"
                        f"📊 *5dk TX:* {total_tx}\n\n"
                        f"🧠 *AI Analizi:* {ai_comment.split('KARAR: POZİTİF')[-1].strip()}\n\n"
                        f"🔗 [DexScreener]({pair['url']}) | [RugCheck](https://rugcheck.xyz/tokens/{addr})"
                    )
                    send_telegram(msg)
                    print(f"✅ SİNYAL GÖNDERİLDİ: {name}")
                
                PROCESSED_TOKENS.add(addr)

    except Exception as e:
        print(f"🚨 Hata: {e}")

if __name__ == "__main__":
    send_telegram("🤖 *Yapay Zeka & Güvenli Mod Devrede!*\nNarrative analizi yapılarak sinyal taranıyor...")
    while True:
        scan()
        time.sleep(45)
