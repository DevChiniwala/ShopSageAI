"""
Database Initialization Script for ShopSage AI.

Creates the SQLite product database with sample data
and builds the FAISS vector index from policy documents.

Usage:
    python scripts/init_db.py
"""
import os
import sys
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from shopsage.config import (
    DB_PATH, POLICY_PATH, FAISS_INDEX_PATH,
    EMBEDDING_MODEL, GOOGLE_API_KEY,
    CHUNK_SIZE, CHUNK_OVERLAP
)


# ─── Sample Product Data ───────────────────────────────────────────────

PRODUCTS = [
    ("NK-RED-001", "Nike Dri-FIT Classic Tee", "100% Polyester", "S, M, L, XL", "Red", "Nike", "Unisex", 45, 2499.00),
    ("NK-BLU-002", "Nike Air Max T-Shirt", "Cotton Blend", "M, L, XL", "Blue", "Nike", "Men", 30, 2799.00),
    ("NK-BLK-003", "Nike Sportswear Club Fleece", "80% Cotton, 20% Polyester", "S, M, L, XL, XXL", "Black", "Nike", "Men", 25, 3499.00),
    ("NK-WHT-004", "Nike Essential Crop Top", "95% Cotton, 5% Spandex", "XS, S, M, L", "White", "Nike", "Women", 40, 1999.00),
    ("AD-RED-005", "Adidas Essentials Tee", "100% Cotton", "S, M, L, XL", "Red", "Adidas", "Men", 55, 1799.00),
    ("AD-BLU-006", "Adidas Originals Trefoil Tee", "Cotton Jersey", "M, L, XL", "Blue", "Adidas", "Unisex", 35, 2299.00),
    ("AD-GRN-007", "Adidas Running Response Tee", "100% Recycled Polyester", "S, M, L", "Green", "Adidas", "Men", 20, 1999.00),
    ("AD-PNK-008", "Adidas Yoga Studio Tee", "Bamboo Blend", "XS, S, M, L", "Pink", "Adidas", "Women", 30, 2499.00),
    ("PM-RED-009", "Puma Essential Logo Tee", "100% Cotton", "S, M, L, XL", "Red", "Puma", "Unisex", 60, 1299.00),
    ("PM-BLK-010", "Puma Motorsport BMW Tee", "Cotton Blend", "M, L, XL", "Black", "Puma", "Men", 25, 2199.00),
    ("PM-WHT-011", "Puma Classics Ribbed Tee", "95% Cotton, 5% Elastane", "XS, S, M, L", "White", "Puma", "Women", 35, 1499.00),
    ("LV-NVY-012", "Levi's Classic Pocket Tee", "100% Cotton", "S, M, L, XL, XXL", "Navy", "Levi's", "Unisex", 40, 1799.00),
    ("LV-BLU-013", "Levi's Graphic Logo Tee", "Cotton Jersey", "M, L, XL", "Blue", "Levi's", "Men", 30, 1599.00),
    ("LV-DEN-014", "Levi's Denim Shirt", "100% Cotton Denim", "S, M, L, XL", "Denim Blue", "Levi's", "Men", 20, 3299.00),
    ("HM-WHT-015", "H&M Regular Fit Oxford Shirt", "100% Cotton", "S, M, L, XL", "White", "H&M", "Men", 50, 1499.00),
    ("HM-BLK-016", "H&M Slim Fit Jersey Top", "95% Cotton, 5% Elastane", "XS, S, M, L", "Black", "H&M", "Women", 45, 999.00),
    ("HM-FLR-017", "H&M Floral Print Dress", "100% Viscose", "S, M, L", "Floral Multi", "H&M", "Women", 25, 2499.00),
    ("HM-GRY-018", "H&M Relaxed Fit Hoodie", "Cotton Blend Fleece", "S, M, L, XL", "Grey", "H&M", "Unisex", 30, 2299.00),
    ("ZR-BLK-019", "Zara Textured Blazer", "Polyester Blend", "S, M, L, XL", "Black", "Zara", "Men", 15, 4999.00),
    ("ZR-RED-020", "Zara Satin Finish Blouse", "100% Polyester Satin", "XS, S, M, L", "Red", "Zara", "Women", 20, 2799.00),
    ("ZR-WHT-021", "Zara Linen Blend Shirt", "55% Linen, 45% Cotton", "M, L, XL", "White", "Zara", "Men", 18, 2999.00),
    ("ZR-NVY-022", "Zara Knit Polo Shirt", "100% Cotton Knit", "S, M, L, XL", "Navy", "Zara", "Men", 22, 2499.00),
    ("US-BLU-023", "US Polo Assn Classic Polo", "100% Cotton Pique", "S, M, L, XL, XXL", "Blue", "US Polo", "Men", 40, 1899.00),
    ("US-WHT-024", "US Polo Assn Striped Shirt", "Cotton Blend", "M, L, XL", "White Striped", "US Polo", "Men", 35, 2199.00),
    ("TH-RED-025", "Tommy Hilfiger Flag Logo Tee", "100% Organic Cotton", "S, M, L, XL", "Red", "Tommy Hilfiger", "Unisex", 30, 2999.00),
    ("TH-NVY-026", "Tommy Hilfiger Slim Polo", "Cotton Pique", "M, L, XL", "Navy", "Tommy Hilfiger", "Men", 25, 3499.00),
    ("TH-PNK-027", "Tommy Hilfiger Logo Sweatshirt", "French Terry", "XS, S, M, L", "Pink", "Tommy Hilfiger", "Women", 20, 4299.00),
    ("CK-BLK-028", "Calvin Klein Logo Band Tee", "100% Cotton", "S, M, L, XL", "Black", "Calvin Klein", "Unisex", 35, 2799.00),
    ("CK-WHT-029", "Calvin Klein Slim Fit Shirt", "Stretch Cotton", "M, L, XL", "White", "Calvin Klein", "Men", 20, 3999.00),
    ("CK-GRY-030", "Calvin Klein Performance Tank", "Moisture-Wicking Blend", "XS, S, M, L", "Grey", "Calvin Klein", "Women", 28, 2299.00),
    ("GA-BLK-031", "Gap Classic Logo Tee", "100% Cotton", "S, M, L, XL, XXL", "Black", "Gap", "Unisex", 50, 1299.00),
    ("GA-BLU-032", "Gap Vintage Soft Hoodie", "Cotton-Polyester Blend", "S, M, L, XL", "Blue", "Gap", "Men", 30, 2799.00),
    ("GA-PNK-033", "Gap Favorite Crewneck Tee", "100% Cotton", "XS, S, M, L", "Pink", "Gap", "Women", 40, 999.00),
    ("JK-BRN-034", "Jack & Jones Leather Jacket", "Genuine Leather", "M, L, XL", "Brown", "Jack & Jones", "Men", 10, 6999.00),
    ("JK-BLK-035", "Jack & Jones Denim Jacket", "100% Cotton Denim", "S, M, L, XL", "Black", "Jack & Jones", "Men", 18, 3499.00),
    ("JK-GRN-036", "Jack & Jones Bomber Jacket", "Nylon Shell", "M, L, XL", "Olive Green", "Jack & Jones", "Men", 15, 4299.00),
    ("UN-BLK-037", "Uniqlo AIRism Cotton Tee", "AIRism Cotton Blend", "S, M, L, XL, XXL", "Black", "Uniqlo", "Unisex", 60, 1499.00),
    ("UN-WHT-038", "Uniqlo Supima Cotton Tee", "100% Supima Cotton", "S, M, L, XL", "White", "Uniqlo", "Unisex", 55, 999.00),
    ("UN-NVY-039", "Uniqlo Ultra Light Down Jacket", "Nylon Shell, Down Fill", "S, M, L, XL", "Navy", "Uniqlo", "Unisex", 20, 4999.00),
    ("UN-GRY-040", "Uniqlo EZY Ankle Pants", "Stretch Twill", "S, M, L, XL", "Grey", "Uniqlo", "Men", 35, 2499.00),
    ("MX-BLU-041", "Max Fashion Casual Shirt", "100% Cotton", "S, M, L, XL", "Blue", "Max", "Men", 45, 799.00),
    ("MX-YLW-042", "Max Fashion Printed Kurti", "Rayon", "S, M, L, XL", "Yellow", "Max", "Women", 50, 699.00),
    ("MX-RED-043", "Max Fashion Track Pants", "Polyester Blend", "S, M, L, XL", "Red", "Max", "Unisex", 55, 599.00),
    ("AL-BLK-044", "Allen Solly Formal Shirt", "Cotton Blend", "38, 40, 42, 44", "Black", "Allen Solly", "Men", 30, 1799.00),
    ("AL-BLU-045", "Allen Solly Chino Trousers", "98% Cotton, 2% Elastane", "30, 32, 34, 36", "Blue", "Allen Solly", "Men", 25, 2299.00),
    ("FP-PRP-046", "FabIndia Block Print Kurta", "100% Cotton", "S, M, L, XL", "Purple", "FabIndia", "Women", 20, 1899.00),
    ("FP-GRN-047", "FabIndia Silk Blend Saree", "Silk-Cotton Blend", "Free Size", "Green", "FabIndia", "Women", 15, 3499.00),
    ("WD-BLK-048", "Woodland Leather Boots", "Genuine Nubuck Leather", "7, 8, 9, 10, 11", "Black", "Woodland", "Men", 20, 4599.00),
    ("WD-BRN-049", "Woodland Casual Sneakers", "Canvas Upper", "7, 8, 9, 10", "Brown", "Woodland", "Men", 25, 2999.00),
    ("BT-WHT-050", "Bata Power Walking Shoes", "Mesh Upper, EVA Sole", "6, 7, 8, 9, 10", "White", "Bata", "Unisex", 40, 1999.00),
]


