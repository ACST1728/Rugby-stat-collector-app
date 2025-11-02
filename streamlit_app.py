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
    db_path = DB_PATH

    # If we cannot access the folder, fall back to memory DB
    try:
        folder = os.path.dirname(db_path)
        if folder and folder not in ("", "/") and not os.path.exists(folder):
            raise PermissionError("Cannot create folder in Streamlit Cloud")

        conn = sqlite3.connect(db_path, check_same_thread=False)
    except Exception:
        st.warning("⚠️ Cloud storage restricted — using temporary DB (data won't persist)")
        conn = sqlite3.connect(":memory:", check_same_thread=False)

    conn.row_factory = sqlite3.Row

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        pass_hash BLOB NOT NULL,
        role TEXT NOT NULL DEFAULT 'admin',
        active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # Seed admin if DB empty
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        user = os.environ.get("APP_ADMIN_USER", "admin")
        pw   = os.environ.get("APP_ADMIN_PASS", "admin123")
        ph   = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
            (user, ph, "admin")
        )
        conn.commit()

    return conn

# ---------------- AUTH UI ---------------- #
def login_page(conn):
    st.title("🔒 Rugby Stats Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login ✅", use_container_width=True):
        row = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (u,)
        ).fetchone()

        if not row:
            st.error("User not found"); return
        if row["active"] != 1:
            st.error("User inactive"); return

        if bcrypt.checkpw(p.encode(), row["pass_hash"]):
            st.session_state["user"] = {
                "username": row["username"],
                "role": row["role"]
            }
            st.rerun()
        else:
            st.error("Incorrect password")

def logout_button():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ---------------- MAIN ---------------- #
def main():
    st.set_page_config(page_title="Rugby Stats v5", layout="wide")

    conn = get_conn()

    if "user" not in st.session_state:
        return login_page(conn)

    logout_button()

    app_mod = importlib.import_module("rugby_stats_app_v5_main")
    app_mod.main(conn, st.session_state["user"]["role"])

main()
