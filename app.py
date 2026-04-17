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

# Initialize Core Services
locator = TrollexaLocator(db_path=DB_PATH)
router = TrollexaRouter()

# Lazy loads - initialized here for YOLO/Whisper
print("Loading AI Models... This may take a moment.")
voice_search = VoiceProductLocator() # Uses Whisper
yolo_model = YOLO("yolov8n.pt")      # Uses YOLOv8
print("AI Models Loaded.")

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



@app.route('/api/update-location', methods=['POST'])
def update_location():
    """
    Receives current RSSI values from Pi beacons, calculates (X, Y)
    using Weighted Centroid, and updates the live_state table.
    """
    data = request.get_json()
    if not data or 'scans' not in data:
        return jsonify({"error": "No beacon data provided"}), 400
        
    # data['scans'] format expected: {'1': -65, '2': -70, ...} minor_id: rssi
    scans_int_keys = {int(k): v for k, v in data['scans'].items()}
    pos = locator.estimate_position(scans_int_keys)
    
    if not pos:
        return jsonify({"error": "Could not determine position"}), 500
        
    # Calculate vector heading
    heading = 0.0
    conn = get_db_connection()
    try:
        old_state = conn.execute("SELECT current_x, current_y, heading FROM live_state WHERE id = 1").fetchone()
        if old_state:
            dx = pos[0] - old_state['current_x']
            dy = pos[1] - old_state['current_y']
            if abs(dx) > 0.05 or abs(dy) > 0.05:
                # Math.atan2(dy, dx) gives angle from X-axis
                raw_deg = math.degrees(math.atan2(dy, dx))
                # Add 90 so 0 degrees equals "UP" (-y direction in SVG)
                heading = (raw_deg + 90) % 360
            else:
                heading = old_state['heading']
    except Exception as e:
        print("Warning: Could not fetch old heading:", e)
            
    conn.execute("UPDATE live_state SET current_x = ?, current_y = ?, heading = ? WHERE id = 1", (pos[0], pos[1], heading))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "x": pos[0], "y": pos[1], "heading": heading})

@app.route('/api/get-route', methods=['POST'])
def get_route():
    """
    Reads the user's current position from live_state and 
    the target product's position, returning an A* Path.
    """
    data = request.get_json()
    product_id = data.get('product_id')
    
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400
        
    conn = get_db_connection()
    
    # 1. Fetch current position from live_state
    state = conn.execute("SELECT current_x, current_y, heading FROM live_state WHERE id = 1").fetchone()
    if not state:
        conn.close()
        return jsonify({"error": "Live state not initialized"}), 500
        
    start_pos = (state['current_x'], state['current_y'])
    heading = state['heading'] if 'heading' in state.keys() else 0.0
    
    # 2. Fetch destination from products
    target = conn.execute("SELECT x, y FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    
    if not target:
        return jsonify({"error": "Product not found"}), 404
        
    goal_pos = (target['x'], target['y'])
    
    # 3. Calculate A* Route
    path = router.a_star(start_pos, goal_pos)
    
    if not path:
        return jsonify({"error": "No valid route found. Obstacles blocking path."}), 404
        
    return jsonify({"path": path, "start": start_pos, "goal": goal_pos, "heading": heading})


if __name__ == '__main__':
    # Automatically open local browser using threading timer
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000/")).start()
    # Running offline mode for Trollexa API Hub
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
