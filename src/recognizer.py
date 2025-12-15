import os
import pickle
import numpy as np
from deepface import DeepFace
from scipy.spatial.distance import cosine

class FaceIdentifier:
    def __init__(self, db_path='db/authorized_users'):
        """
        Initialize FaceIdentifier.
        
        Args:
            db_path: Path to the directory containing user embeddings (.pkl files).
        """
        self.db_path = db_path
        self.users = {}
        self.model_name = "Facenet512"
        self.threshold = 0.4 # Threshold for Cosine distance (0.4 is reliable for FaceNet512)
        
        # Load known users immediately
        self.load_users()

    def load_users(self):
        """
        Loads all .pkl files from the db path into memory.
        """
        self.users = {}
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path, exist_ok=True)
            return

        for file_name in os.listdir(self.db_path):
            if file_name.endswith('.pkl'):
                name = os.path.splitext(file_name)[0]
                file_path = os.path.join(self.db_path, file_name)
                try:
                    with open(file_path, 'rb') as f:
                        embedding = pickle.load(f)
                        self.users[name] = embedding
                except Exception as e:
                    print(f"Error loading {file_path}: {e}")
        
        print(f"Loaded {len(self.users)} users: {list(self.users.keys())}")

    def verify(self, face_crop):
        """
        Generates embedding for the face crop and compares against loaded users.
        
        Args:
            face_crop: Numpy array of the face image.
            
        Returns:
            Tuple (name, distance). Name is "Unknown" if no match found.
        """
        try:
            # Generate embedding
            # enforce_detection=False because we already detected the face in Stage 1
            embedding_objs = DeepFace.represent(
                img_path=face_crop,
                model_name=self.model_name,
                enforce_detection=False,
                detector_backend="skip" 
            )
            
            if not embedding_objs:
                return "Unknown", 0.0
            
            # DeepFace.represent returns a list of dicts. We have one face crop.
            target_embedding = embedding_objs[0]["embedding"]
            
            best_match_name = "Unknown"
            min_distance = float('inf')
            
            for user_name, user_embedding in self.users.items():
                distance = cosine(target_embedding, user_embedding)
                
                if distance < min_distance:
                    min_distance = distance
                    best_match_name = user_name
            
            if min_distance < self.threshold:
                return best_match_name, min_distance
            else:
                return "Unknown", min_distance

        except Exception as e:
            print(f"Recognition error: {e}")
            return "Error", 0.0

    def get_embedding(self, face_image, warmup=False):
        """
        Helper to get embedding for enrollment.
        Args:
            face_image: The face image crop (numpy array).
            warmup: If True, only builds/loads the model and returns None.
        """
        if warmup:
            DeepFace.build_model(self.model_name)
            return None

        embedding_objs = DeepFace.represent(
            img_path=face_image,
            model_name=self.model_name,
            enforce_detection=False, # We assume manual capture or pre-check
            detector_backend="skip" # We are passing a crop from MediaPipe
        )
        if embedding_objs:
            return embedding_objs[0]["embedding"]
        return None
