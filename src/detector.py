import cv2
import mediapipe as mp
import time

class FaceDetector:
    def __init__(self, min_detection_confidence=0.5):
        """
        Initialize MediaPipe Face Detection.
        """
        self.mp_face_detection = mp.solutions.face_detection
        self.face_detection = self.mp_face_detection.FaceDetection(
            min_detection_confidence=min_detection_confidence
        )
    
    def detect(self, frame):
        """
        Detect faces in the frame.
        
        Args:
            frame: Numpy array representing the video frame (BGR).
            
        Returns:
            List of bounding boxes [(x, y, w, h), ...] for valid faces.
        """
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_detection.process(frame_rgb)
        
        bboxes = []
        if results.detections:
            h, w, _ = frame.shape
            min_width = w * 0.10  # 10% of frame width threshold
            
            for detection in results.detections:
                bboxC = detection.location_data.relative_bounding_box
                
                # Convert relative coordinates to absolute pixel values
                abs_x = int(bboxC.xmin * w)
                abs_y = int(bboxC.ymin * h)
                abs_w = int(bboxC.width * w)
                abs_h = int(bboxC.height * h)
                
                # Ensure coordinates are within frame bounds
                abs_x = max(0, abs_x)
                abs_y = max(0, abs_y)
                
                # Filter out small faces to save processing power
                if abs_w < min_width:
                    continue
                    
                bboxes.append((abs_x, abs_y, abs_w, abs_h))
                
        return bboxes
