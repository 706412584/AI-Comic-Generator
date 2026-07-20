@echo off
cd /d %~dp0
python -m uvicorn app.bridge.ai_bridge:app --app-dir backend --host 127.0.0.1 --port 48721
