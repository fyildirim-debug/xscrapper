import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlencode
from fastapi import FastAPI, Query, Path
from typing import Optional, List
from datetime import date, datetime
import uvicorn
from pydantic import BaseModel, Field
from enum import Enum
import os
import json

DOMAIN = "https://nitter.net"
TWITTER_IMG_DOMAIN = "https://pbs.twimg.com"

class FilterType(str, Enum):
    nativeretweets = "nativeretweets"
    media = "media"
    videos = "videos"
    news = "news"
    verified = "verified"
    native_video = "native_video"
    replies = "replies"
    links = "links"
    images = "images"
    safe = "safe"
    quote = "quote"
    pro_video = "pro_video"

app = FastAPI(
    title="Twitter Arama API",
    description="""
    Nitter üzerinden Twitter araması yapmanızı sağlayan API.
    
    ## Özellikler
    * Tweet araması yapma
    * Çeşitli filtreler kullanma
    * Tarih aralığı belirleme
    * Konum bazlı arama
    
    ## Örnek Kullanımlar
    * Basit arama: `/api/search?q=python`
    * Filtreli arama: `/api/search?q=python&include_filters=images,verified`
    * Tarih aralıklı arama: `/api/search?q=python&since=2024-01-01&until=2024-03-20`
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Server is ok"}

@app.get("/api/user/{username}",
         summary="Twitter Kullanıcı Profili",
         response_description="Kullanıcı profili ve tweet bilgileri")
async def get_user_profile(
    username: str = Path(..., 
                      description="Twitter kullanıcı adı (@işareti olmadan)",
                      examples=["elonmusk", "BillGates"],
                      min_length=1),
    max_tweets: int = Query(0,
                          description="Getirilecek maksimum tweet sayısı (0: sadece profil bilgileri)",
                          ge=0,
                          le=1000)
):
    """
    Twitter kullanıcısının profil bilgilerini ve tweetlerini getirir.
    
    ## Parametreler
    * **username**: Twitter kullanıcı adı (@işareti olmadan) (zorunlu)
    * **max_tweets**: Getirilecek maksimum tweet sayısı (varsayılan: 0, sadece profil bilgileri)
    
    ## Dönüş Değerleri
    * **profile**: Kullanıcı profil bilgileri
        * twitter_url: Gerçek Twitter profil URL'i
        * display_name: Görünen adı
        * username: Kullanıcı adı (@ile)
        * stats:
            * tweets: Tweet sayısı
            * following: Takip edilen sayısı
            * followers: Takipçi sayısı
            * likes: Beğeni sayısı
            * media: Medya sayısı
    * **tweets**: Kullanıcının tweetleri (max_tweets > 0 ise)
        * content: Tweet içeriği
        * date: Tweet tarihi
        * stats:
            * likes: Beğeni sayısı
            * comments: Yorum sayısı
            * retweets: Retweet sayısı
        * media: Tweet'teki medya URL'leri
        * tweet_link: Tweet'in linki
    
    ## Örnek İstekler
    ```
    /api/user/elonmusk          # Sadece profil bilgileri
    /api/user/BillGates?max_tweets=100  # Profil bilgileri ve 100 tweet
    ```
    """
    scraper = TwitterScrapper()
    
    try:
        results = await scraper.get_profile(username, max_tweets)
        if not results or not results.get("profile_data"):
            return {
                "error": "Kullanıcı profili bulunamadı",
                "message": "Profil bilgileri alınamadı veya kullanıcı mevcut değil"
            }
            
        return results["profile_data"]
        
    except Exception as e:
        return {
            "error": "Kullanıcı profili alınamadı",
            "message": str(e)
        }

class HTMLCache:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_filename(self, url: str) -> str:
        """URL'yi dosya adına dönüştürür."""
        safe_filename = "".join(c if c.isalnum() else "_" for c in url)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.cache_dir, f"{safe_filename}_{timestamp}.html")
    
    def save_html(self, url: str, html_content: str) -> str:
        """HTML içeriğini kaydeder ve dosya yolunu döndürür."""
        filename = self._get_cache_filename(url)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)
        return filename
    
    def get_html(self, filename: str) -> Optional[str]:
        """Kaydedilmiş HTML içeriğini okur."""
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return f.read()
        except:
            return None

