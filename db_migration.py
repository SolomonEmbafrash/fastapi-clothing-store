from pathlib import Path
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

root = Path(__file__).resolve().parent
schema_path = root / "db" / "migrate-schema.sql"
sample_path = root / "db" / "sample-data.sql"

with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
        cur.execute(sample_path.read_text(encoding="utf-8"))

print("Database migration and sample data completed successfully.")
