"""
Gaze tracking using MediaPipe FaceLandmarker (mediapipe 0.10+).
Logs gaze to CSV for heatmap generation.
Press ESC to stop.
"""

import sys
import csv
import time
import urllib.request
from datetime import datetime
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components import containers

# --- Config ---
SCREEN_WIDTH  = 1920
SCREEN_HEIGHT = 1080
CSV_FILENAME  = f"gaze_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
SMOOTH_WINDOW = 5
MODEL_PATH    = "face_landmarker.task"
MODEL_URL     = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

# Iris landmark indices (same as before, still valid in new API)
LEFT_IRIS        = [468, 469, 470, 471, 472]
RIGHT_IRIS       = [473, 474, 475, 476, 477]
LEFT_EYE_OUTER   = 33
LEFT_EYE_INNER   = 133
LEFT_EYE_TOP     = 159
LEFT_EYE_BOTTOM  = 145
RIGHT_EYE_OUTER  = 263
RIGHT_EYE_INNER  = 362


# --- Download model if not present ---
if not Path(MODEL_PATH).exists():
    print(f"Downloading face landmarker model...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Download complete.")


def get_iris_center(landmarks, indices, w, h):
    xs = [landmarks[i].x * w for i in indices]
    ys = [landmarks[i].y * h for i in indices]
    return int(np.mean(xs)), int(np.mean(ys))


def get_gaze_ratios(landmarks, frame_w, frame_h):
    try:
        # =========================
        # LEFT EYE
        # =========================
        l_outer_x = landmarks[LEFT_EYE_OUTER].x * frame_w
        l_inner_x = landmarks[LEFT_EYE_INNER].x * frame_w

        lx, ly = get_iris_center(
            landmarks,
            LEFT_IRIS,
            frame_w,
            frame_h
        )

        l_eye_w = abs(l_inner_x - l_outer_x)

        # =========================
        # RIGHT EYE
        # =========================
        r_outer_x = landmarks[RIGHT_EYE_OUTER].x * frame_w
        r_inner_x = landmarks[RIGHT_EYE_INNER].x * frame_w

        rx, ry = get_iris_center(
            landmarks,
            RIGHT_IRIS,
            frame_w,
            frame_h
        )

        r_eye_w = abs(r_outer_x - r_inner_x)

        if l_eye_w < 1 or r_eye_w < 1:
            return None, None

        # =====================================
        # NORMALIZED HORIZONTAL POSITIONS
        # =====================================

        # Left eye:
        # outer -> inner
        l_ratio = (lx - l_outer_x) / (l_inner_x - l_outer_x)

        # Right eye:
        # inner -> outer
        r_ratio = (rx - r_inner_x) / (r_outer_x - r_inner_x)

        # Average both
        h_ratio_raw = (l_ratio + r_ratio) / 2.0

        # =====================================
        # VERTICAL
        # =====================================

        top_y = landmarks[LEFT_EYE_TOP].y * frame_h
        bottom_y = landmarks[LEFT_EYE_BOTTOM].y * frame_h

        eye_h = abs(bottom_y - top_y)

        if eye_h < 1:
            return None, None

        v_ratio_raw = (ly - top_y) / eye_h

        # =====================================
        # CALIBRATION / STRETCHING
        # =====================================

        # These values may need tuning
        MIN_H = 0.25
        MAX_H = 0.75

        MIN_V = 0.15
        MAX_V = 0.85

        h_ratio = (h_ratio_raw - MIN_H) / (MAX_H - MIN_H)
        v_ratio = (v_ratio_raw - MIN_V) / (MAX_V - MIN_V)

        h_ratio = float(np.clip(h_ratio, 0.0, 1.0))
        v_ratio = float(np.clip(v_ratio, 0.0, 1.0))

        return h_ratio, v_ratio

    except Exception:
        return None, None


def classify_gaze(h, v):
    h_dir = "Left" if h < 0.40 else "Right" if h > 0.60 else "Center"
    v_dir = "Up"   if v < 0.35 else "Down"  if v > 0.65 else "Middle"
    return f"{v_dir}-{h_dir}"


