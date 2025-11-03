#!/usr/bin/env python3
import os, sqlite3, datetime as dt
from typing import List, Tuple, Optional
import pandas as pd
import streamlit as st
import altair as alt

# --- Optional video component import ---
try:
    from components.video_hotkeys.components_video_hotkeys import streamlit_video_component
except Exception:
    try:
        from components_video_hotkeys import streamlit_video_component  # old location fallback
    except Exception:
        streamlit_video_component = None

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
  name       TEXT UNIQUE NOT NULL,
  label      TEXT NOT NULL,
  group_name TEXT NOT NULL,
  type       TEXT NOT NULL DEFAULT 'count',
  per80      INTEGER NOT NULL DEFAULT 1,
  weight     REAL,
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
  kind     TEXT NOT NULL,
  url      TEXT NOT NULL,
  label    TEXT NOT NULL,
  offset   REAL NOT NULL DEFAULT 0
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
  key       TEXT PRIMARY KEY,
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
    with conn:
        conn.executescript(SCHEMA)
        # seed metrics on first run
        if conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0:
            for key, label, grp, w in DEFAULT_METRICS:
                conn.execute(
                    "INSERT OR IGNORE INTO metrics(name,label,group_name,type,per80,weight,active) VALUES(?,?,?,?,?,?,1)",
                    (key, label, grp, "count", 1, float(w))
                )
        conn.execute("UPDATE metrics SET weight=COALESCE(weight,0.0)")

def _players_df(conn): 
    return pd.read_sql_query("SELECT id,name,position,active FROM players ORDER BY name", conn)

def _metrics_df(conn, only_active=False):
    q = "SELECT id,name,label,group_name,type,per80,weight,active FROM metrics"
    if only_active: q += " WHERE active=1"
    q += " ORDER BY group_name,label"
    return pd.read_sql_query(q, conn)

def _matches_df(conn):
    return pd.read_sql_query("SELECT id,opponent,date FROM matches ORDER BY date DESC,id DESC", conn)

def _metric_id_by_label(conn, label: str) -> Optional[int]:
    r = conn.execute("SELECT id FROM metrics WHERE label=?", (label,)).fetchone()
    return int(r[0]) if r else None

# -------- Players --------
def page_players(conn: sqlite3.Connection, role: str):
    st.header("👥 Players")
    df = _players_df(conn)
    st.dataframe(df, use_container_width=True)
    if role not in ("admin","editor"):
        st.info("Read-only. Admin/editor can add/edit players.")
        return

    with st.expander("➕ Add Player"):
        c1, c2 = st.columns([2,1])
        name = c1.text_input("Name", key="add_p_name")
        pos  = c2.text_input("Position", key="add_p_pos")
        if st.button("Add Player", key="add_p_btn"):
            if not name.strip(): st.error("Enter a name.")
            else:
                with conn:
                    conn.execute("INSERT INTO players(name,position,active) VALUES(?,?,1)", (name.strip(), pos.strip()))
                st.success("Player added.")
                st.rerun()

    with st.expander("✏️ Edit / Deactivate / Delete"):
        if df.empty: st.info("No players yet."); return
        pid = st.selectbox("Player", df["id"].tolist(),
                           format_func=lambda x: df.loc[df["id"]==x,"name"].iloc[0],
                           key="edit_p_sel")
        rec = df[df["id"]==pid].iloc[0]
        c1,c2,c3 = st.columns([2,1,1])
        new_name = c1.text_input("Name", value=rec["name"], key=f"p_name_{pid}")
        new_pos  = c2.text_input("Position", value=rec["position"] or "", key=f"p_pos_{pid}")
        new_act  = c3.checkbox("Active", value=bool(rec["active"]), key=f"p_act_{pid}")
        c4,c5 = st.columns([1,1])
        if c4.button("Save", key=f"p_save_{pid}"):
            with conn:
                conn.execute("UPDATE players SET name=?,position=?,active=? WHERE id=?",
                             (new_name.strip(), new_pos.strip(), int(new_act), int(pid)))
            st.success("Saved."); st.rerun()
        if c5.button("Delete (danger)", key=f"p_del_{pid}"):
            with conn:
                conn.execute("DELETE FROM players WHERE id=?", (int(pid),))
            st.warning("Deleted."); st.rerun()

