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
        date TEXT,
        team_id INTEGER
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
        role TEXT NOT NULL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS teams(
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS team_players(
        id INTEGER PRIMARY KEY,
        team_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        UNIQUE(team_id, player_id)
    );

    CREATE TABLE IF NOT EXISTS match_squad(
        id INTEGER PRIMARY KEY,
        match_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        shirt_number INTEGER,
        starting INTEGER NOT NULL DEFAULT 1,
        UNIQUE(match_id, player_id)
    );
    """)
    conn.commit()


    # Backfill column if needed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)").fetchall()}
    if "team_id" not in cols:
        try:
            conn.execute("ALTER TABLE matches ADD COLUMN team_id INTEGER;")
        except sqlite3.OperationalError:
            pass

    conn.commit()


def _players_df(conn):
    return pd.read_sql("SELECT id,name,position,active FROM players ORDER BY name", conn)

# ---------------- METRICS SETTINGS ----------------
def page_metrics(conn, role):
    st.header("📊 Metrics")

    if role not in ("admin", "editor"):
        st.info("View-only access.")
    
    # fixed groups
    METRIC_GROUPS = [
        "Attack",
        "Defense",
        "Set Piece",
        "Kicking",
        "Discipline",
        "Other"
    ]

    metrics = pd.read_sql(
        "SELECT id, name, label, group_name, type, per80, weight, active FROM metrics ORDER BY group_name, label",
        conn
    )
    st.dataframe(metrics, use_container_width=True)

    st.divider()
    st.subheader("➕ Add Metric")

    name = st.text_input("Internal name (no spaces, e.g. carry, tackle_miss)").strip()
    label = st.text_input("Display Label (e.g. Carry, Missed Tackle)").strip()
    group = st.selectbox("Group", METRIC_GROUPS)
    mtype = st.selectbox("Type", ["count", "value"])
    weight = st.number_input("Weight (optional)", value=1.0)
    
    if st.button("Create Metric", disabled=role not in ("admin","editor")):
        if not name or not label:
            st.error("Name & Label required.")
        else:
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO metrics(name,label,group_name,type,per80,weight,active)
                        VALUES (?,?,?,?,1,?,1)
                    """, (name, label, group, mtype, weight))
                st.success("✅ Metric added")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Metric name must be unique.")

    st.divider()
    st.subheader("✏️ Edit Metric")

    if not metrics.empty:
        sel = st.selectbox("Metric", metrics["id"].tolist(),
            format_func=lambda x: metrics.set_index("id").loc[x,"label"]
        )
        r = metrics[metrics["id"]==sel].iloc[0]

        new_label = st.text_input("Label", r["label"], key=f"ml_{sel}")
        new_group = st.selectbox("Group", METRIC_GROUPS, index=METRIC_GROUPS.index(r["group_name"]), key=f"mg_{sel}")
        new_active = st.checkbox("Active", value=bool(r["active"]), key=f"ma_{sel}")
        new_weight = st.number_input("Weight", value=float(r["weight"] or 1), key=f"mw_{sel}")

        if st.button("Save Metric", key=f"ms_{sel}", disabled=role not in ("admin","editor")):
            with conn:
                conn.execute("""
                    UPDATE metrics
                    SET label=?, group_name=?, weight=?, active=?
                    WHERE id=?
                """, (new_label, new_group, new_weight, int(new_active), sel))
            st.success("✅ Updated")
            st.rerun()

def _metrics_df(conn, only_active=False):
    q = "SELECT id,name,label,group_name,type,per80,weight,active FROM metrics"
    if only_active: q += " WHERE active=1"
    q += " ORDER BY group_name,label"
    return pd.read_sql(q, conn)

def _matches_df(conn):
    return pd.read_sql("SELECT id,opponent,date,team_id FROM matches ORDER BY date DESC,id DESC", conn)

def _teams_df(conn):
    return pd.read_sql("SELECT id,name,active FROM teams ORDER BY name", conn)

def _team_players_df(conn, team_id: int):
    return pd.read_sql("""
        SELECT p.id, p.name, p.position, p.active
        FROM team_players tp
        JOIN players p ON p.id = tp.player_id
        WHERE tp.team_id=?
        ORDER BY p.name
    """, conn, params=(int(team_id),))