def init_database():
    """Create and populate the products SQLite database."""
    print("📦 Initializing product database...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # Remove existing DB to start fresh
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_code TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            material TEXT,
            size TEXT,
            color TEXT,
            brand TEXT,
            gender TEXT,
            stock_quantity INTEGER DEFAULT 0,
            price REAL DEFAULT 0.0
        )
    """)

    # Insert products
    cursor.executemany("""
        INSERT INTO products
        (product_code, product_name, material, size, color, brand, gender, stock_quantity, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, PRODUCTS)

    # Create indexes for faster search
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_name ON products(product_name COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_color ON products(color COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_brand ON products(brand COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gender ON products(gender COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price ON products(price)")

    conn.commit()
    conn.close()

    print(f"   ✅ Created {len(PRODUCTS)} products in {DB_PATH}")


def init_faiss_index():
    """Build FAISS vector index from policy documents."""
    print("📚 Building FAISS vector index from policies...")

    if not os.path.exists(POLICY_PATH):
        print(f"   ❌ Policy file not found: {POLICY_PATH}")
        return

    # Read policy text
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        policy_text = f.read()

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_text(policy_text)
    documents = [Document(page_content=chunk) for chunk in chunks]

    print(f"   📄 Split into {len(documents)} chunks")

    # Create embeddings and FAISS index
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY
    )

    vector_store = FAISS.from_documents(documents, embeddings)

    # Save to disk
    os.makedirs(FAISS_INDEX_PATH, exist_ok=True)
    vector_store.save_local(FAISS_INDEX_PATH)

    print(f"   ✅ FAISS index saved to {FAISS_INDEX_PATH}")


if __name__ == "__main__":
    print("=" * 50)
    print("  ShopSage AI - Database Initialization")
    print("=" * 50)
    print()

    if not GOOGLE_API_KEY:
        print("❌ GOOGLE_API_KEY not found!")
        print("   Please set it in your .env file.")
        sys.exit(1)

    init_database()
    print()
    init_faiss_index()
    print()
    print("🎉 Initialization complete! Run 'uvicorn app:app --reload' to start.")
