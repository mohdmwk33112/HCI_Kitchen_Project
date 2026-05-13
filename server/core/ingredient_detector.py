import cv2
import os
from ultralytics import YOLO

class IngredientDetector:
    def __init__(self, model_path="best.pt"):
        # Load the YOLOv8 model
        # If it's not a local file, it might be an official model name (like yolo11n.pt)
        if not os.path.exists(model_path) and not any(m in model_path for m in ["yolo11", "yolov8", "yolov10"]):
            # Try to find it in the parent directory if called from core/
            alt_path = os.path.join("..", model_path)
            if os.path.exists(alt_path):
                model_path = alt_path
            else:
                print(f"[IngredientDetector] Warning: Model file {model_path} not found. Attempting to download/load as pretrained...")

        
        try:
            self.model = YOLO(model_path)
            print(f"[IngredientDetector] Model loaded from {model_path}")
        except Exception as e:
            print(f"[IngredientDetector] Error loading model: {e}")
            self.model = None

    def detect(self, frame):
        if self.model is None:
            return []

        # Run inference
        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Run inference with explicit size and confidence
        results = self.model(img_rgb, conf=0.4, imgsz=640, verbose=False)

        
        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                # Get coordinates in [x1, y1, x2, y2]
                b = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = self.model.names[cls]

                # Normalize coordinates (0 to 1)
                h, w = frame.shape[:2]
                norm_x = b[0] / w
                norm_y = b[1] / h
                norm_w = (b[2] - b[0]) / w
                norm_h = (b[3] - b[1]) / h

                detections.append({
                    "label": label,
                    "confidence": round(conf, 2),
                    "x": round(norm_x, 4),
                    "y": round(norm_y, 4),
                    "w": round(norm_w, 4),
                    "h": round(norm_h, 4)
                })
        
        return detections
