import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, date, timedelta
import os
import hashlib

# --- CONFIGURATION & SETUP ---
# NOTE: Files uploaded to 'uploads' on Streamlit Cloud are temporary and will vanish on reboot.
# For permanent files, use the "External Link" feature or integrate AWS S3.
UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# --- DATABASE CONNECTION ---
def get_db_connection():
    """Establishes connection to Supabase/Postgres using secrets"""
    try:
        return psycopg2.connect(st.secrets["DB_URL"])
    except Exception as e:
        st.error(f"❌ Database Connection Error: {e}")
        st.stop()

# --- SECURITY UTILS ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

# --- DATABASE FUNCTIONS (POSTGRES ADAPTED) ---
def init_db():
    """Initializes tables in PostgreSQL if they don't exist"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Tasks Table (Using SERIAL for Auto-Increment in Postgres)
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    task_name TEXT,
                    department TEXT,
                    assignee TEXT,
                    status TEXT,
                    deadline DATE,
                    total_items INTEGER,
                    completed_items INTEGER,
                    file_path TEXT,
                    task_link TEXT,
                    is_archived INTEGER DEFAULT 0
                )''')
    
    # 2. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    last_active TIMESTAMP
                )''')

    # 3. Reference Tables
    c.execute('''CREATE TABLE IF NOT EXISTS departments (name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (name TEXT PRIMARY KEY)''')
    
    conn.commit()
    
    # Seed Data (Check if empty first)
    c.execute('SELECT count(*) FROM departments')
    if c.fetchone()[0] == 0:
        depts = [("Engineering",), ("HR",), ("Sales",), ("Marketing",), ("Operations",)]
        c.executemany('INSERT INTO departments VALUES (%s)', depts)
        
    c.execute('SELECT count(*) FROM statuses')
    if c.fetchone()[0] == 0:
        stats = [("To Do",), ("In Progress",), ("Review",), ("Done",)]
        c.executemany('INSERT INTO statuses VALUES (%s)', stats)

    conn.commit()
    conn.close()

# --- HELPERS ---
def run_auto_archive():
    conn = get_db_connection(); c = conn.cursor()
    cutoff_date = date.today() - timedelta(days=30)
    # Postgres syntax uses %s for parameters
    c.execute("UPDATE tasks SET is_archived = 1 WHERE status = 'Done' AND deadline < %s AND is_archived = 0", (cutoff_date,))
    count = c.rowcount; conn.commit(); conn.close()
    return count

def delete_task(task_id):
    conn = get_db_connection(); c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit(); conn.close()

def get_list(table_name):
    conn = get_db_connection(); c = conn.cursor()
    # Safe usage since table_name is hardcoded in calls
    c.execute(f'SELECT name FROM {table_name}')
    return [item[0] for item in c.fetchall()]

def add_item(table_name, value):
    conn = get_db_connection(); c = conn.cursor()
    try: 
        c.execute(f'INSERT INTO {table_name} (name) VALUES (%s)', (value,))
        conn.commit(); success=True
    except: success=False
    conn.close(); return success

def delete_item(table_name, value):
    conn = get_db_connection(); c = conn.cursor()
    c.execute(f'DELETE FROM {table_name} WHERE name = %s', (value,)); conn.commit(); conn.close()

def create_user(username, password, role="Employee"):
    conn = get_db_connection(); c = conn.cursor()
    try: 
        c.execute('INSERT INTO users(username, password, role) VALUES (%s, %s, %s)', 
                  (username, make_hashes(password), role))
        conn.commit(); success=True
    except psycopg2.IntegrityError: 
        success=False
    conn.close(); return success

def delete_user(username):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = %s', (username,)); conn.commit(); conn.close()

def login_user(username, password):
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = %s AND password = %s', 
              (username, make_hashes(password)))
    data = c.fetchall(); conn.close(); return data

def get_all_users_list():
    conn = get_db_connection(); c = conn.cursor()
    c.execute('SELECT username FROM users'); return [u[0] for u in c.fetchall()]

def update_last_active(username):
    conn = get_db_connection(); c = conn.cursor(); now = datetime.now()
    c.execute("UPDATE users SET last_active = %s WHERE username = %s", (now, username))
    conn.commit(); conn.close()

def get_online_users():
    conn = get_db_connection(); c = conn.cursor()
    limit = datetime.now() - timedelta(minutes=5)
    c.execute("SELECT username FROM users WHERE last_active > %s", (limit,))
    return [u[0] for u in c.fetchall()]

def add_task(task_name, department, assignee_list, status, deadline, total, completed):
    conn = get_db_connection(); c = conn.cursor()
    
    # Handle Multi-Assignee List -> String
    if isinstance(assignee_list, list): assignee_str = ",".join(assignee_list)
    else: assignee_str = str(assignee_list)
    
    c.execute('''INSERT INTO tasks 
                 (task_name, department, assignee, status, deadline, total_items, completed_items, is_archived) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, 0)''', 
                 (task_name, department, assignee_str, status, deadline, total, completed))
    conn.commit(); conn.close()

def get_tasks(include_archived=False):
    conn = get_db_connection()
    query = "SELECT * FROM tasks" if include_archived else "SELECT * FROM tasks WHERE is_archived = 0"
    df = pd.read_sql_query(query, conn); conn.close(); return df

def update_task_details(task_id, new_status, new_completed, new_file_path, new_link):
    conn = get_db_connection(); c = conn.cursor()
    query = "UPDATE tasks SET status = %s, completed_items = %s"
    params = [new_status, new_completed]
    if new_file_path: query += ", file_path = %s"; params.append(new_file_path)
    if new_link: query += ", task_link = %s"; params.append(new_link)
    query += " WHERE id = %s"; params.append(task_id)
    c.execute(query, tuple(params)); conn.commit(); conn.close()

def render_metrics(df):
    today = date.today()
    df['deadline'] = pd.to_datetime(df['deadline']).dt.date
    df['is_overdue'] = (df['deadline'] < today) & (df['status'] != 'Done')
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Tasks", len(df)); m2.metric("Completed", len(df[df['status'] == 'Done']))
    m3.metric("Pending", len(df[df['status'] != 'Done'])); m4.metric("Overdue 🚨", len(df[df['is_overdue'] == True]))
    st.markdown("---")

def display_attachment_preview(file_path, link_url):
    if link_url: st.markdown(f"🔗 **Link:** [{link_url}]({link_url})")
    
    # NOTE: File preview only works if file exists locally. 
    # In cloud deployment, this only works for the session the file was uploaded.
    if file_path and os.path.exists(file_path):
        file_ext = os.path.splitext(file_path)[1].lower(); file_name = os.path.basename(file_path)
        if file_ext in ['.png', '.jpg', '.jpeg']: st.image(file_path, caption=file_name, width=200)
        elif file_ext == '.csv':
            with st.expander(f"📊 {file_name}"): st.dataframe(pd.read_csv(file_path).head(5))
        with open(file_path, "rb") as f: st.download_button(f"📥 {file_name}", f, file_name)

# --- DIALOG ---
@st.dialog("Update Task Details")
def update_task_dialog(row, status_list):
    st.write(f"Editing: **{row['task_name']}**")
    c1, c2 = st.columns(2)
    new_comp = c1.number_input("Items Completed", 0, row['total_items'], row['completed_items'])
    current_status_list = status_list.copy()
    if row['status'] not in current_status_list: current_status_list.append(row['status'])
    new_stat = c2.selectbox("Status", current_status_list, index=current_status_list.index(row['status']))
    st.progress(int((new_comp/row['total_items'])*100) if row['total_items']>0 else 0)
    st.markdown("---")
    st.markdown("#### 📎 Attachments")
    st.caption("Note: Direct file uploads are temporary. Use External Links for permanent storage.")
    new_file = st.file_uploader("Upload File (Temporary)")
    new_link = st.text_input("External Link URL (Permanent)", value=row['task_link'] if row['task_link'] else "")
    st.markdown("---")
    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        final_path = None
        if new_file:
            final_path = os.path.join(UPLOAD_DIR, new_file.name)
            with open(final_path, "wb") as f: f.write(new_file.getbuffer())
        update_task_details(row['id'], new_stat, new_comp, final_path, new_link)
        st.success("Updated!"); st.rerun()

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Lynx Tracker", layout="wide", page_icon="🔐")
    
    # Initialize DB (Checks connection & creates tables)
    init_db()

    if run_auto_archive() > 0: st.toast("🧹 Auto-Archived old tasks.")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False; st.session_state['username'] = None; st.session_state['role'] = None

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.markdown("<h1 style='text-align: center;'>🔐 Login</h1>", unsafe_allow_html=True); st.markdown("---")
            tab_login, tab_signup = st.tabs(["Login", "Register"])
            with tab_login:
                u = st.text_input("Username"); p = st.text_input("Password", type='password')
                if st.button("Login", use_container_width=True):
                    res = login_user(u, p)
                    if res: st.session_state['logged_in']=True; st.session_state['username']=u; st.session_state['role']=res[0][2]; update_last_active(u); st.rerun()
                    else: st.error("Invalid Creds")
            with tab_signup:
                nu = st.text_input("New User"); np = st.text_input("New Pass", type='password'); nr = st.selectbox("Role", ["Employee", "Manager"])
                if st.button("Create Account", use_container_width=True):
                    if create_user(nu, np, nr): st.success("Created! Go to Login.")
                    else: st.warning("Exists.")

    # --- LOGGED IN AREA ---
    else:
        update_last_active(st.session_state['username'])
        online_users = get_online_users()
        dept_list = get_list('departments')
        status_list = get_list('statuses')
        users_list = get_all_users_list()

        # Sidebar
        st.sidebar.write(f"👤 **{st.session_state['username']}** ({st.session_state['role']})")
        st.sidebar.markdown("**Online:**"); 
        for u in online_users: 
            if u != st.session_state['username']: st.sidebar.caption(f"🟢 {u}")
        if st.sidebar.button("Log Out"): st.session_state['logged_in'] = False; st.rerun()
        st.sidebar.markdown("---")

        # Sidebar: Add Task
        st.sidebar.header("➕ Create Task")
        with st.sidebar.form("new_task"):
            tn = st.text_input("Task Name"); td = st.selectbox("Dept", dept_list if dept_list else ["General"])
            
            # Multi-select Assignee
            if users_list: ta = st.multiselect("Assign To", users_list)
            else: ta = st.text_input("Assignee")
                
            ts = st.selectbox("Status", status_list if status_list else ["To Do"]); tdl = st.date_input("Deadline")
            c1, c2 = st.columns(2); tt = c1.number_input("Total", 1, 100, 5); tc = c2.number_input("Done", 0, 100, 0)
            if st.form_submit_button("Add"): 
                add_task(tn, td, ta, ts, tdl, tt, tc)
                st.toast("Added!"); st.rerun()

        # Fetch Data
        show_archived = False
        if st.session_state['role'] == "Manager": show_archived = st.sidebar.checkbox("Show Archived")
        df = get_tasks(show_archived)
        
        # --- APP TABS ---
        st.title("📊 Lynx Task Tracker")
        tabs = ["📈 Dashboard", "👤 My Workspace"]
        if st.session_state['role'] == "Manager": tabs.append("🛠️ Admin")
        current_tab = st.tabs(tabs)

        # TAB 1: DASHBOARD
        with current_tab[0]:
            dash_df = df.copy()
            # If Employee, only show rows where their name appears in assignee string
            if st.session_state['role'] == "Employee":
                dash_df = df[df['assignee'].astype(str).str.contains(st.session_state['username'], na=False)]

            if not dash_df.empty:
                render_metrics(dash_df)
                
                c1, c2, c3 = st.columns(3)
                c1.subheader("By Dept"); c1.bar_chart(dash_df['department'].value_counts())
                c2.subheader("By Status"); c2.bar_chart(dash_df['status'].value_counts())
                
                # By Employee (Handle Multi-Assignee Explode)
                c3.subheader("By Employee")
                try:
                    chart_df = dash_df.assign(assignee=dash_df['assignee'].str.split(',')).explode('assignee')
                    chart_df['assignee'] = chart_df['assignee'].str.strip()
                    c3.bar_chart(chart_df['assignee'].value_counts())
                except: st.caption("No data")
                
                st.markdown("### 📄 List")
                lim = st.selectbox("Show:", [10, 20, 50, "All"])
                d_df = dash_df.head(int(lim)) if lim != "All" else dash_df
                st.dataframe(d_df[['task_name', 'department', 'status', 'deadline', 'completed_items']], use_container_width=True)
            else: st.info("No tasks.")

        # TAB 2: WORKSPACE
        with current_tab[1]:
            st.header("Active Tasks")
            work_df = df.copy()
            if st.session_state['role'] == "Employee":
                work_df = df[df['assignee'].astype(str).str.contains(st.session_state['username'], na=False)]

            if not work_df.empty:
                for dept in work_df['department'].unique():
                    st.markdown(f"### 📂 {dept}")
                    st.markdown("---")
                    for idx, row in work_df[work_df['department'] == dept].iterrows():
                        with st.container(border=True):
                            c_info, c_stat, c_act = st.columns([3, 2, 1])
                            with c_info:
                                st.subheader(row['task_name'])
                                st.caption(f"📅 Due: {row['deadline']}")
                                
                                # Assignee Display
                                assignees = str(row['assignee']).replace(",", ", ")
                                st.markdown(f"**👤 Assigned:** `{assignees}`")
                                
                                display_attachment_preview(row['file_path'], row['task_link'])
                            
                            with c_stat:
                                st.write(f"**Status:** {row['status']}")
                                prog = int((row['completed_items']/row['total_items'])*100) if row['total_items']>0 else 0
                                st.progress(prog)
                                st.caption(f"{row['completed_items']} / {row['total_items']} items")

                            with c_act:
                                if st.button("✏️ Update", key=f"upd_{row['id']}", use_container_width=True):
                                    update_task_dialog(row, status_list)
                                if st.session_state['role'] == "Manager":
                                    if st.button("🗑️ Delete", key=f"del_{row['id']}", type="primary", use_container_width=True):
                                        delete_task(row['id']); st.rerun()
                    st.write("")
            else: st.info("No tasks.")

        # TAB 3: ADMIN
        if st.session_state['role'] == "Manager":
            with current_tab[2]:
                st.header("Admin"); ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.subheader("Depts"); nd = st.text_input("New Dept")
                    if st.button("Add Dept", type="primary"): add_item('departments', nd); st.rerun()
                    for d in dept_list: 
                        if st.button(f"Delete {d}", key=f"d_{d}"): delete_item('departments', d); st.rerun()
                with ac2:
                    st.subheader("Statuses"); ns = st.text_input("New Status")
                    if st.button("Add Status", type="primary"): add_item('statuses', ns); st.rerun()
                    for s in status_list:
                         if st.button(f"Delete {s}", key=f"s_{s}"): delete_item('statuses', s); st.rerun()
                with ac3:
                    st.subheader("Users")
                    for u in users_list:
                        c_a, c_b = st.columns([2,1])
                        c_a.write(u)
                        if u != st.session_state['username']:
                             if c_b.button("🗑️", key=f"u_{u}"): delete_user(u); st.rerun()

if __name__ == "__main__":
    main()