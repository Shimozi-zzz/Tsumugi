@echo off
rem ============================================================
rem  Tsumugi quick start
rem  Usage:
rem    start.bat            -> web mode (backend + vite + browser)
rem    start.bat electron   -> client mode (Electron app, auto-manages backend)
rem  NOTE: keep this file ASCII-only. Chinese text saved as UTF-8
rem  will be garbled under cmd's default code page (936/GBK) and
rem  can break batch parsing. Use English text only.
rem ============================================================
chcp 65001 >nul
setlocal

cd /d "%~dp0"

rem ---- Port (single source of truth: TSUMUGI_PORT env var) ----
rem Change it here if you need a different port.
set "TSUMUGI_PORT=8001"

rem ---- 1. .env ----
if not exist ".env" (
    echo [WARN] .env not found, copying from .env.example
    copy ".env.example" ".env" >nul
    echo [WARN] Please edit .env and set DEEPSEEK_API_KEY before asking questions.
)

rem ---- 2. Python venv ----
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo   Create it first:
    echo     py -3.12 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

rem ---- 3. Frontend deps ----
if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

rem ---- 4. Mode branch ----
if /I "%~1"=="electron" goto :client
goto :web

:web
echo [INFO] Web mode: backend + vite + browser
echo [INFO] Starting backend on http://localhost:%TSUMUGI_PORT%
start "Tsumugi Backend" cmd /k "chcp 65001>nul && set TSUMUGI_PORT=%TSUMUGI_PORT% && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %TSUMUGI_PORT%"

echo [INFO] Starting frontend on http://localhost:4173
start "Tsumugi Frontend" cmd /k "chcp 65001>nul && set TSUMUGI_PORT=%TSUMUGI_PORT% && cd /d frontend && npm run dev"

rem Open browser
timeout /t 3 /nobreak >nul
start "" "http://localhost:4173"

echo.
echo [INFO] Tsumugi started (web mode). Keep the two console windows open.
endlocal
exit /b 0

:client
echo [INFO] Client mode: Electron (backend is auto-started by the app)
pushd frontend
call npm run electron
popd
endlocal
exit /b 0