@echo off
REM Starts everything: the SafeMine console + API, and Langfuse (tracing). Run after every reboot or Docker Desktop restart:
REM Docker does not bring the containers back by itself, and while Langfuse is down questions are NOT traced.
cd /d "%~dp0"
docker info >nul 2>&1 || (echo Docker Desktop is not running. Start it, wait until it says "Engine running", then run this again. & pause & exit /b 1)
echo Starting SafeMine console and API ...
docker compose up -d
echo Starting Langfuse (tracing) ...
cd observability
docker compose up -d
cd ..
echo.
echo   Console   http://localhost:8501   (login required)
echo   API docs  http://localhost:8000/docs
echo   Langfuse  http://localhost:3000   (login in observability\.env)
echo.
echo The console sidebar shows "Tracing: Langfuse connected" when traces are being recorded.
