import cv2
import math
import time
import json
import os
import pickle
import socket
from threading import Thread, Lock
from dollarpy import Recognizer, Point
from ultralytics import YOLO

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG  —  Edit these to change behaviour
# ═══════════════════════════════════════════════════════════════════════════════

# YOLO model file — "yolov8n.pt" is fastest (downloads automatically ~6 MB)
YOLO_MODEL = "yolov8n.pt"

# Minimum YOLO confidence to accept ANY detection (0-1)
DETECT_CONFIDENCE = 0.40

# Only track objects in this food allowlist.
# All COCO food, ingredient, drinkware, and utensil classes are included.
# Everything else (people, laptops, phones, furniture, vehicles...) is ignored.
FOOD_CLASSES = {
    # ── Fruit & vegetables ────────────────────────────────────────────────────
    "banana", "apple", "orange", "broccoli", "carrot",
    "sandwich", "hot dog", "pizza", "donut", "cake",
    # ── Drinkware & containers ────────────────────────────────────────────────
    "bottle", "wine glass", "cup", "bowl",
    # ── Utensils ──────────────────────────────────────────────────────────────
    "fork", "knife", "spoon",
}

# How many consecutive frames the object must be present before recording starts
FRAMES_TO_START = 3

# How many consecutive frames the object must be GONE before recognizing
FRAMES_TO_STOP = 8

# EMA smoothing factor for centroid (0 = very smooth/laggy, 1 = raw/jittery)
ALPHA = 0.4

# ── Click (stillness) detection ──────────────────────────────────────────────
# Normalised distance below which the object counts as "not moving"
CLICK_STILL_THRESH = 0.015
# How long (seconds) the object must be still to trigger a click
CLICK_HOLD_SECONDS = 0.8
# Minimum seconds between two consecutive clicks
CLICK_COOLDOWN = 1.0

# ── DollarPy ─────────────────────────────────────────────────────────────────
# Minimum recognizer confidence to broadcast a gesture (0-1)
CONFIDENCE_THRESH = 0.40
TEMPLATE_CACHE = "gesture_templates.pkl"

# ── UDP broadcast ─────────────────────────────────────────────────────────────
UDP_IP   = "127.0.0.1"
UDP_PORT = 5005

# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED STATE  (same pattern as hand_gestures.py)
# ═══════════════════════════════════════════════════════════════════════════════
live_points   = []
points_lock   = Lock()
gesture_ready = False
click_ready   = False
running       = True


# ═══════════════════════════════════════════════════════════════════════════════
#  CAPTURE + TRACKING THREAD
# ═══════════════════════════════════════════════════════════════════════════════

