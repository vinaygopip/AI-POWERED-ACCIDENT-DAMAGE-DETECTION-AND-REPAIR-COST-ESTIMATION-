import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.getenv('SECRET_KEY', 'accident_damage_detection_super_secret_key_2026')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt_accident_detection_secret_key_2026')
JWT_EXPIRATION_HOURS = 24

# MySQL Database Settings
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'root')
MYSQL_DB = os.getenv('MYSQL_DB', 'car_damage_detection')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))

# File Storage
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
REPORT_FOLDER = os.path.join(BASE_DIR, 'static', 'reports')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB limit per file

# AI & Processing Settings
YOLO_MODEL_PATH = os.path.join(BASE_DIR, 'models', 'best.pt')
CONFIDENCE_THRESHOLD = 0.25
IMAGE_TARGET_SIZE = (640, 640)

# Labor & Paint Rates (Default Base Calculations)
LABOUR_RATE_PER_HOUR = 800  # Currency unit e.g. INR / local currency
BASE_PAINT_COST_PER_PART = 2500
TAX_RATE_PERCENTAGE = 18.0

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)
