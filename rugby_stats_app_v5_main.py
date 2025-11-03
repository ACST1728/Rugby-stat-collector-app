#!/usr/bin/env python3
import sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import altair as alt

from components_live_logger import live_logger

# ✅ DB Helpers from your prior file
def _players_df(conn): 
    return pd.read_sql_query("SELECT id,name,position,active FROM players ORDER BY name", conn)

def _metrics_df(conn, only_active=False):
    q = "SELECT id,name,label,group_name,type,per80,weight,active FROM metrics"
    if only_active: q += " WHERE active=1"
    q += " ORDER BY group_name,label"
    return pd.read_sql_query(q, conn)

def _matches_df(conn):
    return pd.read_sql_query("SELECT id,opponent,date FROM matches ORDER BY date DESC,id DESC", conn)

# ✅ Re-use your video screen (we keep full functionality)
from rugby_stats_app_v5_main_old import page_video, init_db  # ↩️ assumes backup file exists

def main(conn: sqlite3.Connection, role: str):
    st.title("🎥 Video + Live Match Tagging")

    init_db(conn)

    matches = _matches_df(conn)
    if matches.empty:
        st.warning("⚠️ Create a match first in Live Logger")
        return

    match_id = st.selectbox(
        "Select Match",
        matches["id"].tolist(),
        format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} — {matches.set_index('id').loc[x,'opponent']}"
    )

    players = _players_df(conn).to_dict("records")
    metrics = _metrics_df(conn, only_active=True).to_dict("records")

    col1, col2 = st.columns([2.3, 1])

    with col1:
        st.subheader("Video & Bookmarks")
        page_video(conn, role)

    with col2:
        st.subheader("Live Stats Logging")
        live_logger(conn, match_id, players, metrics)

