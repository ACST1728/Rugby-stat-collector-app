#!/usr/bin/env python3
import sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import altair as alt
import bcrypt

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

# ---------------- USERS DB ----------------
def init_user_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    # ✅ ensure at least one admin exists
    admin_exists = conn.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone()
    if not admin_exists:
        pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        conn.execute("INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
                     ("admin", pw, "admin"))
    conn.commit()

def create_user(conn, username, password, role):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn.execute(
        "INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
        (username, pw_hash, role)
    )
    conn.commit()

def reset_password(conn, username, new_password):
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash=? WHERE username=?", (pw_hash, username))
    conn.commit()

# ---------------- Combined Tagging Page ----------------
def page_tagging(conn, role):
    st.header("🎥 Video + Live Match Tagging")

    matches = _matches_df(conn)
    if matches.empty:
        st.warning("Create a match first in Live Logger.")
        return

    match_id = st.selectbox(
        "Match",
        matches["id"].tolist(),
        format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} — {matches.set_index('id').loc[x,'opponent']}"
    )

    players = _players_df(conn).to_dict("records")
    metrics = _metrics_df(conn, only_active=True).to_dict("records")

    vids = pd.read_sql(
        "SELECT id,label,url,offset FROM videos WHERE match_id=? ORDER BY id",
        conn, params=(match_id,)
    )
    if vids.empty:
        st.warning("Add a video in Video page first.")
        return

    vid_id = st.selectbox(
        "Video",
        vids["id"].tolist(),
        format_func=lambda x: vids.set_index("id").loc[x,"label"]
    )

    vid = vids.set_index("id").loc[vid_id]
    offset = float(vid["offset"] or 0)

    col1,col2 = st.columns([2.2,1])

    # ----- LEFT: Video + Bookmarks -----
    with col1:
        st.subheader("🎬 Video")
        st.video(vid["url"], start_time=int(offset))

        st.subheader("⭐ New Bookmark")
        ts_key = f"bmt_{vid_id}"
        default_ts = st.session_state.get(ts_key, 0)
        t = st.number_input("Time (sec)", value=float(default_ts), step=1)
        note = st.text_input("Note")

        if st.button("Add ⭐ Bookmark"):
            with conn:
                conn.execute(
                    "INSERT INTO moments(match_id,video_id,video_ts,note) VALUES(?,?,?,?)",
                    (match_id, vid_id, float(t), note.strip())
                )
            st.session_state[ts_key] = float(t)
            st.success("Bookmark saved!")
            st.rerun()

        bms = pd.read_sql(
            "SELECT video_ts,note FROM moments WHERE match_id=? AND video_id=? ORDER BY video_ts",
            conn, params=(match_id,vid_id)
        )
        if not bms.empty:
            st.write("📎 Bookmarks")
            st.dataframe(bms, use_container_width=True)

    # ----- RIGHT: Live Tags -----
    with col2:
        st.subheader("🏉 Log Event")

        cur_player = st.selectbox(
            "Player",
            [p["id"] for p in players],
            format_func=lambda x: next(p["name"] for p in players if p["id"] == x)
        )

        for grp in sorted({m["group_name"] for m in metrics}):
            st.markdown(f"**{grp}**")
            cols = st.columns(3)
            for i, m in enumerate([m for m in metrics if m["group_name"]==grp]):
                if cols[i%3].button(m["label"]):
                    with conn:
                        conn.execute(
                            "INSERT INTO events(match_id,player_id,metric_id) VALUES(?,?,?)",
                            (match_id, cur_player, m["id"])
                        )
                    st.toast(f"{m['label']} logged!", icon="✅")

        st.divider()
        st.write("⏱ Recent Events")
        recent = pd.read_sql("""
            SELECT p.name AS player, m.label AS metric, e.ts
            FROM events e
            JOIN players p ON p.id=e.player_id
            JOIN metrics m ON m.id=e.metric_id
            WHERE match_id=?
            ORDER BY e.id DESC LIMIT 20
        """, conn, params=(match_id,))
        st.dataframe(recent, use_container_width=True)

# ---------------- Main App Router ----------------
import bcrypt

