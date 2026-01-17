@echo off
echo Starting bot with hot reload...
echo Press Ctrl+C to stop

watchmedo auto-restart ^
  --patterns="*.py" ^
  --recursive ^
  --ignore-patterns="*/__pycache__/*;*/.venv/*;*/venv/*;*/.git/*;*/data/*" ^
  -- python -m bot.main

pause