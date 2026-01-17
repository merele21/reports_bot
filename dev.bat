@echo off
watchmedo auto-restart --patterns="*.py" --recursive --ignore-dirs=".venv;__pycache__" -- python -m bot.main
pause