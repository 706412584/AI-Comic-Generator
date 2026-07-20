@echo off
cd /d %~dp0
python -m uvicorn app.bridge.mcp_http_server:app --app-dir backend --host 127.0.0.1 --port 48722
