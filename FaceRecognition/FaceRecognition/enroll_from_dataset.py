"""
Bulk-enroll people from a labeled dataset folder — adds to the SAME
embeddings.pkl that main.py uses, so anyone enrolled this way shows up
immediately next time you run main.py. No retraining needed; a
labeled dataset here is just used for enrollment, not for training the
underlying model.

Expected folder structure:

    dataset/
      john_smith/
        photo1.jpg
        photo2.jpg
      jane_doe/
        photo1.jpg
        photo2.jpg

Each subfolder name becomes the enrolled person's name. Use a handful
of varied photos per person (different angles/lighting) for best
results, same as live enrollment.

Usage:
    python enroll_from_dataset.py --dataset ./dataset
"""

import argparse
import glob
import os
import pickle

import cv2
import numpy as np
from insightface.app import FaceAnalysis

MODEL_NAME = "buffalo_l"
PROVIDERS = ["CPUExecutionProvider"]
DETECTION_SIZE = (320, 320)
DB_PATH = "embeddings.pkl"


def normalize(v):
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


def load_db(path=DB_PATH):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return {}


def save_db(data, path=DB_PATH):
    with open(path, "wb") as f:
        pickle.dump(data, f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="Path to the dataset folder")
    args = parser.parse_args()

    print("Loading model...")
    app = FaceAnalysis(name=MODEL_NAME, providers=PROVIDERS)
    app.prepare(ctx_id=0, det_size=DETECTION_SIZE)

    db = load_db()

    person_folders = sorted(
        d for d in glob.glob(os.path.join(args.dataset, "*")) if os.path.isdir(d)
    )
    if not person_folders:
        print(f"No subfolders found in {args.dataset}")
        return

    for folder in person_folders:
        name = os.path.basename(folder)
        image_paths = sorted(
            p for ext in ("*.jpg", "*.jpeg", "*.png")
            for p in glob.glob(os.path.join(folder, ext))
        )

        added = 0
        for path in image_paths:
            img = cv2.imread(path)
            if img is None:
                print(f"  [skip] could not read {path}")
                continue

            faces = app.get(img)
            if len(faces) != 1:
                print(f"  [skip] {os.path.basename(path)}: expected 1 face, found {len(faces)}")
                continue

            db.setdefault(name, []).append(normalize(faces[0].embedding))
            added += 1

        print(f"{name}: added {added}/{len(image_paths)} photo(s)")

    save_db(db)
    print(f"\nDone. embeddings.pkl now has: {{name: sample_count}} ->")
    print({n: len(e) for n, e in db.items()})


if __name__ == "__main__":
    main()
