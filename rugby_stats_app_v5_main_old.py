# Legacy components we still use (video review + DB init)

import sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import altair as alt

# ========= INIT DB (copied from old file) =========
def init_db(conn: sqlite3.Connection) -> None:
    SCHEMA = """
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS players(
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      position TEXT,
      active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS metrics(
      id INTEGER PRIMARY KEY,
      name TEXT UNIQUE NOT NULL,
      label TEXT NOT NULL,
      group_name TEXT NOT NULL,
      type TEXT NOT NULL DEFAULT 'count',
      per80 INTEGER NOT NULL DEFAULT 1,
      weight REAL,
      active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS matches(
      id INTEGER PRIMARY KEY,
      opponent TEXT NOT NULL,
      date TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY,
      match_id INTEGER NOT NULL,
      player_id INTEGER NOT NULL,
      metric_id INTEGER NOT NULL,
      value REAL NOT NULL DEFAULT 1,
      ts TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS videos(
      id INTEGER PRIMARY KEY,
      match_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      url TEXT NOT NULL,
      label TEXT NOT NULL,
      offset REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS moments(
      id INTEGER PRIMARY KEY,
      match_id INTEGER NOT NULL,
      video_id INTEGER NOT NULL,
      video_ts REAL NOT NULL,
      note TEXT DEFAULT '',
      ts TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """
    with conn: conn.executescript(SCHEMA)


# ========= PAGE: VIDEO REVIEW =========
def page_video(conn, role):
    st.header("🎥 Video Review")

    matches = pd.read_sql("SELECT * FROM matches ORDER BY date DESC", conn)
    if matches.empty:
        st.info("No matches yet — create one in Live Logger.")
        return

    mid = st.selectbox(
        "Match",
        matches["id"].tolist(),
        format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} vs {matches.set_index('id').loc[x,'opponent']}"
    )

    # Videos
    vids = pd.read_sql("SELECT * FROM videos WHERE match_id=?", conn, params=(mid,))
    st.write("### Add Video")
    url = st.text_input("YouTube URL")
    label = st.text_input("Label")

    if st.button("Add Video"):
        with conn:
            conn.execute("INSERT INTO videos(match_id,kind,url,label,offset) VALUES(?,?,?,?,0)",
                         (mid, "youtube", url, label))
        st.success("Added video")
        st.rerun()

    if vids.empty:
        st.info("No videos for this match yet.")
        return

    vid = st.selectbox("Video", vids["id"].tolist(), format_func=lambda x: vids.set_index('id').loc[x,'label'])
    vrow = vids[vids["id"] == vid].iloc[0]
    
    st.video(vrow["url"])

    # Bookmarks
    st.write("### Bookmarks")
    ts = st.number_input("Time (sec)", step=1.0)
    note = st.text_input("Note")

    if st.button("Add Bookmark"):
        with conn:
            conn.execute("INSERT INTO moments(match_id,video_id,video_ts,note) VALUES(?,?,?,?)",
                         (mid, vid, ts, note))
        st.success("Added bookmark")
        st.rerun()

    bms = pd.read_sql(
        "SELECT * FROM moments WHERE match_id=? AND video_id=? ORDER BY video_ts",
        conn, params=(mid, vid)
    )
    st.dataframe(bms)