def yolo_track_capture(video_src, window_label):
    """
    Runs YOLO on each camera frame, extracts the tracked object's centroid,
    applies EMA smoothing, accumulates DollarPy Points, and signals the main
    thread when a gesture or click is ready.
    """
    global live_points, gesture_ready, click_ready, running

    print(f"[YOLO] Loading model '{YOLO_MODEL}'...")
    model = YOLO(YOLO_MODEL)
    print(f"[YOLO] Model ready.  Tracking: food objects only (closest to camera)")

    cap = cv2.VideoCapture(video_src)
    if not cap.isOpened():
        print("[YOLO] ERROR: Could not open camera.")
        running = False
        return

    # ── Per-frame state ───────────────────────────────────────────────────────
    smooth_x, smooth_y         = None, None
    prev_smooth_x, prev_smooth_y = None, None
    is_tracking                = False
    frames_detected            = 0
    frames_undetected          = 0
    trail_pixels               = []   # screen-space trail for drawing
    still_since                = None
    last_click_time            = 0.0

    while cap.isOpened() and running:
        ret, frame = cap.read()
        if not ret:
            break

        h, w = frame.shape[:2]

        # ── YOLO inference — food only, closest object (largest box) ───────────
        results        = model(frame, verbose=False)[0]
        best_box       = None
        best_area      = 0.0
        best_conf      = 0.0
        detected_class = "unknown"

        for box in results.boxes:
            cls_id     = int(box.cls[0])
            conf       = float(box.conf[0])
            class_name = model.names[cls_id]

            # Skip anything that is not food
            if class_name not in FOOD_CLASSES:
                continue
            if conf < DETECT_CONFIDENCE:
                continue

            # Use bounding box area as depth proxy: larger area = closer to cam
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            area = (x2 - x1) * (y2 - y1)
            if area > best_area:
                best_area      = area
                best_conf      = conf
                best_box       = box
                detected_class = class_name

        object_found = best_box is not None

        # ── Object detected this frame ────────────────────────────────────────
        if object_found:
            x1, y1, x2, y2 = best_box.xyxy[0].tolist()
            raw_cx = ((x1 + x2) / 2) / w
            raw_cy = ((y1 + y2) / 2) / h

            # EMA smoothing (identical to hand_gestures.py)
            if smooth_x is None:
                smooth_x, smooth_y = raw_cx, raw_cy
            else:
                smooth_x = ALPHA * raw_cx + (1 - ALPHA) * smooth_x
                smooth_y = ALPHA * raw_cy + (1 - ALPHA) * smooth_y

            frames_detected   += 1
            frames_undetected  = 0

            # ── Start recording ───────────────────────────────────────────────
            if frames_detected >= FRAMES_TO_START and not is_tracking:
                is_tracking = True
                trail_pixels.clear()
                with points_lock:
                    live_points.clear()
                print(f"[YOLO] ▶ Recording started  ({detected_class} {best_conf:.2f})")

            # ── Accumulate trajectory points ──────────────────────────────────
            if is_tracking:
                with points_lock:
                    live_points.append(Point(smooth_x, smooth_y, 1))
                trail_pixels.append((int(smooth_x * w), int(smooth_y * h)))

            # ── Stillness-based click detection ───────────────────────────────
            if prev_smooth_x is not None and is_tracking:
                delta = math.hypot(smooth_x - prev_smooth_x, smooth_y - prev_smooth_y)
                now   = time.time()
                if delta < CLICK_STILL_THRESH:
                    if still_since is None:
                        still_since = now
                    elif (now - still_since) >= CLICK_HOLD_SECONDS:
                        if (now - last_click_time) >= CLICK_COOLDOWN:
                            with points_lock:
                                click_ready = True
                            last_click_time = now
                            still_since     = None
                            # Clear trail so a new gesture starts cleanly after click
                            trail_pixels.clear()
                            with points_lock:
                                live_points.clear()
                            print("[YOLO] 🖱  Click detected!")
                            # Gold ring at centroid to signal click
                            cx_px = int(smooth_x * w)
                            cy_px = int(smooth_y * h)
                            cv2.circle(frame, (cx_px, cy_px), 22, (0, 215, 255), 3)
                else:
                    still_since = None

            prev_smooth_x, prev_smooth_y = smooth_x, smooth_y

            # ── Draw bounding box ─────────────────────────────────────────────
            box_color = (0, 255, 0) if is_tracking else (255, 165, 0)
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), box_color, 2)
            lbl = f"{detected_class} {best_conf:.2f}"
            cv2.putText(frame, lbl, (int(x1), max(int(y1) - 8, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, box_color, 2)

            # Centroid dot
            cx_px = int(smooth_x * w)
            cy_px = int(smooth_y * h)
            cv2.circle(frame, (cx_px, cy_px), 8, box_color, cv2.FILLED)

        # ── Object NOT detected this frame ────────────────────────────────────
        else:
            frames_undetected += 1
            frames_detected    = 0

            if is_tracking and frames_undetected >= FRAMES_TO_STOP:
                is_tracking              = False
                smooth_x, smooth_y       = None, None
                prev_smooth_x, prev_smooth_y = None, None
                still_since              = None
                with points_lock:
                    gesture_ready = True
                print("[YOLO] ■ Recording stopped — recognizing...")

        # ── Draw gesture trail ────────────────────────────────────────────────
        for i in range(1, len(trail_pixels)):
            cv2.line(frame, trail_pixels[i - 1], trail_pixels[i], (0, 215, 255), 2)

        # Trail endpoint dot
        if trail_pixels:
            cv2.circle(frame, trail_pixels[-1], 5, (0, 215, 255), cv2.FILLED)

        # ── HUD ───────────────────────────────────────────────────────────────
        status_text  = f"● RECORDING  [{detected_class}]" if is_tracking else "Waiting for any object..."
        status_color = (0, 255, 0) if is_tracking else (160, 160, 160)
        cv2.putText(frame, status_text,               (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.70, status_color, 2)
        cv2.putText(frame, "Show object → draw gesture", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
        cv2.putText(frame, "Hide object → recognise",    (10, 82),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
        cv2.putText(frame, "Hold still → click",          (10, 106),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 215, 255), 2)

        cv2.imshow(window_label, frame)
        cv2.waitKey(1)

        # Exit when window is closed
        try:
            if cv2.getWindowProperty(window_label, cv2.WND_PROP_VISIBLE) < 1:
                running = False
                break
        except cv2.error:
            running = False
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[YOLO] Camera thread ended.")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║   YOLO Object Gesture Tracker            ║
    ╠══════════════════════════════════════════╣
    ║  Show object  →  start drawing           ║
    ║  Move object  →  trace gesture path      ║
    ║  Hide object  →  recognise gesture       ║
    ║  Hold still   →  click                   ║
    ║  Close window →  quit                    ║
    ╚══════════════════════════════════════════╝
    """)

    # ── Load gesture templates (same file as hand_gestures.py) ───────────────
    if not os.path.exists(TEMPLATE_CACHE):
        print(f"ERROR: '{TEMPLATE_CACHE}' not found.")
        print("Run hand_gestures.py first to generate the template cache.")
        exit(1)

    with open(TEMPLATE_CACHE, "rb") as f:
        templates = pickle.load(f)
    print(f"Loaded {len(templates)} gesture templates from '{TEMPLATE_CACHE}'")

    gesture_names = sorted(set(t.name for t in templates))
    print(f"Gestures available: {', '.join(gesture_names)}")

    recognizer = Recognizer(templates)

    # ── UDP socket ────────────────────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Broadcasting gestures via UDP → {UDP_IP}:{UDP_PORT}")
    print(f"Tracking object: any object  |  Model: {YOLO_MODEL}")
    print("─" * 50)

    # ── Start capture thread ──────────────────────────────────────────────────
    t1 = Thread(target=yolo_track_capture, args=(0, "YOLO Gesture Tracker"))
    t1.daemon = True
    t1.start()

    # ── Recognition loop (main thread) ───────────────────────────────────────
    while running:

        # ── Check click ───────────────────────────────────────────────────────
        do_click = False
        with points_lock:
            if click_ready:
                do_click    = True
                click_ready = False   # type: ignore[assignment]

        if do_click:
            print("[YOLO] Click → broadcasting")
            payload = json.dumps({"gesture": "Click", "confidence": 1.0, "source": "yolo"})
            sock.sendto(payload.encode(), (UDP_IP, UDP_PORT))

        # ── Check trained gesture ─────────────────────────────────────────────
        current_points = []
        with points_lock:
            if gesture_ready:
                current_points = live_points.copy()
                gesture_ready  = False   # type: ignore[assignment]

        if len(current_points) > 5:
            try:
                t_start = time.time()
                result  = recognizer.recognize(current_points)
                t_end   = time.time()

                if result:
                    gesture_name, confidence = result
                    if confidence >= CONFIDENCE_THRESH:
                        print(f"[YOLO] ✓ {gesture_name}  confidence={confidence:.2f}"
                              f"  time={t_end - t_start:.4f}s")
                        payload = json.dumps({
                            "gesture":    gesture_name,
                            "confidence": confidence,
                            "source":     "yolo"
                        })
                        sock.sendto(payload.encode(), (UDP_IP, UDP_PORT))
                    else:
                        print(f"[YOLO] Low confidence ({confidence:.2f}) — no match")
            except Exception as e:
                print(f"[YOLO] Recognition error: {e}")

        time.sleep(0.05)

    t1.join(timeout=2)
    print("[YOLO] Program ended.")
