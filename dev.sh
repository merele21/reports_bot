#!/bin/bash
watchmedo auto-restart --patterns="*.py" --recursive --ignore-dirs=".venv;__pycache__" -- python3 -m bot.main