from pathlib import Path

BOT_NAME = "supplier_scraper"

SPIDER_MODULES = ["supplier_scraper.spiders"]
NEWSPIDER_MODULE = "supplier_scraper.spiders"

ADDONS = {}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
PDFS_DIR = OUTPUT_DIR / "pdfs"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PDFS_DIR.mkdir(parents=True, exist_ok=True)

# Identificación básica del bot
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 supplier_scraper/1.0"
)

# Respeta robots por defecto
ROBOTSTXT_OBEY = True

# Descarga prudente
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_TIMEOUT = 30

# Reintentos
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]

# Cookies normalmente sobran para catálogo/media
COOKIES_ENABLED = False

# Cabeceras razonables
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Pipelines: imágenes + PDFs + pipeline propio
ITEM_PIPELINES = {
    "scrapy.pipelines.images.ImagesPipeline": 100,
    "scrapy.pipelines.files.FilesPipeline": 200,
    "supplier_scraper.pipelines.SupplierScraperPipeline": 300,
}

# Dónde guardar archivos
IMAGES_STORE = str(IMAGES_DIR)
FILES_STORE = str(PDFS_DIR)

# Campos por defecto de Scrapy
IMAGES_URLS_FIELD = "image_urls"
IMAGES_RESULT_FIELD = "images"

FILES_URLS_FIELD = "file_urls"
FILES_RESULT_FIELD = "files"

# Permite redirecciones en media
MEDIA_ALLOW_REDIRECTS = True

# Caché de media
IMAGES_EXPIRES = 90
FILES_EXPIRES = 90

# Throttling automático
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

# Logs
LOG_LEVEL = "INFO"

# Export
FEED_EXPORT_ENCODING = "utf-8"