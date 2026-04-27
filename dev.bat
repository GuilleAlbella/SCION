@echo off
cd /d "%~dp0"
cd frontend
npx concurrently -n backend,frontend -c blue,green "cd /d \"%~dp0backend\" && \"%~dp0.venv\Scripts\python.exe\" -m uvicorn app.main:app --reload --port 8000" "npx next dev"
