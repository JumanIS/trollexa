import re
import sqlite3
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

"""
This script provides text search capabilities for the Trollexa database.
It uses 'TF-IDF' (Term Frequency-Inverse Document Frequency) to match
user voice queries (like "Where is the milk?") with product names and categories.
"""

DB_PATH = Path(__file__).with_name("trollexa.db")

def get_connection():
    """ Helper to get a database connection with Row support (access by name) """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_text(text: str) -> str:
    """ Cleans text by removing symbols and extra spaces """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def clean_user_query(text: str) -> str:
    """ 
    Removes common filler words like 'where is' or 'find me' 
    to focus on the actual product name.
    """
    text = normalize_text(text)
    stop_phrases = [
        "where is", "where are", "find me", "find", 
        "locate", "show me", "show", "i need", 
        "i want", "give me", "search for", "search",
    ]
    for phrase in stop_phrases:
        if text.startswith(phrase):
            text = text[len(phrase):].strip()
    return text

def describe_position(x: float, y: float, store_width: float, store_height: float) -> str:
    """ 
    Converts (X, Y) coordinates into a human-readable area description
    (e.g., "Front-Left side of the store").
    """
    horizontal = "center"
    vertical = "center"

    if x < store_width / 3:
        horizontal = "left"
    elif x > (store_width / 3) * 2:
        horizontal = "right"

    if y < store_height / 3:
        vertical = "front"
    elif y > (store_height / 3) * 2:
        vertical = "back"

    if horizontal == "center" and vertical == "center":
        return "middle of the store"
    if horizontal == "center":
        return f"{vertical} side of the store"
    if vertical == "center":
        return f"{horizontal} side of the store"

    return f"{vertical}-{horizontal} side of the store"

def load_all_products_from_db():
    """ Fetches product info and their coordinates from the SQLite DB """
    conn = get_connection()
    cur = conn.cursor()

    sql = """
    SELECT
        p.id, p.name AS product_name, p.sku,
        c.name AS category_name, p.x AS product_x, p.y AS product_y
    FROM products p
    LEFT JOIN categories c ON c.id = p.category_id
    """
    rows = cur.execute(sql).fetchall()
    conn.close()
    return rows

class ProductSearchEngine:
    """
    The main search engine that 'learns' the product list and 
    compares user queries using Cosine Similarity.
    """
    def __init__(self):
        self.products = load_all_products_from_db()
        self.documents = []
        self.doc_to_product = []

        # Prepare a search index by combining name, category, and description
        for row in self.products:
            phrases = self.build_search_texts(row)
            for phrase in phrases:
                self.documents.append(phrase)
                self.doc_to_product.append(row)

        # Create the TF-IDF Vectorizer
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        if self.documents:
            self.matrix = self.vectorizer.fit_transform(self.documents)

    def build_search_texts(self, row):
        """ Combines various fields into searchable phrases """
        p_name = normalize_text(row["product_name"] or "")
        c_name = normalize_text(row["category_name"] or "")
        
        return [p_name, f"{p_name} {c_name}", f"{c_name} {p_name}"]

    def search(self, query: str, top_n: int = 3):
        """ Returns the best matching products for a text query """
        if not self.documents:
            return []
            
        cleaned_query = clean_user_query(query)
        # Convert query to numbers (vector)
        query_vector = self.vectorizer.transform([cleaned_query])
        # Compare with all products using math (cosine similarity)
        scores = cosine_similarity(query_vector, self.matrix)[0]
        
        # Get indices of best scores
        ranked_indices = np.argsort(scores)[::-1]
        
        results = []
        seen_ids = set()
        for idx in ranked_indices:
            score = float(scores[idx])
            if score < 0.1: continue # Ignore unrelated matches
            
            row = self.doc_to_product[idx]
            if row["id"] in seen_ids: continue
            
            seen_ids.add(row["id"])
            results.append({
                "product_id": row["id"],
                "name": row["product_name"],
                "x_m": row["product_x"],
                "y_m": row["product_y"],
                "score": score
            })
            if len(results) >= top_n: break
            
        return results

# Test search if run directly
if __name__ == "__main__":
    engine = ProductSearchEngine()
    q = "where can I find some fresh milk?"
    matches = engine.search(q)
    for m in matches:
        print(f"Match: {m['name']} (Score: {m['score']:.2f}) at ({m['x_m']}, {m['y_m']})")