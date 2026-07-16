"""
Live camera face recognition — VS Code / local machine version.

Best pretrained model combo for this: InsightFace's "buffalo_l" pack, which
bundles SCRFD (detection + alignment) + ArcFace (recognition embeddings).
This is currently the strongest widely-used pretrained combination for
face recognition and needs no training data of your own.

Since you have no enrollment data yet, this script lets you enroll
yourself LIVE from the camera (no image uploads needed):

    Controls (while the camera window is focused):
      e   -> enroll a new face (you'll be asked to type a name in the terminal)
      q   -> quit
      d   -> delete an enrolled person (asked in the terminal)

Flow:
    1. Run the script. Camera opens.
    2. Press 'e', type a name in the terminal, look at the camera and hold
       still for a few frames while it captures samples of your face.
    3. From then on, your face (and anyone else you enroll) will show
       "ACCESS GRANTED: <name>" in green. Unrecognized faces show
       "UNKNOWN" in red.
    4. Enrolled faces are saved to disk (embeddings.pkl) so they persist
       the next time you run the script.

By default this only tracks ONE face at a time (the closest/largest one
in frame — SINGLE_FACE_MODE in the config section), like a one-person
entry gate. Set SINGLE_FACE_MODE = False if you want every face in
frame labeled at once.

Every recognition decision is logged to recognition_log.csv (timestamp,
name, score, granted) so you can review how well it's performing
afterward — see README.md for a simple accuracy-testing protocol.

Run in VS Code:
    - Open this folder in VS Code.
    - Create/select a Python interpreter (venv recommended, see README).
    - Run via the terminal: python main.py
      (Using the Run button also works, but a real terminal makes it much
      easier to type names when enrolling.)
"""

import csv
import os
import pickle
import time

import cv2
import numpy as np
from insightface.app import FaceAnalysis

# ----------------------------------------------------------------------
# Config — tune these
# ----------------------------------------------------------------------
MODEL_NAME = "buffalo_l"                # "buffalo_s" = noticeably faster, slightly less accurate
PROVIDERS = ["CPUExecutionProvider"]    # GPU: ["CUDAExecutionProvider", "CPUExecutionProvider"]
DETECTION_SIZE = (320, 320)             # smaller = faster detection (was 640x640)
SIMILARITY_THRESHOLD = 0.50             # cosine similarity cutoff for a match
MIN_FACE_SIZE = 60                      # px, filters out tiny/far detections
ENROLL_SAMPLES = 5                      # frames captured per enrollment
DB_PATH = "embeddings.pkl"
LOG_PATH = "recognition_log.csv"        # every recognition event gets logged here
CAMERA_INDEX = 0
FRAME_WIDTH = 960                       # lower capture res = less work per frame (was 1280)
FRAME_HEIGHT = 540

SINGLE_FACE_MODE = True                 # True = only track/label the closest (largest) face
                                         # False = label every face in frame
DETECT_EVERY_N_FRAMES = 2               # run the model every Nth frame, reuse the result
                                         # for frames in between so the video doesn't stall.
                                         # 1 = detect every frame (most accurate, slowest).
                                         # Raise to 3-4 on a slow CPU if it's still laggy.


# ----------------------------------------------------------------------
# Embedding database (simple pickle file, cosine-similarity matching)
# ----------------------------------------------------------------------
class FaceDatabase:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.data = {}
        self.load()

    def load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "rb") as f:
                self.data = pickle.load(f)

    def save(self):
        with open(self.db_path, "wb") as f:
            pickle.dump(self.data, f)

    @staticmethod
    def _normalize(v):
        n = np.linalg.norm(v)
        return v if n == 0 else v / n

    def add_embedding(self, name, embedding):
        self.data.setdefault(name, []).append(self._normalize(embedding))

    def remove_person(self, name):
        return self.data.pop(name, None) is not None

    def list_people(self):
        return {name: len(embs) for name, embs in self.data.items()}

    def match(self, embedding):
        if not self.data:
            return "Unknown", -1.0
        query = self._normalize(embedding)
        best_name, best_score = "Unknown", -1.0
        for name, embeddings in self.data.items():
            for stored in embeddings:
                score = float(np.dot(query, stored))
                if score > best_score:
                    best_score, best_name = score, name
        return best_name, best_score


