import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, date, timedelta
import os
import hashlib
import time
import uuid
from streamlit import cache_data
from supabase import create_client, Client

# --- CONFIGURATION & SETUP ---
# We no longer use a local UPLOAD_DIR because Streamlit Cloud deletes it.

# --- SUPABASE STORAGE CONNECTION ---
def init_supabase():
    """Initialize Supabase Client for Storage"""
    # Try getting secrets from Streamlit's secret manager
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error("❌ Supabase Secrets missing! Add SUPABASE_URL and SUPABASE_KEY to .streamlit/secrets.toml")
        st.stop()

# --- FILE UPLOAD HELPER ---
def upload_file_to_supabase(uploaded_file):
    """Uploads a file to Supabase Storage and returns the Public URL"""
    if not uploaded_file:
        return None
    
    supabase = init_supabase()
    bucket_name = "task-files"
    
    # Create a unique filename (uuid) so files don't overwrite each other
    file_ext = os.path.splitext(uploaded_file.name)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    
    try:
        file_bytes = uploaded_file.getvalue()
        # Upload to Supabase Bucket
        supabase.storage.from_(bucket_name).upload(
            path=unique_filename, 
            file=file_bytes, 
            file_options={"content-type": uploaded_file.type}
        )
        # Get the Public URL so anyone with the link can view it
        public_url = supabase.storage.from_(bucket_name).get_public_url(unique_filename)
        return public_url
    except Exception as e:
        st.error(f"Upload Failed: {e}")
        return None

# --- DATABASE CONNECTION ---
def get_db_connection():
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

# --- CACHE DATA ---
@st.cache_data(ttl=60) 
def get_tasks(include_archived=False):
    conn = get_db_connection()
    query = "SELECT * FROM tasks" if include_archived else "SELECT * FROM tasks WHERE is_archived = 0"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- HELPER: DATE CALCULATOR ---
def get_next_schedule_date(start_date, frequency, days_list_str=None):
    if frequency == "Daily":
        return start_date + timedelta(days=1)
    elif frequency == "Weekly":
        return start_date + timedelta(weeks=1)
    elif frequency == "Monthly":
        return start_date + timedelta(days=30)
    elif frequency == "Specific Days" and days_list_str:
        day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        target_days = sorted([day_map[d] for d in days_list_str.split(',') if d in day_map])
        if not target_days: return start_date + timedelta(days=1) 
        current_weekday = start_date.weekday()
        for day_idx in target_days:
            if day_idx > current_weekday:
                return start_date + timedelta(days=(day_idx - current_weekday))
        days_ahead = (6 - current_weekday) + 1 + target_days[0]
        return start_date + timedelta(days=days_ahead)
    return start_date + timedelta(days=1)