def _squad_df(conn, match_id: int):
    return pd.read_sql("""
        SELECT ms.player_id, p.name, p.position, ms.shirt_number, ms.starting
        FROM match_squad ms
        JOIN players p ON p.id=ms.player_id
        WHERE ms.match_id=?
        ORDER BY COALESCE(ms.shirt_number, 999), p.name
    """, conn, params=(int(match_id),))

def _match_row(conn, match_id: int):
    r = conn.execute("SELECT id, opponent, date, team_id FROM matches WHERE id=?",
                     (int(match_id),)).fetchone()
    return dict(r) if r else None


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
    new_role = st.selectbox("Role", ["admin","editor","viewer"], key="create_role")

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
        sel = st.selectbox("User", users["username"].tolist(), key="edit_user_sel")
        r = users[users["username"]==sel].iloc[0]
        new_role = st.selectbox(
            "Role",
            ["admin","editor","viewer"],
            index=["admin","editor","viewer"].index(r["role"]),
            key=f"edit_role_{sel}"
        )
        active = st.checkbox("Active", value=bool(r["active"]), key=f"edit_active_{sel}")

        if st.button("Save Changes", key=f"user_save_{sel}"):
            with conn:
                conn.execute(
                    "UPDATE users SET role=?, active=? WHERE username=?",
                    (new_role, int(active), sel)
                )
            st.success("Updated")
            st.rerun()

        temp_pw = st.text_input("Temporary Password", key=f"pwreset_{sel}", type="password")

if st.button("Reset Password"):
    if temp_pw:
        ph = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt())
        with conn:
            conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, sel))
        st.success("Password reset!")



# ---------------- SELF ACCOUNT ----------------
def page_my_account(conn, username):
    st.header("🔐 My Account")

    new_pw = st.text_input("New Password", type="password")
    if st.button("Change Password", key="self_pw_change"):
        if not new_pw.strip():
            st.error("Password required")
        else:
            ph = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt())
            with conn:
                conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, username))
            st.success("Password updated!")

# ---------------- MATCH MANAGEMENT ----------------
def page_matches(conn, role):
    st.header("🗓️ Match Manager")

    if role not in ("admin","editor"):
        st.info("Viewer mode — only admins/editors can create matches.")

    teams = pd.read_sql("SELECT id, name FROM teams ORDER BY name", conn)
    matches = pd.read_sql("SELECT id, opponent, date, team_id FROM matches ORDER BY date DESC, id DESC", conn)

    st.subheader("📋 Existing Matches")
    if matches.empty:
        st.info("No matches yet — add one below.")
    else:
        def _fmt_team(x):
            if pd.isna(x): return ""
            return teams.set_index("id").loc[int(x),"name"] if int(x) in teams["id"].tolist() else ""
        show = matches.copy()
        show["team"] = show["team_id"].apply(_fmt_team)
        st.dataframe(show[["date","opponent","team"]], use_container_width=True)

    st.divider()
    st.subheader("➕ Create Match")

    opponent = st.text_input("Opponent")
    date = st.date_input("Match Date")
    team_id = None
    if not teams.empty:
        assign_team = st.checkbox("Assign a team now?")
        if assign_team:
            team_id = st.selectbox(
                "Team",
                teams["id"].tolist(),
                format_func=lambda x: teams.set_index("id").loc[x,"name"]
            )

    if st.button("Create Match", disabled=role not in ("admin","editor")):
        if not opponent.strip():
            st.error("Opponent required.")
        else:
            with conn:
                conn.execute(
                    "INSERT INTO matches(opponent, date, team_id) VALUES(?,?,?)",
                    (opponent.strip(), str(date), team_id)
                )
            st.success("Match created ✅")
            st.rerun()

    if not matches.empty and role in ("admin","editor"):
        st.divider()
        st.subheader("🗑️ Delete a Match")
        del_id = st.selectbox(
            "Select Match to Delete",
            matches["id"].tolist(),
            format_func=lambda x: f"{matches.set_index('id').loc[x,'date']} — {matches.set_index('id').loc[x,'opponent']}"
        )
        if st.button("Delete Match"):
            with conn:
                conn.execute("DELETE FROM matches WHERE id=?", (del_id,))
                conn.execute("DELETE FROM match_squad WHERE match_id=?", (del_id,))
                conn.execute("DELETE FROM events WHERE match_id=?", (del_id,))
                conn.execute("DELETE FROM videos WHERE match_id=?", (del_id,))
                conn.execute("DELETE FROM moments WHERE match_id=?", (del_id,))
            st.warning("Match deleted ⚠️")
            st.rerun()


