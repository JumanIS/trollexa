from flask import copy_current_request_context
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import sqlite3
import difflib
import webbrowser
import threading
import math
import cv2
from PIL import Image
import io
import os
import urllib.request
from pathlib import Path
import asyncio
from bleak import BleakScanner

# Internal imports from Trollexa Core
from localization import TrollexaLocator
from routing import TrollexaRouter
from voice_locate_product import VoiceProductLocator
from ultralytics import YOLO

app = Flask(__name__)
# Enable CORS so the offline frontend can make requests
CORS(app)
# TODO: shelves names and should be copy_current_request_context
# TODO: live routing simulator
DB_PATH = "trollexa.db"

# ==========================================
# Schema Generation & DB Setup
# ==========================================
def initialize_database():
    tdb = Path(DB_PATH)
    force_rebuild = False
    
    # Auto-destroy old un-optimized schema (one that still has live_state table)
    # if tdb.exists():
    #     try:
    #         conn = sqlite3.connect(DB_PATH)
    #         row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_state'").fetchone()
    #         conn.close()
    #         if row:
    #             print("Old schema detected (live_state). Tearing down database...")
    #             os.remove(DB_PATH)
    #             force_rebuild = True
    #     except Exception:
    #         pass

    # Skip if DB already exists and is up-to-date
    if tdb.exists():
        return
        
    print("Database not found! Initializing unified schema + seed data...")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    # Create all tables (no live_state - positions held in memory via BLE)
    cur.executescript("""
        CREATE TABLE stores (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, width_m REAL DEFAULT 6.0, height_m REAL DEFAULT 6.0);
        CREATE TABLE shelves (id INTEGER PRIMARY KEY AUTOINCREMENT, x REAL, y REAL, w REAL, h REAL);
        CREATE TABLE beacons (id INTEGER PRIMARY KEY AUTOINCREMENT, minor INTEGER, x REAL, y REAL, tx_power INTEGER);
        CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT, price REAL, sku TEXT, image_path TEXT, x REAL, y REAL, FOREIGN KEY(category_id) REFERENCES categories(id));
    """)

    # Seed store metadata
    cur.execute("INSERT INTO stores (name, width_m, height_m) VALUES (?, ?, ?)", ("Trollexa College Campus Store", 6.0, 6.0))
    
    # Seed default shelves in a class-table layout
    shelves = [(1.0, 1.0, 1.5, 1.5), (3.5, 1.0, 1.5, 1.5), (1.0, 3.5, 1.5, 1.5), (3.5, 3.5, 1.5, 1.5)]
    cur.executemany("INSERT INTO shelves (x, y, w, h) VALUES (?, ?, ?, ?)", shelves)

    # Seed BLE beacons at each corner of the 6x6m store
    beacons = [(1, 0.0, 0.0, -59), (2, 6.0, 0.0, -59), (3, 0.0, 6.0, -59), (4, 6.0, 6.0, -59)]
    cur.executemany("INSERT INTO beacons (minor, x, y, tx_power) VALUES (?, ?, ?, ?)", beacons)

    # Seed product categories
    cats = {"Fruits": 1, "Vegetables": 2, "Dairy": 3, "Snacks": 4, "Beverages": 5, "College Supplies": 6}
    for name, cid in cats.items():
        cur.execute("INSERT INTO categories (id, name) VALUES (?, ?)", (cid, name))

    # Ensure product image folder exists
    images_dir = Path("frontend") / "images" / "products"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    def download_image(name, sku):
        """Downloads a deterministic product image from picsum."""
        filename = f"{sku}.jpg"
        filepath = images_dir / filename
        keyword = name.split()[0].lower()
        url = f"https://picsum.photos/seed/{keyword}{sku}/200/200"
        if not filepath.exists():
            print(f"Downloading {sku}.jpg...")
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as resp, open(filepath, 'wb') as out_file:
                    out_file.write(resp.read())
            except Exception as e:
                print("Failed to download image:", e)
        return f"images/products/{filename}"

    # Seed products with physical (x, y) coordinates on the store map
    raw_products = [
        (cats["Fruits"], "Fresh Red Apple", 1.50, "FRU-001", 1.2, 2.7),
        (cats["Fruits"], "Yellow Banana Bundle", 2.00, "FRU-002", 1.8, 2.7),
        (cats["Fruits"], "Juicy Orange", 1.30, "FRU-003", 2.2, 2.7),
        (cats["Vegetables"], "Green Cabbage", 2.50, "VEG-001", 3.7, 2.7),
        (cats["Vegetables"], "Organic Carrot", 0.99, "VEG-002", 4.3, 2.7),
        (cats["Vegetables"], "Potato Sack", 4.50, "VEG-003", 4.8, 2.7),
        (cats["Dairy"], "Whole Milk 1L", 1.20, "DAI-001", 1.5, 0.8),
        (cats["Dairy"], "Cheddar Cheese Block", 3.40, "DAI-002", 2.0, 0.8),
        (cats["Snacks"], "Potato Chips Original", 1.80, "SNA-001", 1.3, 3.3),
        (cats["Snacks"], "Chocolate Cookies", 2.10, "SNA-002", 1.8, 3.3),
        (cats["Snacks"], "Salted Peanuts", 1.50, "SNA-003", 2.3, 3.3),
        (cats["Beverages"], "Sparkling Water", 1.00, "BEV-001", 3.8, 3.3),
        (cats["Beverages"], "Cola Soda Can", 0.80, "BEV-002", 4.2, 3.3),
        (cats["Beverages"], "Orange Juice Box", 2.50, "BEV-003", 4.7, 3.3),
        (cats["College Supplies"], "Blue Ballpoint Pen", 0.50, "COL-001", 1.2, 5.2),
        (cats["College Supplies"], "College Notebook", 2.50, "COL-002", 1.8, 5.2),
        (cats["College Supplies"], "Calculator", 15.00, "COL-003", 2.2, 5.2)
    ]
    
    prod_imgs = [(c, n, p, s, download_image(n, s), x, y) for c, n, p, s, x, y in raw_products]
    cur.executemany("INSERT INTO products (category_id, name, price, sku, image_path, x, y) VALUES (?, ?, ?, ?, ?, ?, ?)", prod_imgs)

    conn.commit()
    conn.close()
    print("Database built and seeded successfully.")


