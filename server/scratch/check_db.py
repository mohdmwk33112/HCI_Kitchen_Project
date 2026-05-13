import sqlite3
import os

DB_PATH = "h:/year 4 semester 2/HCI/labs/Lab 2 - TUIO + GUI-20260505/HCI_Kitchen_Project/server/users.db"

def check_db():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    tables = ["USER", "SESSION", "INTERACTION_LOG", "EVALUATION"]
    
    for table in tables:
        print(f"\n--- {table} ---")
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print("Empty")
            else:
                for row in rows:
                    print(dict(row))
        except Exception as e:
            print(f"Error reading {table}: {e}")
    
    conn.close()

if __name__ == "__main__":
    check_db()
