import sqlite3, bcrypt
import streamlit as st

def user_admin(conn, current_role):
    if current_role != "admin":
        return

    st.sidebar.write("### 👤 User Admin")

    tab = st.sidebar.radio("User Controls", ["Add User", "Edit Users", "Change My Password"])

    # Add User
    if tab == "Add User":
        st.sidebar.write("#### ➕ Add New User")
        nu = st.sidebar.text_input("New username")
        np = st.sidebar.text_input("Password", type="password")
        role = st.sidebar.selectbox("Role", ["admin", "analyst", "viewer"])
        if st.sidebar.button("Create User"):
            ph = bcrypt.hashpw(np.encode(), bcrypt.gensalt())
            conn.execute(
                "INSERT OR REPLACE INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
                (nu, ph, role),
            )
            conn.commit()
            st.sidebar.success(f"✅ User {nu} created")

    # Edit existing users
    if tab == "Edit Users":
        st.sidebar.write("#### ✏️ Manage Users")
        users = conn.execute("SELECT username, role, active FROM users").fetchall()
        for u in users:
            with st.sidebar.expander(f"{u['username']} ({u['role']})"):
                active = st.checkbox("Active", u["active"] == 1, key=f"act_{u['username']}")
                conn.execute("UPDATE users SET active=? WHERE username=?", (int(active), u["username"]))
                conn.commit()

    # Change own password
    if tab == "Change My Password":
        st.sidebar.write("#### 🔑 Change My Password")
        old = st.sidebar.text_input("Old Password", type="password")
        new = st.sidebar.text_input("New Password", type="password")
        if st.sidebar.button("Update Password"):
            user = st.session_state.user["u"]
            row = conn.execute("SELECT pass_hash FROM users WHERE username=?", (user,)).fetchone()
            if bcrypt.checkpw(old.encode(), row["pass_hash"]):
                ph = bcrypt.hashpw(new.encode(), bcrypt.gensalt())
                conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, user))
                conn.commit()
                st.sidebar.success("✅ Password Updated")
            else:
                st.sidebar.error("❌ Wrong old password")
