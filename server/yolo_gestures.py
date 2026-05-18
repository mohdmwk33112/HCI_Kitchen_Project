import os
import math
import time
import pickle
from dollarpy import Recognizer, Point

class YoloGestureHandler:
    def __init__(self, templates_path="gestures/gesture_templates.pkl", alpha=0.4, conf_thresh=0.4):
        self.alpha = alpha
        self.conf_thresh = conf_thresh
        
        # ── Stillness-based click detection configuration ─────────────────────────
        self.CLICK_STILL_THRESH = 0.015
        self.CLICK_HOLD_SECONDS = 0.8
        self.CLICK_COOLDOWN = 1.0
        
        # ── Tracking state configuration ──────────────────────────────────────────
        self.FRAMES_TO_START = 3
        self.FRAMES_TO_STOP = 8
        
        # ── Active tracking state buffers ─────────────────────────────────────────
        self.live_points = []
        self.smooth_x = None
        self.smooth_y = None
        self.prev_smooth_x = None
        self.prev_smooth_y = None
        self.is_tracking = False
        self.frames_detected = 0
        self.frames_undetected = 0
        self.still_since = None
        self.last_click_time = 0.0
        self.trail_pixels = []  # Normalized trajectory (x, y) for drawing
        
        # ── Resolve templates path ────────────────────────────────────────────────
        # Probe relative directories
        if not os.path.exists(templates_path):
            alt_path = os.path.join(os.path.dirname(__file__), "gestures", "gesture_templates.pkl")
            if os.path.exists(alt_path):
                templates_path = alt_path
            else:
                alt_path2 = os.path.join(os.path.dirname(__file__), "gesture_templates.pkl")
                if os.path.exists(alt_path2):
                    templates_path = alt_path2

        # ── Load DollarPy templates ───────────────────────────────────────────────
        if os.path.exists(templates_path):
            try:
                with open(templates_path, "rb") as f:
                    templates = pickle.load(f)
                self.recognizer = Recognizer(templates)
                print(f"[YoloGestureHandler] Loaded {len(templates)} templates from '{templates_path}'")
            except Exception as e:
                self.recognizer = None
                print(f"[YoloGestureHandler] Error loading templates: {e}")
        else:
            self.recognizer = None
            print(f"[YoloGestureHandler] Warning: Templates file '{templates_path}' not found. DollarPy disabled.")

    def process_detections(self, detections, timestamp_ms=None):
        """
        Processes normalized yolo ingredient detections.
        detections: list of dicts, each: {"label": str, "x": float, "y": float, "w": float, "h": float}
        Returns: (gesture_payload, pointer_data)
        """
        gesture_payload = None
        pointer_data = None
        
        # Case-insensitive allowlist of COCO food classes + best.pt custom food classes + red laser
        allowed_food = {
            # Red Laser Pointer
            "red laser",

            # COCO food & utensils
            "banana", "apple", "orange", "broccoli", "carrot",
            "sandwich", "hot dog", "pizza", "donut", "cake",
            "bottle", "wine glass", "cup", "bowl",
            "fork", "knife", "spoon",
            
            # best.pt custom food classes
            "strawberry", "tomato", "almond", "apricot", "artichoke", "asparagus", 
            "avocado", "blackberry", "blueberry", "brussels sprouts", 
            "cauliflower", "celery", "cherry", "clementine", "gourd", "grape", 
            "green bean", "kiwi fruit", "lemon", "lettuce", "lime", 
            "mandarin orange", "melon", "mushroom", "onion", "papaya", 
            "peach", "pear", "persimmon", "pickle", "pineapple", "potato", 
            "prune", "pumpkin", "raspberry", "sweet potato", "turnip", "watermelon"
        }

        # 1. Identify closest tracked allowed food item (by largest bounding box area)
        best_det = None
        best_area = 0.0
        
        for det in detections:
            label_lower = det["label"].lower()
            if label_lower not in allowed_food:
                continue
            area = det["w"] * det["h"]
            if area > best_area:
                best_area = area
                best_det = det
                
        object_found = best_det is not None
        
        if object_found:
            # Centroid of the closest item
            raw_cx = best_det["x"] + (best_det["w"] / 2)
            raw_cy = best_det["y"] + (best_det["h"] / 2)
            
            # EMA coordinate smoothing
            if self.smooth_x is None:
                self.smooth_x, self.smooth_y = raw_cx, raw_cy
            else:
                self.smooth_x = self.alpha * raw_cx + (1 - self.alpha) * self.smooth_x
                self.smooth_y = self.alpha * raw_cy + (1 - self.alpha) * self.smooth_y
                
            # Pointer data immediately updated every frame
            pointer_data = {"x": round(self.smooth_x, 3), "y": round(self.smooth_y, 3)}
            
            self.frames_detected += 1
            self.frames_undetected = 0
            
            # Start trajectory recording
            if self.frames_detected >= self.FRAMES_TO_START and not self.is_tracking:
                self.is_tracking = True
                self.live_points.clear()
                self.trail_pixels.clear()
                print(f"[YoloGestureHandler] Tracking wand locked onto: '{best_det['label']}'")
                
            if self.is_tracking:
                self.live_points.append(Point(self.smooth_x, self.smooth_y, 1))
                self.trail_pixels.append((self.smooth_x, self.smooth_y))
                
            # Stillness-based click detection
            if self.prev_smooth_x is not None and self.is_tracking:
                delta = math.hypot(self.smooth_x - self.prev_smooth_x, self.smooth_y - self.prev_smooth_y)
                now = time.time()
                if delta < self.CLICK_STILL_THRESH:
                    if self.still_since is None:
                        self.still_since = now
                    elif (now - self.still_since) >= self.CLICK_HOLD_SECONDS:
                        if (now - self.last_click_time) >= self.CLICK_COOLDOWN:
                            self.last_click_time = now
                            self.still_since = None
                            
                            # Clear trail after click to reset gesture tracking
                            self.live_points.clear()
                            self.trail_pixels.clear()
                            
                            print("[YoloGestureHandler] Stillness Click Registered!")
                            gesture_payload = {"gesture": "Click", "confidence": 1.0, "x": round(self.smooth_x, 3), "y": round(self.smooth_y, 3)}
                else:
                    self.still_since = None
                    
            self.prev_smooth_x, self.prev_smooth_y = self.smooth_x, self.smooth_y
            
        else:
            self.frames_undetected += 1
            self.frames_detected = 0
            
            # Object lost - stop and try recognizing gesture
            if self.is_tracking and self.frames_undetected >= self.FRAMES_TO_STOP:
                self.is_tracking = False
                print("[YoloGestureHandler] Object hidden. Recognizing trajectory gesture...")
                
                if len(self.live_points) > 5 and self.recognizer:
                    try:
                        t_start = time.time()
                        result = self.recognizer.recognize(self.live_points)
                        t_end = time.time()
                        
                        if result:
                            gesture_name, confidence = result
                            if confidence >= self.conf_thresh:
                                print(f"[YoloGestureHandler] Recognized gesture '{gesture_name}' (conf={confidence:.2f}) in {t_end - t_start:.4f}s")
                                gesture_payload = {
                                    "gesture": gesture_name,
                                    "confidence": round(confidence, 2),
                                    "x": round(self.prev_smooth_x, 3) if self.prev_smooth_x is not None else 0.5,
                                    "y": round(self.prev_smooth_y, 3) if self.prev_smooth_y is not None else 0.5
                                }
                            else:
                                print(f"[YoloGestureHandler] Rejected low-confidence gesture '{gesture_name}' ({confidence:.2f})")
                    except Exception as e:
                        print(f"[YoloGestureHandler] DollarPy recognition error: {e}")
                        
                # Clean tracking state
                self.live_points.clear()
                self.trail_pixels.clear()
                self.smooth_x, self.smooth_y = None, None
                self.prev_smooth_x, self.prev_smooth_y = None, None
                self.still_since = None
                
        return gesture_payload, pointer_data
