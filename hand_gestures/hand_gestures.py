import mediapipe as mp
import cv2
import time
import os
import pickle
import math
import socket
import json
from dollarpy import Recognizer, Template, Point
from threading import Thread, Lock

# New MediaPipe Tasks API setup
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

# Shared testing data
live_points = []
points_lock = Lock()
running = True
gesture_ready = False
click_ready = False


def getPoints(videoURL, label, show_video=True):
    try:
        video_src = int(videoURL)
    except ValueError:
        video_src = videoURL

    cap = cv2.VideoCapture(video_src)

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path='hand_landmarker.task'),
        running_mode=VisionRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.7,
        min_tracking_confidence=0.7
    )

    points = []

    with HandLandmarker.create_from_options(options) as landmarker:
        fallback_timestamp = 0
        is_drawing = False
        smooth_x, smooth_y = None, None
        alpha = 0.4  # Smoothing factor
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
            if timestamp_ms <= 0 or timestamp_ms <= fallback_timestamp:
                timestamp_ms = fallback_timestamp + 33
            fallback_timestamp = timestamp_ms

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            try:
                hand_result = landmarker.detect_for_video(mp_image, timestamp_ms)

                if hand_result.hand_landmarks:
                    for hand_landmarks in hand_result.hand_landmarks:
                        wrist = hand_landmarks[0]
                        index_tip = hand_landmarks[8]
                        index_pip = hand_landmarks[6]
                        middle_tip = hand_landmarks[12]
                        middle_pip = hand_landmarks[10]

                        h, w, _ = frame.shape
                        cx, cy = int(index_tip.x * w), int(index_tip.y * h)

                        idx_tip_dist = math.hypot(index_tip.x - wrist.x, index_tip.y - wrist.y)
                        idx_pip_dist = math.hypot(index_pip.x - wrist.x, index_pip.y - wrist.y)
                        mid_tip_dist = math.hypot(middle_tip.x - wrist.x, middle_tip.y - wrist.y)
                        mid_pip_dist = math.hypot(middle_pip.x - wrist.x, middle_pip.y - wrist.y)

                        drawing_pose = (idx_tip_dist > idx_pip_dist) and (mid_tip_dist < mid_pip_dist)

                        if drawing_pose:
                            if not is_drawing:
                                is_drawing = True
                                smooth_x, smooth_y = index_tip.x, index_tip.y
                            else:
                                smooth_x = alpha * index_tip.x + (1 - alpha) * smooth_x
                                smooth_y = alpha * index_tip.y + (1 - alpha) * smooth_y

                            cx, cy = int(smooth_x * w), int(smooth_y * h)
                            cv2.circle(frame, (cx, cy), 10, (0, 255, 0), cv2.FILLED)
                            points.append(Point(smooth_x, smooth_y, 1))
                        else:
                            if is_drawing:
                                is_drawing = False
                                smooth_x, smooth_y = None, None
                            cv2.circle(frame, (cx, cy), 10, (0, 0, 255), cv2.FILLED)
                        break
            except Exception:
                pass

            if show_video:
                cv2.imshow(label, frame)
                if cv2.waitKey(10) & 0xFF == ord('q'):
                    break

    cap.release()
    if show_video:
        cv2.destroyAllWindows()
        cv2.waitKey(100)

    print(f"Points extraction complete for: {label}")
    return points


