import streamlit as st
import sqlite3, bcrypt, os
import importlib

DB_PATH = os.environ.get("RUGBY_DB_PATH", "/mount/data/rugby_stats.db")

# ---------------- DB + Auth ---------------- #

@st.cache_resource
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        );
    """)

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        user = os.environ.get("APP_ADMIN_USER", "ACST28")
        pw = os.environ.get("APP_ADMIN_PASS", "COYB1527")
        ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
        conn.execute("INSERT INTO users(username,pass_hash,role,active) VALUES(?,?,?,1)",
                     (user, ph, "admin"))
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
