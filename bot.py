import requests
import os
import time
from google import genai

# --- AYARLAR ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_KEY)
PROCESSED_TOKENS = set() # Aynı coini defalarca atmaması için

def get_ai_opinion(name, desc, socials):
    # AI'ya daha fazla bağlam veriyoruz
    prompt = (f"Sen bir Solana meme coin uzmanısın. Şu coini analiz et:\n"
              f"İsim: {name}\nAçıklama: {desc}\nSosyal Medya: {socials}\n"
              f"Bu coin bir trend (narrative) yakalayabilir mi? "
              f"Yanıtın sadece 'POZİTİF: [Analiz]' veya 'NEGATİF' olsun.")
    try:
        response = client.models.generate_content(model='gemini-2.0-flash-001', contents=prompt)
        return response.text
    except:
        return "NEGATİF"

def scan():
    # 'search' yerine 'latest' kullanarak en yeni çıkanları yakalıyoruz
    url = "https://api.dexscreener.com/token-profiles/latest/v1" 
    # Not: Token profiles yeni çıkan ve bilgileri girilenleri getirir (Daha kaliteli sinyal)
    
    try:
        # 1. Aşama: Yeni Profilleri Çek
        profiles = requests.get(url).json()
        
        for profile in profiles:
            addr = profile.get('tokenAddress')
            if addr in PROCESSED_TOKENS: continue
            
            # 2. Aşama: Token'ın piyasa verilerini çek
            pair_url = f"https://api.dexscreener.com/latest/dex/tokens/{addr}"
            pair_data = requests.get(pair_url).json()
            pairs = pair_data.get('pairs', [])
            
            if not pairs: continue
            # En yüksek likiditeli Solana çiftini seç
            sol_pairs = [p for p in pairs if p.get('chainId') == 'solana']
            if not sol_pairs: continue
            
            pair = sol_pairs[0]
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            vol_5m = pair.get('volume', {}).get('m5', 0)
            
            # --- 90 PUANLIK FİLTRE SETİ ---
            # MCAP: 15k - 800k (Geniş spektrum)
            # Liq: En az 3.000$ (Rug riskini azaltır ama fırsatı öldürmez)
            # Hacim: Son 5 dk'da en az 1.000$ hacim (Canlılık belirtisi)
            if 15000 <= mcap <= 800000 and liq >= 3000 and vol_5m > 1000:
                
                name = pair['baseToken']['name']
                desc = profile.get('description', 'Açıklama girilmemiş.')
                socials = " | ".join([s.get('type', '') for s in profile.get('links', [])])
                
                # AI Kararı
                ai_decision = get_ai_opinion(name, desc, socials)
                
                if "POZİTİF" in ai_decision:
                    send_alert(pair, ai_decision, mcap, liq, vol_5m, addr)
                    PROCESSED_TOKENS.add(addr) # Hafızaya al

    except Exception as e:
        print(f"Hata: {e}")

def send_alert(pair, ai_decision, mcap, liq, vol, addr):
    # Mesajı bir profesyonel gibi formatlayalım
    clean_ai = ai_decision.replace("POZİTİF:", "✅").replace("NEGATİF", "")
    msg = (
        f"🔥 *POTANSİYEL GÜN YÜZÜNE ÇIKTI!* 🔥\n\n"
        f"💎 *Asset:* {pair['baseToken']['name']} ({pair['baseToken']['symbol']})\n"
        f"💰 *MCAP:* ${mcap:,.0f}\n"
        f"💧 *Liquidity:* ${liq:,.0f}\n"
        f"📊 *5m Vol:* ${vol:,.0f}\n\n"
        f"🧠 *AI Analizi:* {clean_ai}\n\n"
        f"🛠 *Araçlar:*\n"
        f"👉 [DexScreener]({pair['url']})\n"
        f"👉 [RugCheck](https://rugcheck.xyz/tokens/{addr})\n"
        f"👉 [BullX](https://neo.bullx.io/terminal?chain=solana&address={addr})"
    )
    
    send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(send_url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": False})

if __name__ == "__main__":
    print("🎯 Avcı botu 90 puan modunda başlatıldı...")
    while True:
        scan()
        time.sleep(45) # 45 saniyede bir yeni "token profillerini" tara
