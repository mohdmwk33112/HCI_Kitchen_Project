"""
db.py — Database layer for the Kitchen Assistant server.
Schema based on the project ERD:
  USER → RECIPE → SESSION → INTERACTION_LOG
                           → EVALUATION
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")


# ─────────────────────────────────────────────
#  Connection helper
# ─────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # allows dict-like row access
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─────────────────────────────────────────────
#  Schema creation
# ─────────────────────────────────────────────
def init_db():
    """Creates all tables if they do not exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS USER (
            user_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            face_encoding       TEXT,               -- JSON array of 128 floats
            dietary_restrictions TEXT,
            skill_level         TEXT,
            preferred_side      TEXT DEFAULT 'Left'  -- 'Left', 'Center', or 'Right'
        );

        CREATE TABLE IF NOT EXISTS RECIPE (
            recipe_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES USER(user_id),
            title           TEXT    NOT NULL,
            scenario        TEXT,
            steps_json      TEXT    NOT NULL,       -- JSON array of step strings
            ingredients_json TEXT   NOT NULL        -- JSON array of ingredient objects
        );

        CREATE TABLE IF NOT EXISTS SESSION (
            session_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES USER(user_id),
            recipe_id   INTEGER REFERENCES RECIPE(recipe_id),
            scenario    TEXT,
            started_at  TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS INTERACTION_LOG (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES SESSION(session_id),
            type        TEXT    NOT NULL,            -- e.g. 'gesture', 'click', 'step_complete'
            data_json   TEXT,                        -- arbitrary JSON payload
            logged_at   TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS EVALUATION (
            eval_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES SESSION(session_id),
            task_time_sec   INTEGER,
            errors          INTEGER,
            nasa_tlx_score  REAL,
            feedback        TEXT
        );
        """)
    print(f"Database ready at {DB_PATH}")


# ─────────────────────────────────────────────
#  USER helpers
# ─────────────────────────────────────────────
def get_user_by_name(name: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM USER WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM USER WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def create_user(name: str, face_encoding=None, dietary_restrictions=None, skill_level=None):
    encoding_str = json.dumps(face_encoding) if face_encoding is not None else None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO USER (name, face_encoding, dietary_restrictions, skill_level) VALUES (?,?,?,?)",
            (name, encoding_str, dietary_restrictions, skill_level)
        )
        return cur.lastrowid


def update_face_encoding(user_id: int, face_encoding: list):
    with get_conn() as conn:
        conn.execute(
            "UPDATE USER SET face_encoding = ? WHERE user_id = ?",
            (json.dumps(face_encoding), user_id)
        )


def update_preferred_side(user_id: int, side: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE USER SET preferred_side = ? WHERE user_id = ?",
            (side, user_id)
        )


# ─────────────────────────────────────────────
#  RECIPE helpers
# ─────────────────────────────────────────────
def get_recipe(recipe_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM RECIPE WHERE recipe_id = ?", (recipe_id,)
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        r["steps_json"]       = json.loads(r["steps_json"])
        r["ingredients_json"] = json.loads(r["ingredients_json"])
        return r


def get_recipes_for_user(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_id, title, scenario FROM RECIPE WHERE user_id = ? OR user_id IS NULL",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def create_recipe(title, steps, ingredients, scenario=None, user_id=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO RECIPE (user_id, title, scenario, steps_json, ingredients_json) VALUES (?,?,?,?,?)",
            (user_id, title, scenario, json.dumps(steps), json.dumps(ingredients))
        )
        return cur.lastrowid


# ─────────────────────────────────────────────
#  SESSION helpers
# ─────────────────────────────────────────────
def start_session(user_id: int, recipe_id: int = None, scenario: str = None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO SESSION (user_id, recipe_id, scenario) VALUES (?,?,?)",
            (user_id, recipe_id, scenario)
        )
        return cur.lastrowid


def get_session(session_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM SESSION WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
#  INTERACTION_LOG helpers
# ─────────────────────────────────────────────
def log_interaction(session_id: int, interaction_type: str, data: dict = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO INTERACTION_LOG (session_id, type, data_json) VALUES (?,?,?)",
            (session_id, interaction_type, json.dumps(data) if data else None)
        )


# ─────────────────────────────────────────────
#  EVALUATION helpers
# ─────────────────────────────────────────────
def save_evaluation(session_id: int, task_time_sec: int = None,
                    errors: int = None, nasa_tlx_score: float = None,
                    feedback: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO EVALUATION
               (session_id, task_time_sec, errors, nasa_tlx_score, feedback)
               VALUES (?,?,?,?,?)""",
            (session_id, task_time_sec, errors, nasa_tlx_score, feedback)
        )


def sync_users_from_files(people_dir):
    """Ensures all users in face/people exist in the DB."""
    if not os.path.exists(people_dir):
        return
    
    import glob
    extensions = ['*.jpg', '*.jpeg', '*.png']
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(people_dir, ext)))
        
    with get_conn() as conn:
        for path in image_files:
            name = os.path.splitext(os.path.basename(path))[0]
            # Check if exists
            row = conn.execute("SELECT user_id FROM USER WHERE name = ?", (name,)).fetchone()
            if not row:
                print(f"Creating DB user for: {name}")
                conn.execute("INSERT INTO USER (name) VALUES (?)", (name,))

# ─────────────────────────────────────────────
#  Entry point — run directly to initialise DB
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    sync_users_from_files(os.path.join("face", "people"))
    print("Tables created and users synced.")
