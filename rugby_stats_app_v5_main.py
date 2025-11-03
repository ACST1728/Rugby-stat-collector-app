#!/usr/bin/env python3
import sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import altair as alt

# ---------------- DB Helpers ----------------
def init_db(conn):
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT, position TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY, name TEXT UNIQUE, label TEXT, group_name TEXT, type TEXT DEFAULT 'count', per80 INTEGER DEFAULT 1, weight REAL, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY, opponent TEXT, date TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, match_id INTEGER, player_id INTEGER, metric_id INTEGER, value REAL DEFAULT 1, ts TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY, match_id INTEGER, kind TEXT, url TEXT, label TEXT, offset REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS moments(id INTEGER PRIMARY KEY, match_id INTEGER, video_id INTEGER, video_ts REAL, note TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP);
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
def main(conn, role):
    init_db(conn)
    tabs = st.tabs(["⚙️ Setup","📊 Reports","🎥 Tagging"])

    with tabs[0]:
        st.write("Setup pages coming soon (Players, Metrics, Users)")

    with tabs[1]:
        st.write("Reports coming soon")

    with tabs[2]:
        page_tagging(conn, role)
