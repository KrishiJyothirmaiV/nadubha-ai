# FocusNest AI
An ADHD-friendly productivity prototype, not a diagnostic or treatment tool.

## Setup (Windows PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `.env` and insert your Gemini API key. Do not commit `.env`.

## Run
```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8503
```
Open http://localhost:8503.

## Features
- SQLite-backed tasks with To do / Doing / Done status
- Gemini-generated tiny-step task breakdown
- Self-reported focus sessions (not a live timer)
- Progress metrics

## Privacy
The task list and focus session records are stored locally in `focusnest.db`. Task descriptions sent to Gemini for breakdown are transmitted to Google's API. Avoid entering sensitive information. Never commit `.env` or `focusnest.db`.