# ---------------- PLAYERS PAGE ----------------
def page_players(conn, role):
    st.header("👥 Players")

    df = _players_df(conn)
    st.dataframe(df, use_container_width=True)

    readonly = role not in ("admin", "editor")
    if readonly:
        st.info("Viewer role — read-only.")
        return

    st.subheader("➕ Add Player")
    c1, c2, c3 = st.columns([2,1,1])
    new_name = c1.text_input("Name", key="p_add_name")
    new_pos  = c2.text_input("Position", key="p_add_pos", placeholder="e.g., 10 / Fly-half")
    new_act  = c3.checkbox("Active", value=True, key="p_add_active")

    if st.button("Add Player", key="p_add_btn"):
        if not new_name.strip():
            st.error("Name required.")
        else:
            with conn:
                conn.execute(
                    "INSERT INTO players(name,position,active) VALUES(?,?,?)",
                    (new_name.strip(), new_pos.strip(), int(new_act))
                )
            st.success("Player added.")
            st.rerun()

    if df.empty:
        st.info("No players to edit yet.")
        return

    st.subheader("✏️ Edit / Deactivate / Delete")
    pid = st.selectbox(
        "Select player",
        df["id"].tolist(),
        format_func=lambda x: df.set_index("id").loc[x, "name"],
        key="p_edit_sel"
    )
    row = df[df["id"] == pid].iloc[0]

    e1, e2, e3, e4 = st.columns([2,1,1,1])
    name_edit = e1.text_input("Name", value=row["name"], key=f"p_name_{pid}")
    pos_edit  = e2.text_input("Position", value=row["position"] or "", key=f"p_pos_{pid}")
    act_edit  = e3.checkbox("Active", value=bool(row["active"]), key=f"p_act_{pid}")

    if e4.button("Save", key=f"p_save_{pid}", use_container_width=True):
        with conn:
            conn.execute(
                "UPDATE players SET name=?, position=?, active=? WHERE id=?",
                (name_edit.strip(), pos_edit.strip(), int(act_edit), int(pid))
            )
        st.success("Saved.")
        st.rerun()

    dcol1, dcol2 = st.columns([1,3])
    if dcol1.button("Delete (danger)", key=f"p_del_{pid}", use_container_width=True):
        with conn:
            conn.execute("DELETE FROM players WHERE id=?", (int(pid),))
            # also clean squad membership for data integrity (optional)
            conn.execute("DELETE FROM match_squad WHERE player_id=?", (int(pid),))
            conn.execute("DELETE FROM team_players WHERE player_id=?", (int(pid),))
        st.warning("Player deleted.")
        st.rerun()


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
        t = st.number_input("Time (sec)", value=float(st.session_state.get(ts_key, 0)), step=1.0, key=f"bm_t_{vid_id}")
        note = st.text_input("Note", key=f"bm_note_{vid_id}")

        if st.button("Add Bookmark", key=f"bm_add_{vid_id}"):
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

        # Squad-first selector (falls back to full roster)
        squad = _squad_df(conn, int(match_id))
        if not squad.empty:
            cur_player = st.selectbox(
                "Player (Match Squad)",
                squad["player_id"].tolist(),
                format_func=lambda x: squad.set_index("player_id").loc[x,"name"],
                key=f"tag_player_{match_id}"
            )
        else:
            cur_player = st.selectbox(
                "Player (All Players)",
                [p["id"] for p in players],
                format_func=lambda x: next(p["name"] for p in players if p["id"] == x),
                key="tag_player_all"
            )

        for grp in sorted({m["group_name"] for m in metrics}):
            st.markdown(f"**{grp}**")
            cols = st.columns(3)
            grp_metrics = [m for m in metrics if m["group_name"]==grp]
            for i,m in enumerate(grp_metrics):
                if cols[i%3].button(m["label"], key=f"tag_btn_{grp}_{m['id']}"):
                    with conn:
                        conn.execute(
                            "INSERT INTO events(match_id,player_id,metric_id) VALUES(?,?,?)",
                            (match_id, cur_player, m["id"])
                        )
                    st.toast(f"{m['label']} logged!", icon="✅")

                recent = pd.read_sql(
            """
            SELECT p.name, m.label, e.ts
            FROM events e
            JOIN players p ON p.id=e.player_id
            JOIN metrics m ON m.id=e.metric_id
            WHERE match_id=?
            ORDER BY e.id DESC
            LIMIT 12
            """,
            conn, params=(match_id,)
        )
        st.dataframe(recent, use_container_width=True)

