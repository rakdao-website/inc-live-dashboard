"""
Analyze recognition_log.csv and print accuracy metrics.

Run this AFTER you've done a test session in main.py where:
  - You (enrolled) stood in front of the camera for a while
  - Then a teammate (NOT enrolled) stood in front of the camera for a while

Usage:
    python analyze_log.py

It will show, per enrolled name:
  - True Positive Rate  = % of that person's own attempts correctly granted
  - False Accept Rate   = % of "Unknown" attempts that were WRONGLY granted
                           under that name (impostors slipping through)

Read the numbers together with the score distribution it prints — a big
gap between granted-score averages and denied-score averages means the
model is separating people well; a small gap means it's struggling
(usually lighting/angle/enrollment quality, not the model itself).
"""

import csv
from collections import defaultdict

LOG_PATH = "recognition_log.csv"


def main():
    rows = []
    try:
        with open(LOG_PATH, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["score"] = float(row["score"])
                row["granted"] = row["granted"] == "True"
                rows.append(row)
    except FileNotFoundError:
        print(f"No {LOG_PATH} found yet — run main.py and let it recognize some faces first.")
        return

    if not rows:
        print("Log file is empty.")
        return

    by_name = defaultdict(list)
    for r in rows:
        by_name[r["name"]].append(r)

    print(f"Total logged events: {len(rows)}\n")
    print(f"{'Name':20s} {'Attempts':>9s} {'Granted':>9s} {'Rate':>7s} {'Avg score':>10s}")
    print("-" * 60)

    for name, entries in sorted(by_name.items()):
        attempts = len(entries)
        granted = sum(1 for e in entries if e["granted"])
        rate = granted / attempts * 100
        avg_score = sum(e["score"] for e in entries) / attempts
        print(f"{name:20s} {attempts:9d} {granted:9d} {rate:6.1f}% {avg_score:10.3f}")

    print("\nHow to read this:")
    print("  - For a name that IS you/enrolled: high 'Rate' (~90%+) and high avg score (~0.55+) = good.")
    print("  - For 'Unknown' entries: this is where an unenrolled person's face landed.")
    print("    If 'Unknown' avg score is close to your enrolled avg score, the model is")
    print("    borderline on separating you from strangers - re-enroll with more varied")
    print("    angles/lighting, or raise SIMILARITY_THRESHOLD in main.py.")


if __name__ == "__main__":
    main()
