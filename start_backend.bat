@echo off
cd backend
echo Starting Backend...
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 58080
