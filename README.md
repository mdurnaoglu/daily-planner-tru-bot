# Telegram Words + Reminders Bot

## Özellikler
- Her gün 10:00'da 5 Rusça kelime gönderir (Europe/Istanbul).
- Serbest metinden `saat HH:MM` yakalar ve hatırlatıcı kurar.
- Özel cümle: `Mert beni seviyor mu` -> özel cevap.
- Türkçe/Rusça otomatik cevap (mesajın harf setine göre).

## Kurulum (Local)
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `.env.example` dosyasını `.env` olarak kopyala ve doldur.
4. `python app.py`

## Render (Ücretsiz) + Postgres
1. Render hesabı aç.
2. **PostgreSQL** oluştur (Free tier).
3. **Web Service** oluştur:
   - Repo: bu proje
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
   - Runtime: `python-3.11.9` (repo'daki `runtime.txt`)
4. Environment variables:
   - `BOT_TOKEN`
   - `DATABASE_URL` (Render’ın verdiği bağlantı)
   - `TZ=Europe/Istanbul`
   - `DAILY_HOUR=10`, `DAILY_MINUTE=0`
   - `WORDS_PER_DAY=5`

## UptimeRobot (Ücretsiz)
- Render Free 15 dk inaktivitede uyur. Bunu azaltmak için:
  - UptimeRobot’ta bir **HTTP monitor** aç.
  - URL: `https://<render-servis-url>/health`
  - Interval: 5 dakika.

## Kelime Listesi
`words.json` dosyasını kendi listenle değiştirebilirsin.

## Notlar
- Hatırlatıcılar `saat 19:00` gibi bir ifade gördüğünde kurulur.
- Zaman geçmişse otomatik olarak ertesi güne atanır.