# -------- Metrics --------
def page_metrics(conn: sqlite3.Connection, role: str):
    st.header("📊 Metrics (custom + per-80 + weights)")
    mdf = _metrics_df(conn)
    st.dataframe(mdf, use_container_width=True)

    if role != "admin":
        st.info("Admin only to create/edit metrics.")
        return

    with st.expander("➕ Add Metric"):
        c1,c2 = st.columns([1.3,1])
        key = c1.text_input("Key (snake_case)", placeholder="dominant_tackles", key="m_key")
        label = c2.text_input("Label", placeholder="Dominant Tackles", key="m_label")
        c3,c4,c5 = st.columns([1.2,0.8,1])
        grp = c3.selectbox("Group", ["Attack","Defense","Kicking","Discipline","Scoring","Other"], key="m_grp")
        per80 = c4.checkbox("Include in per-80", value=True, key="m_per80")
        weight = c5.number_input("Leaderboard weight", value=0.0, step=0.5, key="m_weight")
        if st.button("Create Metric", key="m_add_btn"):
            if not key.strip() or not label.strip():
                st.error("Key and Label required.")
            else:
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO metrics(name,label,group_name,type,per80,weight,active) VALUES(?,?,?,?,?,?,1)",
                            (key.strip(), label.strip(), grp, "count", int(per80), float(weight))
                        )
                    st.success("Metric added."); st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Key must be unique.")

    with st.expander("✏️ Edit / Toggle / Weights"):
        if mdf.empty: st.info("No metrics yet."); return
        mid = st.selectbox("Metric", mdf["id"].tolist(),
                           format_func=lambda x: mdf.loc[mdf["id"]==x,"label"].iloc[0],
                           key="m_edit_sel")
        rec = mdf[mdf["id"]==mid].iloc[0]
        c1,c2,c3,c4,c5 = st.columns([1.4,1,0.8,0.8,1])
        new_label = c1.text_input("Label", value=rec["label"], key=f"ml_{mid}")
        new_grp = c2.selectbox("Group",
                               ["Attack","Defense","Kicking","Discipline","Scoring","Other"],
                               index=["Attack","Defense","Kicking","Discipline","Scoring","Other"].index(rec["group_name"]),
                               key=f"mg_{mid}")
        new_per80 = c3.checkbox("Per-80", value=bool(rec["per80"]), key=f"mp_{mid}")
        new_active= c4.checkbox("Active", value=bool(rec["active"]), key=f"ma_{mid}")
        base_w = float(rec["weight"]) if pd.notna(rec["weight"]) else 0.0
        new_weight = c5.number_input("Weight", value=base_w, step=0.5, key=f"mw_{mid}")
        if st.button("Save Changes", key=f"m_save_{mid}"):
            with conn:
                conn.execute("UPDATE metrics SET label=?,group_name=?,per80=?,active=?,weight=? WHERE id=?",
                             (new_label.strip(), new_grp, int(new_per80), int(new_active), float(new_weight), int(mid)))
            st.success("Saved."); st.rerun()

