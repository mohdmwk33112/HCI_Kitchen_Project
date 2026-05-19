import cv2
import time
import json
import numpy as np
from threading import Thread
from face.face_handler import FaceHandler
from face.emotion_handler import EmotionHandler
from gestures.hand_gestures import GestureHandler
from yolo_gestures import YoloGestureHandler
from core.ingredient_detector import IngredientDetector
from face.gaze_handler import GazeHandler
import db
import threading
from heat_map import generate_heatmap


class VisionManager:
    def __init__(self, people_dir, conn):
        self.conn = conn
        self.face_handler = FaceHandler(people_dir)
        self.gesture_handler = GestureHandler()
        self.yolo_gesture_handler = YoloGestureHandler()
        self.emotion_handler = EmotionHandler(analysis_interval=15.0)
        self.ingredient_detector = IngredientDetector("best.pt")
        self.gaze_handler = GazeHandler("face_landmarker.task")


        
        self.state = "LOGIN"  # States: LOGIN, GESTURES, CIRCULAR_MENU
        self.running = False
        self.confirmations_needed = 5
        self.confirmation_counts = {}
        self.last_name = None
        self.current_user = None
        self.current_user_id = None
        self.current_user_skill = None   # "Chef", "Home Cook", etc.
        self.current_session_id = None
        
        # Performance tuning
        self.detection_frame_count = 0
        self.detection_interval = 15 # Process ingredients every 15th frame
        self.emotion_frame_count = 0
        self.emotion_interval = 5   # Process emotions every 5th frame
        self.gaze_frame_count = 0
        self.gaze_interval = 1      # Gaze stays high priority

        # Registration state
        self.capture_pending = False
        self.capture_name = None
        self.capture_profession = None
        self.last_face_detected_time = None


    def start(self):
        self.running = True
        Thread(target=self._camera_loop, daemon=True).start()

    def set_state(self, new_state):
        print(f"[VisionManager] State changed to: {new_state}")
        self.state = new_state
        final_side = "Center"
        
        if new_state == "LOGIN":
            # Save gaze preference before clearing user
            if self.current_user:
                user_data = db.get_user_by_name(self.current_user)
                if user_data:
                    final_side = self.gaze_handler.get_most_frequent_side()
                    print("\n" + "="*50)
                    print(f" LOGOUT DECISION for {self.current_user}: {final_side.upper()}")
                    print("="*50 + "\n")
                    
                    # Save heatmap data to CSV
                    log_path = self.gaze_handler.save_log(self.current_user)
                    
                    # Generate heatmap synchronously to ensure completion before shutdown
                    if log_path:
                        try:
                            generate_heatmap(log_path)
                        except Exception as e:
                            print(f"[VisionManager] Error generating heatmap: {e}")
                    
                    # DB LOGGING: Log gaze result if in session
                    if self.current_session_id:
                        db.log_interaction(self.current_session_id, "gaze_summary", {
                            "final_side": final_side,
                            "log_file": log_path
                        })
                    
                    db.update_preferred_side(user_data['user_id'], final_side)

            self.current_user = None
            self.current_user_id = None
            self.current_session_id = None
            self.confirmation_counts = {}
            self.last_name = None
            self.gaze_handler.reset_history()
            self.last_face_detected_time = None
        
        return final_side

    def _camera_loop(self):
        # Auto-detect camera (tries index 0 then 1 then 2)
        cap = None
        for i in range(5):
            print(f"[VisionManager] Probing camera index {i}...")
            test_cap = cv2.VideoCapture(i)
            if test_cap.isOpened():
                ret, frame = test_cap.read()
                if ret and frame is not None:
                    cap = test_cap
                    print(f"[VisionManager] Successfully opened camera index {i}")
                    break
            test_cap.release()

        if cap is None:
            print("Error: Cannot open any camera.")
            self.conn.sendall("error;no_camera\n".encode("utf-8"))
            return

        print("[VisionManager] Camera loop started.")

        try:
            while self.running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                # Downsample frame for processing speed
                small_frame = cv2.resize(frame, (640, 480))
                small_frame = cv2.flip(small_frame, 1)  # Mirror
                timestamp_ms = int(time.time() * 1000)

                # HANDLE CAPTURE REQUEST
                if self.capture_pending and self.capture_name:
                    success = self.face_handler.register_new_face(frame, self.capture_name)
                    if success:
                        if self.capture_profession:
                            import db
                            db.create_user(name=self.capture_name, skill_level=self.capture_profession)
                            if self.state == "SIGNUP":
                                self.current_user = self.capture_name
                                user_data = db.get_user_by_name(self.capture_name)
                                if user_data:
                                    self.current_user_id = user_data['user_id']
                                self.conn.sendall(f"signup_success;{self.capture_name}\n".encode("utf-8"))
                                self.set_state("GESTURES")
                            else:
                                self.conn.sendall(f"capture_success;{self.capture_name}\n".encode("utf-8"))
                        else:
                            self.conn.sendall(f"capture_success;{self.capture_name}\n".encode("utf-8"))
                    else:
                        self.conn.sendall("error;capture_failed\n".encode("utf-8"))
                    self.capture_pending = False
                    self.capture_name = None
                    self.capture_profession = None

                if self.state == "LOGIN":
                    self._process_login(small_frame)
                elif self.state == "SIGNUP":
                    self._process_gestures(small_frame, timestamp_ms)
                elif self.state == "GESTURES":
                    self._process_gestures(small_frame, timestamp_ms)
                elif self.state == "CIRCULAR_MENU":
                    self._process_gestures(small_frame, timestamp_ms, suppress_gestures=True)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.running = False
                    break

        except Exception as e:
            print(f"[VisionManager] Camera loop error: {e}")
        finally:
            if cap: cap.release()
            cv2.destroyAllWindows()
            print("[VisionManager] Camera loop ended.")

    def _process_login(self, frame):
        face_results = self.face_handler.identify_face(frame)
        current_name = None
        current_confidence = 0.0

        if face_results:
            current_name, current_confidence = face_results[0]
            if current_name == "Unknown":
                current_name = None

        if current_name:
            self.last_face_detected_time = time.time()
            label = f"{current_name} ({current_confidence:.1f}%)"
            color = (0, 255, 0)
            
            if current_name == self.last_name:
                self.confirmation_counts[current_name] = self.confirmation_counts.get(current_name, 0) + 1
            else:
                self.confirmation_counts = {current_name: 1}
                self.last_name = current_name

            count = self.confirmation_counts[current_name]
            
            if count >= self.confirmations_needed:
                print(f"Login confirmed: {current_name} at {current_confidence:.1f}%")
                self.current_user = current_name
                
                # Fetch preferred side and skill level from DB
                user_data = db.get_user_by_name(current_name)
                if user_data:
                    self.current_user_id = user_data['user_id']
                    pref_side = user_data.get('preferred_side', 'Left')
                    self.current_user_skill = user_data.get('skill_level') or 'Chef'
                else:
                    pref_side = 'Left'
                    self.current_user_skill = 'Chef'
                
                self.conn.sendall(f"login_success;{current_name};{pref_side};{self.current_user_skill}\n".encode("utf-8"))
                self.set_state("GESTURES")
        else:
            label = "Scanning for faces..."
            color = (0, 0, 255)
            self.last_name = None
            self.confirmation_counts = {}

            # Face undetected timeout check (10.0 seconds)
            if self.last_face_detected_time is None:
                self.last_face_detected_time = time.time()
            
            elapsed = time.time() - self.last_face_detected_time
            countdown = max(0.0, 10.0 - elapsed)
            if countdown > 0:
                cv2.putText(frame, f"Sign-up in {countdown:.1f}s (No Face)", (30, 80), cv2.FONT_HERSHEY_DUPLEX, 0.75, (0, 165, 255), 2)
            
            if elapsed >= 10.0:
                print("[VisionManager] No face detected for 10 seconds. Triggering Sign Up!")
                self.conn.sendall("trigger_signup\n".encode("utf-8"))
                self.set_state("SIGNUP")
                self.last_face_detected_time = time.time()

        cv2.putText(frame, label, (30, 40), cv2.FONT_HERSHEY_DUPLEX, 1.0, color, 2)
        cv2.imshow("Kitchen Assistant - Vision", frame)

    def _process_gestures(self, frame, timestamp_ms, suppress_gestures=False):
        # 1. Run YOLO + HSV Red Laser detector first
        detections = self.ingredient_detector.detect(frame)
        laser_active = any(d["label"] == "red laser" for d in detections) if detections else False

        # 2. Conditionally run MediaPipe hand gesture handler (Bypassed in Laser Dominant mode)
        hand_gesture_payload = None
        hand_pointer_data = None
        if not laser_active:
            hand_gesture_payload, hand_pointer_data = self.gesture_handler.process_frame(frame, timestamp_ms)

        # 3. Run YOLO / Laser object tracking gesture handler (always runs to capture laser)
        yolo_gesture_payload, yolo_pointer_data = self.yolo_gesture_handler.process_detections(detections, timestamp_ms)

        # 4. Resolve pointer data and gestures
        pointer_data = yolo_pointer_data if laser_active else (hand_pointer_data if hand_pointer_data is not None else yolo_pointer_data)
        gesture_payload = yolo_gesture_payload if laser_active else (hand_gesture_payload if hand_gesture_payload is not None else yolo_gesture_payload)

        # Track Gaze
        gaze_h, gaze_v = self.gaze_handler.process_frame(frame, timestamp_ms)
        if gaze_h is not None:
            # Draw Gaze on server HUD
            gh, gw = frame.shape[:2]
            cv2.circle(frame, (int(gaze_h * gw), int(gaze_v * gh)), 5, (255, 0, 255), -1)

        # Detect Emotion (Optimized interval)
        self.emotion_frame_count += 1
        emotion = "neutral"
        if self.emotion_frame_count % self.emotion_interval == 0:
            emotion = self.emotion_handler.analyze_emotion(frame)
        else:
            emotion = getattr(self, 'last_emotion', "neutral")
        self.last_emotion = emotion
        
        # Draw HUD
        cv2.putText(frame, f"User: {self.current_user}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(frame, f"Emotion: {emotion}", (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 100, 0), 2)
        
        if laser_active:
            cv2.putText(frame, "● LASER DOMINANT MODE", (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
        else:
            if suppress_gestures:
                cv2.putText(frame, "[ MENU OPEN - Gestures Paused ]", (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)
            else:
                cv2.putText(frame, "Concurrent Gestures Active", (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        
        # Gaze Debug HUD
        most_frequent = self.gaze_handler.get_most_frequent_side()
        h_ratio = np.mean(self.gaze_handler.h_buffer) if self.gaze_handler.h_buffer else 0.5
        cv2.putText(frame, f"Gaze: {most_frequent} (Ratio: {h_ratio:.2f})", (10, 114), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2)
        
        # YOLO Gesture state HUD
        tracking_status = "● YOLO RECORDING" if self.yolo_gesture_handler.is_tracking else "YOLO Gesture: Waiting..."
        tracking_color = (0, 255, 0) if self.yolo_gesture_handler.is_tracking else (160, 160, 160)
        cv2.putText(frame, tracking_status, (10, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.65, tracking_color, 2)

        # 1. Send Pointer Data (Index finger or YOLO object tracking) - Send every frame if available
        if pointer_data:
            try:
                pointer_payload = json.dumps({"type": "pointer", "x": pointer_data["x"], "y": pointer_data["y"]})
                self.conn.sendall((pointer_payload + "\n").encode("utf-8"))
            except Exception as e:
                print(f"Failed to send pointer: {e}")

        # 2. Send Gesture Data - Skip if in CIRCULAR_MENU state
        if gesture_payload and not suppress_gestures:
            payload = json.dumps(gesture_payload)
            try:
                self.conn.sendall((payload + "\n").encode("utf-8"))
                print(f"Sent Gesture: {payload}")
                
                # DB LOGGING: Log gesture if in session
                if self.current_session_id:
                    db.log_interaction(self.current_session_id, "gesture", gesture_payload)
            except Exception as e:
                print(f"Failed to send gesture: {e}")

        # 3. Send Emotion to Client
        try:
            emotion_payload = json.dumps({"type": "emotion", "value": emotion})
            self.conn.sendall((emotion_payload + "\n").encode("utf-8"))
            
            # DB LOGGING: Log emotion if in session
            if self.current_session_id:
                db.log_interaction(self.current_session_id, "emotion", {"value": emotion})
        except Exception as e:
            print(f"Failed to send emotion: {e}")

        # 4. Detect Ingredients (Every N frames to save CPU and improve stability)
        self.detection_frame_count += 1
        
        # Send detections to client on interval
        if detections is not None:
            if self.detection_frame_count % self.detection_interval == 0:
                try:
                    detection_payload = json.dumps({"type": "detections", "ingredients": detections})
                    self.conn.sendall((detection_payload + "\n").encode("utf-8"))
                    
                    # DB LOGGING: Log detections if in session
                    if self.current_session_id and detections:
                        db.log_interaction(self.current_session_id, "ingredients_detected", {"list": detections})
                except Exception as e:
                    print(f"Failed to send detections: {e}")

            # Draw bounding boxes on server HUD for debugging (drawn every frame when detections are active)
            for det in detections:
                h, w = frame.shape[:2]
                x1 = int(det["x"] * w)
                y1 = int(det["y"] * h)
                bw = int(det["w"] * w)
                bh = int(det["h"] * h)
                cv2.rectangle(frame, (x1, y1), (x1 + bw, y1 + bh), (0, 255, 0), 2)
                cv2.putText(frame, f"{det['label']} {det['confidence']}", (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        cv2.imshow("Kitchen Assistant - Vision", frame)

    def start_new_session(self, recipe_id, scenario):
        """Creates a session in the DB and returns the ID."""
        user_id = self.current_user_id if self.current_user_id else 0
        self.current_session_id = db.start_session(user_id, recipe_id, scenario)
        print(f"[VisionManager] Started session {self.current_session_id} for user {user_id}")
        return self.current_session_id