# --- Smoothing buffers ---
h_buffer = deque(maxlen=SMOOTH_WINDOW)
v_buffer = deque(maxlen=SMOOTH_WINDOW)
last_h, last_v = None, None

# --- Shared result from callback ---
latest_landmarks = None

def result_callback(result, output_image, timestamp_ms):
    global latest_landmarks
    if result.face_landmarks:
        latest_landmarks = result.face_landmarks[0]
    else:
        latest_landmarks = None

# --- Build FaceLandmarker ---
base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.LIVE_STREAM,
    num_faces=1,
    min_face_detection_confidence=0.5,
    min_face_presence_confidence=0.5,
    min_tracking_confidence=0.5,
    output_face_blendshapes=False,
    output_facial_transformation_matrixes=False,
    result_callback=result_callback,
)

# --- Webcam ---
webcam = cv2.VideoCapture(0)
webcam.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
webcam.set(cv2.CAP_PROP_FPS, 30)

if not webcam.isOpened():
    sys.exit("Could not open webcam.")

gaze_log    = []
frame_index = 0

print(f"Logging to: {CSV_FILENAME}\nPress ESC to stop.")

with vision.FaceLandmarker.create_from_options(options) as landmarker:
    while True:
        ret, frame = webcam.read()
        frame = cv2.flip(frame, 1)
        if not ret or frame is None:
            sys.exit("Lost webcam stream.")

        frame_h, frame_w = frame.shape[:2]
        frame_index += 1

        # Convert to MediaPipe image and send async
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )
        landmarker.detect_async(mp_image, int(time.time() * 1000))

        status     = "No face detected"
        display_h  = last_h
        display_v  = last_v

        if latest_landmarks is not None:
            h_ratio, v_ratio = get_gaze_ratios(latest_landmarks, frame_w, frame_h)

            if h_ratio is not None:
                h_buffer.append(h_ratio)
                last_h = h_ratio
            if v_ratio is not None:
                v_buffer.append(v_ratio)
                last_v = v_ratio

            if h_buffer and v_buffer:
                display_h = float(np.mean(h_buffer))
                display_v = float(np.mean(v_buffer))
                status    = classify_gaze(display_h, display_v)

                gaze_log.append({
                    "timestamp": round(time.time(), 4),
                    "screen_x":  int(display_h * SCREEN_WIDTH),
                    "screen_y":  int(display_v * SCREEN_HEIGHT),
                    "direction": status,
                    "h_ratio":   round(display_h, 4),
                    "v_ratio":   round(display_v, 4),
                })

            # Draw iris dots
            lx, ly = get_iris_center(latest_landmarks, LEFT_IRIS,  frame_w, frame_h)
            rx, ry = get_iris_center(latest_landmarks, RIGHT_IRIS, frame_w, frame_h)
            cv2.circle(frame, (lx, ly), 3, (0, 255, 0), -1)
            cv2.circle(frame, (rx, ry), 3, (0, 255, 0), -1)

            if display_h is not None and display_v is not None:
                cv2.putText(frame, f"H: {display_h:.2f}  V: {display_v:.2f}",
                            (90, 165), cv2.FONT_HERSHEY_DUPLEX, 0.7, (147, 58, 31), 1)

        elif last_h is not None and last_v is not None:
            status = f"Lost | last: {classify_gaze(last_h, last_v)}"

        cv2.putText(frame, status, (90, 60),
                    cv2.FONT_HERSHEY_DUPLEX, 1.0, (147, 58, 31), 2)
        cv2.putText(frame, f"Logged: {len(gaze_log)} pts", (90, 130),
                    cv2.FONT_HERSHEY_DUPLEX, 0.7, (50, 200, 50), 1)

        cv2.imshow("Gaze Tracker", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

webcam.release()
cv2.destroyAllWindows()

# --- Save CSV ---
if gaze_log:
    with open(CSV_FILENAME, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "screen_x", "screen_y",
                                                "direction", "h_ratio", "v_ratio"])
        writer.writeheader()
        writer.writerows(gaze_log)
    print(f"Saved {len(gaze_log)} points → {CSV_FILENAME}")
else:
    print("No gaze data recorded.")