# ---------------- TEAMS (minimal) ----------------
def page_teams(conn, role: str):
    import pandas as _pd
    import streamlit as _st

    _st.header("🏟️ Teams")

    # Show existing teams
    _st.subheader("Teams")
    teams_df = _pd.read_sql("SELECT id, name, active FROM teams ORDER BY name", conn)
    _st.dataframe(teams_df, use_container_width=True)

    # View-only for non-admin/editor
    if role not in ("admin", "editor"):
        _st.info("Viewer mode: only admins/editors can add or edit teams.")
        return

    # Add a team
    _st.subheader("➕ Add Team")
    new_team = _st.text_input("Team name", placeholder="U18s, 1st XV, Academy…", key="teams_new_name")
    if _st.button("Create Team", use_container_width=True):
        if not new_team.strip():
            _st.error("Enter a team name.")
        else:
            try:
                with conn:
                    conn.execute("INSERT INTO teams(name, active) VALUES(?, 1)", (new_team.strip(),))
                _st.success("Team created.")
                _st.rerun()
        except sqlite3.IntegrityError:
                _st.error("Team name must be unique.")

    # Quick edit (toggle active / rename / delete)
    _st.subheader("✏️ Edit Team")
    if teams_df.empty:
        _st.caption("No teams yet.")
        return

    sel_id = _st.selectbox(
        "Select team",
        teams_df["id"].tolist(),
        format_func=lambda x: teams_df.set_index("id").loc[x, "name"],
        key="teams_edit_sel",
    )
    row = teams_df.set_index("id").loc[sel_id]
    c1, c2, c3 = _st.columns([2, 1, 1])
    new_name = c1.text_input("Name", value=row["name"], key=f"teams_name_{sel_id}")
    new_active = c2.checkbox("Active", value=bool(row["active"]), key=f"teams_active_{sel_id}")

    if c3.button("Save", key=f"teams_save_{sel_id}", use_container_width=True):
        with conn:
            conn.execute("UPDATE teams SET name=?, active=? WHERE id=?", (new_name.strip(), int(new_active), int(sel_id)))
        _st.success("Saved.")
        _st.rerun()

    if _st.button("Delete (danger)", key=f"teams_del_{sel_id}"):
        with conn:
            conn.execute("DELETE FROM teams WHERE id=?", (int(sel_id),))
        _st.warning("Deleted.")
        _st.rerun()


# ---------------- MAIN ROUTER ----------------
def main(conn, role):
    init_db(conn)

    tabs = st.tabs([
        "👤 Users",
        "👥 Players",
        "📊 Metrics",
        "🗓️ Matches",
        "🏟️ Teams",
        "🎥 Tagging",
        "📈 Reports"
    ])

    with tabs[0]:
        page_users(conn, role)

    with tabs[1]:
        page_players(conn, role)

    with tabs[2]:
        page_metrics(conn, role)

    with tabs[3]:
        page_matches(conn, role)   # ✅ Matches Page

    with tabs[4]:
        page_teams(conn, role)

    with tabs[5]:
        page_tagging(conn, role)

    with tabs[6]:
        page_reports(conn, role)