def page_users(conn, role):
    st.header("👤 User Management")

    if role != "admin":
        st.info("Admin only.")
        return

    st.subheader("Add New User")
    c1, c2 = st.columns(2)
    new_user = c1.text_input("Username")
    new_pass = c2.text_input("Password", type="password")
    new_role = st.selectbox("Role", ["admin", "editor", "viewer"])

    if st.button("Create User"):
        if not new_user or not new_pass:
            st.error("Enter username and password")
        else:
            ph = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt())
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
                        (new_user, ph, new_role)
                    )
                st.success(f"User {new_user} created")
                st.rerun()
            except:
                st.error("Username already exists")

    st.divider()
    st.subheader("Manage Users")

    df = pd.read_sql("SELECT username, role, active FROM users", conn)
    st.dataframe(df, use_container_width=True)

    sel = st.selectbox("Select user", df["username"].tolist())
    new_role2 = st.selectbox("Change role", ["admin","editor","viewer"])
    new_active = st.checkbox("Active", value=bool(df.set_index("username").loc[sel,"active"]))
    reset_pass = st.text_input("Reset Password", type="password")

    if st.button("Save Changes"):
        with conn:
            conn.execute("UPDATE users SET role=?, active=? WHERE username=?",
                         (new_role2, int(new_active), sel))
            if reset_pass.strip():
                ph = bcrypt.hashpw(reset_pass.encode(), bcrypt.gensalt())
                conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, sel))
        st.success("Updated ✅")
        st.rerun()

def page_players(conn, role):
    st.header("👥 Players")

    df = pd.read_sql("SELECT id,name,position,active FROM players ORDER BY name", conn)
    st.dataframe(df, use_container_width=True)

    if role not in ("admin","editor"):
        st.info("Read-only mode")
        return

    st.subheader("➕ Add Player")
    c1,c2 = st.columns([2,1])
    name = c1.text_input("Player Name")
    pos  = c2.text_input("Position")

    if st.button("Add Player"):
        if not name.strip():
            st.error("Enter a player name")
        else:
            with conn:
                conn.execute(
                    "INSERT INTO players(name,position,active) VALUES(?,?,1)",
                    (name.strip(), pos.strip())
                )
            st.success("Player added ✅")
            st.rerun()

    st.divider()
    st.subheader("✏️ Edit Players")

    if df.empty:
        st.info("No players yet")
        return

    pid = st.selectbox("Select Player", df["id"].tolist(), format_func=lambda x: df[df["id"]==x]["name"].iloc[0])
    rec = df[df["id"]==pid].iloc[0]

    new_name = st.text_input("Name", value=rec["name"])
    new_pos  = st.text_input("Position", value=rec["position"])
    active   = st.checkbox("Active", value=bool(rec["active"]))

    c1, c2 = st.columns(2)
    if c1.button("Save Changes"):
        with conn:
            conn.execute(
                "UPDATE players SET name=?, position=?, active=? WHERE id=?",
                (new_name.strip(), new_pos.strip(), int(active), pid)
            )
        st.success("Saved ✅")
        st.rerun()

    if c2.button("Delete Player ❌"):
        with conn:
            conn.execute("DELETE FROM players WHERE id=?", (pid,))
        st.warning("Player deleted")
        st.rerun()

