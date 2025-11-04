#!/usr/bin/env python3
import bcrypt
import sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import altair as alt

# ---------------- DB Helpers ----------------
def init_db(conn):
    conn.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY,
        name TEXT,
        position TEXT,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS metrics(
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        label TEXT,
        group_name TEXT,
        type TEXT DEFAULT 'count',
        per80 INTEGER DEFAULT 1,
        weight REAL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS matches(
        id INTEGER PRIMARY KEY,
        opponent TEXT,
        date TEXT
    );

    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY,
        match_id INTEGER,
        player_id INTEGER,
        metric_id INTEGER,
        value REAL DEFAULT 1,
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS videos(
        id INTEGER PRIMARY KEY,
        match_id INTEGER,
        kind TEXT,
        url TEXT,
        label TEXT,
        offset REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS moments(
        id INTEGER PRIMARY KEY,
        match_id INTEGER,
        video_id INTEGER,
        video_ts REAL,
        note TEXT,
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        pass_hash BLOB NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        active INTEGER NOT NULL DEFAULT 1
    );
    """)
    conn.commit()


def _players_df(conn):
    return pd.read_sql("SELECT id,name,position,active FROM players ORDER BY name", conn)

def _metrics_df(conn, only_active=False):
    q = "SELECT id,name,label,group_name,type,per80,weight,active FROM metrics"
    if only_active: q += " WHERE active=1"
    q += " ORDER BY group_name,label"
    return pd.read_sql(q, conn)

def _matches_df(conn):
    return pd.read_sql("SELECT id,opponent,date FROM matches ORDER BY date DESC,id DESC", conn)

# ---------------- USER SETTINGS ----------------
def page_users(conn, role):
    st.header("👤 User Management")

    if role != "admin":
        st.error("Admin only.")
        return

    users = pd.read_sql("SELECT username, role, active FROM users", conn)
    st.dataframe(users, use_container_width=True)

    st.subheader("➕ Add User")
    new_user = st.text_input("Username")
    new_pass = st.text_input("Password", type="password")
    new_role = st.selectbox("Role", ["admin","editor","viewer"])

    if st.button("Create User"):
        if not new_user.strip() or not new_pass.strip():
            st.error("Enter username & password")
        else:
            ph = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt())
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO users(username,pass_hash,role,active) VALUES(?,?,?,1)",
                        (new_user.strip(), ph, new_role)
                    )
                st.success("User created")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("User already exists")

    st.subheader("✏️ Manage Existing User")
    if not users.empty:
        sel = st.selectbox("User", users["username"].tolist())
        r = users[users["username"]==sel].iloc[0]
        new_role = st.selectbox("Role", ["admin","editor","viewer"], index=["admin","editor","viewer"].index(r["role"]))
        active = st.checkbox("Active", value=bool(r["active"]))

        if st.button("Save Changes"):
            with conn:
                conn.execute(
                    "UPDATE users SET role=?, active=? WHERE username=?",
                    (new_role, int(active), sel)
                )
            st.success("Updated")
            st.rerun()

        if st.button("Reset Password"):
            temp_pw = st.text_input("Temporary Password", key="tmp_pw", type="password")
            if temp_pw:
                ph = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt())
                with conn:
                    conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, sel))
                st.success("Password reset!")

# ---------------- SELF ACCOUNT ----------------
def page_my_account(conn, username):
    st.header("🔐 My Account")

    new_pw = st.text_input("New Password", type="password")
    if st.button("Change Password"):
        if not new_pw.strip():
            st.error("Password required")
        else:
            ph = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt())
            with conn:
                conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, username))
            st.success("Password updated!")

# ---------------- TAGGING PAGE ----------------
def page_tagging(conn, role):
    st.header("🎥 Video + Live Match Tagging")

    matches = _matches_df(conn)
    if matches.empty:
        st.warning("Create a match first.")
        return

    match_id = st.selectbox(
        "Match", matches["id"].tolist(),
        format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} — {matches.set_index('id').loc[x,'opponent']}"
    )

    players = _players_df(conn).to_dict("records")
    metrics = _metrics_df(conn, only_active=True).to_dict("records")

    vids = pd.read_sql(
        "SELECT id,label,url,offset FROM videos WHERE match_id=? ORDER BY id",
        conn, params=(match_id,)
    )

    if vids.empty:
        st.warning("Add a video first.")
        return

    vid_id = st.selectbox(
        "Video",
        vids["id"].tolist(),
        format_func=lambda x: vids.set_index("id").loc[x,"label"]
    )

    vid = vids.set_index("id").loc[vid_id]
    offset = float(vid["offset"] or 0)

    col1,col2 = st.columns([2.2,1])

    with col1:
        st.subheader("🎬 Video")
        st.video(vid["url"], start_time=int(offset))

        st.subheader("⭐ Bookmark")
        ts_key = f"bm_{vid_id}"
        t = st.number_input("Time (sec)", value=float(st.session_state.get(ts_key, 0)), step=1.0)
        note = st.text_input("Note")

        if st.button("Add Bookmark"):
            with conn:
                conn.execute(
                    "INSERT INTO moments(match_id,video_id,video_ts,note) VALUES(?,?,?,?)",
                    (match_id, vid_id, float(t), note.strip())
                )
            st.session_state[ts_key] = float(t)
            st.success("Saved!")
            st.rerun()

        bms = pd.read_sql(
            "SELECT video_ts,note FROM moments WHERE match_id=? AND video_id=? ORDER BY video_ts",
            conn, params=(match_id,vid_id)
        )
        if not bms.empty:
            st.dataframe(bms, use_container_width=True)

    with col2:
        st.subheader("🏉 Log Event")

        cur_player = st.selectbox(
            "Player", [p["id"] for p in players],
            format_func=lambda x: next(p["name"] for p in players if p["id"] == x)
        )

        for grp in sorted({m["group_name"] for m in metrics}):
            st.markdown(f"**{grp}**")
            cols = st.columns(3)
            grp_metrics = [m for m in metrics if m["group_name"]==grp]
            for i,m in enumerate(grp_metrics):
                if cols[i%3].button(m["label"]):
                    with conn:
                        conn.execute(
                            "INSERT INTO events(match_id,player_id,metric_id) VALUES(?,?,?)",
                            (match_id, cur_player, m["id"])
                        )
                    st.toast(f"{m['label']} logged!", icon="✅")

        recent = pd.read_sql(
            """SELECT p.name, m.label, e.ts FROM events e
               JOIN players p ON p.id=e.player_id
               JOIN metrics m ON m.id=e.metric_id
               WHERE match_id=? ORDER BY e.id DESC LIMIT 12""",
            conn, params=(match_id,)
        )
        st.dataframe(recent, use_container_width=True)

# ---------------- MAIN ROUTER ----------------
def main(conn, role):
    init_db(conn)

    username = st.session_state.user["u"]

    tabs = st.tabs(["👤 Users","🔐 My Account","🎥 Tagging"])

    with tabs[0]:
        page_users(conn, role)

    with tabs[1]:
        page_my_account(conn, username)

    with tabs[2]:
        page_tagging(conn, role)