# --- DATABASE FUNCTIONS ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Tasks
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    task_name TEXT,
                    department TEXT,
                    assignee TEXT,
                    status TEXT,
                    deadline DATE,
                    total_items INTEGER,
                    completed_items INTEGER,
                    description TEXT, 
                    file_path TEXT, 
                    task_link TEXT,
                    is_archived INTEGER DEFAULT 0
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    last_active TIMESTAMP
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS departments (name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (name TEXT PRIMARY KEY)''')

    c.execute('''CREATE TABLE IF NOT EXISTS recurring_templates (
                    id SERIAL PRIMARY KEY,
                    task_name TEXT,
                    department TEXT,
                    assignee TEXT,
                    frequency TEXT,
                    days_of_week TEXT, 
                    next_run_date DATE,
                    total_items INTEGER,
                    description TEXT,
                    task_link TEXT
                )''')
    
    # Migrations just in case
    try: c.execute("ALTER TABLE tasks ADD COLUMN description TEXT"); conn.commit()
    except: conn.rollback()
    
    conn.commit()
    
    # Seed Data
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

# --- RECURRING TASK PROCESSOR ---
def process_recurring_tasks():
    conn = get_db_connection()
    c = conn.cursor()
    today = date.today()
    c.execute("SELECT * FROM recurring_templates WHERE next_run_date <= %s", (today,))
    due_templates = c.fetchall()
    tasks_created = 0
    colnames = [desc[0] for desc in c.description]
    
    for row in due_templates:
        t = dict(zip(colnames, row))
        c.execute('''INSERT INTO tasks 
                     (task_name, department, assignee, status, deadline, total_items, completed_items, is_archived, description, task_link) 
                     VALUES (%s, %s, %s, %s, %s, %s, 0, 0, %s, %s)''', 
                     (t['task_name'], t['department'], t['assignee'], "To Do", t['next_run_date'], t['total_items'], t.get('description', ''), t['task_link']))
        new_date = get_next_schedule_date(t['next_run_date'], t['frequency'], t.get('days_of_week'))
        c.execute("UPDATE recurring_templates SET next_run_date = %s WHERE id = %s", (new_date, t['id']))
        tasks_created += 1

    conn.commit()
    conn.close()
    if tasks_created > 0:
        get_tasks.clear()
        return tasks_created
    return 0

# --- CORE FUNCTIONS ---
def run_auto_archive():
    conn = get_db_connection(); c = conn.cursor()
    cutoff_date = date.today() - timedelta(days=30)
    c.execute("UPDATE tasks SET is_archived = 1 WHERE status = 'Done' AND deadline < %s AND is_archived = 0", (cutoff_date,))
    count = c.rowcount; conn.commit(); conn.close()
    return count

def delete_task(task_id):
    conn = get_db_connection(); c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit(); conn.close()
    get_tasks.clear()

def get_list(table_name):
    conn = get_db_connection(); c = conn.cursor()
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

# --- ADD TASK WITH CLOUD UPLOAD ---
def add_task(task_name, department, assignee_list, status, deadline, total, completed, frequency="Once", days_list=None, task_link="", description="", uploaded_file=None):
    # 1. Upload File to Supabase (if exists)
    file_url = None
    if uploaded_file:
        file_url = upload_file_to_supabase(uploaded_file)
    
    conn = get_db_connection(); c = conn.cursor()
    
    if isinstance(assignee_list, list): assignee_str = ",".join(assignee_list)
    else: assignee_str = str(assignee_list)
    days_str = ",".join(days_list) if days_list else None
    
    # 2. Insert into DB (file_path is now file_url)
    c.execute('''INSERT INTO tasks 
                 (task_name, department, assignee, status, deadline, total_items, completed_items, is_archived, description, task_link, file_path) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)''', 
                 (task_name, department, assignee_str, status, deadline, total, completed, description, task_link, file_url))
    
    if frequency != "Once":
        next_run = get_next_schedule_date(deadline, frequency, days_str)
        c.execute('''INSERT INTO recurring_templates 
                     (task_name, department, assignee, frequency, days_of_week, next_run_date, total_items, description, task_link)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                     (task_name, department, assignee_str, frequency, days_str, next_run, total, description, task_link))

    conn.commit(); conn.close()
    get_tasks.clear()

# --- UPDATE TASK WITH CLOUD UPLOAD ---
def update_task_details(task_id, new_status, new_completed, new_link, new_desc, new_uploaded_file=None):
    # 1. Upload new file if provided
    new_file_url = None
    if new_uploaded_file:
        new_file_url = upload_file_to_supabase(new_uploaded_file)
        
    conn = get_db_connection(); c = conn.cursor()
    query = "UPDATE tasks SET status = %s, completed_items = %s, description = %s"
    params = [new_status, new_completed, new_desc]
    
    # Only update file_path if a new file was uploaded
    if new_file_url: 
        query += ", file_path = %s"
        params.append(new_file_url)
        
    if new_link: 
        query += ", task_link = %s"
        params.append(new_link)
    
    query += " WHERE id = %s"; params.append(task_id)
    c.execute(query, tuple(params)); conn.commit(); conn.close()
    get_tasks.clear()

def render_metrics(df):
    today = date.today()
    df['deadline'] = pd.to_datetime(df['deadline']).dt.date
    df['is_overdue'] = (df['deadline'] < today) & (df['status'] != 'Done')
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Tasks", len(df)); m2.metric("Completed", len(df[df['status'] == 'Done']))
    m3.metric("Pending", len(df[df['status'] != 'Done'])); m4.metric("Overdue 🚨", len(df[df['is_overdue'] == True]))
    st.markdown("---")

def display_attachment_preview(file_url, link_url):
    """Displays cloud files or links"""
    if link_url: st.markdown(f"🔗 **Link:** [{link_url}]({link_url})")
    
    # If we have a file_url (from Supabase), display it
    if file_url:
        st.markdown(f"📎 **Attached File:** [Download]({file_url})")
        # Try to preview images
        if any(ext in str(file_url).lower() for ext in ['.png', '.jpg', '.jpeg', '.gif']):
            st.image(file_url, width=200)

