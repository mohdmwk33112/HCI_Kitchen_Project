import cv2
import time
import threading
from deepface import DeepFace
import numpy as np

class EmotionHandler:
    def __init__(self, analysis_interval=30.0):
        """
        Initialize the EmotionHandler.
        :param analysis_interval: Minimum time (seconds) between emotion analyses.
        """
        self.analysis_interval = analysis_interval
        self.last_analysis_time = 0
        self.last_emotion = "Neutral"
        self._analyzing = False

    def analyze_emotion(self, frame):
        """
        Non-blocking emotion analysis.
        Runs DeepFace in a background thread to prevent camera lag.
        """
        current_time = time.time()
        
        if self._analyzing:
            return self.last_emotion

        if current_time - self.last_analysis_time < self.analysis_interval:
            return self.last_emotion

        # Dispatch analysis to background thread
        def _run_analysis(img_copy):
            try:
                self._analyzing = True
                # DeepFace.analyze expects BGR image (OpenCV default)
                results = DeepFace.analyze(img_copy, actions=['emotion'], enforce_detection=False)
                if results:
                    self.last_emotion = results[0]['dominant_emotion']
                    print(f"[EmotionHandler] Detected: {self.last_emotion}")
            except Exception as e:
                print(f"[EmotionHandler] Error: {e}")
            finally:
                self._analyzing = False
                self.last_analysis_time = time.time()

        # Copy the frame so the thread has its own data
        thread = threading.Thread(target=_run_analysis, args=(frame.copy(),), daemon=True)
        thread.start()
            
        return self.last_emotion
