import cv2
import time
import json
from threading import Thread
from face.face_handler import FaceHandler
from face.emotion_handler import EmotionHandler
from gestures.hand_gestures import GestureHandler

class VisionManager:
    def __init__(self, people_dir, conn):
        self.conn = conn
        self.face_handler = FaceHandler(people_dir)
        self.gesture_handler = GestureHandler()
        self.emotion_handler = EmotionHandler(analysis_interval=30.0)
        
        self.state = "LOGIN"  # States: LOGIN, GESTURES, CIRCULAR_MENU
        self.running = False
        self.confirmations_needed = 5
        self.confirmation_counts = {}
        self.last_name = None
        self.current_user = None

    def start(self):
        self.running = True
        Thread(target=self._camera_loop, daemon=True).start()

    def set_state(self, new_state):
        print(f"[VisionManager] State changed to: {new_state}")
        self.state = new_state
        if new_state == "LOGIN":
            self.current_user = None
            self.confirmation_counts = {}
            self.last_name = None

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

                if frame.ndim == 2:  # Grayscale
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                elif frame.shape[2] == 4:  # BGRA
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                frame = cv2.flip(frame, 1)  # Mirror
                timestamp_ms = int(time.time() * 1000)

                if self.state == "LOGIN":
                    self._process_login(frame)
                elif self.state == "GESTURES":
                    self._process_gestures(frame, timestamp_ms)
                elif self.state == "CIRCULAR_MENU":
                    # While menu is open, we skip gesture events but still send pointer tracking
                    self._process_gestures(frame, timestamp_ms, suppress_gestures=True)

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
                self.conn.sendall(f"login_success;{current_name}\n".encode("utf-8"))
                self.set_state("GESTURES")
        else:
            label = "Scanning for faces..."
            color = (0, 0, 255)
            self.last_name = None
            self.confirmation_counts = {}

        cv2.putText(frame, label, (30, 40), cv2.FONT_HERSHEY_DUPLEX, 1.0, color, 2)
        cv2.imshow("Kitchen Assistant - Vision", frame)

    def _process_gestures(self, frame, timestamp_ms, suppress_gestures=False):
        # Pass frame to gesture handler
        gesture_payload, pointer_data = self.gesture_handler.process_frame(frame, timestamp_ms)

        # Detect Emotion (Only in GESTURES state, after login)
        emotion = self.emotion_handler.analyze_emotion(frame)
        
        # Draw HUD
        cv2.putText(frame, f"User: {self.current_user}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(frame, f"Emotion: {emotion}", (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 100, 0), 2)
        
        if suppress_gestures:
            cv2.putText(frame, "[ MENU OPEN - Gestures Paused ]", (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)
        else:
            cv2.putText(frame, "Gestures Active", (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        
        # 1. Send Pointer Data (Index finger tracking) - Send every frame if available
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
            except Exception as e:
                print(f"Failed to send gesture: {e}")

        # 3. Send Emotion to Client
        try:
            emotion_payload = json.dumps({"type": "emotion", "value": emotion})
            self.conn.sendall((emotion_payload + "\n").encode("utf-8"))
        except Exception as e:
            print(f"Failed to send emotion: {e}")

        cv2.imshow("Kitchen Assistant - Vision", frame)
