import requests
import os
import time
from google import genai

# Ayarlar
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_KEY)

def get_ai_opinion(coin_info):
    prompt = f"Sen bir kripto uzmanısın. Bu coin bir 'narrative' (hikaye) sahibi mi? Potansiyeli nedir? Bilgi: {coin_info}. Sadece 'POZİTİF: [Neden]' veya 'NEGATİF' yaz."
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash-001',
            contents=prompt
        )
        return response.text
    except:
        return "NEGATİF"

def scan():
    # Solana ağındaki aktif çiftleri çeker
    url = "https://api.dexscreener.com/latest/dex/search?q=solana"
    try:
        res = requests.get(url).json()
        pairs = res.get('pairs', [])
        
        for pair in pairs:
            # Filtreleri biraz daha gerçekçi yapıyoruz
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            buys = pair.get('txns', {}).get('m5', {}).get('buys', 0)
            
            # GÜNCEL FİLTRE: 30k - 500k MCAP arası, yeterli likidite ve son 5 dk'da hareket
            if 30000 <= mcap <= 500000 and liq >= 5000 and buys >= 5:
                addr = pair['baseToken']['address']
                name = pair['baseToken']['name'].replace('_', ' ') # Markdown hatasını önler
                
                # AI'ya sor
                desc = pair.get('info', {}).get('description', 'No desc')
                ai_decision = get_ai_opinion(f"İsim: {name}, Bilgi: {desc}")
                
                if "POZİTİF" in ai_decision:
                    link = pair['url']
                    rugcheck_link = f"https://rugcheck.xyz/tokens/{addr}"
                    
                    msg = (f"🚀 *YENİ FIRSAT!*\n\n"
                           f"💎 *{name}*\n"
                           f"💰 MCAP: ${mcap:,.0f}\n"
                           f"🧠 AI: {ai_decision.replace('POZİTİF:', '')[:150]}...\n\n"
                           f"🔗 [GRAFİK]({link}) | [RUGCHECK]({rugcheck_link})")
                    
                    # Telegram gönderimi
                    send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                    requests.post(send_url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
                    
                    # Aynı coini defalarca atmaması için kısa bir bekleme (opsiyonel)
                    time.sleep(2) 

    except Exception as e:
        print(f"Hata oluştu: {e}")

if __name__ == "__main__":
    print("✅ Bot aktif! Solana ağını tarıyor...")
    while True:
        scan()
        time.sleep(60) # 1 dakikada bir tara (rate limit yememek için)
