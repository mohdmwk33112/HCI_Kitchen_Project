import cv2
import os
import sys
import time
import torch
import hashlib
import threading
import numpy as np
from collections import defaultdict
from pathlib import Path
from ultralytics import YOLO

class IngredientDetector:
    def __init__(self, model_path="best.pt", device="", tracker="bytetrack", conf=0.45, iou=0.45, imgsz=640, trail_len=30):
        # 1. Resolve model file path
        if not os.path.exists(model_path) and not any(m in model_path for m in ["yolo11", "yolov8", "yolov10"]):
            alt_path = os.path.join("..", model_path)
            if os.path.exists(alt_path):
                model_path = alt_path
            else:
                print(f"[IngredientDetector] Warning: Model file {model_path} not found. Attempting to download/load as pretrained...")

        # 2. Resolve hardware device (CUDA, MPS, CPU) exactly like yolo (1).py
        self.device = self.resolve_device(device)
        print(f"[IngredientDetector] Loading model {model_path} on {self.device}...")

        # 3. Load YOLO model
        try:
            self.model = YOLO(model_path)
            self.model.to(self.device)
            print(f"[IngredientDetector] Model successfully loaded on {self.device}")
        except Exception as e:
            print(f"[IngredientDetector] Error loading model: {e}")
            self.model = None

        # 4. Save tracking parameters
        self.tracker = tracker
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.trail_len = trail_len
        self.trail_map = defaultdict(list)

        # Threading for async YOLO
        self.yolo_frame = None
        self.yolo_detections = []
        self.yolo_track_ids = []
        self.yolo_boxes_xyxy = []
        self.new_frame_event = threading.Event()
        self.lock = threading.Lock()
        self.yolo_thread_running = False
        
        if self.model is not None:
            self.yolo_thread_running = True
            self.yolo_thread = threading.Thread(target=self._yolo_worker, daemon=True)
            self.yolo_thread.start()

    def __del__(self):
        self.yolo_thread_running = False
        if hasattr(self, "new_frame_event"):
            self.new_frame_event.set()

    def _yolo_worker(self):
        while self.yolo_thread_running:
            # Wait for a new frame to process
            self.new_frame_event.wait()
            if not self.yolo_thread_running:
                break
                
            # Get the frame
            with self.lock:
                frame_to_process = self.yolo_frame.copy() if self.yolo_frame is not None else None
                self.new_frame_event.clear()
                
            if frame_to_process is not None:
                try:
                    h, w = frame_to_process.shape[:2]
                    results = self.model.track(
                        frame_to_process,
                        imgsz=self.imgsz,
                        conf=self.conf,
                        iou=self.iou,
                        device=self.device,
                        tracker=f"{self.tracker}.yaml",
                        persist=True,
                        verbose=False
                    )
                    r = results[0]
                    new_detections = []
                    new_track_ids = []
                    new_boxes_xyxy = []
                    
                    if r.boxes is not None:
                        has_ids = r.boxes.id is not None
                        for i in range(len(r.boxes)):
                            box = r.boxes[i]
                            b = box.xyxy[0].tolist()
                            conf = float(box.conf[0])
                            cls = int(box.cls[0])
                            label = self.model.names[cls]
                            
                            track_id = int(box.id[0]) if has_ids else -1

                            norm_x = b[0] / w
                            norm_y = b[1] / h
                            norm_w = (b[2] - b[0]) / w
                            norm_h = (b[3] - b[1]) / h

                            new_detections.append({
                                "label": label,
                                "confidence": round(conf, 2),
                                "x": round(norm_x, 4),
                                "y": round(norm_y, 4),
                                "w": round(norm_w, 4),
                                "h": round(norm_h, 4),
                                "track_id": track_id
                            })

                            if has_ids:
                                new_track_ids.append(track_id)
                                new_boxes_xyxy.append(b)
                                
                    with self.lock:
                        self.yolo_detections = new_detections
                        self.yolo_track_ids = new_track_ids
                        self.yolo_boxes_xyxy = new_boxes_xyxy
                        
                except Exception as e:
                    print(f"[IngredientDetector] Error in YOLO tracking inference: {e}")
                    
            time.sleep(0.01)

    def resolve_device(self, requested: str) -> str:
        """Resolve available hardware acceleration device."""
        if requested:
            return requested
        if torch.cuda.is_available():
            print(f"[IngredientDetector] CUDA GPU acceleration detected: {torch.cuda.get_device_name(0)}")
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            print("[IngredientDetector] Apple Silicon MPS acceleration detected")
            return "mps"
        print("[IngredientDetector] Running on CPU")
        return "cpu"

    def id_to_color(self, track_id: int) -> tuple:
        """Deterministic BGR color from track ID."""
        h = hashlib.md5(str(track_id).encode()).digest()
        return int(h[0]), int(h[1]), int(h[2])

    def update_trails(self, track_ids, boxes) -> None:
        """Update historical trajectory trails for tracked items."""
        active = set()
        for tid, box in zip(track_ids, boxes):
            cx = int((box[0] + box[2]) / 2)
            cy = int((box[1] + box[3]) / 2)
            self.trail_map[tid].append((cx, cy))
            if len(self.trail_map[tid]) > self.trail_len:
                self.trail_map[tid].pop(0)
            active.add(tid)
        # Prune inactive track IDs
        for tid in list(self.trail_map.keys()):
            if tid not in active:
                del self.trail_map[tid]

    def draw_trails(self, frame) -> None:
        """Draw trajectory trails on the frame."""
        for tid, pts in self.trail_map.items():
            color = self.id_to_color(tid)
            for i in range(1, len(pts)):
                alpha = i / len(pts)
                thickness = max(1, int(3 * alpha))
                cv2.line(frame, pts[i - 1], pts[i], color, thickness, cv2.LINE_AA)

    def detect(self, frame):
        detections = []
        track_ids = []
        boxes_xyxy = []
        h, w = frame.shape[:2]
        laser_det = None
        cx, cy = None, None

        # 1. Run High-Precision HSV Red Laser Dot Detection First (ultra-fast, CPU bound)
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            # Balanced saturation and value minimum thresholds for high-light resilience + high sensitivity
            lower_red1 = np.array([0, 135, 215])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([160, 135, 215])
            upper_red2 = np.array([180, 255, 255])
            
            mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            mask = mask1 | mask2
            
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            best_contour = None
            best_area = 0.0
            for c in contours:
                area = cv2.contourArea(c)
                # Expand allowed area range (typically 1.5 to 180 pixels at 640x480)
                if 1.5 < area < 180:
                    # Circularity check: 4 * pi * Area / Perimeter^2
                    perimeter = cv2.arcLength(c, True)
                    if perimeter > 0:
                        circularity = 4 * np.pi * area / (perimeter * perimeter)
                        # Relaxed circularity to tolerate motion-blurred ovals when moving the laser wand
                        if circularity > 0.25:
                            if area > best_area:
                                best_area = area
                                best_contour = c
            
            if best_contour is not None:
                M = cv2.moments(best_contour)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    box_size = 10
                    norm_x = (cx - box_size // 2) / w
                    norm_y = (cy - box_size // 2) / h
                    norm_w = box_size / w
                    norm_h = box_size / h
                    
                    laser_det = {
                        "label": "red laser",
                        "confidence": 1.0,
                        "x": round(norm_x, 4),
                        "y": round(norm_y, 4),
                        "w": round(norm_w, 4),
                        "h": round(norm_h, 4),
                        "track_id": 9999
                    }
        except Exception as e:
            print(f"[IngredientDetector] Error in HSV red laser tracking: {e}")

        # 2. Skip deep learning YOLO if red laser is active (Laser Dominance)
        if laser_det is not None:
            # Laser is dominant! Set laser detection only and draw HUD overlay
            detections.append(laser_det)
            
            cv2.circle(frame, (cx, cy), 8, (0, 0, 255), 2)
            cv2.circle(frame, (cx, cy), 2, (0, 255, 255), -1)
            cv2.putText(frame, "Red Laser (Dominant Mode)", (cx + 12, cy - 8), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
            
            track_ids.append(9999)
            boxes_xyxy.append([cx - 5, cy - 5, cx + 5, cy + 5])
        else:
            # Laser inactive: run full YOLO deep learning inference asynchronously
            if self.model is not None:
                # If background thread is ready to accept a frame, copy and send it
                if not self.new_frame_event.is_set():
                    with self.lock:
                        self.yolo_frame = frame.copy()
                    self.new_frame_event.set()
                
                # Fetch the latest processed detections instantly (non-blocking)
                with self.lock:
                    detections = list(self.yolo_detections)
                    track_ids = list(self.yolo_track_ids)
                    boxes_xyxy = list(self.yolo_boxes_xyxy)

        # 3. Update and draw historical movement trails
        if len(track_ids) > 0 and self.trail_len > 0:
            self.update_trails(track_ids, boxes_xyxy)
            self.draw_trails(frame)

        return detections
