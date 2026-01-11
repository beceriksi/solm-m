import os
import requests
import time

# Ayarlar
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
DB_FILE = "sent_tokens.txt" # Gönderilenleri tutan basit dosya

def send(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": False})
    except Exception as e:
        print(f"Mesaj hatası: {e}")

def check_rugcheck(mint_address):
    """Rugcheck.xyz API üzerinden güvenlik kontrolü yapar"""
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{mint_address}/report/summary"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Risk skorunu al (Genelde 0-1000 arasıdır, 0 en iyisidir)
            score = data.get('score', 1000)
            return score
        return 1000 # Hata varsa riskli say
    except:
        return 1000

def get_history():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r") as f:
        return f.read().splitlines()

def save_history(address):
    with open(DB_FILE, "a") as f:
        f.write(address + "\n")

META_WEIGHTS = {"trump": 3, "maga": 3, "elon": 2, "dog": 1, "pepe": 1, "ai": 2, "sperm": 2}

def scan():
    print("Gelişmiş tarama (Hafıza + RugCheck) başladı...")
    history = get_history()
    url = "https://api.dexscreener.com/latest/dex/networks/solana"
    
    try:
        pairs = requests.get(url, timeout=10).json().get("pairs", [])
    except:
        return

    for p in pairs[:50]:
        addr = p.get('pairAddress')
        mint = p.get('baseToken', {}).get('address')
        
        # 1. HAFIZA KONTROLÜ (Aynı şeyi bir daha atma)
        if addr in history:
            continue

        mc = p.get('fdv', 0) or 0
        liq = p.get('liquidity', {}).get('usd', 0) or 0
        vol_h1 = p.get('volume', {}).get('h1', 0) or 0

        # 2. ANA FİLTRELER
        if 80_000 <= mc <= 2_000_000 and liq > 12_000 and vol_h1 > 10_000:
            
            # 3. RUGCHECK KONTROLÜ (1. Adım: Güvenlik)
            print(f"Güvenlik kontrolü yapılıyor: {mint}")
            rug_score = check_rugcheck(mint)
            
            if rug_score > 500: # 500 üzeri riskli kabul edilir
                print(f"Riskli token elendi. Skor: {rug_score}")
                continue

            # 4. META VE MESAJ HAZIRLIĞI
            name = p.get('baseToken', {}).get('name', '???')
            symbol = p.get('baseToken', {}).get('symbol', '???')
            
            msg = f"""
🛡️ *GÜVENLİ SİNYAL (RugCheck Onaylı)*
🎯 *${symbol}* ({name})

💰 *MC:* ${mc:,.0f}
💧 *LP:* ${liq:,.0f}
📊 *Vol (1h):* ${vol_h1:,.0f}
🛡️ *Rug Score:* {rug_score} (Düşük = İyi)

🎬 *Sinyal:* GİRİŞ UYGUN
[Dexscreener Link](https://dexscreener.com/solana/{addr})
"""
            send(msg)
            save_history(addr) # Bir daha atma
            print(f"Sinyal gönderildi: {symbol}")
            time.sleep(2)

if __name__ == "__main__":
    scan()
