@echo off
setlocal
cd /d %~dp0

where pnpm >nul 2>nul
if errorlevel 1 (
  echo pnpm not found. Please enable corepack or install pnpm first.
  exit /b 1
)

python --version >nul 2>nul
if errorlevel 1 (
  echo Python not found.
  exit /b 1
)

echo Building frontend...
call pnpm --dir frontend install --frozen-lockfile
if errorlevel 1 exit /b 1
call pnpm --dir frontend build
if errorlevel 1 exit /b 1

echo Installing build dependencies...
python -m pip install -r backend\requirements-build.txt
if errorlevel 1 exit /b 1

echo Packaging backend server...
python -m PyInstaller --noconfirm AI-Comic-Generator.spec
if errorlevel 1 exit /b 1

echo Done. Run dist\AI-Comic-Generator\AI-Comic-Generator.exe and open http://127.0.0.1:8000
