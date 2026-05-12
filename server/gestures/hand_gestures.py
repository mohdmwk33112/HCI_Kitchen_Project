import mediapipe as mp
import cv2
import time
import os
import pickle
import math
from dollarpy import Recognizer, Template, Point

BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_DIR, "hand_landmarker.task")
TEMPLATES_PATH = os.path.join(_DIR, "gesture_templates.pkl")

class GestureHandler:
    def __init__(self):
        self.live_points = []
        self.is_drawing = False
        self.drawing_lost_frames = 0
        self.smooth_x = None
        self.smooth_y = None
        self.alpha = 0.4
        
        self.last_click_time = 0
        self.CLICK_COOLDOWN = 0.6
        self.PINCH_THRESHOLD = 0.05
        self.CONFIDENCE_THRESHOLD = 0.4

        # Load templates
        if os.path.exists(TEMPLATES_PATH):
            with open(TEMPLATES_PATH, "rb") as f:
                templates = pickle.load(f)
            self.recognizer = Recognizer(templates)
            print(f"[GestureHandler] Loaded {len(templates)} templates.")
        else:
            self.recognizer = None
            print("[GestureHandler] Warning: No gesture templates found.")

        # Init Mediapipe
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=VisionRunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.7,
            min_hand_presence_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.landmarker = HandLandmarker.create_from_options(options)

    def process_frame(self, frame, timestamp_ms):
        """
        Processes a single frame. Returns a dictionary if a gesture is detected, else None.
        e.g., {"gesture": "Swipe Left", "confidence": 0.85, "x": 0.5, "y": 0.5}
        """
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        result_payload = None

        try:
            hand_result = self.landmarker.detect_for_video(mp_image, timestamp_ms)
            if hand_result.hand_landmarks:
                for hand_landmarks in hand_result.hand_landmarks:
                    wrist      = hand_landmarks[0]
                    thumb_tip  = hand_landmarks[4]
                    index_tip  = hand_landmarks[8]
                    index_pip  = hand_landmarks[6]
                    middle_tip = hand_landmarks[12]
                    middle_pip = hand_landmarks[10]
                    ring_tip   = hand_landmarks[16]
                    ring_pip   = hand_landmarks[14]
                    pinky_tip  = hand_landmarks[20]
                    pinky_pip  = hand_landmarks[18]

                    h, w, _ = frame.shape
                    cx, cy = int(index_tip.x * w), int(index_tip.y * h)

                    idx_tip_dist  = math.hypot(index_tip.x  - wrist.x, index_tip.y  - wrist.y)
                    idx_pip_dist  = math.hypot(index_pip.x  - wrist.x, index_pip.y  - wrist.y)
                    mid_tip_dist  = math.hypot(middle_tip.x - wrist.x, middle_tip.y - wrist.y)
                    mid_pip_dist  = math.hypot(middle_pip.x - wrist.x, middle_pip.y - wrist.y)
                    ring_tip_dist = math.hypot(ring_tip.x   - wrist.x, ring_tip.y   - wrist.y)
                    ring_pip_dist = math.hypot(ring_pip.x   - wrist.x, ring_pip.y   - wrist.y)
                    pink_tip_dist = math.hypot(pinky_tip.x  - wrist.x, pinky_tip.y  - wrist.y)
                    pink_pip_dist = math.hypot(pinky_pip.x  - wrist.x, pinky_pip.y  - wrist.y)

                    drawing_pose = (idx_tip_dist > idx_pip_dist) and (mid_tip_dist < mid_pip_dist)

                    # Fist detection (Loosened to 0.95 to be more forgiving)
                    FIST_RATIO = 0.95
                    closed_fist = (
                        (idx_tip_dist  / idx_pip_dist)  < FIST_RATIO and
                        (mid_tip_dist  / mid_pip_dist)  < FIST_RATIO and
                        (ring_tip_dist / ring_pip_dist) < FIST_RATIO and
                        (pink_tip_dist / pink_pip_dist) < FIST_RATIO
                    )

                    # ── Pinch-click detection ──
                    pinch_dist = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
                    now = time.time()
                    if pinch_dist < self.PINCH_THRESHOLD and not closed_fist and (now - self.last_click_time) > self.CLICK_COOLDOWN:
                        self.last_click_time = now
                        
                        mid_x = (thumb_tip.x + index_tip.x) / 2
                        mid_y = (thumb_tip.y + index_tip.y) / 2
                        result_payload = {"gesture": "Click", "confidence": 1.0, "x": round(mid_x, 3), "y": round(mid_y, 3)}
                        
                        cv2.circle(frame, (int(mid_x * w), int(mid_y * h)), 14, (0, 215, 255), cv2.FILLED)

                    # ── Drawing & Recognition ──
                    if drawing_pose:
                        self.drawing_lost_frames = 0
                        if not self.is_drawing:
                            self.is_drawing = True
                            self.smooth_x, self.smooth_y = index_tip.x, index_tip.y
                            self.live_points.clear()
                        else:
                            self.smooth_x = self.alpha * index_tip.x + (1 - self.alpha) * self.smooth_x
                            self.smooth_y = self.alpha * index_tip.y + (1 - self.alpha) * self.smooth_y
                        
                        self.live_points.append(Point(self.smooth_x, self.smooth_y, 1))
                        
                        px, py = int(self.smooth_x * w), int(self.smooth_y * h)
                        cv2.circle(frame, (px, py), 10, (0, 255, 0), cv2.FILLED)
                    else:
                        if self.is_drawing:
                            self.drawing_lost_frames += 1
                            # Allow up to 15 frames of tracking loss before resetting the stroke
                            if self.drawing_lost_frames > 15:
                                self.is_drawing = False
                                self.smooth_x, self.smooth_y = None, None
                        
                        if closed_fist and len(self.live_points) > 5 and self.recognizer:
                            res = self.recognizer.recognize(self.live_points)
                            if res:
                                g_name, conf = res
                                print(f"[Gesture Debug] Drew shape. Best match: {g_name} ({conf:.2f})")
                                if conf >= self.CONFIDENCE_THRESHOLD and not result_payload:
                                    # Output the coordinates of the fist/index for the payload
                                    result_payload = {"gesture": g_name, "confidence": round(conf, 2), "x": round(index_tip.x, 3), "y": round(index_tip.y, 3)}
                            self.live_points.clear()
                            self.is_drawing = False
                        
                        cv2.circle(frame, (cx, cy), 10, (0, 0, 255), cv2.FILLED)
                    break
        except Exception as e:
            print(f"[GestureHandler] Error: {e}")

        return result_payload