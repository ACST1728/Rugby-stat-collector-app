# ===============================================
# Rugby Stats Collector – Streamlit Login Layer
# ===============================================

#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

# ✅ DB path for Streamlit Cloud persistent storage
def _db_path():
    # Streamlit Cloud persistent dir
    cloud_path = "/mount/data/rugby_stats.db"
    try:
        os.makedirs("/mount/data", exist_ok=True)
        return cloud_path
    except Exception:
        pass

    # Local dev fallback
    local = "rugby_stats.db"
    return local

DB_PATH = _db_path()


# ✅ Create DB connection
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

        conn.execute("INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
                     (user, ph, "admin"))
        conn.commit()

# ✅ Login form
def login(conn):
    st.title("🏉 Rugby Stats Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login ✅"):
        row = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if not row:
            st.error("User not found")
            return
        
        if row["active"] != 1:
            st.error("User inactive")
            return

        if bcrypt.checkpw(p.encode(), row["pass_hash"]):
            st.session_state.user = {"u": row["username"], "role": row["role"]}
            st.rerun()
        else:
            st.error("Wrong password")

# ✅ Logout button
def logout():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.experimental_rerun()

# ✅ App router
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
