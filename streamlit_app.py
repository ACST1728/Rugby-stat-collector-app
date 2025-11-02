#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

# ---------------- DB PATH ---------------- #
def _db_path() -> str:
    try:
        if "RUGBY_DB_PATH" in st.secrets:
            return str(st.secrets["RUGBY_DB_PATH"])
    except Exception:
        pass

    return os.environ.get("RUGBY_DB_PATH", "data/rugby_stats.db")

DB_PATH = _db_path()

# ---------------- DB CONN ---------------- #
@st.cache_resource
def get_conn() -> sqlite3.Connection:
    # Create folder IF allowed in Streamlit FS
    folder = os.path.dirname(DB_PATH)
    if folder and folder not in ("", "/"):
        try:
            os.makedirs(folder, exist_ok=True)
        except PermissionError:
            pass

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Ensure users table
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        pass_hash BLOB NOT NULL,
        role TEXT NOT NULL DEFAULT 'admin',
        active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # Ensure default admin ONLY IF DB empty
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        default_user = os.environ.get("APP_ADMIN_USER", "admin")
        default_pass = os.environ.get("APP_ADMIN_PASS", "admin123")
        ph = bcrypt.hashpw(default_pass.encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
            (default_user, ph, "admin")
        )
        conn.commit()

    return conn

# ---------------- AUTH UI ---------------- #
def login(conn):
    st.title("🔒 Login")

    user = st.text_input("Username")
    pw   = st.text_input("Password", type="password")

    if st.button("Login ✅", use_container_width=True):
        row = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (user,)
        ).fetchone()

        if not row:
            st.error("User not found"); return

        if row["active"] != 1:
            st.error("User inactive"); return

        if bcrypt.checkpw(pw.encode(), row["pass_hash"]):
            st.session_state["user"] = {
                "username": row["username"],
                "role": row["role"]
            }
            st.rerun()
        else:
            st.error("Incorrect password")

def logout():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ---------------- MAIN ---------------- #
def main():
    st.set_page_config(page_title="Rugby Stats v5", layout="wide")

    conn = get_conn()  # safe init here

    if "user" not in st.session_state:
        return login(conn)

    logout()

    # Load v5 app module
    app_mod = importlib.import_module("rugby_stats_app_v5_main")
    app_mod.main(conn, st.session_state["user"]["role"])

main()
