import tensorflow as tf
import os
import pickle
import numpy as np
import cv2
from scipy.spatial.distance import cosine
import sys

import deepface
print("deepface version: ", deepface.__version__)
print("TensorFlow version: ", tf.__version__)
import mediapipe as mp
print("MediaPipe version: ", mp.__version__)
print(f"tf-keras version: {tf.keras.__version__}")
print("OpenCV version: ", cv2.__version__)