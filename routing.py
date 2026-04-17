import heapq
import math
import sqlite3

"""
This script handles the pathfinding logic for the Trollexa Smart Cart.
It uses the A* (A-Star) algorithm to find the shortest path from the 
user's current position to a target product, avoiding obstacles (shelves).
"""

class TrollexaRouter:
    def __init__(self, width_m=6.0, height_m=6.0, resolution=0.2):
        self.width_m = width_m
        self.height_m = height_m
        self.resolution = resolution # Each grid cell is 20cm x 20cm
        
        # Calculate grid size
        self.cols = int(width_m / resolution)
        self.rows = int(height_m / resolution)
        
        # Define obstacles (shelves) from database
        self.shelves = self._load_shelves_from_db()

    def _load_shelves_from_db(self, db_path="trollexa.db"):
        """
        Loads the physical dimensions of shelves to act as A* obstacles.
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT x, y, w, h FROM shelves")
            shelves = cursor.fetchall()
            conn.close()
            return shelves
        except Exception as e:
            print(f"Error loading shelves from DB: {e}")
            return []

    def is_obstacle(self, x_m, y_m):
        """
        Checks if a given (x,y) point in meters is inside any shelf.
        We add a small buffer (0.05m) to keep the cart away from shelf edges,
        but small enough so products on the edge are still reachable!
        """
        buffer = 0.05
        for sx, sy, sw, sh in self.shelves:
            if (sx - buffer <= x_m <= sx + sw + buffer) and \
               (sy - buffer <= y_m <= sy + sh + buffer):
                return True
        return False

    def get_neighbors(self, node):
        """
        Returns walkable neighboring grid cells.
        """
        neighbors = []
        x, y = node
        # Up, Down, Left, Right ONLY (Orthogonal movement for straight lines)
        for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                # Convert grid back to meters to check for obstacles
                mx, my = nx * self.resolution, ny * self.resolution
                if not self.is_obstacle(mx, my):
                    neighbors.append((nx, ny))
        return neighbors

    def find_nearest_walkable(self, node_x, node_y, max_radius=15):
        from collections import deque
        queue = deque([(node_x, node_y)])
        visited = set([(node_x, node_y)])
        while queue:
            cx, cy = queue.popleft()
            if not self.is_obstacle(cx * self.resolution, cy * self.resolution):
                return (cx, cy)
            if abs(cx - node_x) + abs(cy - node_y) > max_radius:
                continue
            for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if (nx, ny) not in visited:
                        visited.add((nx, ny))
                        queue.append((nx, ny))
        return (node_x, node_y)

    def a_star(self, start_m, goal_m):
        """
        Calculates optimal orthogonal path using A*
        """
        start_raw = (int(start_m[0] / self.resolution), int(start_m[1] / self.resolution))
        goal_raw = (int(goal_m[0] / self.resolution), int(goal_m[1] / self.resolution))

        # Snap to walkable nodes so A* doesn't fail if target or user is physically inside a shelf
        start = self.find_nearest_walkable(start_raw[0], start_raw[1])
        goal = self.find_nearest_walkable(goal_raw[0], goal_raw[1])

        frontier = []
        # Store metadata in frontier: (priority, id, node, dx, dy)
        # Using counter to prevent comparing nodes when priorities clash
        import itertools
        counter = itertools.count()
        heapq.heappush(frontier, (0, next(counter), start, 0, 0))
        
        came_from = {start: None}
        cost_so_far = {start: 0}

        while frontier:
            item = heapq.heappop(frontier)
            current = item[2]
            cdx = item[3]
            cdy = item[4]

            if current == goal:
                break

            for next_node in self.get_neighbors(current):
                ndx = next_node[0] - current[0]
                ndy = next_node[1] - current[1]
                
                # Base cost is 1.0 (since it's only 4-way now)
                move_cost = 1.0
                
                # Turn penalty: if direction changes, heavily penalize it to prevent stair-casing
                if (cdx, cdy) != (0, 0) and (ndx, ndy) != (cdx, cdy):
                    move_cost += 5.0 
                    
                new_cost = cost_so_far[current] + move_cost
                
                # Simplified tracking - node-based is enough for simple static mazes
                if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                    cost_so_far[next_node] = new_cost
                    # Heuristic: Manhattan distance
                    h = abs(goal[0]-next_node[0]) + abs(goal[1]-next_node[1])
                    priority = new_cost + h
                    heapq.heappush(frontier, (priority, next(counter), next_node, ndx, ndy))
                    came_from[next_node] = current

        # Reconstruct path
        if goal not in came_from:
            return None # No path found
            
        path = []
        curr = goal
        while curr is not None:
            path.append((round(curr[0] * self.resolution, 2), round(curr[1] * self.resolution, 2)))
            curr = came_from[curr]
        
        path.reverse()
        
        # Apply line-of-sight smoothing to make the path straight and smooth
        return self.smooth_path(path)

    def smooth_path(self, path):
        """
        Removes unnecessary waypoints by only keeping the corners where the direction changes.
        This forces the SVG to draw perfectly straight orthogonal lines.
        """
        if not path or len(path) <= 2:
            return path
            
        smoothed_path = [path[0]]
        
        for i in range(1, len(path)-1):
            prev = path[i-1]
            curr = path[i]
            nxt = path[i+1]
            
            # Use a tiny threshold handling float equality for the meter coordinates
            dx1 = round(curr[0] - prev[0], 3)
            dy1 = round(curr[1] - prev[1], 3)
            dx2 = round(nxt[0] - curr[0], 3)
            dy2 = round(nxt[1] - curr[1], 3)
            
            # If the vector changes, it's a corner, so we keep it.
            if (dx1 != dx2) or (dy1 != dy2):
                smoothed_path.append(curr)
                
        smoothed_path.append(path[-1])
        return smoothed_path

    def generate_directions(self, path):
        """
        Converts a list of coordinates into simple text instructions.
        """
        if not path or len(path) < 2:
            return ["You have arrived!"]
            
        instructions = []
        instructions.append(f"Start at {path[0]}")
        
        # Simple logic: compare consecutive points
        # For a college project, we can just say "Move to point X, then Y"
        # or calculate simple turn angles.
        for i in range(1, len(path)):
            instructions.append(f"Move to {path[i]}")
            
        instructions.append("You have reached your destination.")
        return instructions

# Simple test block
if __name__ == "__main__":
    router = TrollexaRouter()
    
    start_pos = (0.5, 0.5) # Bottom left corner
    goal_pos = (5.5, 5.5)  # Top right corner
    
    path = router.a_star(start_pos, goal_pos)
    if path:
        print(f"Path found with {len(path)} steps.")
        print("First 5 steps:", path[:5])
        # directions = router.generate_directions(path)
        # for d in directions: print(d)
    else:
        print("No path found! Obstacles might be blocking the way.")
