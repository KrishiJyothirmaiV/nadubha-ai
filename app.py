import sqlite3
import time
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from adhd_hub import (
    OBSTACLES,
    generate_plan,
    render_adhd_hub,
    setup_database,
)


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

DB = ROOT / "nadubha.db"

if not DB.exists() and (ROOT / "focusnest.db").exists():
    DB = ROOT / "focusnest.db"

st.set_page_config(
    page_title="NaDuBha AI",
    page_icon="🧠",
    layout="wide",
)


# ==================================================
# DATABASE
# ==================================================

def connection():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    return con


def query(sql, args=()):
    with connection() as con:
        return [
            dict(row)
            for row in con.execute(sql, args)
        ]


def execute(sql, args=()):
    with connection() as con:
        cursor = con.execute(sql, args)
        return cursor.lastrowid


def now():
    return datetime.now().isoformat(
        timespec="seconds"
    )


def init_db():
    with connection() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'To do',
                created_at TEXT NOT NULL
            )
        """)

        columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(tasks)"
            )
        }

        additions = {
            "priority": "TEXT DEFAULT 'Medium'",
            "notes": "TEXT DEFAULT ''",
            "due_date": "TEXT",
            "estimated_minutes": "INTEGER DEFAULT 25",
            "project_id": "INTEGER",
            "completed_at": "TEXT",
        }

        
        for name, definition in additions.items():
            existing_columns = {
                row[1]
                for row in con.execute("PRAGMA table_info(tasks)")
            }

            if name not in existing_columns:
                try:
                    con.execute(
                        f"ALTER TABLE tasks ADD COLUMN {name} {definition}"
            )
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise

        con.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS habit_checks (
                habit_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                PRIMARY KEY(habit_id, day)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS wellness (
                day TEXT PRIMARY KEY,
                mood INTEGER,
                energy INTEGER,
                note TEXT
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_due
            ON tasks(due_date)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_project
            ON tasks(project_id)
        """)

    setup_database(DB)


init_db()


def get_tasks():
    return query(
        "SELECT * FROM tasks ORDER BY id DESC"
    )


def get_projects():
    return query(
        "SELECT * FROM projects ORDER BY id DESC"
    )


def create_task(
    title,
    priority="Medium",
    minutes=25,
    due_date=None,
    notes="",
    project_id=None,
):
    if not title.strip():
        return None

    return execute(
        """
        INSERT INTO tasks
        (title, status, priority,
         estimated_minutes, due_date,
         notes, project_id, created_at)
        VALUES (?, 'To do', ?, ?, ?, ?, ?, ?)
        """,
        (
            title.strip(),
            priority,
            int(minutes),
            due_date,
            notes,
            project_id,
            now(),
        ),
    )


def update_status(task_id, status):
    completed_at = (
        now() if status == "Done" else None
    )

    execute(
        """
        UPDATE tasks
        SET status=?, completed_at=?
        WHERE id=?
        """,
        (
            status,
            completed_at,
            task_id,
        ),
    )


def task_score(task):
    priority = {
        "High": 3,
        "Medium": 2,
        "Low": 1,
    }.get(task.get("priority"), 2)

    if task["status"] == "Doing":
        priority += 2

    try:
        due = date.fromisoformat(
            task["due_date"][:10]
        )
        days = (
            due - date.today()
        ).days

        if days < 0:
            priority += 5
        elif days == 0:
            priority += 4
        elif days <= 2:
            priority += 2

    except (ValueError, TypeError):
        pass

    return priority


def schedule_tasks(pending_tasks, available):
    remaining = available
    schedule = []

    ranked = sorted(
        pending_tasks,
        key=task_score,
        reverse=True,
    )

    for task in ranked:
        estimate = max(
            5,
            int(
                task.get("estimated_minutes")
                or 25
            ),
        )

        if estimate > remaining:
            continue

        schedule.append({
            "task": task["title"],
            "minutes": estimate,
            "type": "task",
        })

        remaining -= estimate

        if remaining >= 5:
            schedule.append({
                "task": "Short break",
                "minutes": 5,
                "type": "break",
            })
            remaining -= 5

    return schedule, remaining


