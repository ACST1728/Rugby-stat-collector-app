#!/usr/bin/env python3
import os, sqlite3, bcrypt, importlib
import streamlit as st

from dropbox import Dropbox

def dropbox_download(dbx, cloud_path, local_path):
    try:
        md, res = dbx.files_download(cloud_path)
        with open(local_path, "wb") as f:
            f.write(res.content)
        return True
    except:
        return False

def dropbox_upload(dbx, local_path, cloud_path):
    try:
        with open(local_path, "rb") as f:
            dbx.files_upload(f.read(), cloud_path, mode=dropbox.files.WriteMode.overwrite)
        return True
    except Exception as e:
        st.error(f"Dropbox sync failed: {e}")
        return False

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
def get_conn():
    import os

    dbx = Dropbox(st.secrets["DROPBOX_TOKEN"])
    
    cloud = st.secrets["DROPBOX_DB_PATH"]
    local = st.secrets["LOCAL_DB_PATH"]

    # Ensure folder exists
    os.makedirs(os.path.dirname(local), exist_ok=True) if "/" in local else None

    # Try download DB first
    dropbox_download(dbx, cloud, local)

    conn = sqlite3.connect(local, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Auto create schema
    create_schema_if_needed(conn)

    # Upload DB back on shutdown
    def sync_to_dropbox():
        dropbox_upload(dbx, local, cloud)

    st.session_state["_dbx_sync"] = sync_to_dropbox
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
       # Run Dropbox sync if exists
if st.session_state.get("_dbx_sync"):
    try:
        st.session_state["_dbx_sync"]()
    except Exception as e:
        st.warning(f"Dropbox sync failed: {e}")



def create_schema_if_needed(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY,
            pass_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()

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
if "_dbx_sync" in st.session_state:
    st.session_state["_dbx_sync"]()