# --- DIALOGS ---
@st.dialog("Confirm Deletion")
def dialog_confirm_delete(item_type, item_name, delete_func, *args):
    st.write(f"Delete {item_type}: **{item_name}**?")
    st.warning("Cannot be undone.")
    if st.button("Yes, Delete", type="primary", use_container_width=True):
        with st.spinner(f"Deleting..."):
            delete_func(*args)
        st.success("Deleted!"); st.rerun()

@st.dialog("Confirm Task Creation")
def dialog_confirm_add(t_name, t_dept, t_assignee, t_status, t_deadline, t_total, t_completed, t_freq, t_days, t_link, t_desc, t_file):
    st.write("Review Details:")
    st.markdown(f"**Task:** {t_name}")
    st.markdown(f"**Assignee:** {t_assignee}")
    freq_msg = t_freq
    if t_freq == "Specific Days" and t_days: freq_msg = f"{t_freq} ({', '.join(t_days)})"
    st.markdown(f"**Frequency:** {freq_msg}")
    
    if t_file: st.markdown(f"**Attachment:** {t_file.name}")
    if t_desc:
        with st.expander("View Description"): st.write(t_desc)
    
    st.divider()
    if st.button("Confirm & Create", type="primary", use_container_width=True):
        with st.spinner("Uploading & Saving..."):
             add_task(t_name, t_dept, t_assignee, t_status, t_deadline, t_total, t_completed, t_freq, t_days, t_link, t_desc, t_file)
        st.success("Created!"); st.rerun()

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
    current_desc = row['description'] if row['description'] else ""
    st.markdown("#### 📝 Verbal Report / Description")
    new_desc = st.text_area("Update status, add notes, or describe issues:", value=current_desc, height=150)

    st.markdown("---")
    st.markdown("#### 📎 Attachments")
    # File uploader now goes to Cloud
    new_file = st.file_uploader("Upload New File (Overwrites old)")
    new_link = st.text_input("External Link URL", value=row['task_link'] if row['task_link'] else "")
    st.markdown("---")
    
    if st.button("💾 Save", type="primary", use_container_width=True):
        with st.spinner("Updating..."):
            # Update function now accepts the file object directly
            update_task_details(row['id'], new_stat, new_comp, new_link, new_desc, new_file)
        st.success("Updated!"); st.rerun()