# ==================================================
# THEME
# ==================================================

st.markdown("""
<style>
.stApp {
    background: #09090D;
    color: #F7F2F4;
}
[data-testid="stSidebar"] {
    background: #121217;
    border-right: 1px solid #492632;
}
[data-testid="stMetric"] {
    background: #19191F;
    padding: 18px;
    border: 1px solid #49303A;
    border-radius: 16px;
}
[data-testid="stMetricValue"] {
    color: #FF536B;
}
.stApp input,
.stApp textarea,
.stApp [data-baseweb="input"],
.stApp [data-baseweb="textarea"],
.stApp [data-baseweb="select"] > div {
    background-color: #202027 !important;
    color: #FFFFFF !important;
}
.stApp input,
.stApp textarea {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}
.stApp input::placeholder,
.stApp textarea::placeholder {
    color: #AAA0A7 !important;
    -webkit-text-fill-color: #AAA0A7 !important;
}
[data-baseweb="popover"],
[data-baseweb="menu"],
[role="listbox"] {
    background: #202027 !important;
    color: white !important;
}
.stButton button {
    border-radius: 10px;
}
.stButton button[kind="primary"] {
    background: #D92B47 !important;
    color: white !important;
    border-color: #D92B47 !important;
}
.hero {
    padding: 30px;
    background: linear-gradient(
        110deg, #330D19, #7B1930, #22121B
    );
    border-radius: 20px;
    margin-bottom: 25px;
}
.hero h1 {
    color: white;
    margin: 0;
}
.hero p {
    color: #FFD0D9;
}
</style>
""", unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(
        f"""
        <div class="hero">
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==================================================
# NAVIGATION
# ==================================================

PAGES = [
    "Dashboard",
    "Tasks",
    "Projects",
    "Kanban",
    "AI Coach",
    "Smart Planner",
    "Focus Studio",
    "Habits",
    "Wellness",
    "ADHD Support Hub",
    "Analytics",
]

ICONS = {
    "Dashboard": "🏠",
    "Tasks": "📋",
    "Projects": "📁",
    "Kanban": "🗂️",
    "AI Coach": "✨",
    "Smart Planner": "📅",
    "Focus Studio": "⏱️",
    "Habits": "🔁",
    "Wellness": "🌿",
    "ADHD Support Hub": "🧠",
    "Analytics": "📊",
}

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

with st.sidebar:
    st.title("🔴 NaDuBha AI")
    st.caption("AI Productivity OS")
    st.divider()

    for page in PAGES:
        if st.button(
            f"{ICONS[page]} {page}",
            key=f"nav_{page}",
            use_container_width=True,
            type=(
                "primary"
                if st.session_state.page == page
                else "secondary"
            ),
        ):
            st.session_state.page = page
            st.rerun()

    st.divider()
    st.caption(
        "Progress over perfection."
    )
    st.caption(
        "Cloud AI requires explicit permission."
    )


# ==================================================
# SHARED DATA
# ==================================================

tasks = get_tasks()
projects = get_projects()

pending = [
    task
    for task in tasks
    if task["status"] != "Done"
]

completed = [
    task
    for task in tasks
    if task["status"] == "Done"
]

project_names = {
    project["id"]: project["name"]
    for project in projects
}


# ==================================================
# DASHBOARD
# ==================================================

if st.session_state.page == "Dashboard":

    hero(
        "Welcome to NaDuBha AI 🧠",
        "Your personal AI productivity workspace.",
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Total tasks",
        len(tasks),
    )
    b.metric(
        "Completed",
        len(completed),
    )
    c.metric(
        "Pending",
        len(pending),
    )
    d.metric(
        "Projects",
        len(projects),
    )

    st.subheader(
        "🔥 Priority Tasks"
    )

    ranked = sorted(
        pending,
        key=task_score,
        reverse=True,
    )

    if not ranked:
        st.info(
            "No pending tasks. "
            "Add your first task below."
        )

    for task in ranked[:5]:
        with st.container(border=True):
            left, right = st.columns(
                [4, 1]
            )

            left.write(
                f"**{task['title']}**"
            )

            left.caption(
                "Priority: "
                f"{task.get('priority') or 'Medium'}"
            )

            if right.button(
                "Complete",
                key=f"dash_done_{task['id']}",
            ):
                update_status(
                    task["id"],
                    "Done",
                )
                st.rerun()

    st.subheader(
        "Quick Capture"
    )

    with st.form(
        "quick_capture",
        clear_on_submit=True,
    ):
        title = st.text_input(
            "New task",
            placeholder=(
                "What do you want to accomplish?"
            ),
        )

        if st.form_submit_button(
            "Add task"
        ):
            if title.strip():
                create_task(title)
                st.rerun()
            else:
                st.warning(
                    "Enter a task title."
                )

    if tasks:
        st.progress(
            len(completed) / len(tasks),
            text=(
                f"{len(completed)} of "
                f"{len(tasks)} tasks completed"
            ),
        )


# ==================================================
# TASK MANAGER
# ==================================================

elif st.session_state.page == "Tasks":

    hero(
        "Task Manager 📋",
        "Organize and manage your responsibilities.",
    )

    with st.expander(
        "➕ Create New Task",
        expanded=True,
    ):
        with st.form(
            "create_task_form",
            clear_on_submit=True,
        ):
            title = st.text_input(
                "Task title"
            )

            a, b = st.columns(2)

            priority = a.selectbox(
                "Priority",
                ["Low", "Medium", "High"],
                index=1,
            )

            minutes = b.number_input(
                "Estimated minutes",
                min_value=5,
                max_value=480,
                value=25,
                step=5,
            )

            use_due = st.checkbox(
                "Add deadline"
            )

            due = (
                st.date_input("Deadline")
                if use_due
                else None
            )

            project_options = [None] + [
                p["id"] for p in projects
            ]

            project_id = st.selectbox(
                "Project",
                project_options,
                format_func=lambda value: (
                    project_names.get(
                        value, "Inbox"
                    )
                    if value is not None
                    else "Inbox"
                ),
            )

            notes = st.text_area(
                "Notes"
            )

            if st.form_submit_button(
                "Create Task",
                type="primary",
            ):
                if title.strip():
                    create_task(
                        title,
                        priority,
                        minutes,
                        (
                            due.isoformat()
                            if due
                            else None
                        ),
                        notes,
                        project_id,
                    )
                    st.rerun()
                else:
                    st.warning(
                        "Enter a task title."
                    )

    st.subheader(
        "Your Tasks"
    )

    search = st.text_input(
        "Search tasks"
    )

    status_filter = st.selectbox(
        "Filter by status",
        [
            "All",
            "To do",
            "Doing",
            "Done",
        ],
    )

    for task in tasks:
        if (
            search.lower()
            not in task["title"].lower()
        ):
            continue

        if (
            status_filter != "All"
            and task["status"] != status_filter
        ):
            continue

        with st.expander(
            task["title"]
        ):
            st.caption(
                f"Priority: {task.get('priority')} | "
                f"Due: "
                f"{task.get('due_date') or 'None'} | "
                f"Project: "
                f"{project_names.get(task.get('project_id'), 'Inbox')}"
            )

            st.write(
                task.get("notes") or ""
            )

            statuses = [
                "To do",
                "Doing",
                "Done",
            ]

            current_status = (
                task["status"]
                if task["status"] in statuses
                else "To do"
            )

            status = st.selectbox(
                "Status",
                statuses,
                index=statuses.index(
                    current_status
                ),
                key=f"task_status_{task['id']}",
            )

            if status != task["status"]:
                update_status(
                    task["id"],
                    status,
                )
                st.rerun()

            if st.button(
                "Delete task",
                key=f"task_delete_{task['id']}",
            ):
                st.session_state[
                    "delete_task_id"
                ] = task["id"]

            if (
                st.session_state.get(
                    "delete_task_id"
                ) == task["id"]
            ):
                st.warning(
                    "Are you sure you want "
                    "to delete this task?"
                )

                yes, no = st.columns(2)

                if yes.button(
                    "Confirm delete",
                    key=f"confirm_delete_{task['id']}",
                ):
                    execute(
                        """
                        DELETE FROM tasks
                        WHERE id=?
                        """,
                        (task["id"],),
                    )

                    st.session_state.pop(
                        "delete_task_id",
                        None,
                    )
                    st.rerun()

                if no.button(
                    "Cancel",
                    key=f"cancel_delete_{task['id']}",
                ):
                    st.session_state.pop(
                        "delete_task_id",
                        None,
                    )
                    st.rerun()


# ==================================================
# PROJECT MANAGER
# ==================================================

elif st.session_state.page == "Projects":

    hero(
        "Project Workspace 📁",
        "Track bigger goals and related tasks.",
    )

    with st.form(
        "new_project",
        clear_on_submit=True,
    ):
        name = st.text_input(
            "Project name"
        )

        description = st.text_area(
            "Description"
        )

        if st.form_submit_button(
            "Create Project",
            type="primary",
        ):
            if name.strip():
                execute(
                    """
                    INSERT INTO projects
                    (name, description, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        name.strip(),
                        description,
                        now(),
                    ),
                )
                st.rerun()
            else:
                st.warning(
                    "Enter a project name."
                )

    for project in projects:
        related = [
            task
            for task in tasks
            if (
                task.get("project_id")
                == project["id"]
            )
        ]

        finished = sum(
            task["status"] == "Done"
            for task in related
        )

        with st.container(border=True):
            st.subheader(
                project["name"]
            )

            st.write(
                project.get("description") or ""
            )

            st.progress(
                (
                    finished / len(related)
                    if related
                    else 0
                ),
                text=(
                    f"{finished}/{len(related)} "
                    "tasks completed"
                ),
            )

            for task in related:
                marker = (
                    "✅"
                    if task["status"] == "Done"
                    else "○"
                )

                st.write(
                    f"{marker} {task['title']}"
                )


# ==================================================
# KANBAN BOARD
# ==================================================

elif st.session_state.page == "Kanban":

    hero(
        "Kanban Board 🗂️",
        "Visualize your task workflow.",
    )

    columns = st.columns(3)

    for col, status in zip(
        columns,
        ["To do", "Doing", "Done"],
    ):
        with col:
            st.subheader(status)

            for task in tasks:
                if task["status"] != status:
                    continue

                with st.container(border=True):
                    st.write(
                        f"**{task['title']}**"
                    )

                    st.caption(
                        task.get("priority")
                        or "Medium"
                    )

                    choices = [
                        value
                        for value in [
                            "To do",
                            "Doing",
                            "Done",
                        ]
                        if value != status
                    ]

                    new_status = st.selectbox(
                        "Move to",
                        choices,
                        key=f"kanban_{task['id']}",
                    )

                    if st.button(
                        "Move",
                        key=f"move_{task['id']}",
                    ):
                        update_status(
                            task["id"],
                            new_status,
                        )
                        st.rerun()


# ==================================================
# AI COACH
# ==================================================

elif st.session_state.page == "AI Coach":

    hero(
        "AI Productivity Coach ✨",
        "Create practical plans with cloud, local, or offline AI.",
    )

    task = st.text_area(
        "What do you need help with?",
        placeholder=(
            "Example: Build a Python analytics project."
        ),
        key="coach_task",
    )

    left, right = st.columns(2)

    minutes = left.slider(
        "Available time (minutes)",
        5,
        180,
        30,
        5,
        key="coach_minutes",
    )

    energy = right.selectbox(
        "Energy level",
        [
            "Very low",
            "Low",
            "Medium",
            "High",
        ],
        index=2,
        key="coach_energy",
    )

    obstacle = st.selectbox(
        "What's making this task difficult?",
        OBSTACLES,
        key="coach_obstacle",
    )

    mode = st.radio(
        "Choose your AI engine",
        [
            "Auto",
            "Gemini AI",
            "Local AI (Ollama)",
            "Smart Offline",
        ],
        horizontal=True,
        key="coach_engine",
    )

    allow_cloud = st.checkbox(
        "Allow sending this task to Gemini",
        value=False,
        key="coach_cloud_consent",
    )

    st.caption(
        "Auto uses Gemini only with permission, "
        "then Ollama, then Smart Offline."
    )

    if st.button(
        "Generate My Plan",
        type="primary",
        key="coach_generate",
    ):
        st.session_state.pop(
            "coach_plan",
            None,
        )

        st.session_state.pop(
            "coach_source",
            None,
        )

        st.session_state[
            "coach_errors"
        ] = []

        if not task.strip():
            st.warning(
                "Please enter a task."
            )
        else:
            with st.spinner(
                "Creating your plan..."
            ):
                plan, source, errors = generate_plan(
                    task=task,
                    obstacle=obstacle,
                    energy=energy,
                    minutes=minutes,
                    mode=mode,
                    allow_cloud=allow_cloud,
                    db_path=DB,
                )

            st.session_state[
                "coach_plan"
            ] = plan

            st.session_state[
                "coach_source"
            ] = source

            st.session_state[
                "coach_errors"
            ] = errors

            st.session_state[
                "coach_plan_task"
            ] = task.strip()

            st.session_state[
                "coach_elapsed"
            ] = st.session_state.get(
                "nd_last_ai_seconds",
                0,
            )

    plan = st.session_state.get(
        "coach_plan"
    )

    if plan:
        st.divider()

        source = st.session_state.get(
            "coach_source",
            "Unknown",
        )

        elapsed = st.session_state.get(
            "coach_elapsed",
            0,
        )

        a, b, c = st.columns(3)

        a.metric(
            "AI Engine",
            source,
        )

        b.metric(
            "Generation Time",
            f"{elapsed:.2f}s",
        )

        c.metric(
            "Plan Steps",
            len(plan["steps"]),
        )

        st.subheader(
            "Your Personalized Plan"
        )

        st.success(
            plan["strategy"]
        )

        st.info(
            plan["instruction"]
        )

        total = sum(
            step["minutes"]
            for step in plan["steps"]
        )

        st.caption(
            f"Estimated duration: {total} minutes"
        )

        for index, step in enumerate(
            plan["steps"],
            1,
        ):
            with st.container(border=True):
                st.markdown(
                    f"**Step {index}:** "
                    f"{step['text']}"
                )

                st.caption(
                    "Estimated time: "
                    f"{step['minutes']} min"
                )

        lines = [
            (
                "Task: "
                + st.session_state.get(
                    "coach_plan_task",
                    "",
                )
            ),
            f"Strategy: {plan['strategy']}",
            "",
        ]

        lines.extend(
            (
                f"{i}. {step['text']} "
                f"({step['minutes']} min)"
            )
            for i, step in enumerate(
                plan["steps"],
                1,
            )
        )

        with st.expander(
            "Copy-ready plan"
        ):
            st.code(
                "\n".join(lines),
                language=None,
            )

    errors = st.session_state.get(
        "coach_errors",
        [],
    )

    if errors:
        with st.expander(
            "AI connection details"
        ):
            for error in errors:
                st.warning(error)

    if errors and not plan:
        st.info(
            "Try Auto or Smart Offline "
            "if the selected AI provider "
            "is unavailable."
        )


# ==================================================
# SMART PLANNER
# ==================================================

elif st.session_state.page == "Smart Planner":

    hero(
        "Smart Daily Planner 📅",
        "Plan your day based on priority and available time.",
    )

    available = st.slider(
        "Available minutes",
        15,
        480,
        120,
        15,
    )

    if st.button(
        "Generate Daily Schedule",
        type="primary",
    ):
        schedule, remaining = schedule_tasks(
            pending,
            available,
        )

        st.session_state[
            "daily_schedule"
        ] = schedule

        st.session_state[
            "daily_remaining"
        ] = remaining

    schedule = st.session_state.get(
        "daily_schedule"
    )

    if schedule is not None:
        if not schedule:
            st.info(
                "No tasks fit the selected time. "
                "Try a smaller starting task."
            )
        else:
            st.subheader(
                "Today's Schedule"
            )

            for item in schedule:
                if item["type"] == "break":
                    st.caption(
                        f"☕ {item['task']} — "
                        f"{item['minutes']} min"
                    )
                else:
                    st.write(
                        f"**{item['task']}** — "
                        f"{item['minutes']} min"
                    )

            st.metric(
                "Unallocated time",
                (
                    f"{st.session_state.daily_remaining} "
                    "min"
                ),
            )

    st.caption(
        "This schedule uses priority and "
        "time estimates. It is rule-based, "
        "not generated by an LLM."
    )


# ==================================================
# FOCUS STUDIO
# ==================================================

elif st.session_state.page == "Focus Studio":

    hero(
        "Focus Studio ⏱️",
        "Stay focused one session at a time.",
    )

    duration = st.selectbox(
        "Focus duration",
        [5, 10, 15, 25, 45],
        index=3,
    )

    state = st.session_state

    state.setdefault(
        "focus_end",
        None,
    )
    state.setdefault(
        "focus_remaining",
        duration * 60,
    )
    state.setdefault(
        "focus_duration",
        duration,
    )
    state.setdefault(
        "focus_logged",
        False,
    )

    if (
        state.focus_end is None
        and state.focus_duration != duration
    ):
        state.focus_duration = duration
        state.focus_remaining = duration * 60
        state.focus_logged = False

    @st.fragment(run_every="1s")
    def focus_timer():
        end = state.focus_end

        if end is not None:
            remaining = max(
                0,
                int(
                    end - time.time() + 0.999
                ),
            )

            state.focus_remaining = remaining

            if remaining == 0:
                state.focus_end = None

                if not state.focus_logged:
                    execute(
                        """
                        INSERT INTO focus_sessions
                        (minutes, created_at)
                        VALUES (?, ?)
                        """,
                        (
                            state.focus_duration,
                            now(),
                        ),
                    )

                    state.focus_logged = True

                    st.success(
                        "Focus session complete!"
                    )

        remaining = state.focus_remaining

        st.title(
            f"{remaining // 60:02d}:"
            f"{remaining % 60:02d}"
        )

        st.progress(
            max(
                0.0,
                min(
                    1.0,
                    1 - remaining / max(
                        1,
                        state.focus_duration * 60,
                    ),
                ),
            )
        )

        a, b, c = st.columns(3)

        if a.button(
            "Start",
            key="focus_start",
        ):
            if (
                remaining == 0
                or state.focus_logged
            ):
                remaining = duration * 60
                state.focus_remaining = remaining
                state.focus_logged = False

            state.focus_end = (
                time.time() + remaining
            )

            st.rerun(
                scope="fragment"
            )

        if b.button(
            "Pause",
            key="focus_pause",
        ):
            if state.focus_end is not None:
                state.focus_remaining = max(
                    0,
                    int(
                        state.focus_end
                        - time.time()
                        + 0.999
                    ),
                )

                state.focus_end = None

            st.rerun(
                scope="fragment"
            )

        if c.button(
            "Reset",
            key="focus_reset",
        ):
            state.focus_end = None
            state.focus_remaining = duration * 60
            state.focus_logged = False

            st.rerun(
                scope="fragment"
            )

    focus_timer()


# ==================================================
# HABIT TRACKER
# ==================================================

elif st.session_state.page == "Habits":

    hero(
        "Habit Tracker 🔁",
        "Build small habits consistently.",
    )

    with st.form(
        "habit_form",
        clear_on_submit=True,
    ):
        title = st.text_input(
            "New habit"
        )

        if st.form_submit_button(
            "Add Habit"
        ):
            if title.strip():
                execute(
                    """
                    INSERT INTO habits
                    (title, created_at)
                    VALUES (?, ?)
                    """,
                    (
                        title.strip(),
                        now(),
                    ),
                )
                st.rerun()
            else:
                st.warning(
                    "Enter a habit."
                )

    habits = query(
        """
        SELECT *
        FROM habits
        ORDER BY id DESC
        """
    )

    today = date.today().isoformat()

    for habit in habits:
        checks = {
            row["day"]
            for row in query(
                """
                SELECT day
                FROM habit_checks
                WHERE habit_id=?
                """,
                (habit["id"],),
            )
        }

        checked = today in checks

        value = st.checkbox(
            habit["title"],
            value=checked,
            key=f"habit_{habit['id']}",
        )

        if value != checked:
            if value:
                execute(
                    """
                    INSERT OR IGNORE
                    INTO habit_checks
                    (habit_id, day)
                    VALUES (?, ?)
                    """,
                    (
                        habit["id"],
                        today,
                    ),
                )
            else:
                execute(
                    """
                    DELETE FROM habit_checks
                    WHERE habit_id=? AND day=?
                    """,
                    (
                        habit["id"],
                        today,
                    ),
                )

            st.rerun()

        streak = 0
        current = date.today()

        while current.isoformat() in checks:
            streak += 1
            current -= timedelta(days=1)

        st.caption(
            f"Current streak: {streak} days"
        )


# ==================================================
# WELLNESS
# ==================================================

elif st.session_state.page == "Wellness":

    hero(
        "Wellness Journal 🌿",
        "Reflect on your mood and energy.",
    )

    today = date.today().isoformat()

    existing = query(
        """
        SELECT *
        FROM wellness
        WHERE day=?
        """,
        (today,),
    )

    current = (
        existing[0]
        if existing
        else None
    )

    with st.form(
        "wellness_form"
    ):
        mood = st.slider(
            "Mood",
            1,
            5,
            (
                current["mood"]
                if (
                    current
                    and current["mood"] is not None
                )
                else 3
            ),
        )

        energy = st.slider(
            "Energy",
            1,
            5,
            (
                current["energy"]
                if (
                    current
                    and current["energy"] is not None
                )
                else 3
            ),
        )

        note = st.text_area(
            "Reflection",
            value=(
                (current["note"] or "")
                if current
                else ""
            ),
        )

        if st.form_submit_button(
            "Save Check-In"
        ):
            execute(
                """
                INSERT INTO wellness
                (day, mood, energy, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    mood=excluded.mood,
                    energy=excluded.energy,
                    note=excluded.note
                """,
                (
                    today,
                    mood,
                    energy,
                    note,
                ),
            )

            st.success(
                "Check-in saved."
            )

    history = query(
        """
        SELECT *
        FROM wellness
        ORDER BY day DESC
        """
    )

    if history:
        frame = pd.DataFrame(
            history
        ).sort_values("day")

        st.line_chart(
            frame.set_index(
                "day"
            )[["mood", "energy"]]
        )


# ==================================================
# ADHD SUPPORT HUB
# ==================================================

elif st.session_state.page == "ADHD Support Hub":

    render_adhd_hub(DB)


# ==================================================
# ANALYTICS
# ==================================================

elif st.session_state.page == "Analytics":

    hero(
        "Productivity Analytics 📊",
        "Explore your progress and focus patterns.",
    )

    focus_sessions = query(
        "SELECT * FROM focus_sessions"
    )

    adhd_sessions = query(
        "SELECT * FROM adhd_work_sessions"
    )

    standard_minutes = sum(
        int(session["minutes"])
        for session in focus_sessions
    )

    adhd_seconds = sum(
        int(
            session.get("completed_seconds")
            if (
                session.get("completed_seconds")
                is not None
            )
            else (
                session.get("completed_minutes")
                or 0
            ) * 60
        )
        for session in adhd_sessions
    )

    total_minutes = (
        standard_minutes
        + adhd_seconds / 60
    )

    total_sessions = (
        len(focus_sessions)
        + len(adhd_sessions)
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Tasks",
        len(tasks),
    )

    b.metric(
        "Completed",
        len(completed),
    )

    c.metric(
        "Focus sessions",
        total_sessions,
    )

    d.metric(
        "Focus minutes",
        round(total_minutes, 1),
    )

    if tasks:
        st.subheader(
            "Task Status"
        )

        frame = pd.DataFrame({
            "Status": [
                "To do",
                "Doing",
                "Done",
            ],
            "Count": [
                sum(
                    task["status"] == status
                    for task in tasks
                )
                for status in [
                    "To do",
                    "Doing",
                    "Done",
                ]
            ],
        })

        st.bar_chart(
            frame.set_index("Status")
        )

    activity = []

    for session in focus_sessions:
        activity.append({
            "day": (
                session["created_at"][:10]
            ),
            "minutes": float(
                session["minutes"]
            ),
        })

    for session in adhd_sessions:
        seconds = session.get(
            "completed_seconds"
        )

        if seconds is None:
            seconds = (
                session.get("completed_minutes")
                or 0
            ) * 60

        activity.append({
            "day": (
                session["created_at"][:10]
            ),
            "minutes": float(
                seconds
            ) / 60,
        })

    if activity:
        st.subheader(
            "Combined Focus Activity"
        )

        frame = pd.DataFrame(
            activity
        )

        daily = frame.groupby(
            "day"
        )["minutes"].sum()

        st.bar_chart(daily)

    st.subheader(
        "AI Engine Performance"
    )

    metrics = query(
        """
        SELECT provider,
               success,
               elapsed_seconds
        FROM ai_metrics
        ORDER BY id DESC
        LIMIT 500
        """
    )

    if metrics:
        frame = pd.DataFrame(
            metrics
        )

        summary = (
            frame.groupby("provider")
            .agg(
                Requests=(
                    "success",
                    "count",
                ),
                Successes=(
                    "success",
                    "sum",
                ),
                Average_seconds=(
                    "elapsed_seconds",
                    "mean",
                ),
            )
            .reset_index()
        )

        summary["Success_rate_%"] = (
            summary["Successes"]
            / summary["Requests"]
            * 100
        ).round(1)

        summary["Average_seconds"] = (
            summary["Average_seconds"]
            .round(2)
        )

        st.dataframe(
            summary,
            hide_index=True,
        )
    else:
        st.info(
            "Generate AI plans to see "
            "model performance."
        )

    st.subheader(
        "Data Export"
    )

    st.caption(
        "Exports are generated only when "
        "requested. Keep exported "
        "personal data private."
    )

    exports = {
        "Tasks": tasks,
        "Projects": projects,
        "Focus": focus_sessions,
        "ADHD Focus": adhd_sessions,
        "Habits": query(
            "SELECT * FROM habits"
        ),
    }

    for name, records in exports.items():
        if records:
            with st.expander(
                f"Export {name}"
            ):
                st.download_button(
                    f"Export {name} CSV",
                    pd.DataFrame(
                        records
                    ).to_csv(
                        index=False
                    ),
                    file_name=(
                        name.lower().replace(
                            " ", "_"
                        ) + ".csv"
                    ),
                    mime="text/csv",
                    key=f"download_{name}",
                )


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "NaDuBha AI | AI Productivity & "
    "ADHD-Friendly Support Platform"
)