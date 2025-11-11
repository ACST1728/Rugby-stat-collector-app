#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

# ✅ DB path for Streamlit Cloud persistent storage
def _db_path():
    cloud_path = "/mount/data/rugby_stats.db"
    try:
        os.makedirs("/mount/data", exist_ok=True)
        return cloud_path
    except Exception:
        pass
    return "rugby_stats.db"

DB_PATH = _db_path()

# ✅ DB connection
@st.cache_resource
def get_conn():
    d = os.path.dirname(DB_PATH)
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    ensure_admin(conn)
    return conn

# ✅ Ensure default admin exists
def ensure_admin(conn):
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        user = os.environ.get("APP_ADMIN_USER", "admin")
        pw   = os.environ.get("APP_ADMIN_PASS", "admin123")
        ph   = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
            (user, ph, "admin")
        )
        conn.commit()

# ✅ Login form
def login(conn):
    st.title("🏉 Rugby Stats Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login ✅"):
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

        if not row:
            st.error("User not found")
            return

        if row["active"] != 1:
            st.error("User inactive")
            return

        if bcrypt.checkpw(password.encode(), row["pass_hash"]):
            st.session_state.user = {
                "u": row["username"],
                "role": row["role"]
            }
            st.rerun()
        else:
            st.error("Wrong password")

# ✅ Logout button
def logout():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ✅ Main app router
def main():
    st.set_page_config(page_title="Rugby Stats V5", layout="wide")
    conn = get_conn()

    # Not logged in → show login
    if "user" not in st.session_state:
        login(conn)
        return

    # Logout always present
    logout()

    # Admin sidebar button
    if st.session_state.user.get("role") == "admin":
        with st.sidebar:
            if st.button("👤 Manage Users"):
                st.session_state.show_user_admin = True

    # Admin user management screen
    if st.session_state.get("show_user_admin"):
        from user_admin_page import user_admin_page
        user_admin_page(conn)
        return

    # Load main rugby app
    app = importlib.import_module("rugby_stats_app_v5_main")
    app.main(conn, st.session_state.user["role"])


if __name__ == "__main__":
    main()

import threading, time, requests

def keep_awake(url: str):
    """Periodically ping the app to prevent it from sleeping."""
    def loop():
        while True:
            try:
                requests.get(url, timeout=10)
            except Exception:
                pass
            time.sleep(600)  # every 10 minutes
    threading.Thread(target=loop, daemon=True).start()

# Replace with your actual deployed app URL:
keep_awake("https://rugby-stat-collector-app-biejazu9hgtewyjjhbswh7.streamlit.app/")
