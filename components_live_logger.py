import streamlit as st
import pandas as pd
import sqlite3

def live_logger(conn, match_id, player_list, metrics):
    st.write("### 🏷️ Live Event Log")

    event_player = st.selectbox("Player", player_list)
    event_metric = st.selectbox("Metric", [m["label"] for m in metrics])

    if st.button("Add Event"):
        m_id = next(m["id"] for m in metrics if m["label"] == event_metric)
        p_id = next(p["id"] for p in player_list if p["name"] == event_player)
        conn.execute("INSERT INTO events(match_id, player_id, metric_id) VALUES(?,?,?)",
                     (match_id, p_id, m_id))
        conn.commit()
        st.success("✅ Event logged")

    st.write("#### Recent Events")
    df = pd.read_sql("SELECT * FROM events WHERE match_id=? ORDER BY id DESC LIMIT 20",
                     conn, params=(match_id,))
    st.dataframe(df)
