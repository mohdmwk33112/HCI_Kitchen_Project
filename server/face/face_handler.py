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

                image = cv2.imread(image_path)
                if image is None:
                    print(f"  Error: Could not read {image_path}")
                    continue

                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

                # Downscale large images — dlib works best under 800px wide
                h, w = image.shape[:2]
                if w > 800:
                    scale = 800 / w
                    image = cv2.resize(image, (800, int(h * scale)))

                # C-contiguous uint8 required by dlib (NumPy 1.x compatibility)
                image = np.ascontiguousarray(image, dtype=np.uint8)

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
    # 0.6 is the library default (too loose). Tune this if needed.
    CONFIDENCE_THRESHOLD = 0.45

    def identify_face(self, frame):
        """
        Identifies faces in a single frame.
        Returns list of (name, confidence_pct) tuples.
        Only returns a name if face distance is below CONFIDENCE_THRESHOLD.
        """
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = np.ascontiguousarray(
            cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB), dtype=np.uint8
        )

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

            # Convert distance to a 0-100% confidence score
            confidence_pct = max(0.0, (1.0 - best_distance) * 100)

            if best_distance < self.CONFIDENCE_THRESHOLD:
                name = self.known_face_names[best_index]
            else:
                name = "Unknown"

            results.append((name, confidence_pct))

        return results

