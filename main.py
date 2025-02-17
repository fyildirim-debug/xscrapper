import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlencode
from fastapi import FastAPI, Query
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
    * Konum bazlı arama: `/api/search?q=python&near=Istanbul`
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

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
        self.chrome_options.add_argument("--log-level=3")  # Sadece önemli hataları göster
        self.chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])  # Chrome loglarını kapat

        self.service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(options=self.chrome_options)
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
        return int(stat.replace(",", "")) if stat else 0

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
            time.sleep(5)
            
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
                        href = link.get('href', '')
                        if "cursor=" in href and "Load newest" not in link.text:
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

    async def get_profile(self, username: str) -> object:
        """Get profile information of a user (async)."""
        html = await self.run_in_thread(self.profile_html_contents, username)
        return await self.extract_profile_contents(html)

    async def run_in_thread(self, func, *args, **kwargs):
        """Run blocking functions inside a ThreadPoolExecutor asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: func(*args, **kwargs)
        )

    def profile_html_contents(self, username: str) -> str | None:
        """Fetch the profile page HTML using Selenium."""
        url = f"{DOMAIN}/{username}/search"

        try:
            self.driver.get(url)
            time.sleep(5)
            return self.driver.page_source
        except Exception as e:
            print("Error:", e)
            return None

    async def extract_profile_contents(self, html: str) -> object:
        """Extract profile details, tweets, and media from the profile page."""
        soup = BeautifulSoup(html, 'html.parser')

        profile = {
            "full_name": soup.select_one(".profile-card-fullname").text.strip(),
            "username": self.username_cleaner(soup.select_one(".profile-card-username").text.strip()),
            "bio": soup.select_one(".profile-bio p").text.strip() if soup.select_one(".profile-bio p") else "",
            "location": (soup.select_one(".profile-location span:nth-of-type(2)").text.strip()
                         if soup.select_one(".profile-location span:nth-of-type(2)") else ""),
            "join_date": soup.select_one(".profile-joindate span").text.strip().replace("Joined", "").strip(),
            "tweets": self.stat_cleaner(soup.select_one(".posts .profile-stat-num").text.strip()),
            "following": self.stat_cleaner(soup.select_one(".following .profile-stat-num").text.strip()),
            "followers": self.stat_cleaner(soup.select_one(".followers .profile-stat-num").text.strip()),
            "likes": self.stat_cleaner(soup.select_one(".likes .profile-stat-num").text.strip()),
            "profile_image": self.convert_nitter_image_to_twitter(DOMAIN + soup.select_one(".profile-card-avatar img")["src"]),
            "banner_image": (self.convert_nitter_image_to_twitter(DOMAIN + soup.select_one(".profile-banner img")["src"])
                             if soup.select_one(".profile-banner img") else "")
        }

        tweets = []
        for tweet in soup.select(".timeline-item"):
            tweet_images = [self.convert_nitter_image_to_twitter(DOMAIN + img["src"]) for img in tweet.select(".attachment.image img")]

            retweeted_by = tweet.select_one(".retweet-header div")
            replying_to = tweet.select_one(".tweet-body .replying-to a")

            tweet_data = {
                "content": tweet.select_one(".tweet-content").text.strip() if tweet.select_one(".tweet-content") else "",
                "date": tweet.select_one(".tweet-date a").text.strip(),
                "likes": tweet.select_one(".icon-heart").parent.text.strip() if tweet.select_one(".icon-heart") else "0",
                "comments": tweet.select_one(".icon-comment").parent.text.strip() if tweet.select_one(".icon-comment") else "0",
                "retweets": tweet.select_one(".icon-retweet").parent.text.strip() if tweet.select_one(".icon-retweet") else "0",
                "tweet_link": tweet.select_one(".tweet-link")["href"] if tweet.select_one(".tweet-link") else "",
                "images": tweet_images,
                "retweeted_by": retweeted_by.text.strip() if retweeted_by else None,
                "is_retweet": bool(retweeted_by),
                "is_reply": bool(replying_to),
                "replying_to": replying_to.text.strip() if replying_to else None,
            }
            tweets.append(tweet_data)

        media = [self.convert_nitter_image_to_twitter(DOMAIN + img["src"]) for img in soup.select(".photo-rail-grid a img")]

        return {"profile": profile, "tweets": tweets, "media": media}

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

