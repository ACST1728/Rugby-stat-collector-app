#!/usr/bin/env python3
import os, io, sqlite3, bcrypt, importlib, time
import streamlit as st

# ----------------------------------------
# ✅ Persistent DB path (Streamlit Cloud)
# ----------------------------------------
def _db_path():
    cloud = "/mount/data/rugby_stats.db"
    if os.path.exists("/mount/data"):
        return cloud
    return "rugby_stats.db"

DB_PATH = _db_path()

# ----------------------------------------
# ✅ DB connection + users table
# ----------------------------------------
@st.cache_resource
def get_conn():
    d = os.path.dirname(DB_PATH)
    if d and d not in ("/", ""):
        try: os.makedirs(d, exist_ok=True)
        except Exception: pass

    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
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

# ----------------------------------------
# ✅ Create admin once silently
# ----------------------------------------
def seed_admin(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    username = os.environ.get("APP_ADMIN_USER", "admin")
    pw       = os.environ.get("APP_ADMIN_PASS", "admin123")
    ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
    conn.execute("""
        INSERT INTO users(username, pass_hash, role, active)
        VALUES (?,?,?,1)
    """, (username, ph, "admin"))
    conn.commit()

# ----------------------------------------
# ☁️ Optional Dropbox sync helpers (DB file only)
# ----------------------------------------
def _dbx():
    """Return a Dropbox client if token provided, else None."""
    try:
        token = st.secrets.get("DROPBOX_TOKEN", "").strip()
        if not token:
            return None
        from dropbox import Dropbox
        return Dropbox(token)
    except Exception:
        return None

def dbx_upload(dbx, local_path, cloud_path):
    try:
        from dropbox.files import WriteMode
        with open(local_path, "rb") as f:
            dbx.files_upload(f.read(), cloud_path, mode=WriteMode("overwrite"))
        return True, None
    except Exception as e:
        return False, str(e)

def dbx_download(dbx, cloud_path, local_path):
    try:
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        md, res = dbx.files_download(cloud_path)
        with open(local_path, "wb") as f:
            f.write(res.content)
        return True, None
    except Exception as e:
        return False, str(e)

def dropbox_sidebar():
    dbx = _dbx()
    with st.sidebar.expander("☁️ Dropbox Sync", expanded=False):
        if not dbx:
            st.caption("Add `DROPBOX_TOKEN` in **Settings → Secrets** to enable DB backup.")
            return
        cloud_path = st.secrets.get("DROPBOX_DB_PATH", "/apps/rugby-stats/rugby_stats.db")
        st.caption(f"Cloud path: `{cloud_path}`")
        c1, c2 = st.columns(2)
        if c1.button("⬆️ Upload DB"):
            ok, err = dbx_upload(dbx, DB_PATH, cloud_path)
            st.success("Uploaded ✅") if ok else st.error(f"Upload failed: {err}")
        if c2.button("⬇️ Download DB"):
            ok, err = dbx_download(dbx, cloud_path, DB_PATH)
            if ok:
                st.success("Downloaded ✅")
                # purge the connection cache so Streamlit re-opens the DB file
                st.cache_resource.clear()
                st.rerun()
            else:
                st.error(f"Download failed: {err}")

        # Optional gentle auto refresh to encourage periodic use; not a background task
        st.caption("Tip: click Upload after sessions to back up your data.")

# ----------------------------------------
# ✅ Login screen — no re-runs until success
# ----------------------------------------
def login_screen(conn):
    st.title("🏉 Rugby Stats Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login ✅", use_container_width=True):
        row = conn.execute(
            "SELECT username, pass_hash, role, active FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if not row:
            st.error("❌ Unknown user")
            return

        if row["active"] != 1:
            st.error("🚫 User disabled")
            return

        if bcrypt.checkpw(password.encode(), row["pass_hash"]):
            st.session_state.user = {
                "username": row["username"],
                "role": row["role"]
            }
            st.rerun()
        else:
            st.error("❌ Incorrect password")

# ----------------------------------------
# ✅ Logout
# ----------------------------------------
def logout_button():
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ----------------------------------------
# ✅ Router
# ----------------------------------------
def main():
    st.set_page_config(page_title="Rugby Stats", layout="wide")
    conn = get_conn()

    # Dropbox tools in sidebar (optional)
    dropbox_sidebar()

    if "user" not in st.session_state:
        return login_screen(conn)

    logout_button()

    app = importlib.import_module("rugby_stats_app_v5_main")
    app.main(conn, st.session_state.user["role"])

if __name__ == "__main__":
    main()
