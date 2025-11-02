#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

def _db_path():
    db = "data/rugby_stats.db"
    os.makedirs("data", exist_ok=True)
    return db

DB_PATH = _db_path()

@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        );
    """)

    # seed admin
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        user = "admin"
        pw   = "admin123"
        ph   = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
            (user, ph, "admin"),
        )
        conn.commit()

    return conn

def login(conn):
    st.title("🏉 Rugby Stats Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login ✅"):
        r = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (u,),
        ).fetchone()

        if not r:
            st.error("User not found")
            return

        if r["active"] != 1:
            st.error("User inactive")
            return

        if bcrypt.checkpw(p.encode(), r["pass_hash"]):
            st.session_state["user"] = {"u": r["username"], "role": r["role"]}
            st.rerun()
        else:
            st.error("Incorrect password")

def logout():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

def main():
    st.set_page_config(page_title="Rugby Stats v5", layout="wide")
    conn = get_conn()

    if "user" not in st.session_state:
        return login(conn)

    logout()

    app = importlib.import_module("rugby_stats_app_v5_main")
    app.main(conn, st.session_state["user"]["role"])

if __name__ == "__main__":
    main()