@st.dialog("Confirm Logout")
def dialog_confirm_logout():
    st.write("Are you sure?")
    if st.button("Log Out", type="primary", use_container_width=True):
        with st.spinner("Logging out..."):
            time.sleep(0.5)
            st.session_state['logged_in'] = False; st.session_state['username'] = None; st.session_state['role'] = None; st.rerun()

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Lynx Tracker", layout="wide", page_icon="🔐")
    init_db()

    new_recurr = process_recurring_tasks()
    if new_recurr > 0: st.toast(f"🔄 Generated {new_recurr} recurring tasks!")
    if run_auto_archive() > 0: st.toast("🧹 Auto-Archived.")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False; st.session_state['username'] = None; st.session_state['role'] = None

    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.markdown("<h1 style='text-align: center;'>🔐 Login</h1>", unsafe_allow_html=True); st.markdown("---")
            tab_login, tab_signup = st.tabs(["Login", "Register"])
            with tab_login:
                u = st.text_input("Username"); p = st.text_input("Password", type='password')
                if st.button("Login", use_container_width=True):
                    with st.spinner("Verifying..."):
                        res = login_user(u, p); 
                        if not res: time.sleep(0.5)
                    if res: st.session_state['logged_in']=True; st.session_state['username']=u; st.session_state['role']=res[0][2]; update_last_active(u); st.rerun()
                    else: st.error("Invalid Creds")
            with tab_signup:
                nu = st.text_input("New User"); np = st.text_input("New Pass", type='password'); nr = st.selectbox("Role", ["Employee", "Manager"])
                if st.button("Create Account", use_container_width=True):
                    with st.spinner("Creating..."):
                        if create_user(nu, np, nr): st.success("Created! Login now.")
                        else: st.warning("Exists.")

    else:
        update_last_active(st.session_state['username'])
        online_users = get_online_users()
        dept_list = get_list('departments')
        status_list = get_list('statuses')
        users_list = get_all_users_list()

        st.sidebar.write(f"👤 **{st.session_state['username']}** ({st.session_state['role']})")
        st.sidebar.markdown("**Online:**"); 
        for u in online_users: 
            if u != st.session_state['username']: st.sidebar.caption(f"🟢 {u}")
        if st.sidebar.button("Log Out"): dialog_confirm_logout()
        st.sidebar.markdown("---")

        st.sidebar.header("➕ Create Task")
        
        tn = st.sidebar.text_input("Task Name")
        td = st.sidebar.selectbox("Dept", dept_list if dept_list else ["General"])
        if users_list: ta = st.sidebar.multiselect("Assign To", users_list)
        else: ta = st.sidebar.text_input("Assignee")
        freq = st.sidebar.selectbox("Frequency", ["Once", "Daily", "Weekly", "Monthly", "Specific Days"])
        days_selected = []
        if freq == "Specific Days":
            days_selected = st.sidebar.multiselect("Select Days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        ts = st.sidebar.selectbox("Status", status_list if status_list else ["To Do"])
        tdl = st.sidebar.date_input("Deadline")
        t_desc = st.sidebar.text_area("Description / Instructions")
        c1, c2 = st.sidebar.columns(2)
        tt = c1.number_input("Total", 1, 100, 5); tc = c2.number_input("Done", 0, 100, 0)
        t_link = st.sidebar.text_input("External Link")
        t_file = st.sidebar.file_uploader("Attach File (Permanent Cloud)")

        if st.sidebar.button("Add Task", type="primary"):
            dialog_confirm_add(tn, td, ta, ts, tdl, tt, tc, freq, days_selected, t_link, t_desc, t_file)

        show_archived = False
        if st.session_state['role'] == "Manager": show_archived = st.sidebar.checkbox("Show Archived")
        df = get_tasks(show_archived)
        
        st.title("📊 Lynx Task Tracker")
        tabs = ["📈 Dashboard", "👤 My Workspace"]
        if st.session_state['role'] == "Manager": tabs.append("🛠️ Admin")
        current_tab = st.tabs(tabs)

        with current_tab[0]:
            dash_df = df.copy()
            if st.session_state['role'] == "Employee":
                dash_df = df[df['assignee'].astype(str).apply(lambda x: st.session_state['username'] in [a.strip() for a in x.split(',')])]

            if not dash_df.empty:
                render_metrics(dash_df)
                c1, c2, c3 = st.columns(3)
                c1.subheader("By Dept"); c1.bar_chart(dash_df['department'].value_counts())
                c2.subheader("By Status"); c2.bar_chart(dash_df['status'].value_counts())
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

        with current_tab[1]:
            st.header("Active Tasks")
            selected_statuses = st.multiselect("Filter by Status:", options=status_list, default=status_list)
            
            work_df = df.copy()
            if st.session_state['role'] == "Employee":
                work_df = work_df[work_df['assignee'].astype(str).apply(lambda x: st.session_state['username'] in [a.strip() for a in x.split(',')])]
            
            if selected_statuses: work_df = work_df[work_df['status'].isin(selected_statuses)]
            else: work_df = work_df[0:0] 

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
                                assignees = str(row['assignee']).replace(",", ", ")
                                st.markdown(f"**👤 Assigned:** `{assignees}`")
                                if row['description']:
                                    with st.expander("📄 View Description/Report"): st.write(row['description'])
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
                                        dialog_confirm_delete("Task", row['task_name'], delete_task, row['id'])
                    st.write("")
            else: st.info("No tasks match your filters.")

        if st.session_state['role'] == "Manager":
            with current_tab[2]:
                st.header("Admin"); ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.subheader("Depts"); nd = st.text_input("New Dept")
                    if st.button("Add Dept", type="primary"): 
                        with st.spinner("Adding..."):
                            add_item('departments', nd); st.rerun()
                    for d in dept_list: 
                        if st.button(f"Delete {d}", key=f"d_{d}"): dialog_confirm_delete("Department", d, delete_item, 'departments', d)
                with ac2:
                    st.subheader("Statuses"); ns = st.text_input("New Status")
                    if st.button("Add Status", type="primary"): 
                        with st.spinner("Adding..."):
                            add_item('statuses', ns); st.rerun()
                    for s in status_list:
                         if st.button(f"Delete {s}", key=f"s_{s}"): dialog_confirm_delete("Status", s, delete_item, 'statuses', s)
                with ac3:
                    st.subheader("Users")
                    for u in users_list:
                        c_a, c_b = st.columns([2,1])
                        c_a.write(u)
                        if u != st.session_state['username']:
                             if c_b.button("🗑️", key=f"u_{u}"): dialog_confirm_delete("User", u, delete_user, u)

if __name__ == "__main__":
    main()