def live_test_capture(videoURL, label):
    global live_points, running, gesture_ready, click_ready

    try:
        video_src = int(videoURL)
    except ValueError:
        video_src = videoURL

    cap = cv2.VideoCapture(video_src)

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path='hand_landmarker.task'),
        running_mode=VisionRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.7,
        min_tracking_confidence=0.7
    )

    with HandLandmarker.create_from_options(options) as landmarker:
        fallback_timestamp = 0
        is_drawing = False
        smooth_x, smooth_y = None, None
        alpha = 0.4          # Smoothing factor
        last_click_time = 0  # Cooldown tracker for pinch-click
        CLICK_COOLDOWN  = 0.6  # seconds between clicks
        PINCH_THRESHOLD = 0.05 # normalised distance to trigger click

        while cap.isOpened() and running:
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
            if timestamp_ms <= 0 or timestamp_ms <= fallback_timestamp:
                timestamp_ms = fallback_timestamp + 33
            fallback_timestamp = timestamp_ms

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            try:
                hand_result = landmarker.detect_for_video(mp_image, timestamp_ms)

                if hand_result.hand_landmarks:
                    for hand_landmarks in hand_result.hand_landmarks:
                        wrist        = hand_landmarks[0]
                        thumb_tip    = hand_landmarks[4]
                        index_tip    = hand_landmarks[8]
                        index_pip    = hand_landmarks[6]
                        middle_tip   = hand_landmarks[12]
                        middle_pip   = hand_landmarks[10]
                        ring_tip     = hand_landmarks[16]
                        ring_pip     = hand_landmarks[14]
                        pinky_tip    = hand_landmarks[20]
                        pinky_pip    = hand_landmarks[18]

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

                        # Drawing: index fully extended, middle folded
                        drawing_pose = (idx_tip_dist > idx_pip_dist) and (mid_tip_dist < mid_pip_dist)

                        # Closed fist: ALL four fingers curled — tip must be
                        # significantly closer to wrist than PIP (ratio < 0.85)
                        FIST_RATIO = 0.85
                        closed_fist = (
                            (idx_tip_dist  / idx_pip_dist)  < FIST_RATIO and
                            (mid_tip_dist  / mid_pip_dist)  < FIST_RATIO and
                            (ring_tip_dist / ring_pip_dist) < FIST_RATIO and
                            (pink_tip_dist / pink_pip_dist) < FIST_RATIO
                        )

                        # ── Pinch-click detection (no training needed) ──────
                        pinch_dist = math.hypot(
                            thumb_tip.x - index_tip.x,
                            thumb_tip.y - index_tip.y
                        )
                        now = time.time()
                        if pinch_dist < PINCH_THRESHOLD and (now - last_click_time) > CLICK_COOLDOWN:
                            last_click_time = now
                            with points_lock:
                                click_ready = True
                            # Visual feedback: yellow circle between thumb and index
                            mid_px = int(((thumb_tip.x + index_tip.x) / 2) * w)
                            mid_py = int(((thumb_tip.y + index_tip.y) / 2) * h)
                            cv2.circle(frame, (mid_px, mid_py), 14, (0, 215, 255), cv2.FILLED)

                        if drawing_pose:
                            with points_lock:
                                if not is_drawing:
                                    is_drawing = True
                                    smooth_x, smooth_y = index_tip.x, index_tip.y
                                    live_points.clear()
                                else:
                                    smooth_x = alpha * index_tip.x + (1 - alpha) * smooth_x
                                    smooth_y = alpha * index_tip.y + (1 - alpha) * smooth_y
                                live_points.append(Point(smooth_x, smooth_y, 1))

                            cx, cy = int(smooth_x * w), int(smooth_y * h)
                            cv2.circle(frame, (cx, cy), 10, (0, 255, 0), cv2.FILLED)
                        else:
                            # Stop drawing regardless, but only recognise on full fist
                            with points_lock:
                                if is_drawing:
                                    is_drawing = False
                                    smooth_x, smooth_y = None, None
                            if closed_fist:
                                with points_lock:
                                    gesture_ready = True
                            cv2.circle(frame, (cx, cy), 10, (0, 0, 255), cv2.FILLED)
                        break
            except Exception:
                pass

            # HUD instructions
            cv2.putText(frame, "Point index finger to draw", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            cv2.putText(frame, "Close full fist to recognise", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            cv2.putText(frame, "Pinch thumb+index to click", (10, 86),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 215, 255), 2)

            cv2.imshow(label, frame)
            cv2.waitKey(10)

            try:
                if cv2.getWindowProperty(label, cv2.WND_PROP_VISIBLE) < 1:
                    running = False
                    break
            except cv2.error:
                running = False
                break

    cap.release()
    cv2.destroyAllWindows()
    cv2.waitKey(100)


if __name__ == "__main__":
    templates = []
    template_cache_file = "gesture_templates.pkl"

    print("""
    ==============================
    DollarPy Hand Gestures Setup
    ==============================
    Live testing mode (Keyboardless):
    - Point index finger (middle folded) to start drawing
    - Open or close hand to recognize the gesture
    - Close the window to quit
    """)

    if os.path.exists(template_cache_file):
        print(f"Loading cached templates from {template_cache_file}...")
        with open(template_cache_file, 'rb') as f:
            templates = pickle.load(f)
    else:
        print("No cached templates found. Extracting points from training videos...")
        gestures = {
            "Swipe Left": "left_swipe_train",
            "Swipe Right": "right_swipe_train",
            "Circle": "circle_train",
            "L Shape": "l_shape_train"
        }

        SAMPLES_PER_GESTURE = 10
        total_samples = len(gestures) * SAMPLES_PER_GESTURE
        processed = 0
        training_summary = []  # [(gesture, sample_idx, status, pts_count)]

        print("\n" + "=" * 60)
        print(f"  TRAINING  |  {len(gestures)} gestures  x  {SAMPLES_PER_GESTURE} samples  =  {total_samples} total")
        print("=" * 60)

        for name, prefix in gestures.items():
            gesture_ok = 0
            gesture_fail = 0
            print(f"\n  ► Gesture: {name}")
            print(f"    {'Sample':<10} {'File':<30} {'Points':>7} {'Status'}")
            print(f"    {'-'*10} {'-'*30} {'-'*7} {'-'*8}")

            for i in range(1, SAMPLES_PER_GESTURE + 1):
                video_file = f"{prefix}.mp4" if i == 1 else f"{prefix} ({i-1}).mp4"
                pts = getPoints(video_file, f"{name} Training {i}", show_video=False)
                processed += 1

                # Build progress bar
                bar_filled = int((processed / total_samples) * 20)
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                pct = int((processed / total_samples) * 100)

                if len(pts) > 0:
                    templates.append(Template(name, pts))
                    status = "✓ OK"
                    gesture_ok += 1
                    training_summary.append((name, i, "OK", len(pts)))
                else:
                    status = "✗ FAIL"
                    gesture_fail += 1
                    training_summary.append((name, i, "FAIL", 0))

                print(f"    {i:<10} {video_file:<30} {len(pts):>7} {status}")
                print(f"    Overall: [{bar}] {pct}% ({processed}/{total_samples})", end="\r")

            print(f"    Overall: [{bar}] {pct}% ({processed}/{total_samples})  <- {name} done ({gesture_ok} OK / {gesture_fail} failed)")

        # Final summary table
        print("\n" + "=" * 60)
        print("  TRAINING COMPLETE — Summary")
        print("=" * 60)
        print(f"  {'Gesture':<15} {'Sample':>7} {'Points':>8} {'Status'}")
        print(f"  {'-'*15} {'-'*7} {'-'*8} {'-'*8}")
        for (g, idx, st, cnt) in training_summary:
            tick = "✓" if st == "OK" else "✗"
            print(f"  {g:<15} {idx:>7} {cnt:>8} {tick} {st}")
        ok_count = sum(1 for r in training_summary if r[2] == "OK")
        print("=" * 60)
        print(f"  Templates created: {ok_count} / {total_samples}")
        print("=" * 60 + "\n")

        if len(templates) > 0:
            with open(template_cache_file, 'wb') as f:
                pickle.dump(templates, f)
            print(f"Saved extracted templates to {template_cache_file}")

    if len(templates) == 0:
        print("No templates available.")
        exit()

    recognizer = Recognizer(templates)

    # Socket setup for broadcasting gestures
    UDP_IP = "127.0.0.1"
    UDP_PORT = 5005
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Broadcasting gestures via UDP to {UDP_IP}:{UDP_PORT}")

    test_vid = 0
    t1 = Thread(target=live_test_capture, args=(test_vid, "Testing Gesture"))
    t1.start()

    while running:
        # ── Check for pinch-click (rule-based, no DollarPy needed) ──
        do_click = False
        with points_lock:
            if click_ready:
                do_click = True
                click_ready = False

        if do_click:
            print("Click detected! (pinch gesture)")
            payload = json.dumps({"gesture": "Click", "confidence": 1.0})
            sock.sendto(payload.encode(), (UDP_IP, UDP_PORT))

        # ── Check for trained gesture (DollarPy) ────────────────────
        current_points = []
        with points_lock:
            if gesture_ready:
                current_points = live_points.copy()
                gesture_ready = False

        if len(current_points) > 5:
            try:
                start = time.time()
                result = recognizer.recognize(current_points)
                end = time.time()

                if result:
                    gesture_name, confidence = result
                    confidence_threshold = 0.4  # Adjustable threshold

                    if confidence >= confidence_threshold:
                        print(f"Best match: {gesture_name} (Confidence: {confidence:.2f})")
                        print(f"Time taken to classify: {end - start:.4f} seconds")

                        # Send JSON payload via socket
                        payload = json.dumps({"gesture": gesture_name, "confidence": confidence})
                        sock.sendto(payload.encode(), (UDP_IP, UDP_PORT))
                    else:
                        print(f"Confidence {confidence:.2f} below threshold ({confidence_threshold}). Best match: None")
            except Exception as e:
                print("Recognition error:", e)

        time.sleep(0.05)

    t1.join()
    print("Program ended.")