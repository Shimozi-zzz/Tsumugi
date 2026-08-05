@echo off
rem ============================================================
rem  Tsumugi 打包脚本（Windows）
rem  产物：frontend/release/Tsumugi Setup *.exe
rem  步骤：
rem    1. PyInstaller 打包后端 -> ../dist/tsumugi-backend/
rem    2. vite build 前端     -> ../frontend/dist/
rem    3. electron-builder     -> ../frontend/release/
rem  注意：PyInstaller 打包 chromadb/onnxruntime 非常耗时（>15 分钟），
rem  请确保磁盘空间充足（需 >5GB）。保持本文件 ASCII 编码。
rem ============================================================
chcp 65001 >nul
setlocal

cd /d "%~dp0\.."

rem ---- 1. 检查环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run install first.
    pause
    exit /b 1
)

rem ---- 2. PyInstaller 打包后端 ----
echo [INFO] Step 1/3: PyInstaller backend (this takes a while)...
.venv\Scripts\python.exe -m PyInstaller scripts/backend.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    pause
    exit /b 1
)

rem ---- 3. 前端 build ----
echo [INFO] Step 2/3: Vite build frontend...
pushd frontend
call npm run build
if errorlevel 1 (
    echo [ERROR] Vite build failed.
    popd
    pause
    exit /b 1
)
popd

rem ---- 4. electron-builder ----
echo [INFO] Step 3/3: electron-builder...
pushd frontend
call npm run dist
if errorlevel 1 (
    echo [ERROR] electron-builder failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo [INFO] Build complete. Installer: frontend\release\Tsumugi Setup *.exe
endlocal
