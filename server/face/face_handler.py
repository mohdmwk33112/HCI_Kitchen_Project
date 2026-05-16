import face_recognition
import cv2
import numpy as np
import os
import glob


class FaceHandler:
    def __init__(self, people_dir):
        self.known_face_encodings = []
        self.known_face_names = []
        self.people_dir = people_dir
        self.load_known_faces()

    def load_known_faces(self):
        print(f"Loading known faces from {self.people_dir}...")
        extensions = ['*.jpg', '*.jpeg', '*.png']
        image_files = []
        for ext in extensions:
            image_files.extend(glob.glob(os.path.join(self.people_dir, ext)))

        for image_path in image_files:
            try:
                name = os.path.splitext(os.path.basename(image_path))[0]

                # Use face_recognition's own loader (PIL-based)
                # Then explicitly convert to RGB 8-bit to satisfy dlib
                image = face_recognition.load_image_file(image_path)
                
                # Normalize image format
                if image.ndim == 2: # Grayscale
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
                elif image.shape[2] == 4: # RGBA
                    image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
                elif image.shape[2] == 3: # Already RGB, but let's be sure
                    pass

                # Downscale large images — dlib works best under 800px wide
                h, w = image.shape[:2]
                if w > 800:
                    scale = 800 / w
                    image = cv2.resize(image, (800, int(h * scale)))

                # FINAL SANITY CHECK: uint8 and C-contiguous is MANDATORY for dlib
                # Forcing a copy with astype can help with numpy 2.0 compatibility
                image = np.ascontiguousarray(image).astype(np.uint8, copy=True)

                encodings = face_recognition.face_encodings(image)

                if len(encodings) > 0:
                    self.known_face_encodings.append(encodings[0])
                    self.known_face_names.append(name)
                    print(f"  Loaded: {name}")
                else:
                    print(f"  Warning: No face found in {image_path}")
            except Exception as e:
                import traceback
                print(f"  Error loading {image_path}: {e}")
                traceback.print_exc()

        print(f"Total faces loaded: {len(self.known_face_names)}")

    # Distance threshold: lower = stricter. 0.45 is high confidence.
    CONFIDENCE_THRESHOLD = 0.45

    def identify_face(self, frame):
        """
        Identifies faces in a single frame.
        """
        if frame is None:
            return []
            
        # DroidCam / IP-cam often sends weird channel counts
        # Normalize to 3-channel BGR first if needed
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        
        # Normalize format and convert to RGB
        if small_frame.ndim == 2:
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_GRAY2RGB)
        elif small_frame.shape[2] == 4:
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGRA2RGB)
        else:
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            
        rgb_small_frame = np.ascontiguousarray(rgb_small_frame).astype(np.uint8, copy=True)

        face_locations = face_recognition.face_locations(rgb_small_frame)
        face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

        results = []
        for face_encoding in face_encodings:
            face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)

            if len(face_distances) == 0:
                results.append(("Unknown", 0.0))
                continue

            best_index = np.argmin(face_distances)
            best_distance = face_distances[best_index]

            confidence_pct = max(0.0, (1.0 - best_distance) * 100)

            if best_distance < self.CONFIDENCE_THRESHOLD:
                name = self.known_face_names[best_index]
            else:
                name = "Unknown"

            results.append((name, confidence_pct))

        return results

    def register_new_face(self, frame, name):
        """
        Saves a frame as a new face image and reloads the face database.
        """
        if frame is None or not name:
            return False
            
        filename = f"{name}.jpg"
        filepath = os.path.join(self.people_dir, filename)
        
        # Save the full resolution frame (BGR format for CV2)
        cv2.imwrite(filepath, frame)
        print(f"Registered new face: {name} at {filepath}")
        
        # Reload the database to include the new face immediately
        self.load_known_faces()
        return True