# Initialize the database and seed it FIRST, before any service touches it
initialize_database()

# Initialize Core Services (require DB tables to already exist)
locator = TrollexaLocator(db_path=DB_PATH)
router = TrollexaRouter()

# Lazy loads - initialized here for YOLO/Whisper
print("Loading AI Models... This may take a moment.")
voice_search = VoiceProductLocator() # Uses Whisper
yolo_model = YOLO("yolov8n.pt")      # Uses YOLOv8
print("AI Models Loaded.")

# ==========================================
# In-Memory BLE Tracking Engine
# ==========================================
LIVE_X = 0.5
LIVE_Y = 0.5
LIVE_HEADING = 0.0

BEACON_MAP = {
    "DD:34:02:0C:00:6B": {"x": 2.5, "y": 2.5, "name": "center"},
    "DD:34:02:0C:01:A0": {"x": 0.0, "y": 0.0, "name": "TR"},
    "DD:34:02:0C:01:68": {"x": 5.0, "y": 0.0, "name": "TL"},
    "DD:34:02:0C:00:F2": {"x": 0.0, "y": 5.0, "name": "DL"},
    "DD:34:02:0C:02:56": {"x": 5.0, "y": 5.0, "name": "DR"},
}

MEASURED_POWER = -59  
N_FACTOR = 2.4        
RSSI_THRESHOLD = -85  
latest_rssi = {}

def calculate_distance(rssi):
    if rssi >= 0: return 0.1
    return math.pow(10, (MEASURED_POWER - rssi) / (10 * N_FACTOR))

def estimate_location():
    total_weight, sum_x, sum_y = 0, 0, 0
    active_count = 0
    min_dist = 999 
    
    for mac, rssi_list in latest_rssi.items():
        if not rssi_list or mac not in BEACON_MAP: continue
        avg_rssi = sum(rssi_list) / len(rssi_list)
        if avg_rssi < RSSI_THRESHOLD: continue
        dist = calculate_distance(avg_rssi)
        if dist < min_dist: min_dist = dist
        weight = 1.0 / math.pow(dist, 3) 
        
        sum_x += BEACON_MAP[mac]['x'] * weight
        sum_y += BEACON_MAP[mac]['y'] * weight
        total_weight += weight
        active_count += 1
        
    if active_count > 0 and min_dist > 4.5:
        return "OUTSIDE"
    if total_weight == 0 or active_count < 2:
        return None
    return (sum_x / total_weight, sum_y / total_weight)

