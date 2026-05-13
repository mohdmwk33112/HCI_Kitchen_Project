import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from collections import deque, Counter
import time
import csv
import os
from datetime import datetime

# Iris and Eye landmarks
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145
RIGHT_EYE_OUTER = 263
RIGHT_EYE_INNER = 362

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080

class GazeHandler:
    def __init__(self, model_path="face_landmarker.task", smooth_window=5):
        self.model_path = model_path
        self.smooth_window = smooth_window
        
        # Smoothing buffers
        self.h_buffer = deque(maxlen=smooth_window)
        self.v_buffer = deque(maxlen=smooth_window)
        
        # History for "most frequent side"
        self.side_history = deque(maxlen=3000) # Increased for longer sessions
        
        # Log for heatmap
        self.gaze_log = []
        
        self.latest_landmarks = None
        
        # Initialize MediaPipe
        base_options = python.BaseOptions(model_asset_path=self.model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.LIVE_STREAM,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            result_callback=self._result_callback,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)

    def _result_callback(self, result, output_image, timestamp_ms):
        if result.face_landmarks:
            self.latest_landmarks = result.face_landmarks[0]
            # print(f"[GazeHandler] Face detected")
        else:
            self.latest_landmarks = None
            # print(f"[GazeHandler] No face detected")

    def process_frame(self, frame, timestamp_ms):
        # Convert frame to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        
        # Async detection
        self.landmarker.detect_async(mp_image, timestamp_ms)
        
        if self.latest_landmarks:
            h_ratio, v_ratio = self._get_gaze_ratios(self.latest_landmarks, frame.shape[1], frame.shape[0])
            
            if h_ratio is not None:
                self.h_buffer.append(h_ratio)
            if v_ratio is not None:
                self.v_buffer.append(v_ratio)
            
            if self.h_buffer and self.v_buffer:
                smooth_h = float(np.mean(self.h_buffer))
                smooth_v = float(np.mean(self.v_buffer))
                
                # Classify and add to history
                side = self._classify_side(smooth_h)
                self.side_history.append(side)
                
                # Log for heatmap
                self.gaze_log.append({
                    "timestamp": round(time.time(), 4),
                    "screen_x": int(smooth_h * SCREEN_WIDTH),
                    "screen_y": int(smooth_v * SCREEN_HEIGHT),
                    "direction": side,
                    "h_ratio": round(smooth_h, 4),
                    "v_ratio": round(smooth_v, 4),
                })
                
                return smooth_h, smooth_v
                
        return None, None

    def _get_iris_center(self, landmarks, indices, w, h):
        xs = [landmarks[i].x * w for i in indices]
        ys = [landmarks[i].y * h for i in indices]
        return int(np.mean(xs)), int(np.mean(ys))

    def _get_gaze_ratios(self, landmarks, frame_w, frame_h):
        try:
            # LEFT EYE
            l_outer_x = landmarks[LEFT_EYE_OUTER].x * frame_w
            l_inner_x = landmarks[LEFT_EYE_INNER].x * frame_w
            lx, ly = self._get_iris_center(landmarks, LEFT_IRIS, frame_w, frame_h)
            l_eye_w = abs(l_inner_x - l_outer_x)

            # RIGHT EYE
            r_outer_x = landmarks[RIGHT_EYE_OUTER].x * frame_w
            r_inner_x = landmarks[RIGHT_EYE_INNER].x * frame_w
            rx, ry = self._get_iris_center(landmarks, RIGHT_IRIS, frame_w, frame_h)
            r_eye_w = abs(r_outer_x - r_inner_x)

            if l_eye_w < 1 or r_eye_w < 1:
                return None, None

            # Normalization
            l_ratio = (lx - l_outer_x) / (l_inner_x - l_outer_x)
            r_ratio = (rx - r_inner_x) / (r_outer_x - r_inner_x)
            h_ratio_raw = (l_ratio + r_ratio) / 2.0

            # Vertical
            top_y = landmarks[LEFT_EYE_TOP].y * frame_h
            bottom_y = landmarks[LEFT_EYE_BOTTOM].y * frame_h
            eye_h = abs(bottom_y - top_y)
            if eye_h < 1: return None, None
            v_ratio_raw = (ly - top_y) / eye_h

            # Calibration (same as gaze.py)
            MIN_H, MAX_H = 0.25, 0.75
            MIN_V, MAX_V = 0.15, 0.85

            h_ratio = np.clip((h_ratio_raw - MIN_H) / (MAX_H - MIN_H), 0.0, 1.0)
            v_ratio = np.clip((v_ratio_raw - MIN_V) / (MAX_V - MIN_V), 0.0, 1.0)

            return float(h_ratio), float(v_ratio)
        except Exception:
            return None, None

    def _classify_side(self, h):
        if h < 0.40: return "Left"
        if h > 0.60: return "Right"
        return "Center"

    def get_most_frequent_side(self):
        if not self.side_history:
            return "Center"
        counts = Counter(self.side_history)
        return counts.most_common(1)[0][0]

    def save_log(self, user_name):
        if not self.gaze_log:
            print(f"No gaze data to save for {user_name}")
            return
            
        filename = f"gaze_log_{user_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join("logs", filename)
        os.makedirs("logs", exist_ok=True)
        
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "screen_x", "screen_y", "direction", "h_ratio", "v_ratio"])
            writer.writeheader()
            writer.writerows(self.gaze_log)
        print(f"Gaze log saved to {filepath}")
        return filepath

    def reset_history(self):
        self.h_buffer.clear()
        self.v_buffer.clear()
        self.side_history.clear()
        self.gaze_log = []
        self.latest_landmarks = None

    def __del__(self):
        if hasattr(self, 'landmarker'):
            self.landmarker.close()
