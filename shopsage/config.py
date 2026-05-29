"""Central configuration for ShopSage AI."""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ──────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ─── Model Configuration ──────────────────────────────────────────────
LLM_MODEL = "gemini-2.0-flash"
EMBEDDING_MODEL = "models/gemini-embedding-001"

# ─── Paths & Databases ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "shopsage.sqlite3")
POLICY_PATH = os.path.join(DATA_DIR, "policy.txt")
FAISS_INDEX_PATH = os.path.join(DATA_DIR, "faiss_index")

# SQLAlchemy connection string. Defaults to async SQLite for local dev.
# For production PostgreSQL, set this to e.g., postgresql+asyncpg://user:pass@host:port/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    f"sqlite+aiosqlite:///{DB_PATH}"
)

# ─── RAG Configuration ────────────────────────────────────────────────
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
TOP_K_RESULTS = 3

# ─── User Memory Configuration ────────────────────────────────────────
ENABLE_USER_MEMORY = True
MAX_PROFILE_NOTES_LENGTH = 2000

# ─── Price Scraper Configuration ──────────────────────────────────────
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "8"))
SCRAPER_CACHE_TTL = int(os.getenv("SCRAPER_CACHE_TTL", "600"))
MAX_RESULTS_PER_STORE = int(os.getenv("MAX_RESULTS_PER_STORE", "3"))

# ─── Server Configuration ─────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8000