def page_metrics(conn, role):
    st.header("📊 Metrics")

    df = pd.read_sql("SELECT id,label,group_name,per80,weight,active FROM metrics ORDER BY group_name,label", conn)
    st.dataframe(df, use_container_width=True)

    if role != "admin":
        st.info("Admin only")
        return

    st.subheader("➕ Add Metric")
    key = st.text_input("Metric Key (snake_case)", placeholder="dominant_tackles")
    label = st.text_input("Display Label", placeholder="Dominant Tackles")
    grp = st.selectbox("Group", ["Attack","Defense","Kicking","Discipline","Scoring","Other"])
    per80 = st.checkbox("Include in per-80 stats", value=True)
    weight = st.number_input("Weight (leaderboard)", value=0.0, step=0.5)

    if st.button("Add Metric"):
        if not key or not label:
            st.error("Key & Label required")
        else:
            with conn:
                conn.execute(
                    "INSERT INTO metrics(name,label,group_name,type,per80,weight,active) VALUES(?,?,?,?,?,?,1)",
                    (key.strip(), label.strip(), grp, "count", int(per80), float(weight))
                )
            st.success("Metric added ✅")
            st.rerun()

    st.divider()
    st.subheader("✏️ Edit Metrics")

    if df.empty:
        st.info("No metrics yet")
        return

    mid = st.selectbox("Select Metric", df["id"].tolist(), format_func=lambda x: df[df["id"]==x]["label"].iloc[0])
    rec = df[df["id"]==mid].iloc[0]

    new_label = st.text_input("Label", value=rec["label"])
    new_grp   = st.selectbox("Group", ["Attack","Defense","Kicking","Discipline","Scoring","Other"], index=["Attack","Defense","Kicking","Discipline","Scoring","Other"].index(rec["group_name"]))
    new_per80 = st.checkbox("Per-80", value=bool(rec["per80"]))
    new_active= st.checkbox("Active", value=bool(rec["active"]))
    new_weight= st.number_input("Weight", value=float(rec["weight"] or 0.0), step=0.5)

    if st.button("Save Metric"):
        with conn:
            conn.execute(
                "UPDATE metrics SET label=?, group_name=?, per80=?, active=?, weight=? WHERE id=?",
                (new_label.strip(), new_grp, int(new_per80), int(new_active), float(new_weight), mid)
            )
        st.success("Saved ✅")
        st.rerun()

def main(conn, role):
    init_db(conn)
    init_user_table(conn)


    tabs = st.tabs(["🛠 My Account","👤 Users","👥 Players","📊 Metrics","🎥 Tagging","📈 Reports"])

    with tabs[0]:
    st.header("🛠 My Account")

    st.subheader("Change Password")
    current_pw = st.text_input("Current Password", type="password")
    new_pw = st.text_input("New Password", type="password")
    confirm_pw = st.text_input("Confirm New Password", type="password")

    if st.button("Update Password"):
        user = st.session_state.user["username"]
        row = conn.execute("SELECT password_hash FROM users WHERE username=?", (user,)).fetchone()

        if not row:
            st.error("User not found.")
        else:
            stored_hash = row["password_hash"]

            if not bcrypt.checkpw(current_pw.encode(), stored_hash.encode()):
                st.error("❌ Current password incorrect.")
            elif new_pw != confirm_pw:
                st.error("❌ New passwords don't match.")
            elif len(new_pw) < 6:
                st.error("⚠️ New password must be at least 6 characters.")
            else:
                new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                conn.execute("UPDATE users SET password_hash=? WHERE username=?", (new_hash, user))
                conn.commit()
                st.success("✅ Password updated successfully!")
                st.toast("Password changed 🚀", icon="🔐")

    with tabs[1]:
    if role != "admin":
        st.error("Admins only")
    else:
        st.header("👤 User Management")

        # List users
        users = pd.read_sql("SELECT username, role, active FROM users", conn)
        st.dataframe(users, use_container_width=True)

        st.subheader("➕ Add User")
        nu = st.text_input("Username")
        npw = st.text_input("Password", type="password")
        nrole = st.selectbox("Role", ["admin","editor","viewer"])
        if st.button("Create user"):
            if nu.strip() and npw.strip():
                try:
                    create_user(conn, nu.strip(), npw, nrole)
                    st.success(f"User {nu} created")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        st.subheader("🔁 Reset Password")
        ru = st.text_input("User to reset")
        rpw = st.text_input("New password", type="password")
        if st.button("Reset password"):
            try:
                reset_password(conn, ru.strip(), rpw)
                st.success(f"Password reset for {ru}")
            except:
                st.error("User not found")

        st.subheader("🚫 Deactivate User")
        du = st.text_input("User to deactivate")
        if st.button("Deactivate"):
            conn.execute("UPDATE users SET active=0 WHERE username=?", (du.strip(),))
            conn.commit()
            st.success(f"User {du} deactivated")

    with tabs[2]:
        st.write("Metrics settings coming soon")

    with tabs[3]:
        page_tagging(conn, role)

    with tabs[4]:
        st.write("Reports coming soon")
