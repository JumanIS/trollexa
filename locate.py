import asyncio
import math
import os
from bleak import BleakScanner

# ==========================================
# CONFIGURATION
# ==========================================
# Map coordinates (x, y) in meters for a 5x5m room
BEACON_MAP = {
    "DD:34:02:0C:00:6B": {"x": 2.5, "y": 2.5, "name": "center"},
    "DD:34:02:0C:01:A0": {"x": 0.0, "y": 0.0, "name": "TR"},
    "DD:34:02:0C:01:68": {"x": 5.0, "y": 0.0, "name": "TL"},
    "DD:34:02:0C:00:F2": {"x": 0.0, "y": 5.0, "name": "DL"},
    "DD:34:02:0C:02:56": {"x": 5.0, "y": 5.0, "name": "DR"},
}

MEASURED_POWER = -59  # RSSI expected at 1 meter
N_FACTOR = 2.4        # Environmental factor (2.0=vacuum, 3.0+=noisy indoor)
RSSI_THRESHOLD = -85  # Ignore very weak/ghost signals (Tuned from -90)

# State storage
latest_rssi = {}

def calculate_distance(rssi):
    """Log-distance path loss model to convert RSSI to meters."""
    if rssi >= 0: return 0.1
    return math.pow(10, (MEASURED_POWER - rssi) / (10 * N_FACTOR))

def draw_map(x, y):
    """Draws a 20x10 ASCII grid representing the 5x5m room."""
    width, height = 20, 10
    grid = [[" " for _ in range(width)] for _ in range(height)]
    
    # Draw Beacons (B)
    for mac, data in BEACON_MAP.items():
        gx = int(data['x'] * (width-1)/5)
        gy = int(data['y'] * (height-1)/5)
        if 0 <= gx < width and 0 <= gy < height:
            grid[gy][gx] = "B"

    # Draw User (U)
    ux, uy = int(x * (width-1)/5), int(y * (height-1)/5)
    if 0 <= ux < width and 0 <= uy < height:
        grid[uy][ux] = "U"

    output = "\n" + "-" * (width + 2) + "\n"
    for row in grid:
        output += "|" + "".join(row) + "|\n"
    output += "-" * (width + 2)
    return output

def estimate_location():
    """Calculates weighted centroid and checks for 'Outside' status."""
    total_weight, sum_x, sum_y = 0, 0, 0
    active_count = 0
    min_dist = 999 
    
    for mac, rssi_list in latest_rssi.items():
        if not rssi_list or mac not in BEACON_MAP: continue
            
        avg_rssi = sum(rssi_list) / len(rssi_list)
        
        # Filter signals that are too weak to be useful
        if avg_rssi < RSSI_THRESHOLD: continue
        
        dist = calculate_distance(avg_rssi)
        if dist < min_dist: min_dist = dist
        
        # Inverse cube weighting (1/d^3) prioritizes the nearest beacons
        weight = 1.0 / math.pow(dist, 3) 
        
        sum_x += BEACON_MAP[mac]['x'] * weight
        sum_y += BEACON_MAP[mac]['y'] * weight
        total_weight += weight
        active_count += 1
        
    # Boundary Check: If the closest beacon is > 4.5m away, user is outside
    if active_count > 0 and min_dist > 4.5:
        return "OUTSIDE"
        
    if total_weight == 0 or active_count < 2:
        return None
        
    return (sum_x / total_weight, sum_y / total_weight)

async def run_localization():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("--- Trollexa Pro Radar (5x5m) ---")

    def callback(device, adv):
        mac = device.address
        if mac in BEACON_MAP:
            latest_rssi.setdefault(mac, [])
            # Fix: Use adv.rssi for WinRT backend compatibility
            latest_rssi[mac].append(adv.rssi)
            # Rolling average window size
            if len(latest_rssi[mac]) > 5: latest_rssi[mac].pop(0)

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    
    try:
        while True:
            pos = estimate_location()
            
            # Reset cursor to top-left for flicker-free update
            print("\033[H", end="") 
            print(f"--- Trollexa Pro Radar (5x5m) ---")
            
            if pos == "OUTSIDE":
                print("\n\n   [ WARNING: USER IS OUTSIDE ROOM ]    ")
                print("   Closest beacon is too far for tracking. \n\n")
            elif pos:
                x, y = pos # Safe to unpack now
                print(draw_map(x, y))
                print(f"Position: ({x:4.2f}m, {y:4.2f}m)               ")
                
                # Update database for app.py SSE endpoint to read
                try:
                    import sqlite3
                    conn = sqlite3.connect("trollexa.db")
                    # Calculate basic heading
                    old_state = conn.execute("SELECT current_x, current_y, heading FROM live_state WHERE id = 1").fetchone()
                    heading = 0.0
                    if old_state:
                        dx = x - old_state[0]
                        dy = y - old_state[1]
                        if abs(dx) > 0.05 or abs(dy) > 0.05:
                            raw_deg = math.degrees(math.atan2(dy, dx))
                            heading = (raw_deg + 90) % 360
                        else:
                            heading = old_state[2]
                            
                    conn.execute("UPDATE live_state SET current_x=?, current_y=?, heading=? WHERE id=1", (x, y, heading))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"DB Update failed: {e}")
                    
            else:
                print("\n\n   [ SEARCHING FOR BEACON SIGNALS... ]   \n\n")
            
            await asyncio.sleep(0.5) # Reduced frequency slightly to save CPU/DB load
    except KeyboardInterrupt:
        print("\nShutting down Trollexa...")
    finally:
        await scanner.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_localization())
    except KeyboardInterrupt:
        pass