class SearchMetadata:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        self.metadata_file = os.path.join(cache_dir, "search_metadata.json")
        os.makedirs(cache_dir, exist_ok=True)
        self.load_metadata()
    
    def load_metadata(self):
        """Metadata dosyasını yükler."""
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
        except:
            self.metadata = []
    
    def save_metadata(self):
        """Metadata dosyasını kaydeder."""
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
    
    def add_search(self, query: str, url: str, html_file: str, params: dict):
        """Yeni arama bilgisini ekler."""
        search_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "url": url,
            "html_file": html_file,
            "parameters": params
        }
        self.metadata.append(search_data)
        self.save_metadata()

class TwitterScrapper:
    """
     --------- Twitter Scrapper ---------
     @author Blessing Ajala | Software Engineer 👨‍💻
     @github https://github.com/Oyelamin

    """
    def __init__(self):
        """Initialize the Selenium WebDriver and cache system."""
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920x1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--log-level=3")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self.chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.chrome_options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)

        self.service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(10)  # 10 saniye bekleme süresi
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Cache sistemini başlat
        self.html_cache = HTMLCache()
        self.search_metadata = SearchMetadata()

    def __del__(self):
        """Ensure the WebDriver is properly closed when the object is deleted."""
        self.driver.quit()
        self.executor.shutdown(wait=True)

    @staticmethod
    def username_cleaner(username: str) -> str:
        return username.replace("@", "")

    @staticmethod
    def stat_cleaner(stat: str) -> int:
        """Sayısal değerleri temizler ve int'e çevirir.
        Örnek: "1,234" -> 1234
               "12.3K" -> 12300
               "1.5M" -> 1500000
               "2.3B" -> 2300000000
        """
        # None veya boş string kontrolü
        if stat is None or not isinstance(stat, str):
            return 0
            
        # Boş string veya sadece boşluk karakteri kontrolü
        stat = stat.strip()
        if not stat:
            return 0
            
        try:
            # Virgülleri kaldır
            stat = stat.replace(",", "")
            
            # K/M/B formatını kontrol et
            if "K" in stat.upper():
                num = float(stat.upper().replace("K", ""))
                return int(num * 1000)
            elif "M" in stat.upper():
                num = float(stat.upper().replace("M", ""))
                return int(num * 1000000)
            elif "B" in stat.upper():
                num = float(stat.upper().replace("B", ""))
                return int(num * 1000000000)
            
            # Sayısal değer kontrolü
            if not any(c.isdigit() for c in stat):
                return 0
                
            return int(float(stat))
        except:
            return 0

    @staticmethod
    def convert_nitter_image_to_twitter(nitter_url: str) -> str:
        """Converts Nitter image URLs to the corresponding Twitter image URLs."""
        if nitter_url.startswith(f"{DOMAIN}/pic/"):
            return unquote(nitter_url.replace(f"{DOMAIN}/pic/", f"{TWITTER_IMG_DOMAIN}/"))
        return nitter_url

    def build_search_url(self, 
                        query: str,
                        include_filters: List[str] = None,
                        exclude_filters: List[str] = None,
                        since: str = None,
                        until: str = None) -> str:
        """Arama URL'sini oluşturur."""
        params = {
            "f": "tweets",
            "q": query
        }
        
        # Dahil edilecek filtreleri ekle
        if include_filters:
            for filter_name in include_filters:
                params[f"f-{filter_name}"] = "on"
        
        # Hariç tutulacak filtreleri ekle
        if exclude_filters:
            for filter_name in exclude_filters:
                params[f"e-{filter_name}"] = "on"
        
        # Tarih aralığı
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        
        return f"{DOMAIN}/search?{urlencode(params)}"

    def search_html_contents(self, 
                           query: str,
                           include_filters: List[str] = None,
                           exclude_filters: List[str] = None,
                           since: str = None,
                           until: str = None,
                           max_tweets: int = 50) -> str | None:
        """Arama sayfasının HTML içeriğini getirir ve kaydeder."""
        base_url = self.build_search_url(
            query=query,
            include_filters=include_filters,
            exclude_filters=exclude_filters,
            since=since,
            until=until
        )

        try:
            self.driver.get(base_url)
            time.sleep(10)
            
            # İlk tweet sayısını al
            initial_tweet_count = len(self.driver.find_elements("css selector", ".timeline-item"))
            print(f"Başlangıç tweet sayısı: {initial_tweet_count}")
            
            all_tweets = []  # Tüm tweetleri tutacak liste
            current_html = self.driver.page_source
            
            # İlk sayfadaki tweetleri ekle
            soup = BeautifulSoup(current_html, 'html.parser')
            tweets = soup.select(".timeline-item")
            for tweet in tweets:
                if not "show-more" in tweet.get("class", []):
                    all_tweets.append(str(tweet))
            
            total_tweets = len(all_tweets)
            page_count = 1
            
            # İstenen tweet sayısına ulaşana kadar devam et
            while total_tweets < max_tweets:
                try:
                    # Load more butonunu ve URL'sini bul
                    show_more_links = soup.select(".show-more a")
                    
                    # "Load more" içeren linki bul (Load newest değil)
                    load_more = None
                    for link in show_more_links:
                        if "Load newest" not in link.text and "cursor=" in link.get('href', ''):
                            load_more = link
                            break
                    
                    if not load_more:
                        print("Load more linki bulunamadı, mevcut tweetlerle devam ediliyor.")
                        break
                        
                    # Yeni URL'yi oluştur
                    next_page_url = f"{DOMAIN}/search{load_more['href']}"
                    print(f"Sayfa {page_count + 1} yükleniyor: {next_page_url}")
                    
                    # Yeni sayfayı yükle
                    self.driver.get(next_page_url)
                    time.sleep(3)
                    
                    # Yeni HTML'i al
                    current_html = self.driver.page_source
                    soup = BeautifulSoup(current_html, 'html.parser')
                    
                    # Yeni sayfadaki tweetleri ekle
                    previous_count = total_tweets
                    new_tweets = soup.select(".timeline-item")
                    for tweet in new_tweets:
                        if not "show-more" in tweet.get("class", []):
                            all_tweets.append(str(tweet))
                    
                    # Toplam tweet sayısını güncelle
                    total_tweets = len(all_tweets)
                    print(f"Sayfa {page_count + 1} sonrası toplam tweet sayısı: {total_tweets}")
                    
                    # Eğer yeni tweet eklenemediyse dur
                    if total_tweets <= previous_count:
                        print("Yeni tweet eklenemedi, mevcut tweetlerle devam ediliyor.")
                        break
                    
                    page_count += 1
                    
                except Exception as e:
                    print(f"Load more error: {e}")
                    break
            
            # Son tweet sayısını göster
            print(f"Toplam tweet sayısı: {total_tweets}")
            
            # Tüm tweetleri tek bir HTML içinde birleştir
            timeline_html = f"""
            <div class="timeline">
                {"".join(all_tweets)}
            </div>
            """
            
            # HTML içeriğini kaydet
            html_file = self.html_cache.save_html(base_url, timeline_html)
            
            # Metadata'yı kaydet
            self.search_metadata.add_search(
                query=query,
                url=base_url,
                html_file=html_file,
                params={
                    "include_filters": include_filters,
                    "exclude_filters": exclude_filters,
                    "since": since,
                    "until": until,
                    "total_tweets": total_tweets,
                    "requested_tweets": max_tweets,
                    "pages_loaded": page_count
                }
            )
            
            return timeline_html
        except Exception as e:
            print("Error:", e)
            return None

    async def search(self, 
                    query: str,
                    include_filters: List[str] = None,
                    exclude_filters: List[str] = None,
                    since: str = None,
                    until: str = None,
                    max_tweets: int = 50) -> object:
        """Search for tweets based on query and filters (async)."""
        html = await self.run_in_thread(
            self.search_html_contents,
            query=query,
            include_filters=include_filters,
            exclude_filters=exclude_filters,
            since=since,
            until=until,
            max_tweets=max_tweets
        )
        return await self.extract_search_contents(html)

    async def get_profile(self, username: str, max_tweets: int = 50) -> object:
        """Get profile information of a user (async)."""
        html, stats = await self.run_in_thread(self.profile_html_contents, username, max_tweets)
        profile_data = await self.extract_profile_contents(html, max_tweets) if html else None
        return {
            "stats": stats,
            "profile_data": profile_data
        }

    async def run_in_thread(self, func, *args, **kwargs):
        """Run blocking functions inside a ThreadPoolExecutor asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: func(*args, **kwargs)
        )

    def profile_html_contents(self, username: str, max_tweets: int = 50) -> tuple[str | None, dict]:
        """Kullanıcı profil sayfasının HTML içeriğini getirir."""
        url = f"{DOMAIN}/{self.username_cleaner(username)}"
        stats = {
            "total_tweets": 0,
            "pages_loaded": 1,
            "requested_tweets": max_tweets
        }

        try:
            self.driver.get(url)
            time.sleep(10)  # Sayfanın yüklenmesi için bekle
            
            # Profil bilgilerinin yüklendiğinden emin ol
            profile_card = self.driver.find_element("css selector", ".profile-card")
            if not profile_card:
                raise Exception("Profil bilgileri yüklenemedi")
            
            # İlk tweet sayısını al
            initial_tweet_count = len(self.driver.find_elements("css selector", ".timeline-item"))
            print(f"Başlangıç tweet sayısı: {initial_tweet_count}")
            
            all_tweets = []  # Tüm tweetleri tutacak liste
            current_html = self.driver.page_source
            
            # İlk sayfadaki tweetleri ekle
            soup = BeautifulSoup(current_html, 'html.parser')
            tweets = soup.select(".timeline-item")
            for tweet in tweets:
                if not "show-more" in tweet.get("class", []):
                    all_tweets.append(str(tweet))
            
            total_tweets = len(all_tweets)
            page_count = 1
            
            # İstenen tweet sayısına ulaşana kadar devam et
            while total_tweets < max_tweets:
                try:
                    # Load more butonunu ve URL'sini bul
                    show_more_links = soup.select(".show-more a")
                    
                    # "Load more" içeren linki bul (Load newest değil)
                    load_more = None
                    for link in show_more_links:
                        if "Load newest" not in link.text and "cursor=" in link.get('href', ''):
                            load_more = link
                            break
                    
                    if not load_more:
                        print("Load more linki bulunamadı, mevcut tweetlerle devam ediliyor.")
                        break
                        
                    # Yeni URL'yi oluştur
                    next_page_url = f"{DOMAIN}{load_more['href']}"
                    print(f"Sayfa {page_count + 1} yükleniyor: {next_page_url}")
                    
                    # Yeni sayfayı yükle
                    self.driver.get(next_page_url)
                    time.sleep(3)
                    
                    # Yeni HTML'i al
                    current_html = self.driver.page_source
                    soup = BeautifulSoup(current_html, 'html.parser')
                    
                    # Yeni sayfadaki tweetleri ekle
                    previous_count = total_tweets
                    new_tweets = soup.select(".timeline-item")
                    for tweet in new_tweets:
                        if not "show-more" in tweet.get("class", []):
                            all_tweets.append(str(tweet))
                    
                    # Toplam tweet sayısını güncelle
                    total_tweets = len(all_tweets)
                    print(f"Sayfa {page_count + 1} sonrası toplam tweet sayısı: {total_tweets}")
                    
                    # Eğer yeni tweet eklenemediyse dur
                    if total_tweets <= previous_count:
                        print("Yeni tweet eklenemedi, mevcut tweetlerle devam ediliyor.")
                        break
                    
                    page_count += 1
                    
                except Exception as e:
                    print(f"Load more error: {e}")
                    break
            
            # Son tweet sayısını göster
            print(f"Toplam tweet sayısı: {total_tweets}")
            
            # Tüm tweetleri tek bir HTML içinde birleştir
            timeline_html = f"""
            <div class="profile-card">{str(profile_card.get_attribute('outerHTML'))}</div>
            <div class="timeline">
                {"".join(all_tweets)}
            </div>
            """
            
            # HTML içeriğini kaydet
            html_file = self.html_cache.save_html(url, timeline_html)
            
            # Metadata'yı kaydet
            stats.update({
                "total_tweets": total_tweets,
                "pages_loaded": page_count
            })
            self.search_metadata.add_search(
                query=username,
                url=url,
                html_file=html_file,
                params=stats
            )
            
            return timeline_html, stats
            
        except Exception as e:
            print(f"Profil sayfası yüklenirken hata: {e}")
            return None, stats

    async def extract_profile_contents(self, html: str, max_tweets: int = 0) -> object:
        """Profil detaylarını, tweetleri ve medyayı çıkarır."""
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Güvenli element seçimi için yardımcı fonksiyon
        def safe_select(selector, attr="text", default=""):
            element = soup.select_one(selector)
            if not element:
                return default
            if attr == "text":
                return element.text.strip()
            return element.get(attr, default)

        # Profil bilgilerini güvenli şekilde al
        username = safe_select('.profile-card-username', 'text')
        twitter_url = f"https://x.com/{username.replace('@', '')}"
        display_name = safe_select('.profile-card-fullname', 'text')
        
        # İstatistikleri al
        tweets_count = self.stat_cleaner(safe_select('.posts .profile-stat-num', 'text'))
        following_count = self.stat_cleaner(safe_select('.following .profile-stat-num', 'text'))
        followers_count = self.stat_cleaner(safe_select('.followers .profile-stat-num', 'text'))
        likes_count = self.stat_cleaner(safe_select('.likes .profile-stat-num', 'text'))
        
        # Profil resmini al
        profile_image = ""
        avatar_link = soup.select_one('.profile-card-avatar')
        if avatar_link:
            img_src = avatar_link.get('href', '')
            if img_src:
                profile_image = self.convert_nitter_image_to_twitter(DOMAIN + img_src)
        
        # Medya sayısını al
        media_count = 0
        media_text = safe_select('.photo-rail-header a', 'text')
        if media_text:
            # "3,380 Photos and videos" formatından sayıyı çıkar
            try:
                # Metni temizle ve ilk sayıyı al
                media_count = self.stat_cleaner(''.join(c for c in media_text.split()[0] if c.isdigit() or c in ',.KMB'))
            except:
                media_count = 0
        
        profile_info = {
            "twitter_url": twitter_url,
            "display_name": display_name,
            "username": username,
            "profile_image": profile_image,
            "stats": {
                "tweets": tweets_count,
                "following": following_count,
                "followers": followers_count,
                "likes": likes_count,
                "media": media_count
            }
        }
        
        # max_tweets=0 ise sadece profil bilgilerini döndür
        if max_tweets == 0:
            return {"profile": profile_info}

        tweets = []
        seen_tweet_ids = set()  # Tweet ID'lerini takip etmek için set
        
        # Timeline'daki tüm tweetleri topla
        timeline_items = soup.select(".timeline-item")
        print(f"Bulunan tweet sayısı: {len(timeline_items)}")
        
        for tweet in timeline_items:
            # Show more butonlarını atla
            if "show-more" in tweet.get("class", []):
                continue
                
            # Tweet linkinden ID'yi çıkar
            tweet_link = ""
            tweet_link_element = tweet.select_one(".tweet-link")
            if tweet_link_element and tweet_link_element.get("href"):
                tweet_link = tweet_link_element["href"]
                tweet_id = tweet_link.split('/status/')[1].split('#')[0] if '/status/' in tweet_link else ""
                
                # Eğer bu tweet ID'sini daha önce gördüysek, bu tweet'i atla
                if tweet_id in seen_tweet_ids:
                    continue
                    
                seen_tweet_ids.add(tweet_id)
                tweet_link = f"https://x.com/{username.replace('@', '')}/status/{tweet_id}"
            
            tweet_images = [
                self.convert_nitter_image_to_twitter(DOMAIN + img["src"]) 
                for img in tweet.select(".attachment.image img")
            ]
            
            # Tweet istatistiklerini güvenli şekilde al
            stats = {}
            for stat_type, icon_class in [("likes", "icon-heart"), ("comments", "icon-comment"), ("retweets", "icon-retweet")]:
                stat_element = tweet.select_one(f".{icon_class}")
                if stat_element and stat_element.parent:
                    stats[stat_type] = self.stat_cleaner(stat_element.parent.text.strip())
                else:
                    stats[stat_type] = 0
            
            # Tweet içeriğini al
            content = ""
            content_element = tweet.select_one(".tweet-content")
            if content_element:
                content = content_element.text.strip()
            
            # Tweet tarihini al
            date = ""
            date_element = tweet.select_one(".tweet-date a")
            if date_element:
                date = date_element.text.strip()
            
            tweet_data = {
                "content": content,
                "date": date,
                "stats": stats,
                "media": tweet_images,
                "tweet_link": tweet_link
            }
            
            tweets.append(tweet_data)
            
            # İstenen tweet sayısına ulaştıysak döngüyü sonlandır
            if len(tweets) >= max_tweets:
                break

        print(f"Döndürülen tweet sayısı: {len(tweets)}")
        
        return {
            "profile": profile_info,
            "tweets": tweets
        }

    async def extract_search_contents(self, html: str) -> list:
        """Extract tweet search results from the HTML content."""
        soup = BeautifulSoup(html, 'html.parser')
        tweets = []

        for tweet in soup.select(".timeline-item"):
            tweet_images = [self.convert_nitter_image_to_twitter(DOMAIN + img["src"]) 
                          for img in tweet.select(".attachment.image img")]
            
            username = tweet.select_one(".username")
            fullname = tweet.select_one(".fullname")
            tweet_link = tweet.select_one(".tweet-link")
            
            if username and fullname:
                # Tweet linkini X.com formatına dönüştür
                x_link = ""
                if tweet_link and tweet_link.get('href'):
                    # /username/status/123456789#m formatından ID'yi al
                    href = tweet_link['href']
                    if '/status/' in href:
                        tweet_id = href.split('/status/')[1].split('#')[0]
                        username_clean = username.text.strip().replace("@", "")
                        x_link = f"https://x.com/{username_clean}/status/{tweet_id}"
                
                tweet_data = {
                    "username": username.text.strip(),
                    "full_name": fullname.text.strip(),
                    "content": tweet.select_one(".tweet-content").text.strip() if tweet.select_one(".tweet-content") else "",
                    "date": tweet.select_one(".tweet-date a").text.strip() if tweet.select_one(".tweet-date a") else "",
                    "likes": tweet.select_one(".icon-heart").parent.text.strip() if tweet.select_one(".icon-heart") else "0",
                    "retweets": tweet.select_one(".icon-retweet").parent.text.strip() if tweet.select_one(".icon-retweet") else "0",
                    "comments": tweet.select_one(".icon-comment").parent.text.strip() if tweet.select_one(".icon-comment") else "0",
                    "images": tweet_images,
                    "profile_image": self.convert_nitter_image_to_twitter(DOMAIN + tweet.select_one(".tweet-avatar img")["src"]) if tweet.select_one(".tweet-avatar img") else "",
                    "tweet_link": x_link
                }
                tweets.append(tweet_data)

        return tweets

# FastAPI route'ları
@app.get("/api/search", 
         summary="Twitter'da Tweet Araması",
         response_description="Arama sonuçları ve kullanılan parametreler")
async def search_tweets(
    q: str = Query(..., 
                  description="Arama sorgusu", 
                  examples=["python programming", "galatasaray", "yapay zeka"],
                  min_length=1),
    include_filters: List[FilterType] = Query(None, 
                                            description="Dahil edilecek filtreler",
                                            examples=[["images", "verified"], ["media", "links"]]),
    exclude_filters: List[FilterType] = Query(None, 
                                            description="Hariç tutulacak filtreler",
                                            examples=[["replies"], ["nativeretweets"]]),
    since: Optional[date] = Query(None, 
                                 description="Bu tarihten itibaren ara (YYYY-MM-DD)",
                                 examples=["2024-01-01"]),
    until: Optional[date] = Query(None, 
                                 description="Bu tarihe kadar ara (YYYY-MM-DD)",
                                 examples=["2024-03-20"]),
    max_tweets: int = Query(50, 
                          description="Maksimum tweet sayısı",
                          ge=1,
                          le=1000)
):
    """
    Twitter'da tweet araması yapar.
    
    ## Parametreler
    * **q**: Arama sorgusu (zorunlu)
    * **include_filters**: Dahil edilecek filtreler (isteğe bağlı)
    * **exclude_filters**: Hariç tutulacak filtreler (isteğe bağlı)
    * **since**: Başlangıç tarihi (isteğe bağlı)
    * **until**: Bitiş tarihi (isteğe bağlı)
    * **max_tweets**: Maksimum tweet sayısı (varsayılan: 50, min: 1, max: 1000)
    
    ## Filtreler
    * **nativeretweets**: Retweetler
    * **media**: Medya içeren tweetler
    * **videos**: Video içeren tweetler
    * **news**: Haber içeren tweetler
    * **verified**: Onaylı hesapların tweetleri
    * **native_video**: Native video içeren tweetler
    * **replies**: Yanıtlar
    * **links**: Link içeren tweetler
    * **images**: Resim içeren tweetler
    * **safe**: Güvenli içerik
    * **quote**: Alıntı tweetler
    * **pro_video**: Pro video içeren tweetler
    
    ## Örnek İstekler
    ```
    /api/search?q=python
    /api/search?q=python&include_filters=images,verified
    /api/search?q=python&since=2024-01-01&until=2024-03-20
    /api/search?q=python&max_tweets=100
    ```
    """
    scraper = TwitterScrapper()
    
    results = await scraper.search(
        query=q,
        include_filters=include_filters,
        exclude_filters=exclude_filters,
        since=str(since) if since else None,
        until=str(until) if until else None,
        max_tweets=max_tweets
    )
    
    return {
        "query": q,
        "filters": {
            "include": include_filters,
            "exclude": exclude_filters
        },
        "date_range": {
            "since": since,
            "until": until
        },
        "max_tweets": max_tweets,
        "results": results
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

