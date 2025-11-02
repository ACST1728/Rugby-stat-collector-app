import streamlit as st
import sqlite3, bcrypt, os
import importlib

DB_PATH = os.environ.get("RUGBY_DB_PATH", "/mount/data/rugby_stats.db")

# ---------------- DB + Auth ---------------- #

@st.cache_resource
def get_conn():
  # Decide DB location
    default_path = "/mount/data/rugby_stats.db"
    fallback_path = "rugby_stats.db"

    # Try secure DB path first
    db_path = default_path
    try:
        os.makedirs(os.path.dirname(default_path), exist_ok=True)
    except Exception:
        # Streamlit Cloud fallback
        db_path = fallback_path

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Create users table if missing
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()
    return conn

def login(conn, u, p):
    row = conn.execute(
        "SELECT username, pass_hash, role, active FROM users WHERE username=?",
        (u,)
    ).fetchone()
    if row and row["active"] == 1:
        if bcrypt.checkpw(p.encode(), row["pass_hash"]):
            return row["username"], row["role"]
    return None, None

def logout():
    for k in ["user","role"]:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# -------------- UI Wrapper --------------- #

def login_screen(conn):
    st.title("🏉 Rugby Stats Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login"):
        user, role = login(conn, u, p)
        if user:
            st.session_state["user"] = user
            st.session_state["role"] = role
            st.success("Logged in!")
            st.rerun()
        else:
            st.error("Invalid login")

def main():
    conn = get_conn()

    # Show login if not logged in
    if "user" not in st.session_state:
        login_screen(conn)
        return

    # Show top bar
    st.sidebar.success(f"Logged in as {st.session_state['user']} ({st.session_state['role']})")
    if st.sidebar.button("Logout"):
        logout()

    # Load V5 app
    app_mod = importlib.import_module("rugby_stats_app_v5_main")
    app_mod.main()

if __name__ == "__main__":
    main()
