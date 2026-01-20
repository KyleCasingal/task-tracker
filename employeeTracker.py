import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, timedelta
import os
import hashlib

# --- CONFIGURATION & SETUP ---
DB_FILE = "tasks.db"
UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# --- SECURITY UTILS ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

# --- DATABASE FUNCTIONS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT,
                    department TEXT,
                    assignee TEXT,
                    status TEXT,
                    deadline DATE,
                    total_items INTEGER,
                    completed_items INTEGER,
                    file_path TEXT,
                    task_link TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    last_active DATETIME
                )''')
    try: c.execute("ALTER TABLE users ADD COLUMN last_active DATETIME")
    except: pass
    c.execute('''CREATE TABLE IF NOT EXISTS departments (name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (name TEXT PRIMARY KEY)''')
    c.execute('SELECT count(*) FROM departments')
    if c.fetchone()[0] == 0:
        depts = [("Engineering",), ("HR",), ("Sales",), ("Marketing",), ("Operations",)]
        c.executemany('INSERT INTO departments VALUES (?)', depts)
    c.execute('SELECT count(*) FROM statuses')
    if c.fetchone()[0] == 0:
        stats = [("To Do",), ("In Progress",), ("Review",), ("Done",)]
        c.executemany('INSERT INTO statuses VALUES (?)', stats)
    conn.commit(); conn.close()

# --- ACTIVITY TRACKING ---
def update_last_active(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now()
    c.execute("UPDATE users SET last_active = ? WHERE username = ?", (now, username))
    conn.commit(); conn.close()

def get_online_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    limit_time = datetime.now() - timedelta(minutes=5)
    c.execute("SELECT username FROM users WHERE last_active > ?", (limit_time,))
    online_users = [u[0] for u in c.fetchall()]
    conn.close(); return online_users

# --- DATA FUNCTIONS ---
def get_list(table_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'SELECT name FROM {table_name}')
    return [item[0] for item in c.fetchall()]

def add_item(table_name, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(f'INSERT INTO {table_name} (name) VALUES (?)', (value,))
        conn.commit(); success = True
    except: success = False
    conn.close(); return success

def delete_item(table_name, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'DELETE FROM {table_name} WHERE name = ?', (value,))
    conn.commit(); conn.close()

def create_user(username, password, role="Employee"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users(username, password, role) VALUES (?,?,?)', 
                  (username, make_hashes(password), role))
        conn.commit(); success = True
    except sqlite3.IntegrityError: success = False
    conn.close(); return success

def delete_user(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = ?', (username,))
    conn.commit(); conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
              (username, make_hashes(password)))
    data = c.fetchall()
    conn.close(); return data

def get_all_users_list():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT username FROM users')
    return [u[0] for u in c.fetchall()]

def add_task(task_name, department, assignee, status, deadline, total, completed):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO tasks 
                 (task_name, department, assignee, status, deadline, total_items, completed_items) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                 (task_name, department, assignee, status, deadline, total, completed))
    conn.commit(); conn.close()

def get_all_tasks():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM tasks", conn)
    conn.close(); return df

def update_task_details(task_id, new_status, new_completed, new_file_path, new_link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = "UPDATE tasks SET status = ?, completed_items = ?"
    params = [new_status, new_completed]
    if new_file_path:
        query += ", file_path = ?"
        params.append(new_file_path)
    if new_link:
        query += ", task_link = ?"
        params.append(new_link)
    query += " WHERE id = ?"
    params.append(task_id)
    c.execute(query, tuple(params))
    conn.commit(); conn.close()

# --- UI HELPERS ---
def render_metrics(df):
    today = date.today()
    df['deadline'] = pd.to_datetime(df['deadline']).dt.date
    df['is_overdue'] = (df['deadline'] < today) & (df['status'] != 'Done')
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Tasks", len(df))
    m2.metric("Completed", len(df[df['status'] == 'Done']))
    m3.metric("Pending", len(df[df['status'] != 'Done']))
    m4.metric("Overdue 🚨", len(df[df['is_overdue'] == True]))
    st.markdown("---")

def display_attachment_preview(file_path, link_url):
    if link_url:
        st.markdown(f"🔗 **Link:** [{link_url}]({link_url})")
    if file_path and os.path.exists(file_path):
        file_ext = os.path.splitext(file_path)[1].lower()
        file_name = os.path.basename(file_path)
        if file_ext in ['.png', '.jpg', '.jpeg', '.gif']:
            st.image(file_path, caption=file_name, width=300)
        elif file_ext in ['.csv']:
            with st.expander(f"📊 Preview {file_name}"):
                try: st.dataframe(pd.read_csv(file_path).head(5))
                except: st.error("Error reading CSV")
        with open(file_path, "rb") as f:
            st.download_button(f"📥 Download {file_name}", f, file_name)

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Task Tracker Pro", layout="wide", page_icon="🔐")
    init_db()

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = None
        st.session_state['role'] = None

    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.markdown("<h1 style='text-align: center;'>🔐 Login</h1>", unsafe_allow_html=True)
            st.markdown("---")
            tab_login, tab_signup = st.tabs(["Login", "Register"])
            with tab_login:
                username = st.text_input("Username")
                password = st.text_input("Password", type='password')
                if st.button("Login", use_container_width=True):
                    user_result = login_user(username, password)
                    if user_result:
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = username
                        st.session_state['role'] = user_result[0][2]
                        update_last_active(username)
                        st.rerun()
                    else: st.error("Invalid Creds")
            with tab_signup:
                new_user = st.text_input("New Username")
                new_pass = st.text_input("New Password", type='password')
                new_role = st.selectbox("Role", ["Employee", "Manager"])
                if st.button("Create Account", use_container_width=True):
                    if create_user(new_user, new_pass, new_role): st.success("Created! Go to Login.")
                    else: st.warning("User exists.")

    else:
        update_last_active(st.session_state['username'])
        online_users = get_online_users()
        dept_list = get_list('departments')
        status_list = get_list('statuses')
        users_list = get_all_users_list()

        st.sidebar.write(f"👤 **{st.session_state['username']}** ({st.session_state['role']})")
        st.sidebar.markdown("**Online Colleagues:**")
        for u in online_users:
            if u != st.session_state['username']: st.sidebar.caption(f"🟢 {u}")
        if st.sidebar.button("Log Out"):
            st.session_state['logged_in'] = False; st.rerun()
        st.sidebar.markdown("---")

        st.sidebar.header("➕ Create Task")
        with st.sidebar.form("new_task_form", clear_on_submit=True):
            t_name = st.text_input("Task Name")
            t_dept = st.selectbox("Department", dept_list if dept_list else ["General"])
            if users_list: t_assignee = st.selectbox("Assign To", users_list)
            else: t_assignee = st.text_input("Assignee")
            t_status = st.selectbox("Initial Status", status_list if status_list else ["To Do"])
            t_deadline = st.date_input("Deadline")
            c1, c2 = st.columns(2)
            t_total = c1.number_input("Total Items", 1, 100, 5)
            t_completed = c2.number_input("Completed", 0, 100, 0)
            if st.form_submit_button("Add Task"):
                add_task(t_name, t_dept, t_assignee, t_status, t_deadline, t_total, t_completed)
                st.toast("Task Added!"); st.rerun()

        # --- DATA & FILTERING ---
        df = get_all_tasks()
        if st.session_state['role'] == "Employee":
             df = df[df['assignee'] == st.session_state['username']]

        st.title("📊 Lynx Bridge Task Tracker")
        tabs = ["📈 Dashboard", "👤 My Workspace"]
        if st.session_state['role'] == "Manager": tabs.append("🛠️ Admin Controls")
        current_tab = st.tabs(tabs)

        # --- TAB 1: DASHBOARD ---
        with current_tab[0]:
            if not df.empty:
                render_metrics(df)
                if st.session_state['role'] == "Manager": st.subheader("Global Overview")
                else: st.subheader("My Performance Overview")
                    
                c1, c2 = st.columns(2)
                c1.bar_chart(df['department'].value_counts())
                c2.bar_chart(df['status'].value_counts())
                
                # --- NEW: DISPLAY LIMIT CONTROL ---
                st.markdown("### 📄 Task List")
                col_ctrl1, col_ctrl2 = st.columns([1, 4])
                with col_ctrl1:
                    # Dropdown for limit
                    limit_options = [10, 20, 50, 100, "All"]
                    display_limit = st.selectbox("Rows to display:", limit_options, index=0)
                
                # Apply Limit Logic
                display_df = df.copy()
                if display_limit != "All":
                    display_df = display_df.head(int(display_limit))
                    st.caption(f"Showing top {len(display_df)} of {len(df)} tasks")
                else:
                    st.caption(f"Showing all {len(df)} tasks")
                
                # Display Table
                st.dataframe(display_df[['task_name', 'department', 'status', 'deadline', 'completed_items']], use_container_width=True)
            else:
                st.info("No tasks found.")

        # --- TAB 2: MY WORKSPACE ---
        with current_tab[1]:
            st.header(f"Active Tasks")
            if not df.empty:
                my_depts = df['department'].unique()
                for dept in my_depts:
                    st.markdown(f"### 📂 {dept} Department")
                    st.markdown("---")
                    dept_tasks = df[df['department'] == dept]
                    for idx, row in dept_tasks.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 2])
                            with c1:
                                st.subheader(row['task_name'])
                                st.caption(f"📅 Due: {row['deadline']}")
                                display_attachment_preview(row['file_path'], row['task_link'])
                            with c2:
                                st.write("**Progress**")
                                st.progress(int((row['completed_items']/row['total_items'])*100) if row['total_items']>0 else 0)
                                new_comp = st.number_input("Completed", 0, row['total_items'], row['completed_items'], key=f"n_{row['id']}")
                            with c3:
                                st.write("**Update**")
                                current_status_list = status_list.copy()
                                if row['status'] not in current_status_list: current_status_list.append(row['status'])
                                new_stat = st.selectbox("Status", current_status_list, index=current_status_list.index(row['status']), key=f"s_{row['id']}")
                                with st.expander("📎 Attach File/Link"):
                                    new_file = st.file_uploader("Upload", key=f"up_{row['id']}")
                                    new_link = st.text_input("Link URL", value=row['task_link'] if row['task_link'] else "", key=f"lnk_{row['id']}")
                                if st.button("Update Task", key=f"btn_{row['id']}"):
                                    final_path = None
                                    if new_file:
                                        final_path = os.path.join(UPLOAD_DIR, new_file.name)
                                        with open(final_path, "wb") as f: f.write(new_file.getbuffer())
                                    update_task_details(row['id'], new_stat, new_comp, final_path, new_link)
                                    st.success("Updated!"); st.rerun()
                    st.write("")
            else: st.info("No tasks found.")

        # --- TAB 3: ADMIN ---
        if st.session_state['role'] == "Manager":
            with current_tab[2]:
                st.header("Admin Controls")
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.subheader("Depts"); new_d = st.text_input("Add Dept")
                    if st.button("Add D"): add_item('departments', new_d); st.rerun()
                    for d in dept_list: 
                        if st.button(f"🗑️ {d}", key=f"dd_{d}"): delete_item('departments', d); st.rerun()
                with ac2:
                    st.subheader("Statuses"); new_s = st.text_input("Add Status")
                    if st.button("Add S"): add_item('statuses', new_s); st.rerun()
                    for s in status_list:
                        if st.button(f"🗑️ {s}", key=f"ds_{s}"): delete_item('statuses', s); st.rerun()
                with ac3:
                    st.subheader("Users"); 
                    for u in users_list:
                        st.write(u)
                        if u != st.session_state['username']:
                            if st.button(f"🗑️ Delete {u}", key=f"du_{u}"): delete_user(u); st.rerun()

if __name__ == "__main__":
    main()