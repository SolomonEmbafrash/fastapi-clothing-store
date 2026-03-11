import os, psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg.connect(DATABASE_URL, autocommit=True)

# Migration: create / update database schema
def migrate_schema():
    print("INFO: Migrating schema...")
    try:
        with open("./db/migrate-schema.sql") as f:
            schema_sql = f.read()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(schema_sql)
            print("INFO: DB Schema migrated.")
    except Exception as e:
        print(f"ERROR: Failed to migrate schema: {e}")

def seed_sample_data():
    print("INFO: Checking sample data...")
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Check if categories table is empty
            cur.execute("SELECT 1 FROM categories LIMIT 1")
            if cur.fetchone():
                print("INFO: Tables not empty, skip data seed.")
            else:
                print("INFO: Seeding sample data...")
                with open("./db/sample-data.sql") as f:
                    data_sql = f.read()
                    cur.execute(data_sql)
                    print("INFO: Sample data inserted.")
    except Exception as e:
        print(f"ERROR: Failed to seed data: {e}")

if __name__ == "__main__":
    migrate_schema()
    seed_sample_data()