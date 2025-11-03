import streamlit as st
import pandas as pd

def live_logger(conn, match_id, players, metrics):
    st.subheader("🏷️ Live Event Tagging")

    player_names = [p["name"] for p in players]
    metric_labels = [m["label"] for m in metrics]

    event_player = st.selectbox("Player", player_names, key="live_player")
    event_metric = st.selectbox("Metric", metric_labels, key="live_metric")

    if st.button("Add Event", use_container_width=True, key="live_add"):
        m_id = next(m["id"] for m in metrics if m["label"] == event_metric)
        p_id = next(p["id"] for p in players if p["name"] == event_player)

        conn.execute(
            "INSERT INTO events(match_id, player_id, metric_id) VALUES(?,?,?)",
            (match_id, p_id, m_id)
        )
        conn.commit()
        st.success(f"✅ {event_player} • {event_metric}")

    st.markdown("### 📋 Recent Events")

    df = pd.read_sql(
        "SELECT e.id, p.name player, m.label metric, e.ts "
        "FROM events e JOIN players p ON p.id=e.player_id "
        "JOIN metrics m ON m.id=e.metric_id "
        "WHERE match_id=? ORDER BY e.id DESC LIMIT 20",
        conn, params=(match_id,)
    )
    st.dataframe(df, use_container_width=True)
