# dev.sh (Linux/macOS)
# ============================================
#!/bin/bash

echo "Starting bot with hot reload..."
echo "Press Ctrl+C to stop"

# Установка watchdog если не установлен
if ! command -v watchmedo &> /dev/null
then
    echo "Installing watchdog..."
    pip install watchdog
fi

watchmedo auto-restart \
  --patterns="*.py" \
  --recursive \
  --ignore-patterns="*/__pycache__/*;*/.venv/*;*/venv/*;*/.git/*;*/data/*" \
  -- python3 -m bot.main

# ============================================
# Makefile.vps (альтернатива для удобного запуска)
# ============================================
.PHONY: dev run migrate clean install help

help:
	@echo "Available commands:"
	@echo "  make dev       - Run bot with hot reload"
	@echo "  make run       - Run bot normally"
	@echo "  make migrate   - Run database migrations"
	@echo "  make clean     - Clean cache files"
	@echo "  make install   - Install dependencies"

dev:
	@echo "🔥 Starting bot with hot reload..."
	@watchmedo auto-restart \
		--patterns="*.py" \
		--recursive \
		--ignore-patterns="*/__pycache__/*;*/.venv/*" \
		-- python -m bot.main

run:
	@echo "🤖 Starting bot..."
	@python -m bot.main

migrate:
	@echo "🔄 Running migrations..."
	@python migrate_db.py

clean:
	@echo "🧹 Cleaning cache files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cache cleaned"

install:
	@echo "📦 Installing dependencies..."
	@pip install -r requirements.txt
	@echo "✅ Dependencies installed"