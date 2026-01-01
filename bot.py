import requests
import os
import google.generativeai as genai

# Anahtarlar (GitHub Secrets'tan çekilir)
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# AI Kurulumu
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_ai_opinion(coin_info):
    prompt = f"""
    Sen bir Solana meme coin uzmanısın. Bu coin isminde trend kelimeler geçmese bile, 
    açıklaması veya işleyişi (AI ajanları, otonom botlar, kült projeler vb.) bakımından 
    şu anki piyasa hype'ına uygun mu? 
    Veri: {coin_info}
    Yanıtın sadece 'POZİTİF: [Neden]' veya 'NEGATİF' olsun.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "NEGATİF"

def check_security(address):
    # RugCheck API veya benzeri bir basitleştirilmiş kontrol simülasyonu
    # Gerçek API entegrasyonu için ek servisler gerekebilir, 
    # ancak DexScreener üzerindeki 'audit' verilerini süzüyoruz.
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}").json()
        pair = res.get('pairs', [{}])[0]
        # LP kilitli mi ve Mint kapalı mı kontrolü (DexScreener etiketlerinden)
        labels = pair.get('labels', [])
        is_safe = "liquidty_burned" in str(labels).lower() or "locked" in str(labels).lower()
        return is_safe
    except:
        return False

def scan():
    # Solana'daki yeni ve popüler çiftleri çek
    url = "https://api.dexscreener.com/latest/dex/search?q=solana"
    try:
        res = requests.get(url).json()
        for pair in res.get('pairs', []):
            mcap = pair.get('fdv', 0)
            liq = pair.get('liquidity', {}).get('usd', 0)
            buys = pair.get('txns', {}).get('m5', {}).get('buys', 0)
            addr = pair['baseToken']['address']
            
            # 1. SERT MATEMATİKSEL FİLTRELER
            if 45000 <= mcap <= 85000 and liq >= (mcap * 0.12) and buys > 10:
                
                # 2. GÜVENLİK KONTROLÜ (Mint & LP)
                # Not: DexScreener her zaman label vermez, bu yüzden ek link ekliyoruz
                
                # 3. AI ANALİZİ
                name = pair['baseToken']['name']
                desc = pair.get('info', {}).get('description', 'Açıklama yok')
                socials = pair.get('info', {}).get('socials', [])
                
                if socials: # Sadece sosyal medyası olanlar
                    ai_decision = get_ai_opinion(f"İsim: {name}, Açıklama: {desc}")
                    
                    if "POZİTİF" in ai_decision:
                        link = pair['url']
                        rugcheck_link = f"https://rugcheck.xyz/tokens/{addr}"
                        
                        msg = (f"🚨 *STRATEJİK FIRSAT YAKALANDI!*\n\n"
                               f"💎 *{name}* (#{pair['baseToken']['symbol']})\n"
                               f"💰 MCAP: {mcap:,}$\n"
                               f"💧 Likidite: {liq:,}$\n"
                               f"📈 5dk Alım: {buys}\n\n"
                               f"🧠 *AI ANALİZİ:* {ai_decision.replace('POZİTİF:', '')}\n\n"
                               f"🛡 *GÜVENLİK:* Mint ve LP kontrolü için aşağıdaki linki aç!\n"
                               f"📍 Adres: `{addr}`\n\n"
                               f"🔗 [GRAFİK]({link}) | [RUGCHECK]({rugcheck_link})")
                        
                        requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown")
    except Exception as e:
        print(f"Hata: {e}")

if __name__ == "__main__":
    scan()
