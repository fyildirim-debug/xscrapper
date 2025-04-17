# Twitter Data Scraper API

Modern ve güçlü Twitter veri çekme API'si.

## 🚀 Özellikler

* **Gelişmiş Arama Özellikleri**
  * Tweet araması
  * Kullanıcı profili analizi
  * Çoklu filtreleme seçenekleri
  * Tarih bazlı arama

* **Teknik Altyapı**
  * FastAPI tabanlı REST API
  * Selenium web scraping
  * Asenkron işlem yapısı
  * Önbellek sistemi

* **Veri Çıktıları**
  * Tweet içerikleri
  * Kullanıcı profilleri
  * Medya içerikleri
  * İstatistiksel veriler

## 🛠️ Kurulum

```bash
# Gereksinimleri yükleyin
pip install -r requirements.txt

# Uygulamayı başlatın
python main.py
```

## 📚 API Kullanımı

### Tweet Araması
```bash
GET /api/search?q=python&include_filters=images,verified
```

### Kullanıcı Profili
```bash
GET /api/user/{username}?max_tweets=100
```

## 💡 Örnekler

```python
# Tweet araması örneği
response = requests.get(
    "http://localhost:8000/api/search",
    params={
        "q": "python programming",
        "include_filters": ["verified"],
        "max_tweets": 50
    }
)
```

## 📋 Gereksinimler

* Python 3.8+
* FastAPI
* Selenium
* BeautifulSoup4
* Chrome WebDriver

## 🤝 Katkıda Bulunma

1. Fork edin
2. Feature branch oluşturun (`git checkout -b feature/amazing`)
3. Değişikliklerinizi commit edin (`git commit -m 'Add amazing feature'`)
4. Branch'inizi push edin (`git push origin feature/amazing`)
5. Pull Request açın

