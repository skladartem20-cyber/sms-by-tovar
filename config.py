import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "data", "store.db"))
UPLOADS_PATH = os.environ.get("UPLOADS_PATH", os.path.join(BASE_DIR, "data", "uploads"))
REVIEWS_PATH = os.environ.get("REVIEWS_PATH", os.path.join(BASE_DIR, "data", "reviews"))

os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
os.makedirs(UPLOADS_PATH, exist_ok=True)
os.makedirs(REVIEWS_PATH, exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-me")
ADMIN_PASSWORD_DEFAULT = os.environ.get("ADMIN_PASSWORD", "sp010203")

TELEGRAM_BOT_TOKEN_DEFAULT = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID_DEFAULT = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_PROXY_URL_DEFAULT = os.environ.get("TELEGRAM_PROXY_URL", "")

S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "https://s3.timeweb.cloud")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_REGION = os.environ.get("S3_REGION", "ru-1")
S3_BACKUP_FOLDER = os.environ.get("S3_BACKUP_FOLDER", "BU_TOVAR")

SITE_TITLE_DEFAULT = os.environ.get("SITE_TITLE", "Склад уценённых товаров")
CONTACT_PHONE_DEFAULT = os.environ.get("CONTACT_PHONE", "+7 999 616-49-94")
CONTACT_NAME_DEFAULT = os.environ.get("CONTACT_NAME", "Max")
SHIP_ADDRESS_DEFAULT = os.environ.get("SHIP_ADDRESS", "г. Уссурийск")

MAX_PHOTOS_PER_PRODUCT = 10
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}
MAX_UPLOAD_MB = 15
MAX_BACKUP_UPLOAD_MB = int(os.environ.get("MAX_BACKUP_UPLOAD_MB", 500))
