@echo off
setlocal EnableExtensions
title AssistiveGraspAnnotator Web

cd /d "%~dp0"

echo.
echo === AssistiveGraspAnnotator Web ===
echo Working directory:
echo   %CD%
echo.

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo [1/4] Checking project virtual environment...
if not exist "%PYTHON_EXE%" (
  echo   .venv not found. Creating local virtual environment:
  echo   %VENV_DIR%
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv "%VENV_DIR%"
  ) else (
    python -m venv "%VENV_DIR%"
  )
  if errorlevel 1 (
    echo.
    echo Failed to create .venv. Install Python 3.10+ and run this file again.
    pause
    exit /b 1
  )
)

if not exist "%PYTHON_EXE%" (
  echo.
  echo Could not find venv Python:
  echo   %PYTHON_EXE%
  pause
  exit /b 1
)

echo   Using:
echo   %PYTHON_EXE%
%PYTHON_EXE% --version

echo.
echo [2/4] Checking backend dependencies...
%PYTHON_EXE% -c "import fastapi, uvicorn, pydantic, multipart, PIL, yaml, numpy" >nul 2>nul
if errorlevel 1 (
  echo Missing Python packages. Installing into project .venv only...
  %PYTHON_EXE% -m pip install --disable-pip-version-check -r "%~dp0requirements-web.txt"
  if errorlevel 1 (
    echo.
    echo Failed to install Python dependencies into .venv.
    pause
    exit /b 1
  )
)

if not exist "%~dp0web_frontend\dist\index.html" (
  echo.
  echo [3/4] Frontend build not found. Building web UI...
  where npm >nul 2>nul
  if errorlevel 1 (
    echo npm was not found. Install Node.js first, then run this file again.
    pause
    exit /b 1
  )
  pushd "%~dp0web_frontend"
  if not exist "node_modules" (
    call npm install
    if errorlevel 1 (
      popd
      pause
      exit /b 1
    )
  )
  call npm run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
) else (
  echo.
  echo [3/4] Frontend build already exists.
)

echo.
echo [4/4] Starting local web service...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_web.ps1" -PythonExe "%PYTHON_EXE%"
if errorlevel 1 (
  echo.
  echo Failed to start AssistiveGraspAnnotator Web.
  pause
  exit /b 1
)

echo.
echo Ready. AssistiveGraspAnnotator Web is running:
echo   http://127.0.0.1:8000/
echo.
echo Dataset library:
echo   D:\AssistiveGraspAnnotatorData\datasets
echo.
start "" "http://127.0.0.1:8000/"
pause
