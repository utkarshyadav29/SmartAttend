import os
import json
import numpy as np

def detect_and_encode_faces(image_path):
    """
    Returns list of face encodings from an image.
    Uses YOLOv8 for detection + DeepFace for encoding.
    Falls back to mock data if models not installed.
    """
    try:
        from ultralytics import YOLO
        from deepface import DeepFace
        import cv2

        model = YOLO('yolov8n.pt')
        img = cv2.imread(image_path)
        if img is None:
            return []

        results = model(img, conf=0.4, classes=[0])  # class 0 = person (use face model in prod)
        encodings = []

        for box in results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            face_crop = img[y1:y2, x1:x2]
            if face_crop.size == 0:
                continue
            temp_path = f"/tmp/face_crop_{len(encodings)}.jpg"
            cv2.imwrite(temp_path, face_crop)
            try:
                rep = DeepFace.represent(temp_path, model_name='Facenet', enforce_detection=False)
                if rep:
                    encodings.append(rep[0]['embedding'])
            except:
                pass
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return encodings

    except ImportError:
        # Mock encoding for development without GPU/models
        import random
        random.seed(hash(image_path) % 1000)
        n = random.randint(1, 3)
        return [[random.gauss(0, 1) for _ in range(128)] for _ in range(n)]


def match_face_to_students(face_encoding, students, threshold=0.6):
    """
    Match a single face encoding to student database.
    Returns (student, confidence) or (None, 0).
    """
    best_match = None
    best_score = 0.0

    for student in students:
        stored = student.get_encoding()
        if not stored:
            continue
        for enc in stored:
            score = cosine_similarity(face_encoding, enc)
            if score > best_score:
                best_score = score
                best_match = student

    if best_score >= threshold:
        return best_match, best_score
    return None, best_score


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def process_attendance_image(image_path, students):
    """
    Full pipeline: detect → encode → match.
    Returns list of {student, confidence, matched}
    """
    encodings = detect_and_encode_faces(image_path)
    results = []
    matched_ids = set()

    for enc in encodings:
        student, conf = match_face_to_students(enc, students)
        if student and student.id not in matched_ids:
            matched_ids.add(student.id)
            results.append({'student': student, 'confidence': conf, 'matched': True})

    # Mark unmatched students as absent
    for student in students:
        if student.id not in matched_ids:
            results.append({'student': student, 'confidence': 0.0, 'matched': False})

    return results
