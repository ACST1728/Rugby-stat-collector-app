import streamlit as st
import bcrypt

def user_admin_page(conn):
    st.title("👤 User & Password Management")

    # Return to app
    if st.button("⬅️ Back to App"):
        st.session_state.show_user_admin = False
        st.rerun()

    st.subheader("Add New User")

    new_user = st.text_input("Username")
    new_pass = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["admin", "editor", "viewer"])

    if st.button("Create User"):
        if not new_user or not new_pass:
            st.error("Username & password required")
        else:
            ph = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt())
            try:
                with conn:
                    conn.execute("INSERT INTO users(username, pass_hash, role, active) VALUES(?,?,?,1)",
                                 (new_user, ph, role))
                st.success(f"✅ User created: {new_user} ({role})")
                st.rerun()
            except:
                st.error("❌ Username already exists")

    st.subheader("Existing Users")
    users = conn.execute("SELECT username, role, active FROM users").fetchall()

    for u, role, active in users:
        st.write(f"**{u}** — {role} — {'✅ Active' if active else '❌ Inactive'}")

        col1, col2, col3 = st.columns(3)

        with col1:
            new_role = st.selectbox("Role", ["admin","editor","viewer"], index=["admin","editor","viewer"].index(role), key=f"role_{u}")
        with col2:
            new_active = st.checkbox("Active", value=bool(active), key=f"act_{u}")
        with col3:
            if st.button("Save", key=f"save_{u}"):
                with conn:
                    conn.execute("UPDATE users SET role=?, active=? WHERE username=?",
                                 (new_role, int(new_active), u))
                st.success("✅ Updated")
                st.rerun()

        # Reset password
        new_pw = st.text_input(f"New password for {u}", type="password", key=f"pw_{u}")
        if st.button(f"Reset Password for {u}", key=f"reset_{u}"):
            if not new_pw:
                st.error("Enter new password")
            else:
                ph = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt())
                with conn:
                    conn.execute("UPDATE users SET pass_hash=? WHERE username=?", (ph, u))
                st.success("🔐 Password reset")
                st.rerun()

        st.divider()