async def run_localization():
    def callback(device, adv):
        mac = device.address
        if mac in BEACON_MAP:
            latest_rssi.setdefault(mac, [])
            latest_rssi[mac].append(adv.rssi)
            if len(latest_rssi[mac]) > 5: latest_rssi[mac].pop(0)

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    
    global LIVE_X, LIVE_Y, LIVE_HEADING
    try:
        while True:
            pos = estimate_location()
            if pos and pos != "OUTSIDE":
                x, y = pos
                dx = x - LIVE_X
                dy = y - LIVE_Y
                if abs(dx) > 0.05 or abs(dy) > 0.05:
                    raw_deg = math.degrees(math.atan2(dy, dx))
                    LIVE_HEADING = (raw_deg + 90) % 360
                
                LIVE_X = x
                LIVE_Y = y
            await asyncio.sleep(0.5)
    except Exception as e:
        print("BLE Loop Error:", e)
    finally:
        await scanner.stop()

def start_ble_scanner():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_localization())


def get_db_connection():
    """Helper function to get a clean database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ================================
# Static Frontend Serving
# ================================
@app.route('/')
def serve_index():
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('frontend', path)


@app.route('/api/categories', methods=['GET'])
def get_categories():
    """
    Returns all product categories for the frontend modal.
    """
    conn = get_db_connection()
    categories = conn.execute("SELECT id, name FROM categories").fetchall()
    conn.close()
    return jsonify([dict(c) for c in categories])

@app.route('/api/search', methods=['POST'])
def search_products():
    """
    Search by 'query' (Fuzzy Match Text Similarity) or 'category_id'.
    Returns matching products and their physical (X,Y) coordinates.
    """
    data = request.get_json() or {}
    query = data.get('query', '').strip()
    category_id = data.get('category_id')

    conn = get_db_connection()
    
    if category_id:
        # Search directly by Category ID
        results = conn.execute("""
            SELECT p.id, p.name, p.price, p.sku, p.image_path, c.name as category, p.x, p.y 
            FROM products p 
            JOIN categories c ON p.category_id = c.id
            WHERE p.category_id = ?
        """, (category_id,)).fetchall()
        
        products = [dict(r) for r in results]
    elif query:
        # Semantic/Fuzzy Search logic using Text Similarity (difflib)
        all_products = conn.execute("""
            SELECT p.id, p.name, p.price, p.sku, p.image_path, c.name as category, p.x, p.y 
            FROM products p
            JOIN categories c ON p.category_id = c.id
        """).fetchall()
        
        products = []
        for p in all_products:
            # Calculate match ratio for Name and SKU
            name_score = difflib.SequenceMatcher(None, query.lower(), p['name'].lower()).ratio()
            sku_score = difflib.SequenceMatcher(None, query.lower(), p['sku'].lower()).ratio()
            
            # If the text similarity is > 40%, we count it as a match
            if max(name_score, sku_score) > 0.4:
                p_dict = dict(p)
                p_dict['match_score'] = max(name_score, sku_score)
                products.append(p_dict)
                
        # Sort by best match score
        products.sort(key=lambda x: x['match_score'], reverse=True)
    else:
        products = []

    # Fetch shelves to draw the map dynamically
    shelves_data = conn.execute("SELECT x, y, w, h FROM shelves").fetchall()
    shelves = [dict(s) for s in shelves_data]

    conn.close()
    return jsonify({"results": products, "shelves": shelves})

@app.route('/api/save-layout', methods=['POST'])
def save_layout():
    """
    Saves the new store layout (shelves dimensions and coordinates) 
    from the Admin Manager Tool into the SQLite database.
    """
    data = request.get_json()
    shelves = data.get('shelves', [])
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Wipe the entire shelves table
        cur.execute("DELETE FROM shelves")
        
        # Batch insert all incoming shelves
        for s in shelves:
            cur.execute("INSERT INTO shelves (x, y, w, h) VALUES (?, ?, ?, ?)", (s['x'], s['y'], s['w'], s['h']))
            
        conn.commit()
        
        # IMPORTANT: Trigger the A* Router to reload its graph 
        # so live navigation instantly respects the new obstacles
        router.shelves = router._load_shelves_from_db()
        
        return jsonify({"status": "success", "message": "Layout saved successfully"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/voice-search', methods=['POST'])
def voice_search_stt():
    """
    Uses Whisper strictly for Speech-to-Text conversion.
    Frontend gets text back and decides whether to search it.
    """
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
        
    audio_file = request.files['audio']
    audio_path = "temp_voice.wav"
    audio_file.save(audio_path)
    
    # Run Whisper STT via our VoiceProductLocator
    # We tweak its usage slightly to just do STT for this route
    try:
        transcription = voice_search.transcribe(audio_path)
        return jsonify({"text": transcription})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Global state to share between background OpenCV thread and Frontend JSON polling
live_detections = []

def gen_frames():
    """ Backend OpenCV YOLO Streaming Generator (MJPEG) """
    global live_detections
    # Open local USB webcam or Raspberry Pi camera zero
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Error: Could not open local camera.")
        return
        
    while True:
        success, frame = camera.read()
        if not success:
            break
            
        # Run YOLO on the cv2 BGR frame natively
        results = yolo_model(frame, verbose=False)
        seen_classes = set()
        new_detections = []
        
        if len(results) > 0 and len(results[0].boxes) > 0:
            # Tell YOLO to draw the bounding boxes onto the frame automatically!
            frame = results[0].plot()
            
            for box in results[0].boxes:
                conf = float(box.conf[0])
                class_id = int(box.cls[0])
                class_name = results[0].names[class_id]
                
                if conf > 0.2 and class_name not in seen_classes:
                    seen_classes.add(class_name)
                    new_detections.append({
                        "class_name": class_name,
                        "confidence": conf
                    })
                    
        new_detections.sort(key=lambda x: x['confidence'], reverse=True)
        live_detections = new_detections
        
        # Convert drawn frame back to JPEG bytes
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        
        # Yield the multipart chunk
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
               
    camera.release()

@app.route('/api/video-feed')
def video_feed():
    """ Route to embed directly into an <img> src for 45fps live view """
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/latest-detections')
def get_latest_detections():
    """ Lightweight endpoint for frontend to repeatedly poll while stream runs """
    global live_detections
    return jsonify({"detections": live_detections})



@app.route('/api/get-route', methods=['GET'])
def get_route():
    """
    Server-Sent Events (SSE) endpoint that continuously streams
    the updated A* path and current location.
    """
    product_id = request.args.get('product_id')
    
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400
        
    def generate():
        import json
        import time
        while True:
            # Send live position instantly directly from memory thread syncs
            global LIVE_X, LIVE_Y, LIVE_HEADING
            start_pos = (LIVE_X, LIVE_Y)
            heading = LIVE_HEADING
            
            # Fetch destination from products
            conn = get_db_connection()
            target = conn.execute("SELECT x, y FROM products WHERE id = ?", (product_id,)).fetchone()
            conn.close()
            
            if not target:
                yield f"data: {json.dumps({'error': 'Product not found'})}\n\n"
                time.sleep(1)
                continue
                
            goal_pos = (target['x'], target['y'])
            
            # Calculate A* Route
            path = router.a_star(start_pos, goal_pos)
            
            if not path:
                yield f"data: {json.dumps({'error': 'No valid route found'})}\n\n"
            else:
                yield f"data: {json.dumps({'path': path, 'start': start_pos, 'goal': goal_pos, 'heading': heading})}\n\n"
            time.sleep(1) # Send an update down the socket

    return Response(generate(), mimetype='text/event-stream')

import subprocess

def launch_kiosk():
    # Launches Chromium in full-screen kiosk mode on the Pi
    try:
        subprocess.Popen(['chromium-browser', '--kiosk', 'http://localhost:5000/'])
    except Exception as e:
        print(f"Could not launch browser: {e}")

if __name__ == '__main__':
    # Fire up background BLE scanner routine
    threading.Thread(target=start_ble_scanner, daemon=True).start()
    
    # Automatically open local browser in Kiosk mode
    threading.Timer(1.5, launch_kiosk).start()
    
    # Running offline mode for Trollexa API Hub
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)


# if __name__ == '__main__':
#     # Fire up background BLE scanner routine
#     threading.Thread(target=start_ble_scanner, daemon=True).start()
    
#     # Automatically open local browser using threading timer
#     threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000/")).start()
#     # Running offline mode for Trollexa API Hub
#     app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
