#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

### ---------------------- DB PATH ---------------------- ###
def _db_path() -> str:
    # Priority order: secret override > env var > local data folder
    try:
        if "RUGBY_DB_PATH" in st.secrets:
            return str(st.secrets["RUGBY_DB_PATH"])
    except Exception:
        pass

    env = os.environ.get("RUGBY_DB_PATH")
    if env:
        return env

    # ✅ Guaranteed writable on Streamlit Cloud
    local_path = "data/rugby_stats.db"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    return local_path

DB_PATH = _db_path()

### ---------------------- DB CONNECTION ---------------------- ###
@st.cache_resource
def get_conn() -> sqlite3.Connection:
    # Ensure directory exists
    d = os.path.dirname(DB_PATH)
    if d and d not in ("/", ""):
        try: os.makedirs(d, exist_ok=True)
        except PermissionError: pass

    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    # Create users table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()

    ensure_default_admin(conn)
    return conn

### ---------------------- DEFAULT ADMIN SEED ---------------------- ###
def ensure_default_admin(conn):
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        user = os.environ.get("APP_ADMIN_USER", "admin")
        pw = os.environ.get("APP_ADMIN_PASS", "admin123")
        ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

        conn.execute(
            "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
            (user, ph, "admin"),
        )
        conn.commit()

### ---------------------- AUTH HELPERS ---------------------- ###
def login_form(conn):
    st.title("🔒 Rugby Stats Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login ✅", use_container_width=True):
        row = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (username,),
        ).fetchone()

        if not row:
            st.error("User not found"); return

        if row["active"] != 1:
            st.error("User inactive"); return

        if bcrypt.checkpw(password.encode(), row["pass_hash"]):
            st.session_state["user"] = {
                "username": row["username"],
                "role": row["role"]
            }
            st.rerun()   # ✅ fixed
        else:
            st.error("Incorrect password")

def logout_button():
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()  # ✅ fixed

### ---------------------- MAIN ROUTER ---------------------- ###
def main():
    st.set_page_config(page_title="Rugby Stats V5", layout="wide")

    conn = get_conn()

    # If not logged in -> login page
    if "user" not in st.session_state:
        return login_form(conn)

    # Show logout button
    logout_button()

    # Load main rugby app
    app_mod = importlib.import_module("rugby_stats_app_v5_main")
    app_mod.main(conn, st.session_state["user"]["role"])

### ---------------------- START ---------------------- ###
if __name__ == "__main__":
    main()
