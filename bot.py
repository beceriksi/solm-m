import os
import time
import sys

# Kütüphane kontrolü (Loglarda hata görmek için)
try:
    import requests
    from google import genai
    print("✅ Kütüphaneler başarıyla yüklendi.", flush=True)
except ImportError as e:
    print(f"❌ Kütüphane hatası: {e}", flush=True)
    sys.exit(1)

# Ayarlar
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Bağlantı Testi
if not TOKEN or not CHAT_ID or not GEMINI_KEY:
    print("❌ HATA: API Anahtarları (Secrets) eksik!", flush=True)
    sys.exit(1)

client = genai.Client(api_key=GEMINI_KEY)

def scan():
    print(f"🔎 {time.strftime('%H:%M:%S')} - Ağ taranıyor...", flush=True)
    url = "https://api.dexscreener.com/latest/dex/search?q=solana"
    try:
        res = requests.get(url, timeout=15)
        pairs = res.json().get('pairs', [])
        print(f"📊 {len(pairs)} adet çift bulundu. Filtreler uygulanıyor...", flush=True)
        
        # Basit bir döngü ve mesaj testi
        for pair in pairs[:10]:
            mcap = pair.get('fdv', 0)
            if mcap > 20000:
                print(f"🎯 Uygun bulundu: {pair['baseToken']['name']}. AI'ya gidiliyor...", flush=True)
                # Buraya mesaj gönderme kodlarını ekleyebilirsin (önceki kodun aynısı)
                break
    except Exception as e:
        print(f"🚨 Hata: {e}", flush=True)

if __name__ == "__main__":
    print("🚀 Bot başlatma komutu alındı...", flush=True)
    while True:
        scan()
        time.sleep(60)
