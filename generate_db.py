import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("trollexa.db")

def create_db(db_path: Path) -> None:
    """
    Creates the Trollexa (v2.6) optimized SQLite schema.
    This schema merges product locations into the products table 
    and uses a single-row live_state for high-speed Pi lookups.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS live_state;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS categories;
        DROP TABLE IF EXISTS beacons;
        DROP TABLE IF EXISTS shelves;
        DROP TABLE IF EXISTS stores;

        -- 1. Physical Environment
        CREATE TABLE stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            width_m REAL DEFAULT 6.0,
            height_m REAL DEFAULT 6.0
        );

        CREATE TABLE shelves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            x REAL, 
            y REAL, 
            w REAL, 
            h REAL  -- Rectangular obstacles for A*
        );

        CREATE TABLE beacons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            minor INTEGER,                  -- Unique ID for BLE Beacon
            x REAL, 
            y REAL,                 -- Physical coordinates
            tx_power INTEGER                -- Reference power for distance
        );

        -- 2. Product & Category Data
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT
        );

        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            name TEXT,
            price REAL,
            sku TEXT,
            image_path TEXT,                -- Added for product square images
            x REAL,                         -- Target X coordinate on map
            y REAL,                         -- Target Y coordinate on map
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );

        -- 3. Real-Time State (Single-User/Pi)
        CREATE TABLE live_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), -- Fixed row for single user
            current_x REAL DEFAULT 0.0,
            current_y REAL DEFAULT 0.0,
            heading REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Initialize the live_state table with the single user row
        INSERT INTO live_state (id, current_x, current_y, heading) VALUES (1, 0.5, 0.5, 0.0);
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_db(DB_PATH)
    print("Trollexa v2.6 Database Schema created successfully at:", DB_PATH)
