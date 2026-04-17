import math
import sqlite3

"""
This script handles the localization logic for the Trollexa Smart Cart.
It converts BLE beacon signal strength (RSSI) into a physical (X, Y) position
inside the store using a simple Weighted Centroid algorithm.
"""

class TrollexaLocator:
    def __init__(self, db_path="trollexa.db"):
        self.db_path = db_path
        # System parameters for signal-to-distance conversion
        # N value typically ranges from 2 to 4 (environment factor)
        self.PATH_LOSS_EXPONENT = 2.5 
        # Measured Power (RSSI at 1 meter distance)
        self.MEASURED_POWER = -59 

    def calculate_distance(self, rssi):
        """
        Converts RSSI (Signal Strength) to an approximate distance in meters.
        Formula: Distance = 10 ^ ((Measured Power - RSSI) / (10 * N))
        """
        if rssi == 0:
            return -1.0
        
        ratio = (self.MEASURED_POWER - rssi) / (10 * self.PATH_LOSS_EXPONENT)
        distance = math.pow(10, ratio)
        return distance

    def get_beacon_coordinates(self, beacon_minor):
        """
        Fetch the (X, Y) coordinates of a beacon from the database using its 'minor' ID.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # In our database, the columns are x and y
        cursor.execute("SELECT x, y FROM beacons WHERE minor = ?", (beacon_minor,))
        result = cursor.fetchone()
        
        conn.close()
        return result

    def estimate_position(self, scan_results):
        """
        Estimates the cart's position (X, Y) based on a list of beacon scans.
        The algorithm used is 'Weighted Centroid':
        The closer the beacon (stronger signal), the more 'weight' it has on the final position.
        
        scan_results: A dictionary like {1: -65, 2: -70} where keys are minor IDs.
        """
        total_weight = 0
        sum_x = 0
        sum_y = 0
        
        for beacon_minor, rssi in scan_results.items():
            # 1. Get beacon location from DB
            coords = self.get_beacon_coordinates(beacon_minor)
            if not coords:
                continue
                
            bx, by = coords
            
            # 2. Calculate distance and weight
            # Weight is the inverse of distance squared (closer = much heavier)
            dist = self.calculate_distance(rssi)
            if dist <= 0:
                continue
                
            weight = 1.0 / (dist * dist)
            
            # 3. Accumulate weighted coordinates
            sum_x += bx * weight
            sum_y += by * weight
            total_weight += weight
            
        if total_weight == 0:
            return None # Could not determine position
            
        # Final Estimated Coordinates
        est_x = sum_x / total_weight
        est_y = sum_y / total_weight
        
        return round(est_x, 2), round(est_y, 2)

# Simple test block (runs only if this script is executed directly)
if __name__ == "__main__":
    locator = TrollexaLocator()
    
    # Mock data: Signals from beacons with minor IDs 1, 2, and 4
    mock_scans = {
        1: -60,  # Near Beacon 1 (0.3, 0.3)
        2: -80,  # Far from Beacon 2 (5.7, 0.3)
        4: -85   # Very far from Beacon 4 (5.7, 5.7)
    }
    
    pos = locator.estimate_position(mock_scans)
    if pos:
        print(f"Estimated Cart Position: X={pos[0]}m, Y={pos[1]}m")
    else:
        print("Failed to estimate position. Please check beacon IDs in DB.")
