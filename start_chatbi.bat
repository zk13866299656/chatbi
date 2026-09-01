@echo off
REM ============================================
REM  ChatBI one-click launcher
REM  Backend : http://localhost:8000  (API docs: /docs)
REM  Frontend: http://localhost:5173
REM ============================================

cd /d E:\chatbi

echo [1/3] Stopping stale instances on port 8000 / 5173 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [2/3] Starting backend (http://localhost:8000) ...
start "ChatBI Backend" cmd /k "cd /d E:\chatbi\backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [3/3] Starting frontend (http://localhost:5173) ...
start "ChatBI Frontend" cmd /k "cd /d E:\chatbi\frontend && npm run dev"

echo Waiting for services to boot ...
ping -n 9 127.0.0.1 >nul
start http://localhost:5173
echo Done. Backend and frontend are running in their own windows.
echo Close those windows to stop the services.
