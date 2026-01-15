import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
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
    
    # 1. Tasks Table (Updated Schema)
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
    
    # MIGRATION: Attempt to add task_link column if it doesn't exist (for existing users)
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN task_link TEXT")
    except sqlite3.OperationalError:
        pass # Column likely already exists

    # 2. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT
                )''')

    # 3. Departments & Statuses
    c.execute('''CREATE TABLE IF NOT EXISTS departments (name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (name TEXT PRIMARY KEY)''')

    # Seed Initial Data
    c.execute('SELECT count(*) FROM departments')
    if c.fetchone()[0] == 0:
        depts = [("Engineering",), ("HR",), ("Sales",), ("Marketing",), ("Operations",)]
        c.executemany('INSERT INTO departments VALUES (?)', depts)
        
    c.execute('SELECT count(*) FROM statuses')
    if c.fetchone()[0] == 0:
        stats = [("To Do",), ("In Progress",), ("Review",), ("Done",)]
        c.executemany('INSERT INTO statuses VALUES (?)', stats)

    conn.commit()
    conn.close()

# --- GENERIC DATA FUNCTIONS ---
def get_list(table_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'SELECT name FROM {table_name}')
    data = [item[0] for item in c.fetchall()]
    conn.close()
    return data

def add_item(table_name, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(f'INSERT INTO {table_name} (name) VALUES (?)', (value,))
        conn.commit()
        success = True
    except:
        success = False
    conn.close()
    return success

def delete_item(table_name, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'DELETE FROM {table_name} WHERE name = ?', (value,))
    conn.commit()
    conn.close()

# --- USER FUNCTIONS ---
def create_user(username, password, role="Employee"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users(username, password, role) VALUES (?,?,?)', 
                  (username, make_hashes(password), role))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def delete_user(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = ?', (username,))
    conn.commit()
    conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
              (username, make_hashes(password)))
    data = c.fetchall()
    conn.close()
    return data

def get_all_users_list():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT username FROM users')
    return [u[0] for u in c.fetchall()]

# --- TASK FUNCTIONS ---
def add_task(task_name, department, assignee, status, deadline, total, completed, file_path, task_link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO tasks 
                 (task_name, department, assignee, status, deadline, total_items, completed_items, file_path, task_link) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                 (task_name, department, assignee, status, deadline, total, completed, file_path, task_link))
    conn.commit()
    conn.close()

def get_all_tasks():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM tasks", conn)
    conn.close()
    return df

def update_task_progress(task_id, new_status, new_completed_items):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = ?, completed_items = ? WHERE id = ?", 
              (new_status, new_completed_items, task_id))
    conn.commit()
    conn.close()

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
    """Smart viewer for files and links"""
    
    # 1. Handle Links
    if link_url:
        st.markdown(f"🔗 **External Link:** [{link_url}]({link_url})")

    # 2. Handle Files
    if file_path and os.path.exists(file_path):
        file_ext = os.path.splitext(file_path)[1].lower()
        file_name = os.path.basename(file_path)
        
        # A. Images (Show directly)
        if file_ext in ['.png', '.jpg', '.jpeg', '.gif']:
            st.image(file_path, caption=f"Attached Image: {file_name}", use_container_width=True)
            
        # B. CSV/Excel (Show data table)
        elif file_ext in ['.csv']:
            with st.expander(f"📊 Preview Data: {file_name}"):
                try:
                    preview_df = pd.read_csv(file_path)
                    st.dataframe(preview_df.head(10)) # Show first 10 rows
                    st.caption("Showing first 10 rows only.")
                except:
                    st.error("Could not preview CSV.")
        
        # C. Default (Download Button)
        # We also show download button for images/csvs just in case
        with open(file_path, "rb") as f:
            st.download_button(
                label=f"📥 Download {file_name}",
                data=f,
                file_name=file_name,
                mime="application/octet-stream"
            )

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Task Tracker Pro", layout="wide", page_icon="🔐")
    init_db()

    # Session State
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = None
        st.session_state['role'] = None

    # --- LOGIN SCREEN ---
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
                        st.rerun()
                    else:
                        st.error("Invalid Username or Password")

            with tab_signup:
                new_user = st.text_input("New Username")
                new_pass = st.text_input("New Password", type='password')
                new_role = st.selectbox("Role", ["Employee", "Manager"])
                if st.button("Create Account", use_container_width=True):
                    if create_user(new_user, new_pass, new_role):
                        st.success("Account Created! Go to Login.")
                    else:
                        st.warning("User already exists.")

    # --- LOGGED IN DASHBOARD ---
    else:
        dept_list = get_list('departments')
        status_list = get_list('statuses')
        users_list = get_all_users_list()

        # SIDEBAR
        st.sidebar.write(f"👤 **{st.session_state['username']}** ({st.session_state['role']})")
        if st.sidebar.button("Log Out"):
            st.session_state['logged_in'] = False
            st.rerun()
        st.sidebar.markdown("---")

        # Add Task Form
        st.sidebar.header("➕ Create Task")
        with st.sidebar.form("new_task_form", clear_on_submit=True):
            t_name = st.text_input("Task Name")
            t_dept = st.selectbox("Department", dept_list if dept_list else ["General"])
            if users_list:
                t_assignee = st.selectbox("Assign To", users_list)
            else:
                t_assignee = st.text_input("Assignee")
            t_status = st.selectbox("Initial Status", status_list if status_list else ["To Do"])
            t_deadline = st.date_input("Deadline")
            
            c1, c2 = st.columns(2)
            t_total = c1.number_input("Total Sub-items", 1, 100, 5)
            t_completed = c2.number_input("Completed", 0, 100, 0)
            
            st.markdown("**Attachments**")
            t_file = st.file_uploader("Upload File (Img/CSV/PDF)")
            t_link = st.text_input("Or Paste Link (URL)")
            
            if st.form_submit_button("Add Task"):
                f_path = None
                if t_file:
                    f_path = os.path.join(UPLOAD_DIR, t_file.name)
                    with open(f_path, "wb") as f:
                        f.write(t_file.getbuffer())
                add_task(t_name, t_dept, t_assignee, t_status, t_deadline, t_total, t_completed, f_path, t_link)
                st.toast("Task Added!")
                st.rerun()

        # MAIN CONTENT
        st.title("📊 Enterprise Task Tracker")
        
        tabs = ["📈 Dashboard", "👤 My Workspace"]
        if st.session_state['role'] == "Manager":
            tabs.append("🛠️ Admin Controls")
        
        current_tab = st.tabs(tabs)
        df = get_all_tasks()

        # --- TAB 1: DASHBOARD ---
        with current_tab[0]:
            if not df.empty:
                render_metrics(df)
                c1, c2 = st.columns(2)
                c1.subheader("By Department")
                c1.bar_chart(df['department'].value_counts())
                c2.subheader("By Assignee")
                c2.bar_chart(df['assignee'].value_counts())
                
                st.markdown("### All Tasks")
                st.dataframe(df.drop(columns=['file_path']), use_container_width=True)
            else:
                st.info("No tasks found.")

        # --- TAB 2: MY WORKSPACE ---
        with current_tab[1]:
            st.header(f"Tasks for {st.session_state['username']}")
            if not df.empty:
                my_tasks = df[df['assignee'] == st.session_state['username']].copy()
                if not my_tasks.empty:
                    for idx, row in my_tasks.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 2])
                            with c1:
                                st.subheader(row['task_name'])
                                st.caption(f"Deadline: {row['deadline']} | {row['department']}")
                                
                                # --- NEW: DISPLAY PREVIEW ---
                                st.markdown("---")
                                display_attachment_preview(row['file_path'], row['task_link'])
                                
                            with c2:
                                st.progress(int((row['completed_items']/row['total_items'])*100) if row['total_items']>0 else 0)
                                new_comp = st.number_input("Completed", 0, row['total_items'], row['completed_items'], key=f"n_{row['id']}")
                            with c3:
                                current_status_list = status_list.copy()
                                if row['status'] not in current_status_list:
                                    current_status_list.append(row['status'])
                                new_stat = st.selectbox("Status", current_status_list, index=current_status_list.index(row['status']), key=f"s_{row['id']}")
                                if st.button("Update", key=f"b_{row['id']}"):
                                    update_task_progress(row['id'], new_stat, new_comp)
                                    st.rerun()
                else:
                    st.info("No tasks assigned to you.")

        # --- TAB 3: ADMIN CONTROLS ---
        if st.session_state['role'] == "Manager":
            with current_tab[2]:
                st.header("🛠️ Admin Configuration")
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.subheader("Depts")
                    new_dept = st.text_input("Add Dept")
                    if st.button("Add Dept"):
                        if new_dept: add_item('departments', new_dept); st.rerun()
                    for d in dept_list:
                        c_a, c_b = st.columns([3, 1])
                        c_a.write(d)
                        if c_b.button("🗑️", key=f"del_d_{d}"): delete_item('departments', d); st.rerun()
                with ac2:
                    st.subheader("Statuses")
                    new_stat = st.text_input("Add Status")
                    if st.button("Add Status"):
                        if new_stat: add_item('statuses', new_stat); st.rerun()
                    for s in status_list:
                        c_a, c_b = st.columns([3, 1])
                        c_a.write(s)
                        if c_b.button("🗑️", key=f"del_s_{s}"): delete_item('statuses', s); st.rerun()
                with ac3:
                    st.subheader("Users")
                    for u in users_list:
                        c_a, c_b = st.columns([3, 1])
                        c_a.write(u)
                        if u != st.session_state['username']:
                            if c_b.button("🗑️", key=f"del_u_{u}"): delete_user(u); st.rerun()

if __name__ == "__main__":
    main()