# ----------------------------------------------------------------------
# Recognition event logging — lets you review accuracy after the fact
# ----------------------------------------------------------------------
def log_event(name, score, granted):
    new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "name", "score", "granted"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), name, f"{score:.4f}", granted])


# ----------------------------------------------------------------------
# Live enrollment: capture a few frames of the largest face in view
# ----------------------------------------------------------------------
def live_enroll(cap, app, db, name, num_samples=ENROLL_SAMPLES):
    print(f"[enroll] Look at the camera. Capturing {num_samples} samples of '{name}'...")
    collected = 0
    last_capture_time = 0

    while collected < num_samples:
        ok, frame = cap.read()
        if not ok:
            break

        faces = app.get(frame)
        display = frame.copy()

        if faces:
            # use the largest detected face
            face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            x1, y1, x2, y2 = face.bbox.astype(int)
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 200, 255), 2)

            now = time.time()
            if now - last_capture_time > 0.5:  # throttle captures ~2/sec
                db.add_embedding(name, face.embedding)
                collected += 1
                last_capture_time = now
                print(f"  [ok] sample {collected}/{num_samples}")

        cv2.putText(display, f"Enrolling '{name}': {collected}/{num_samples}",
                    (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow("Face Recognition", display)
        cv2.waitKey(1)

    db.save()
    print(f"[enroll] Done. '{name}' now has {len(db.data.get(name, []))} sample(s) saved.")


# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    print("Loading model (SCRFD detector + ArcFace recognizer)...")
    app = FaceAnalysis(name=MODEL_NAME, providers=PROVIDERS)
    app.prepare(ctx_id=0, det_size=DETECTION_SIZE)

    db = FaceDatabase()
    print("Enrolled people:", db.list_people() or "(none yet — press 'e' to enroll)")

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print("Could not open camera. Check CAMERA_INDEX in the config section.")
        return

    print("\nControls: [e] enroll new face   [d] delete a person   [q] quit\n")
    print(f"Logging every recognition event to {LOG_PATH}\n")

    prev_time = time.time()
    frame_count = 0
    last_results = []  # reused on frames where we skip detection, so video stays smooth
    last_logged = {}   # name -> last time we logged it, to avoid spamming the CSV

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed.")
            break

        frame_count += 1
        if frame_count % DETECT_EVERY_N_FRAMES == 0:
            faces = app.get(frame)

            # keep only faces above the minimum size
            faces = [
                f for f in faces
                if (f.bbox[2] - f.bbox[0]) >= MIN_FACE_SIZE and (f.bbox[3] - f.bbox[1]) >= MIN_FACE_SIZE
            ]

            if SINGLE_FACE_MODE and faces:
                # only the closest/largest face — treats this like a one-person-at-a-time gate
                faces = [max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))]

            results = []
            for face in faces:
                x1, y1, x2, y2 = face.bbox.astype(int)
                name, score = db.match(face.embedding)
                granted = score >= SIMILARITY_THRESHOLD
                results.append((x1, y1, x2, y2, name, score, granted))

                # throttle logging to once every 2s per person so the CSV stays readable
                now = time.time()
                if now - last_logged.get(name, 0) > 2.0:
                    log_event(name, score, granted)
                    last_logged[name] = now

            last_results = results

        for (x1, y1, x2, y2, name, score, granted) in last_results:
            label = f"ACCESS GRANTED: {name}" if granted else "UNKNOWN"
            color = (0, 200, 0) if granted else (0, 0, 220)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{label} ({score:.2f})", (x1, max(0, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

        now = time.time()
        fps = 1.0 / max(now - prev_time, 1e-6)
        prev_time = now
        cv2.putText(frame, f"FPS: {fps:.1f}  |  [e]nroll [d]elete [q]uit",
                    (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        cv2.imshow("Face Recognition", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("e"):
            name = input("Enter name to enroll: ").strip()
            if name:
                live_enroll(cap, app, db, name)
        elif key == ord("d"):
            name = input("Enter name to delete: ").strip()
            if db.remove_person(name):
                db.save()
                print(f"Removed '{name}'.")
            else:
                print(f"'{name}' not found.")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()