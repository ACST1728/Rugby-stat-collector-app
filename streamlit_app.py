#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

# ------------------------------------
# ✅ DB PATH (persistent if allowed)
# ------------------------------------
def _db_path():
    cloud = "/mount/data/rugby_stats.db"
    if os.path.exists("/mount/data"):
        return cloud
    return "rugby_stats.db"  # local fallback

DB_PATH = _db_path()


# ------------------------------------
# ✅ DB Connection
# ------------------------------------
@st.cache_resource
def get_conn():
    folder = os.path.dirname(DB_PATH)
    if folder and folder not in ("/", ""):
        try: os.makedirs(folder, exist_ok=True)
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

    seed_admin(conn)
    return conn


# ------------------------------------
# ✅ Create admin ONLY if DB is empty
# ------------------------------------
def seed_admin(conn):
    has_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if has_users > 0:
        return

    user = os.environ.get("APP_ADMIN_USER", "admin")
    pw = os.environ.get("APP_ADMIN_PASS", "admin123")

    ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

    conn.execute(
        "INSERT INTO users(username, pass_hash, role, active) VALUES (?,?,?,1)",
        (user, ph, "admin")
    )
    conn.commit()


# ------------------------------------
# ✅ Login UI
# ------------------------------------
def login(conn):
    st.title("🏉 Rugby Stats Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login ✅", use_container_width=True):
        row = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (u,)
        ).fetchone()

        if not row:
            st.error("❌ Unknown user")
            return

        if row["active"] != 1:
            st.error("🚫 User disabled")
            return

        if bcrypt.checkpw(p.encode(), row["pass_hash"]):
            st.session_state.user = {"username": row["username"], "role": row["role"]}
            st.rerun()
        else:
            st.error("❌ Wrong password")


# ------------------------------------
# ✅ Logout
# ------------------------------------
def logout():
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ------------------------------------
# ✅ Main Router
# ------------------------------------
def main():
    st.set_page_config(page_title="Rugby Stats V5", layout="wide")
    conn = get_conn()

    if "user" not in st.session_state:
        return login(conn)

    logout()

    app = importlib.import_module("rugby_stats_app_v5_main")
    app.main(conn, st.session_state.user["role"])


if __name__ == "__main__":
    main()
