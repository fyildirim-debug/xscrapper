Ana Yapı ve Teknolojiler:
FastAPI framework'ü kullanılarak REST API oluşturulmuş
Selenium ve BeautifulSoup ile web scraping yapılıyor
Asenkron programlama için asyncio kullanılmış
Önbellek sistemi için özel bir cache mekanizması geliştirilmiş
Temel Özellikler:
Twitter'da tweet araması yapma
Kullanıcı profili bilgilerini getirme
Tweet filtreleme (medya, onaylı hesaplar vb.)
Tarih aralığına göre arama
Çoklu dil desteği
Ana Sınıflar:
TwitterScrapper: Ana scraping işlemlerini yürütür
HTMLCache: HTML içeriklerini önbellekleme
SearchMetadata: Arama verilerini yönetme
API Endpoints:
/api/search: Tweet araması
/api/user/{username}: Kullanıcı profili
Swagger belgesi için /docs
Güvenlik ve Optimizasyon:
Rate limiting
Hata yönetimi
Önbellekleme sistemi
Asenkron işlem yapısı
