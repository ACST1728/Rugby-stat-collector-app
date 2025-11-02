#!/usr/bin/env python3
import os, sqlite3, datetime as dt
from typing import Dict, Any, Optional, List, Tuple

import pandas as pd
import streamlit as st
import altair as alt

# --- Component import (tolerant to your repo layout) ---
try:
    # Preferred (your screenshot folder layout)
    from components.video_hotkeys.components_video_hotkeys import streamlit_video_component
except Exception:
    # Fallback if you kept an older root helper
    try:
        from components_video_hotkeys import streamlit_video_component  # type: ignore
    except Exception:
        streamlit_video_component = None  # Component not available


# =======================================================
#                     DATABASE SCHEMA
# =======================================================

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS players(
  id       INTEGER PRIMARY KEY,
  name     TEXT NOT NULL,
  position TEXT,
  active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS metrics(
  id         INTEGER PRIMARY KEY,
  name       TEXT UNIQUE NOT NULL,        -- snake_case key
  label      TEXT NOT NULL,               -- display label
  group_name TEXT NOT NULL,               -- Attack/Defense/...
  type       TEXT NOT NULL DEFAULT 'count',
  per80      INTEGER NOT NULL DEFAULT 1,  -- include in per-80 calc
  weight     REAL,                        -- leaderboard weight
  active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS matches(
  id       INTEGER PRIMARY KEY,
  opponent TEXT NOT NULL,
  date     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events(
  id        INTEGER PRIMARY KEY,
  match_id  INTEGER NOT NULL,
  player_id INTEGER NOT NULL,
  metric_id INTEGER NOT NULL,
  value     REAL NOT NULL DEFAULT 1,
  ts        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS videos(
  id       INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  kind     TEXT NOT NULL,          -- 'url'
  url      TEXT NOT NULL,
  label    TEXT NOT NULL,
  offset   REAL NOT NULL DEFAULT 0  -- seconds
);

CREATE TABLE IF NOT EXISTS moments(
  id        INTEGER PRIMARY KEY,
  match_id  INTEGER NOT NULL,
  video_id  INTEGER NOT NULL,
  video_ts  REAL NOT NULL,
  note      TEXT DEFAULT '',
  ts        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hotkeys(
  key       TEXT PRIMARY KEY,       -- e.g. 'KeyW'
  metric_id INTEGER NOT NULL
);
"""

DEFAULT_METRICS: List[Tuple[str,str,str,float]] = [
    ("carries_made","Carries Made","Attack", 1.0),
    ("tackles_made","Tackles Made","Defense", 1.0),
    ("tackles_missed","Tackles Missed","Defense", -1.0),
    ("turnovers_won","Turnovers Won","Defense", 4.0),
    ("turnovers_conceded","Turnovers Conceded","Discipline", -2.0),
    ("line_breaks","Line Breaks","Attack", 3.0),
    ("offloads","Offloads","Attack", 1.0),
    ("handling_errors","Handling Errors","Attack", -1.0),
    ("kick_gain","Kick w/ Territory Gain","Kicking", 1.0),
    ("kick_no_gain","Kick w/o Territory Gain","Kicking", 0.0),
    ("tries","Tries","Scoring", 5.0),
    ("conversions","Conversions","Scoring", 2.0),
    ("penalties","Penalties Scored","Scoring", 3.0),
    ("drop_goals","Drop Goals","Scoring", 4.0),
    ("assists","Assists","Attack", 2.0),
    ("penalties_conceded","Penalties Conceded","Discipline", -2.0),
]


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables + seed default metrics + normalise weights."""
    with conn:
        conn.executescript(SCHEMA)

        # Seed metrics first time
        n = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        if n == 0:
            for key, label, grp, w in DEFAULT_METRICS:
                conn.execute(
                    "INSERT OR IGNORE INTO metrics(name,label,group_name,per80,weight,active) VALUES(?,?,?,?,?,1)",
                    (key, label, grp, 1, float(w)),
                )
        # Ensure weights not null
        conn.execute("UPDATE metrics SET weight=COALESCE(weight,0.0)")


# =======================================================
#                     HELPERS
# =======================================================

def _metric_id_by_label(conn: sqlite3.Connection, label: str) -> Optional[int]:
    r = conn.execute("SELECT id FROM metrics WHERE label=?", (label,)).fetchone()
    return int(r[0]) if r else None


def _players_df(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, name, position, active FROM players ORDER BY name",
        conn,
    )


def _metrics_df(conn: sqlite3.Connection, only_active: bool = False) -> pd.DataFrame:
    q = "SELECT id,name,label,group_name,type,per80,weight,active FROM metrics"
    if only_active:
        q += " WHERE active=1"
    q += " ORDER BY group_name, label"
    return pd.read_sql_query(q, conn)


def _matches_df(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, opponent, date FROM matches ORDER BY date DESC, id DESC",
        conn,
    )


# =======================================================
#                     PAGES
# =======================================================

def page_players(conn: sqlite3.Connection, role: str) -> None:
    st.header("👥 Players")

    df = _players_df(conn)
    st.dataframe(df, use_container_width=True)

    if role in ("admin", "editor"):
        with st.expander("➕ Add Player"):
            c1, c2 = st.columns([2, 1])
            name = c1.text_input("Name", key="add_player_name")
            pos = c2.text_input("Position", key="add_player_pos")
            if st.button("Add Player", key="add_player_btn"):
                if not name.strip():
                    st.error("Please enter a player name.")
                else:
                    with conn:
                        conn.execute(
                            "INSERT INTO players(name,position,active) VALUES(?,?,1)",
                            (name.strip(), pos.strip()),
                        )
                    st.success("Player added.")
                    st.rerun()

        with st.expander("✏️ Edit / Deactivate"):
            if df.empty:
                st.info("No players yet.")
            else:
                pid = st.selectbox(
                    "Select player",
                    df["id"].tolist(),
                    format_func=lambda x: df.loc[df["id"] == x, "name"].iloc[0],
                    key="edit_player_select",
                )
                rec = df[df["id"] == pid].iloc[0]
                c1, c2, c3 = st.columns([2, 1, 1])
                new_name = c1.text_input("Name", value=rec["name"], key=f"edit_name_{pid}")
                new_pos = c2.text_input("Position", value=rec["position"] or "", key=f"edit_pos_{pid}")
                new_active = c3.checkbox("Active", value=bool(rec["active"]), key=f"edit_active_{pid}")
                if st.button("Save Changes", key=f"save_player_{pid}"):
                    with conn:
                        conn.execute(
                            "UPDATE players SET name=?, position=?, active=? WHERE id=?",
                            (new_name.strip(), new_pos.strip(), int(new_active), int(pid)),
                        )
                    st.success("Saved.")
                    st.rerun()

        with st.expander("🗑 Delete Player (danger)"):
            if df.empty:
                st.info("No players to delete.")
            else:
                del_id = st.selectbox(
                    "Player to delete",
                    df["id"].tolist(),
                    format_func=lambda x: df.loc[df["id"] == x, "name"].iloc[0],
                    key="del_player_select",
                )
                if st.button("Delete Permanently", key="del_player_btn", type="primary"):
                    with conn:
                        conn.execute("DELETE FROM players WHERE id=?", (int(del_id),))
                    st.warning("Player deleted.")
                    st.rerun()
    else:
        st.info("Read-only. Log in as admin/editor to manage players.")


def page_metrics(conn: sqlite3.Connection, role: str) -> None:
    st.header("📊 Metrics (custom + per-80 + weights)")
    mdf = _metrics_df(conn)
    st.dataframe(mdf, use_container_width=True)

    if role != "admin":
        st.info("Admin only for creating and editing metrics.")
        return

    with st.expander("➕ Add Metric"):
        c1, c2 = st.columns([1.3, 1])
        key = c1.text_input("Key (snake_case)", placeholder="dominant_tackles", key="add_metric_key")
        label = c2.text_input("Label", placeholder="Dominant Tackles", key="add_metric_label")
        c3, c4, c5 = st.columns([1.2, 0.8, 1])
        grp = c3.selectbox("Group", ["Attack", "Defense", "Kicking", "Discipline", "Scoring", "Other"], key="add_metric_group")
        per80 = c4.checkbox("Include in per-80", value=True, key="add_metric_per80")
        weight = c5.number_input("Leaderboard Weight", value=0.0, step=0.5, key="add_metric_weight")

        if st.button("Create Metric", key="add_metric_btn"):
            if not key.strip() or not label.strip():
                st.error("Key and Label are required.")
            else:
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO metrics(name,label,group_name,type,per80,weight,active) VALUES(?,?,?,?,?,?,1)",
                            (key.strip(), label.strip(), grp, "count", int(per80), float(weight)),
                        )
                    st.success("Metric added.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Key must be unique.")

    with st.expander("✏️ Edit / Toggle Active / Weights"):
        if mdf.empty:
            st.info("No metrics yet.")
        else:
            mid = st.selectbox(
                "Select metric",
                mdf["id"].tolist(),
                format_func=lambda x: mdf.loc[mdf["id"] == x, "label"].iloc[0],
                key="edit_metric_select",
            )
            rec = mdf[mdf["id"] == mid].iloc[0]
            c1, c2, c3, c4, c5 = st.columns([1.4, 1, 0.8, 0.8, 1])
            new_label = c1.text_input("Label", value=rec["label"], key=f"metric_label_{mid}")
            new_grp = c2.selectbox(
                "Group",
                ["Attack", "Defense", "Kicking", "Discipline", "Scoring", "Other"],
                index=["Attack", "Defense", "Kicking", "Discipline", "Scoring", "Other"].index(rec["group_name"]),
                key=f"metric_group_{mid}",
            )
            new_per80 = c3.checkbox("Per-80", value=bool(rec["per80"]), key=f"metric_per80_{mid}")
            new_active = c4.checkbox("Active", value=bool(rec["active"]), key=f"metric_active_{mid}")
            base_w = float(rec["weight"]) if pd.notna(rec["weight"]) else 0.0
            new_weight = c5.number_input("Weight", value=base_w, step=0.5, key=f"metric_weight_{mid}")

            if st.button("Save Metric Changes", key=f"save_metric_{mid}"):
                with conn:
                    conn.execute(
                        "UPDATE metrics SET label=?, group_name=?, per80=?, active=?, weight=? WHERE id=?",
                        (new_label.strip(), new_grp, int(new_per80), int(new_active), float(new_weight), int(mid)),
                    )
                st.success("Saved.")
                st.rerun()


def page_hotkeys(conn: sqlite3.Connection, role: str) -> None:
    if role != "admin":
        st.header("⌨️ Hotkeys")
        st.info("Admin only.")
        return

    st.header("⌨️ Hotkeys (WASD preset & custom)")

    mdf = _metrics_df(conn, only_active=True)
    if mdf.empty:
        st.info("No active metrics yet.")
        return

    # Show current mapping
    hmap = pd.read_sql_query(
        "SELECT h.key, m.label, m.group_name FROM hotkeys h JOIN metrics m ON m.id=h.metric_id ORDER BY h.key",
        conn,
    )
    st.subheader("Current Mapping")
    st.dataframe(hmap, use_container_width=True)

    ALL_KEYS = [f"Key{c}" for c in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")] + [f"Digit{d}" for d in "0123456789"]
    c1, c2 = st.columns([1, 2])
    key_choice = c1.selectbox("Key", ALL_KEYS, key="hk_key")
    metric_choice = c2.selectbox(
        "Metric",
        options=mdf["id"].tolist(),
        format_func=lambda x: f"{mdf.loc[mdf['id']==x,'label'].iloc[0]} ({mdf.loc[mdf['id']==x,'group_name'].iloc[0]})",
        key="hk_metric",
    )

    if st.button("Save Mapping", key="hk_save"):
        with conn:
            conn.execute("INSERT OR REPLACE INTO hotkeys(key, metric_id) VALUES(?,?)", (key_choice, int(metric_choice)))
        st.success("Saved.")
        st.rerun()

    if st.button("Load WASD Preset", key="hk_wasd"):
        preset = {
            "KeyW": "Tackles Made",
            "KeyS": "Tackles Missed",
            "KeyA": "Carries Made",
            "KeyD": "Offloads",
            "KeyQ": "Line Breaks",
            "KeyE": "Assists",
            "KeyR": "Tries",
            "KeyF": "Turnovers Won",
            "KeyG": "Turnovers Conceded",
            "KeyV": "Handling Errors",
            "KeyX": "Kick w/ Territory Gain",
            "KeyC": "Kick w/o Territory Gain",
            "KeyZ": "Penalties Conceded",
        }
        for k, label in preset.items():
            mid = _metric_id_by_label(conn, label)
            if mid:
                with conn:
                    conn.execute("INSERT OR REPLACE INTO hotkeys(key, metric_id) VALUES(?,?)", (k, int(mid)))
        st.success("WASD preset loaded.")
        st.rerun()

    if st.button("Clear All Hotkeys", key="hk_clear"):
        with conn:
            conn.execute("DELETE FROM hotkeys")
        st.warning("Cleared all hotkeys.")
        st.rerun()


def page_logger(conn: sqlite3.Connection, role: str) -> None:
    st.header("📝 Live Logger (Event → Player)")

    # Create / select match
    with st.expander("Match Setup", expanded=True):
        c1, c2, c3 = st.columns([1.2, 1, 1])
        opponent = c1.text_input("Opponent", key="lg_opp")
        date = c2.date_input("Date", value=dt.date.today(), key="lg_date")
        if c3.button("Create/Use Match", key="lg_make"):
            if not opponent.strip():
                st.error("Enter opponent.")
            else:
                row = conn.execute(
                    "SELECT id FROM matches WHERE opponent=? AND date=?",
                    (opponent.strip(), str(date)),
                ).fetchone()
                if row:
                    mid = int(row["id"])
                else:
                    with conn:
                        conn.execute("INSERT INTO matches(opponent, date) VALUES(?,?)", (opponent.strip(), str(date)))
                        mid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                st.session_state["match_id"] = mid
                st.success(f"Match loaded: {opponent} — {date}")
                st.rerun()

    mid = st.session_state.get("match_id")
    if not mid:
        st.info("Create or select a match first.")
        return

    # Current player
    players = _players_df(conn)
    if players.empty:
        st.warning("Add players first.")
        return

    current_player = st.selectbox(
        "Current Player",
        players["id"].tolist(),
        format_func=lambda x: players.set_index("id")["name"].to_dict().get(x, "?"),
        key="lg_player",
    )

    # Metrics grouped
    metrics = _metrics_df(conn, only_active=True)
    for grp in metrics["group_name"].unique():
        st.subheader(grp)
        cols = st.columns(4)
        subset = metrics[metrics["group_name"] == grp]
        for i, (_, row) in enumerate(subset.iterrows()):
            if cols[i % 4].button(row["label"], key=f"lg_btn_{int(row['id'])}"):
                with conn:
                    conn.execute(
                        "INSERT INTO events(match_id,player_id,metric_id,value) VALUES(?,?,?,1)",
                        (int(mid), int(current_player), int(row["id"])),
                    )
                st.toast(f"{row['label']} — logged for {players.set_index('id')['name'][int(current_player)]}", icon="✅")

    st.divider()
    st.subheader("Recent (this match)")
    recent = pd.read_sql_query(
        """
        SELECT e.id, p.name as player, m.label as metric, e.ts
        FROM events e
        JOIN players p ON p.id=e.player_id
        JOIN metrics m ON m.id=e.metric_id
        WHERE e.match_id=?
        ORDER BY e.id DESC LIMIT 30
        """,
        conn,
        params=(int(mid),),
    )
    if not recent.empty:
        st.dataframe(recent, use_container_width=True)


def page_reports(conn: sqlite3.Connection, role: str) -> None:
    st.header("📈 Reports & Leaderboard")

    df = pd.read_sql_query(
        """
        SELECT p.name AS player, m.label AS metric, SUM(e.value) AS total
        FROM events e
        JOIN players p ON p.id=e.player_id
        JOIN metrics m ON m.id=e.metric_id
        GROUP BY p.id, m.id
        ORDER BY p.name, m.label
        """,
        conn,
    )

    if df.empty:
        st.info("No events recorded yet.")
        return

    totals = df.pivot(index="player", columns="metric", values="total").fillna(0).astype(int)
    st.subheader("Totals")
    st.dataframe(totals, use_container_width=True)

    # Per-80 for metrics with per80=1
    per80_list = pd.read_sql_query("SELECT label FROM metrics WHERE per80=1 AND active=1", conn)["label"].tolist()
    if per80_list:
        minutes_df = pd.read_sql_query(
            """
            SELECT p.name AS player, COALESCE(SUM(e.value),0) AS minutes
            FROM events e
            JOIN players p ON p.id=e.player_id
            JOIN metrics m ON m.id=e.metric_id
            WHERE m.name='minutes' -- optional; if not present we'll fallback to count matches*80
            GROUP BY p.id
            """,
            conn,
        )
        # If no minutes metric exists, approximate per-player minutes by #matches * 80
        if minutes_df.empty:
            approx = pd.read_sql_query(
                """
                SELECT p.name AS player, COUNT(DISTINCT e.match_id)*80.0 AS minutes
                FROM events e
                JOIN players p ON p.id=e.player_id
                GROUP BY p.id
                """,
                conn,
            )
            minutes_df = approx

        mins = minutes_df.set_index("player")["minutes"]
        per80 = pd.DataFrame(index=totals.index)
        for col in totals.columns:
            if col in per80_list:
                per80[col] = (totals[col] / mins.replace(0, pd.NA)) * 80.0
        per80 = per80.replace([pd.NA, pd.NaT], 0).fillna(0)
        st.subheader("Per-80 (for flagged metrics)")
        st.dataframe(per80.round(2), use_container_width=True)

    # Weighted leaderboard
    w = pd.read_sql_query("SELECT label, COALESCE(weight,0) AS weight FROM metrics WHERE active=1", conn)
    weights = dict(zip(w["label"], w["weight"]))
    w_series = pd.Series({col: float(weights.get(col, 0.0)) for col in totals.columns})
    score_df = totals.mul(w_series, axis=1)
    score_df["Score"] = score_df.sum(axis=1)
    st.subheader("Leaderboard (Weighted)")
    st.dataframe(score_df[["Score"]].sort_values("Score", ascending=False), use_container_width=True)

    # Small chart example
    st.subheader("Chart: Top 10 by Score")
    chart_df = score_df[["Score"]].sort_values("Score", ascending=False).head(10).reset_index(names="player")
    c = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(x="Score:Q", y=alt.Y("player:N", sort="-x"))
        .properties(height=350)
    )
    st.altair_chart(c, use_container_width=True)


def page_video(conn: sqlite3.Connection, role: str) -> None:
    st.header("🎥 Video Review / Bookmarks / Speed")

    if streamlit_video_component is None:
        st.warning("Video component not found. Make sure `components/video_hotkeys/index.html` and the helper module exist.")
        return

    matches = _matches_df(conn)
    if matches.empty:
        st.info("Create or load a match in the Logger first.")
        return

    opts = [(int(r["id"]), f"{r['date']} — {r['opponent']}") for _, r in matches.iterrows()]
    mid = st.selectbox("Match", [o[0] for o in opts], format_func=dict(opts).get, key="vid_match")

    # Manage video list for this match
    vids = pd.read_sql_query(
        "SELECT id, label, kind, url, offset FROM videos WHERE match_id=? ORDER BY id",
        conn,
        params=(int(mid),),
    )

    with st.expander("➕ Add video (Paste URL)"):
        lbl = st.text_input("Label", value="Main Feed", key="vid_add_label")
        url = st.text_input("Video URL (MP4/MOV/streamable link)", key="vid_add_url")
        if st.button("Add URL", key="vid_add_btn"):
            if not url.strip():
                st.error("Paste a URL.")
            else:
                with conn:
                    conn.execute(
                        "INSERT INTO videos(match_id,kind,url,label,offset) VALUES(?,?,?,?,0)",
                        (int(mid), "url", url.strip(), lbl.strip()),
                    )
                st.success("Video added.")
                st.rerun()

    if vids.empty:
        st.info("No videos for this match yet.")
        return

    vopts = [(int(r["id"]), f"{r['label']} ({r['kind']})") for _, r in vids.iterrows()]
    vid = st.selectbox("Active video", [o[0] for o in vopts], format_func=dict(vopts).get, key="vid_active")

    vrow = conn.execute("SELECT id, url, offset FROM videos WHERE id=?", (int(vid),)).fetchone()
    off = st.number_input("Offset (sec)", value=float(vrow["offset"] or 0.0), step=1.0, key=f"vid_off_{vid}")
    if st.button("Save offset", key=f"vid_off_save_{vid}"):
        with conn:
            conn.execute("UPDATE videos SET offset=? WHERE id=?", (float(off), int(vid)))
        st.success("Saved.")
        st.rerun()

    # Player (component) + bookmarks
    st.subheader("Player")
    # The component returns a dict when user presses Space (bookmark)
    payload = streamlit_video_component(video_url=vrow["url"], start_time=float(off))

    if payload:
        # Expecting {'type':'bookmark','t': <seconds>} from the component JS
        t = float(payload.get("t") or 0.0)
        if payload.get("type") == "bookmark":
            note_default_key = "vid_note_default"
            st.session_state.setdefault(note_default_key, "")
            note = st.session_state.get(note_default_key, "")
            with conn:
                conn.execute(
                    "INSERT INTO moments(match_id, video_id, video_ts, note) VALUES(?,?,?,?)",
                    (int(mid), int(vid), t, note),
                )
            st.toast(f"⭐ Bookmark saved @ {int(t)}s")

    st.subheader("Bookmarks")
    st.session_state.setdefault("vid_note_default", "")
    st.session_state["vid_note_default"] = st.text_input("Default note for next bookmark", value=st.session_state["vid_note_default"], key="vid_note_box")

    bms = pd.read_sql_query(
        "SELECT id, video_ts, note FROM moments WHERE match_id=? AND video_id=? ORDER BY video_ts",
        conn,
        params=(int(mid), int(vid)),
    )
    if bms.empty:
        st.caption("Press Space while playing to add a bookmark.")
    else:
        for _, row in bms.iterrows():
            c1, c2, c3, c4 = st.columns([1, 5, 1, 1])
            tsec = float(row["video_ts"])
            with c1:
                st.write(f"{int(tsec//60):02d}:{int(tsec%60):02d}")
            with c2:
                new_note = st.text_input("Note", value=row["note"], key=f"bm_note_{int(row['id'])}")
            with c3:
                if st.button("Save", key=f"bm_save_{int(row['id'])}"):
                    with conn:
                        conn.execute("UPDATE moments SET note=? WHERE id=?", (new_note, int(row["id"])))
                    st.success("Saved")
            with c4:
                if st.button("Delete", key=f"bm_del_{int(row['id'])}"):
                    with conn:
                        conn.execute("DELETE FROM moments WHERE id=?", (int(row["id"]),))
                    st.warning("Deleted")
                    st.rerun()


# =======================================================
#                     MASTER ROUTER
# =======================================================

def main(conn: sqlite3.Connection, role: str) -> None:
    """Entry point called by streamlit_app.py"""
    init_db(conn)

    tabs = st.tabs(["Players", "Metrics", "Hotkeys", "Live Logger", "Reports", "Video Review"])

    with tabs[0]:
        page_players(conn, role)

    with tabs[1]:
        page_metrics(conn, role)

    with tabs[2]:
        page_hotkeys(conn, role)

    with tabs[3]:
        page_logger(conn, role)

    with tabs[4]:
        page_reports(conn, role)

    with tabs[5]:
        page_video(conn, role)
