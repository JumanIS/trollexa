import sqlite3
import random
import urllib.request
import os
from pathlib import Path

DB_PATH = Path(__file__).with_name("trollexa.db")
IMAGES_DIR = Path(__file__).parent / "frontend" / "images" / "products"

def download_image(name, sku):
    """
    Downloads a deterministic square image from a placeholder service.
    """
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        
    filename = f"{sku}.jpg"
    filepath = IMAGES_DIR / filename
    
    # We use a deterministic seed so we don't get random images on every refresh
    # Using specific keyword blocks from the name for realism
    keyword = name.split()[0].lower()
    url = f"https://picsum.photos/seed/{keyword}{sku}/200/200"
    
    if not filepath.exists():
        print(f"Downloading image for {name} ({sku})...")
        try:
            # Masking as browser since some APIs block simple urllib
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
        except Exception as e:
            print(f"Failed to download image for {sku}: {e}")
            
    return f"images/products/{filename}"

def seed_db(db_path: Path):
    """
    Seeds the Trollexa database with a single 6x6m store, 
    shelves structured like class tables, categories, 
    products with coordinates and downloaded images, and beacons.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # --- 1. Seed Store ---
    cur.execute("INSERT INTO stores (name, width_m, height_m) VALUES (?, ?, ?)", 
                ("Trollexa College Campus Store", 6.0, 6.0))
    store_id = cur.lastrowid
    
    # --- 2. Seed Shelves (Class Table Layout) ---
    shelves = [
        (1.0, 1.0, 1.5, 1.5),
        (3.5, 1.0, 1.5, 1.5),
        (1.0, 3.5, 1.5, 1.5),
        (3.5, 3.5, 1.5, 1.5)
    ]
    cur.executemany("INSERT INTO shelves (x, y, w, h) VALUES (?, ?, ?, ?)", shelves)

    # --- 3. Seed Beacons ---
    beacons = [
        (1, 0.0, 0.0, -59),
        (2, 6.0, 0.0, -59),
        (3, 0.0, 6.0, -59),
        (4, 6.0, 6.0, -59)
    ]
    cur.executemany("INSERT INTO beacons (minor, x, y, tx_power) VALUES (?, ?, ?, ?)", beacons)

    # --- 4. Seed Categories ---
    categories_dict = {
        "Fruits": 1,
        "Vegetables": 2,
        "Dairy": 3,
        "Snacks": 4,
        "Beverages": 5,
        "College Supplies": 6
    }
    for name, cid in categories_dict.items():
        cur.execute("INSERT INTO categories (id, name) VALUES (?, ?)", (cid, name))

    # --- 5. Seed Products (With Images) ---
    raw_products = [
        (categories_dict["Fruits"], "Fresh Red Apple", 1.50, "FRU-001", 1.2, 2.7),
        (categories_dict["Fruits"], "Yellow Banana Bundle", 2.00, "FRU-002", 1.8, 2.7),
        (categories_dict["Fruits"], "Juicy Orange", 1.30, "FRU-003", 2.2, 2.7),
        
        (categories_dict["Vegetables"], "Green Cabbage", 2.50, "VEG-001", 3.7, 2.7),
        (categories_dict["Vegetables"], "Organic Carrot", 0.99, "VEG-002", 4.3, 2.7),
        (categories_dict["Vegetables"], "Potato Sack", 4.50, "VEG-003", 4.8, 2.7),

        (categories_dict["Dairy"], "Whole Milk 1L", 1.20, "DAI-001", 1.5, 0.8),
        (categories_dict["Dairy"], "Cheddar Cheese Block", 3.40, "DAI-002", 2.0, 0.8),

        (categories_dict["Snacks"], "Potato Chips Original", 1.80, "SNA-001", 1.3, 3.3),
        (categories_dict["Snacks"], "Chocolate Cookies", 2.10, "SNA-002", 1.8, 3.3),
        (categories_dict["Snacks"], "Salted Peanuts", 1.50, "SNA-003", 2.3, 3.3),

        (categories_dict["Beverages"], "Sparkling Water", 1.00, "BEV-001", 3.8, 3.3),
        (categories_dict["Beverages"], "Cola Soda Can", 0.80, "BEV-002", 4.2, 3.3),
        (categories_dict["Beverages"], "Orange Juice Box", 2.50, "BEV-003", 4.7, 3.3),

        (categories_dict["College Supplies"], "Blue Ballpoint Pen", 0.50, "COL-001", 1.2, 5.2),
        (categories_dict["College Supplies"], "College Notebook", 2.50, "COL-002", 1.8, 5.2),
        (categories_dict["College Supplies"], "Calculator", 15.00, "COL-003", 2.2, 5.2)
    ]
    
    products_with_images = []
    for cat_id, name, price, sku, x, y in raw_products:
        img_path = download_image(name, sku)
        products_with_images.append((cat_id, name, price, sku, img_path, x, y))

    cur.executemany("""
        INSERT INTO products (category_id, name, price, sku, image_path, x, y) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, products_with_images)

    conn.commit()
    conn.close()
    
    print(f"\nDatabase seeded successfully with {len(products_with_images)} images!")

if __name__ == "__main__":
    seed_db(DB_PATH)
