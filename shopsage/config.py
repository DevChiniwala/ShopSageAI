"""Central configuration for ShopSage AI."""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ──────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ─── Model Configuration ──────────────────────────────────────────────
LLM_MODEL = "gemini-2.0-flash"
EMBEDDING_MODEL = "models/gemini-embedding-001"

# ─── Paths ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "products.db")
POLICY_PATH = os.path.join(DATA_DIR, "policy.txt")
FAISS_INDEX_PATH = os.path.join(DATA_DIR, "faiss_index")

# ─── RAG Configuration ────────────────────────────────────────────────
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
TOP_K_RESULTS = 3

# ─── Server Configuration ─────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8000
