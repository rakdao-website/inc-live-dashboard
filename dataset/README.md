# Face import dataset

One folder per seeded visitor. Folder name = phone number (matches `Visitor.visitor_phone`).

## Seeded people

| Folder | Name | Notes |
|--------|------|-------|
| `+971501234567` | Aisha Khan | client, face consent yes |
| `+971551112233` | Omar Hassan | visitor, face consent yes |
| `+971529998877` | Sara Al Maktoum | client, face consent yes |
| `+971504445566` | James Chen | visitor, face consent yes |
| `+971567778899` | Fatima Noor | client, face consent **no** (enroll only after consent API) |

## How to use

1. Seed DB visitors:
   ```bash
   python scripts/seed_poc.py --create-tables
   ```
2. Drop 1–3 clear front-facing photos into each person's folder (`.jpg` / `.png`).
3. Import embeddings into `face_embeddings`:
   ```bash
   python scripts/import_existing_faces.py --dataset ./dataset
   ```
4. Test:
   ```bash
   POST /api/face/detect  { "image_base64": "..." }
   ```

## Tip

If you only have photos for one person, start with Aisha (`+971501234567`) — she also has a seeded booking on MR_1.