# -------- Hotkeys --------
def page_hotkeys(conn: sqlite3.Connection, role: str):
    st.header("⌨️ Hotkeys")
    if role != "admin":
        st.info("Admin only."); return
    mdf = _metrics_df(conn, only_active=True)
    if mdf.empty: st.info("No active metrics."); return

    mapping = pd.read_sql_query("""
        SELECT h.key, m.label, m.group_name
        FROM hotkeys h JOIN metrics m ON m.id=h.metric_id
        ORDER BY h.key
    """, conn)
    st.subheader("Current Mapping"); st.dataframe(mapping, use_container_width=True)

    ALL_KEYS = [f"Key{c}" for c in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")] + [f"Digit{d}" for d in "0123456789"]
    c1,c2 = st.columns([1,2])
    hk = c1.selectbox("Key", ALL_KEYS, key="hk_key")
    mid = c2.selectbox("Metric", mdf["id"].tolist(),
                       format_func=lambda x: f"{mdf.loc[mdf['id']==x,'label'].iloc[0]} ({mdf.loc[mdf['id']==x,'group_name'].iloc[0]})",
                       key="hk_metric")
    if st.button("Save Mapping", key="hk_save"):
        with conn:
            conn.execute("INSERT OR REPLACE INTO hotkeys(key,metric_id) VALUES(?,?)", (hk, int(mid)))
        st.success("Saved."); st.rerun()

    if st.button("Load WASD Preset", key="hk_wasd"):
        preset = {
            "KeyW":"Tackles Made","KeyS":"Tackles Missed","KeyA":"Carries Made","KeyD":"Offloads",
            "KeyQ":"Line Breaks","KeyE":"Assists","KeyR":"Tries","KeyF":"Turnovers Won",
            "KeyG":"Turnovers Conceded","KeyV":"Handling Errors","KeyX":"Kick w/ Territory Gain",
            "KeyC":"Kick w/o Territory Gain","KeyZ":"Penalties Conceded",
        }
        for k,label in preset.items():
            _id = _metric_id_by_label(conn, label)
            if _id:
                with conn:
                    conn.execute("INSERT OR REPLACE INTO hotkeys(key,metric_id) VALUES(?,?)",(k,int(_id)))
        st.success("Preset loaded."); st.rerun()

    if st.button("Clear All", key="hk_clear"):
        with conn: conn.execute("DELETE FROM hotkeys")
        st.warning("Cleared."); st.rerun()

# -------- Live Logger --------
def page_logger(conn: sqlite3.Connection, role: str):
    st.header("📝 Live Logger (Event → Player)")
    with st.expander("Match Setup", expanded=True):
        c1,c2,c3 = st.columns([1.2,1,1])
        opp = c1.text_input("Opponent", key="lg_opp")
        date= c2.date_input("Date", value=dt.date.today(), key="lg_date")
        if c3.button("Create/Use Match", key="lg_make"):
            if not opp.strip(): st.error("Enter opponent.")
            else:
                r = conn.execute("SELECT id FROM matches WHERE opponent=? AND date=?", (opp.strip(), str(date))).fetchone()
                mid = int(r["id"]) if r else None
                if not mid:
                    with conn:
                        conn.execute("INSERT INTO matches(opponent,date) VALUES(?,?)", (opp.strip(), str(date)))
                        mid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                st.session_state["match_id"] = mid
                st.success(f"Match loaded: {opp} — {date}"); st.rerun()

    mid = st.session_state.get("match_id")
    if not mid:
        st.info("Create or select a match first."); return

    players = _players_df(conn)
    if players.empty: st.warning("Add players first."); return

    cur = st.selectbox("Current Player", players["id"].tolist(),
                       format_func=lambda x: players.set_index("id")["name"].to_dict().get(x,"?"),
                       key="lg_player")

    metrics = _metrics_df(conn, only_active=True)
    for grp in metrics["group_name"].unique():
        st.subheader(grp)
        cols = st.columns(4)
        subset = metrics[metrics["group_name"]==grp]
        for i, (_, row) in enumerate(subset.iterrows()):
            if cols[i%4].button(row["label"], key=f"lg_btn_{int(row['id'])}"):
                with conn:
                    conn.execute("INSERT INTO events(match_id,player_id,metric_id,value) VALUES(?,?,?,1)",
                                 (int(mid), int(cur), int(row["id"])))
                st.toast(f"{row['label']} — {players.set_index('id')['name'][int(cur)]}", icon="✅")

    st.divider()
    st.subheader("Recent (this match)")
    recent = pd.read_sql_query("""
        SELECT e.id, p.name AS player, m.label AS metric, e.ts
        FROM events e
        JOIN players p ON p.id=e.player_id
        JOIN metrics m ON m.id=e.metric_id
        WHERE e.match_id=?
        ORDER BY e.id DESC LIMIT 30
    """, conn, params=(int(mid),))
    if not recent.empty:
        st.dataframe(recent, use_container_width=True)

# -------- Reports --------
def page_reports(conn: sqlite3.Connection, role: str):
    st.header("📈 Reports & Leaderboard")

    df = pd.read_sql_query("""
        SELECT p.name AS player, m.label AS metric, SUM(e.value) AS total
        FROM events e
        JOIN players p ON p.id=e.player_id
        JOIN metrics m ON m.id=e.metric_id
        GROUP BY p.id, m.id
        ORDER BY p.name, m.label
    """, conn)

    if df.empty:
        st.info("No events recorded yet."); return

    totals = df.pivot(index="player", columns="metric", values="total").fillna(0).astype(int)
    st.subheader("Totals"); st.dataframe(totals, use_container_width=True)

    per80_list = pd.read_sql_query("SELECT label FROM metrics WHERE per80=1 AND active=1", conn)["label"].tolist()
    if per80_list:
        # Try minutes metric; else approx matches*80
        minutes_df = pd.read_sql_query("""
            SELECT p.name AS player, COALESCE(SUM(e.value),0) AS minutes
            FROM events e JOIN players p ON p.id=e.player_id
            JOIN metrics m ON m.id=e.metric_id
            WHERE m.name='minutes'
            GROUP BY p.id
        """, conn)
        if minutes_df.empty:
            minutes_df = pd.read_sql_query("""
                SELECT p.name AS player, COUNT(DISTINCT e.match_id)*80.0 AS minutes
                FROM events e JOIN players p ON p.id=e.player_id
                GROUP BY p.id
            """, conn)

        mins = minutes_df.set_index("player")["minutes"]
        per80 = pd.DataFrame(index=totals.index)
        for col in totals.columns:
            if col in per80_list:
                per80[col] = (totals[col] / mins.replace(0, pd.NA)) * 80.0
        per80 = per80.replace([pd.NA, pd.NaT], 0).fillna(0)
        st.subheader("Per-80 (flagged metrics)"); st.dataframe(per80.round(2), use_container_width=True)

    w = pd.read_sql_query("SELECT label, COALESCE(weight,0) AS weight FROM metrics WHERE active=1", conn)
    weights = dict(zip(w["label"], w["weight"]))
    w_series = pd.Series({c: float(weights.get(c,0.0)) for c in totals.columns})
    score_df = totals.mul(w_series, axis=1)
    score_df["Score"] = score_df.sum(axis=1)
    st.subheader("Leaderboard (Weighted)")
    st.dataframe(score_df[["Score"]].sort_values("Score", ascending=False), use_container_width=True)

    st.subheader("Chart: Top 10 by Score")
    chart_df = score_df[["Score"]].sort_values("Score", ascending=False).head(10).reset_index(names="player")
    chart = alt.Chart(chart_df).mark_bar().encode(x="Score:Q", y=alt.Y("player:N", sort="-x")).properties(height=350)
    st.altair_chart(chart, use_container_width=True)

# -------- Video Review --------
def page_video(conn: sqlite3.Connection, role: str):
    """
    Mode B: Simple player (YouTube private link) + bookmarks list on the right.
    No custom JS component required; timestamps are entered quickly via inputs and helpers.
    Naming format enforced on add: YYYY-MM-DD_Team_vs_Opponent_Half
    """
    st.header("🎥 Video Review / Bookmarks")

    # Ensure we have videos/moments tables (should already exist from SCHEMA)
    conn.execute("CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL, label TEXT NOT NULL, offset REAL NOT NULL DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS moments(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, video_id INTEGER NOT NULL, video_ts REAL NOT NULL, note TEXT DEFAULT '', ts TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.commit()

    matches = _matches_df(conn)
    if matches.empty:
        st.info("Create or load a match in **Live Logger** first.")
        return

    st.subheader("Select Match")
    opts = [(int(r["id"]), f"{r['date']} — {r['opponent']}") for _, r in matches.iterrows()]
    mid = st.selectbox("Match", [o[0] for o in opts], format_func=dict(opts).get, key="vid_match")

    st.divider()
    with st.expander("➕ Add YouTube video (private/unlisted link)", expanded=False):
        c1,c2,c3 = st.columns([1,1,1])
        date_str = c1.text_input("Date (YYYY-MM-DD)", value=str(matches.set_index("id").loc[mid, "date"]))
        opponent = c2.text_input("Opponent", value=matches.set_index("id").loc[mid, "opponent"])
        half     = c3.selectbox("Half", ["1stHalf","2ndHalf","Full"], index=0)
        yt_url   = st.text_input("YouTube URL (private/unlisted)")
        # Label format B:
        # 2025-10-14_U18s_vs_Harlequins_1stHalf
        team_name = st.text_input("Team label (e.g., U18s)", value="U18s")
        if st.button("Add Video"):
            if not yt_url.strip():
                st.error("Paste a YouTube URL")
            else:
                label = f"{date_str}_{team_name}_vs_{opponent}_{half}".replace(" ", "")
                with conn:
                    conn.execute(
                        "INSERT INTO videos(match_id,kind,url,label,offset) VALUES(?,?,?,?,0)",
                        (int(mid), "youtube", yt_url.strip(), label)
                    )
                st.success(f"Added: {label}")
                st.rerun()

    vids = pd.read_sql_query(
        "SELECT id,label,kind,url,offset FROM videos WHERE match_id=? ORDER BY id",
        conn, params=(int(mid),)
    )
    if vids.empty:
        st.info("No videos yet for this match.")
        return

    st.subheader("Active video")
    vopts = [(int(r["id"]), f"{r['label']} ({r['kind']})") for _, r in vids.iterrows()]
    vid = st.selectbox("Video", [o[0] for o in vopts], format_func=dict(vopts).get, key="vid_active")

    vrow = conn.execute("SELECT id,url,offset FROM videos WHERE id=?", (int(vid),)).fetchone()
    off  = st.number_input("Start offset (sec)", value=float(vrow["offset"] or 0.0), step=1.0, key=f"vid_off_{vid}")
    if st.button("Save offset", key=f"vid_off_save_{vid}"):
        with conn:
            conn.execute("UPDATE videos SET offset=? WHERE id=?", (float(off), int(vid)))
        st.success("Saved.")
        st.rerun()

    # --- Layout: player left, bookmarks right ---
    col_left, col_right = st.columns([2,1])

    with col_left:
        st.subheader("Player")
        # Streamlit can play YT URLs directly
        st.video(vrow["url"], start_time=int(off))

    with col_right:
        st.subheader("⭐ Bookmarks")
        st.caption("Quickly add timestamps (in seconds) and a short note.")

        c1,c2 = st.columns([1,2])
        # Keep last used ts in session to speed data entry
        last_ts_key = f"last_ts_{vid}"
        default_ts = st.session_state.get(last_ts_key, 0)
        tsec = c1.number_input("Time (s)", value=float(default_ts), step=1.0, key=f"bm_t_{vid}")
        note = c2.text_input("Note", value="", key=f"bm_note_{vid}")

        cc1,cc2,cc3 = st.columns(3)
        if cc1.button("Add ⭐", key=f"bm_add_{vid}", use_container_width=True):
            with conn:
                conn.execute(
                    "INSERT INTO moments(match_id,video_id,video_ts,note) VALUES(?,?,?,?)",
                    (int(mid), int(vid), float(tsec), note.strip())
                )
            st.session_state[last_ts_key] = float(tsec)  # remember last
            st.success("Bookmark added.")
            st.rerun()

        if cc2.button("+5s", key=f"bm_plus5_{vid}", use_container_width=True):
            st.session_state[last_ts_key] = float(default_ts) + 5.0
            st.rerun()
        if cc3.button("+10s", key=f"bm_plus10_{vid}", use_container_width=True):
            st.session_state[last_ts_key] = float(default_ts) + 10.0
            st.rerun()

        # List bookmarks
        bms = pd.read_sql_query(
            "SELECT id,video_ts,note FROM moments WHERE match_id=? AND video_id=? ORDER BY video_ts",
            conn, params=(int(mid), int(vid))
        )
        if bms.empty:
            st.caption("No bookmarks yet.")
        else:
            for _, row in bms.iterrows():
                c1,c2,c3,c4 = st.columns([1,5,1,1])
                t = float(row["video_ts"])
                with c1:
                    st.write(f"{int(t//60):02d}:{int(t%60):02d}")
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
                        st.warning("Deleted"); st.rerun()

            # Export CSV
            st.divider()
            csv = bms.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Export bookmarks (CSV)", data=csv, file_name="bookmarks.csv", mime="text/csv", use_container_width=True)


# -------- Master router --------
def main(conn: sqlite3.Connection, role: str):
    init_db(conn)
   from components_live_logger import live_logger

def main(conn: sqlite3.Connection, role: str):
    init_db(conn)
    st.title("🎥 Video + Live Match Tagging (Pro Mode)")

    matches = _matches_df(conn)
    if matches.empty:
        st.warning("Create a match in Live Logger first")
        return

    mid = st.selectbox(
        "Match",
        matches["id"].tolist(),
        format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} — {matches.set_index('id').loc[x,'opponent']}"
    )

    # Load players + metrics
    players = _players_df(conn).to_dict("records")
    metrics = _metrics_df(conn, only_active=True).to_dict("records")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Video + Hotkeys")
        st.write("Use hotkeys to tag events & create bookmarks automatically")
        page_video(conn, role)  # reuse existing video player

    with col2:
        live_logger(conn, mid, players, metrics)
