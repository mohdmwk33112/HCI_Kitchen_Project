import cv2
import time
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

    def analyze_emotion(self, frame):
        """
        Analyzes the frame for facial expressions/emotions.
        Returns the dominant emotion if the interval has passed, otherwise returns the last detected emotion.
        """
        current_time = time.time()
        
        # Rate limiting to avoid blocking the main vision thread
        if current_time - self.last_analysis_time < self.analysis_interval:
            return self.last_emotion

        try:
            # DeepFace.analyze expects BGR image (OpenCV default)
            # actions=['emotion'] detects happy, sad, angry, etc.
            # enforce_detection=False prevents it from throwing an exception if no face is found
            results = DeepFace.analyze(frame, actions=['emotion'], enforce_detection=False)
            
            if results:
                # results is a list of dicts (one for each face detected)
                # We'll take the first face detected
                self.last_emotion = results[0]['dominant_emotion']
                self.last_analysis_time = current_time
                print(f"[EmotionHandler] Detected: {self.last_emotion}")
                
        except Exception as e:
            print(f"[EmotionHandler] Error during analysis: {e}")
            # We don't update last_analysis_time on error to retry sooner if needed, 
            # but we keep the last_emotion to avoid flickering.
            
        return self.last_emotion
