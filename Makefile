.PHONY: help dev dev-bg stop logs shell test lint format clean

# Colors
RED    := $(shell tput -Txterm setaf 1)
GREEN  := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
BLUE   := $(shell tput -Txterm setaf 4)
PURPLE := $(shell tput -Txterm setaf 5)
CYAN   := $(shell tput -Txterm setaf 6)
RESET  := $(shell tput -Txterm sgr0)

# Variables
DOCKER_COMPOSE := docker-compose -f docker-compose.local.yml
PROJECT_NAME := report-bot-local

help: ## Show this help
	@echo '${GREEN}╔═══════════════════════════════════════════════════════╗${RESET}'
	@echo '${GREEN}║  Report Bot - Local Environment          			   ║${RESET}'
	@echo '${GREEN}╚═══════════════════════════════════════════════════════╝${RESET}'
	@echo ''
	@echo 'Usage:'
	@echo '  ${YELLOW}make${RESET} ${GREEN}<target>${RESET}'
	@echo ''
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?##.*$$/{printf "  ${YELLOW}%-20s${RESET} %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ''
	@echo '${CYAN}Service URLs:${RESET}'
	@echo '  ${BLUE}Bot Metrics:${RESET}     http://localhost:8000/metrics'
	@echo '  ${BLUE}Bot Health:${RESET}      http://localhost:8000/health'
	@echo '  ${BLUE}Grafana:${RESET}         http://localhost:3000 (admin/admin)'
	@echo '  ${BLUE}Prometheus:${RESET}      http://localhost:9090'
	@echo '  ${BLUE}Loki:${RESET}            http://localhost:3100'
	@echo '  ${BLUE}Alertmanager:${RESET}    http://localhost:9093'
	@echo '  ${BLUE}MailHog:${RESET}         http://localhost:8025'
	@echo '  ${BLUE}Redis Commander:${RESET} http://localhost:8081'
	@echo '  ${BLUE}Jaeger:${RESET}          http://localhost:16686'
	@echo '  ${BLUE}Portainer:${RESET}       http://localhost:9000'

## ==================== Local ====================
local: ## Start local environment (foreground)
	@echo "${GREEN}Starting local environment...${RESET}"
	$(DOCKER_COMPOSE) up

local-bg: ## Start local environment (background)
	@echo "${GREEN}Starting local environment in background...${RESET}"
	$(DOCKER_COMPOSE) up -d
	@sleep 3
	@make urls

stop: ## Stop all services
	@echo "${YELLOW}Stopping all services...${RESET}"
	$(DOCKER_COMPOSE) down

restart: ## Restart all services
	@echo "${YELLOW}Restarting services...${RESET}"
	$(DOCKER_COMPOSE) restart

restart-bot: ## Restart only bot
	@echo "${YELLOW}Restarting bot...${RESET}"
	$(DOCKER_COMPOSE) restart bot
	$(DOCKER_COMPOSE) logs -f bot

rebuild: ## Rebuild and restart
	@echo "${YELLOW}Rebuilding images...${RESET}"
	$(DOCKER_COMPOSE) build --no-cache
	$(DOCKER_COMPOSE) up -d

## ==================== Logs ====================
logs: ## Show all logs
	$(DOCKER_COMPOSE) logs -f

logs-bot: ## Show bot logs
	$(DOCKER_COMPOSE) logs -f bot

logs-prometheus: ## Show Prometheus logs
	$(DOCKER_COMPOSE) logs -f prometheus

logs-grafana: ## Show Grafana logs
	$(DOCKER_COMPOSE) logs -f grafana

## ==================== Shell Access ====================
shell: ## Open shell in bot container
	$(DOCKER_COMPOSE) exec bot /bin/bash

shell-redis: ## Open Redis CLI
	$(DOCKER_COMPOSE) exec redis redis-cli

ipython: ## Open IPython shell in bot context
	$(DOCKER_COMPOSE) exec bot ipython

## ==================== Database ====================
db-shell: ## Open SQLite shell
	$(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db

db-backup: ## Backup database
	@mkdir -p backups
	@echo "${GREEN}Creating backup...${RESET}"
	$(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db ".backup '/app/data/backup_$$(date +%Y%m%d_%H%M%S).db'"
	@echo "${GREEN}Backup created in data/ directory${RESET}"

db-restore: ## Restore database (arg: file=backup.db)
	@if [ -z "$(file)" ]; then \
		echo "${RED}Usage: make db-restore file=data/backup_XXX.db${RESET}"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db ".restore '$(file)'"
	@echo "${GREEN}Database restored from $(file)${RESET}"

migrate: ## Run database migrations
	$(DOCKER_COMPOSE) exec bot python migrate_db.py

## ==================== Testing ====================
test: ## Run tests
	@echo "${CYAN}Running tests...${RESET}"
	pytest tests/ -v --cov=bot --cov-report=html --cov-report=term

test-watch: ## Run tests in watch mode
	@echo "${CYAN}Running tests in watch mode...${RESET}"
	ptw tests/ -v

test-unit: ## Run only unit tests
	pytest tests/unit/ -v

test-integration: ## Run only integration tests
	pytest tests/integration/ -v

test-coverage: ## Generate coverage report
	pytest tests/ --cov=bot --cov-report=html
	@echo "${GREEN}Coverage report: htmlcov/index.html${RESET}"
	@python -m webbrowser htmlcov/index.html

## ==================== Code Quality ====================
lint: ## Run all linters
	@echo "${CYAN}Running linters...${RESET}"
	ruff check bot/
	mypy bot/ --ignore-missing-imports

lint-fix: ## Fix linting issues
	ruff check --fix bot/

format: ## Format code
	@echo "${CYAN}Formatting code...${RESET}"
	black bot/
	isort bot/

format-check: ## Check code formatting
	black --check bot/
	isort --check bot/

security: ## Run security checks
	@echo "${CYAN}Running security checks...${RESET}"
	bandit -r bot/ -ll
	safety check --json

all-checks: format lint test security ## Run all checks

## ==================== Debugging ====================
debug: ## Start bot with debugger attached
	@echo "${PURPLE}Starting bot with debugger on port 5678...${RESET}"
	@echo "${PURPLE}Attach your IDE debugger to localhost:5678${RESET}"
	$(DOCKER_COMPOSE) up bot

debug-logs: ## Show debug logs
	$(DOCKER_COMPOSE) logs -f bot | grep -i "debug\|error\|warning"

## ==================== Monitoring ====================
metrics: ## Show bot metrics
	@curl -s http://localhost:8000/metrics | grep -v '^#' | head -30

health: ## Health check all services
	@echo "${CYAN}Checking service health...${RESET}"
	@echo "${BLUE}Bot:${RESET}"
	@curl -s http://localhost:8000/health || echo "${RED}❌ Down${RESET}"
	@echo ""
	@echo "${BLUE}Prometheus:${RESET}"
	@curl -s http://localhost:9090/-/healthy || echo "${RED}❌ Down${RESET}"
	@echo ""
	@echo "${BLUE}Grafana:${RESET}"
	@curl -s http://localhost:3000/api/health || echo "${RED}❌ Down${RESET}"
	@echo ""

grafana-open: ## Open Grafana in browser
	@python -m webbrowser http://localhost:3000

prometheus-open: ## Open Prometheus in browser
	@python -m webbrowser http://localhost:9090

jaeger-open: ## Open Jaeger in browser
	@python -m webbrowser http://localhost:16686

mailhog-open: ## Open MailHog in browser
	@python -m webbrowser http://localhost:8025

portainer-open: ## Open Portainer in browser
	@python -m webbrowser http://localhost:9000

## ==================== Docker Management ====================
ps: ## Show running containers
	$(DOCKER_COMPOSE) ps

stats: ## Show container stats
	docker stats --no-stream

top: ## Show processes in containers
	$(DOCKER_COMPOSE) top

events: ## Show Docker events
	docker events --filter 'container=$(PROJECT_NAME)'

## ==================== Cleanup ====================
clean: ## Clean temporary files
	@echo "${YELLOW}Cleaning temporary files...${RESET}"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/ .pytest_cache/ .mypy_cache/ .ruff_cache/
	@echo "${GREEN}Cleanup complete!${RESET}"

clean-logs: ## Clean log files
	@echo "${YELLOW}Cleaning logs...${RESET}"
	rm -rf logs/*.log
	@echo "${GREEN}Logs cleaned!${RESET}"

clean-data: ## Clean data directory (WARNING!)
	@echo "${RED}WARNING: This will delete all data!${RESET}"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf data/*.db; \
		echo "${GREEN}Data cleaned!${RESET}"; \
	fi

clean-docker: ## Clean Docker resources
	@echo "${YELLOW}Cleaning Docker resources...${RESET}"
	$(DOCKER_COMPOSE) down -v
	docker system prune -f
	@echo "${GREEN}Docker cleanup complete!${RESET}"

clean-all: clean clean-logs clean-docker ## Clean everything

## ==================== Setup ====================
init: ## Initialize local environment
	@echo "${GREEN}Initializing local environment...${RESET}"
	@echo "${CYAN}1. Creating directories...${RESET}"
	@mkdir -p data logs backups monitoring/grafana/dashboards
	@echo "${CYAN}2. Copying example configs...${RESET}"
	@test -f .env || cp .env.local.example .env
	@echo "${CYAN}3. Installing Python dependencies...${RESET}"
	@pip install -r requirements.txt -r requirements-local.txt
	@echo "${CYAN}4. Setting up pre-commit hooks...${RESET}"
	@pre-commit install || echo "pre-commit not installed, skipping..."
	@echo "${GREEN}✓ Initialization complete!${RESET}"
	@echo ""
	@echo "${YELLOW}Next steps:${RESET}"
	@echo "  1. Edit .env with your bot token"
	@echo "  2. Run: ${GREEN}make local${RESET}"
	@echo "  3. Open Grafana: ${BLUE}http://localhost:3000${RESET}"

update-deps: ## Update dependencies
	@echo "${CYAN}Updating dependencies...${RESET}"
	pip install --upgrade pip setuptools wheel
	pip install --upgrade -r requirements.txt -r requirements-local.txt
	@echo "${GREEN}Dependencies updated!${RESET}"

## ==================== Utilities ====================
urls: ## Show all service URLs
	@echo "${CYAN}╔═══════════════════════════════════════════════════════╗${RESET}"
	@echo "${CYAN}║  Available Services                                   ║${RESET}"
	@echo "${CYAN}╚═══════════════════════════════════════════════════════╝${RESET}"
	@echo ""
	@echo "${GREEN}📊 Monitoring:${RESET}"
	@echo "  Grafana:         ${BLUE}http://localhost:3000${RESET} (admin/admin)"
	@echo "  Prometheus:      ${BLUE}http://localhost:9090${RESET}"
	@echo "  Alertmanager:    ${BLUE}http://localhost:9093${RESET}"
	@echo ""
	@echo "${GREEN}📝 Logging:${RESET}"
	@echo "  Loki:            ${BLUE}http://localhost:3100${RESET}"
	@echo ""
	@echo "${GREEN}🔍 Debugging:${RESET}"
	@echo "  Jaeger:          ${BLUE}http://localhost:16686${RESET}"
	@echo "  Debugger:        ${PURPLE}localhost:5678${RESET} (attach IDE)"
	@echo ""
	@echo "${GREEN}🛠 Tools:${RESET}"
	@echo "  MailHog:         ${BLUE}http://localhost:8025${RESET}"
	@echo "  Redis Commander: ${BLUE}http://localhost:8081${RESET}"
	@echo "  Portainer:       ${BLUE}http://localhost:9000${RESET}"
	@echo ""
	@echo "${GREEN}🤖 Bot:${RESET}"
	@echo "  Metrics:         ${BLUE}http://localhost:8000/metrics${RESET}"
	@echo "  Health:          ${BLUE}http://localhost:8000/health${RESET}"

info: ## Show environment info
	@echo "${CYAN}╔═══════════════════════════════════════════════════════╗${RESET}"
	@echo "${CYAN}║  Local Environment Info                         	  ║${RESET}"
	@echo "${CYAN}╚═══════════════════════════════════════════════════════╝${RESET}"
	@echo ""
	@echo "${GREEN}Python:${RESET}          $$(python --version)"
	@echo "${GREEN}Docker:${RESET}          $$(docker --version)"
	@echo "${GREEN}Docker Compose:${RESET}  $$(docker-compose --version)"
	@echo ""
	@echo "${GREEN}Disk Usage:${RESET}"
	@df -h . | tail -1
	@echo ""
	@echo "${GREEN}Container Status:${RESET}"
	@$(DOCKER_COMPOSE) ps
	@echo ""
	@echo "${GREEN}Resource Usage:${RESET}"
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

version: ## Show versions
	@echo "Python:         $$(python --version)"
	@echo "Docker:         $$(docker --version)"
	@echo "Docker Compose: $$(docker-compose --version)"
	@echo "Git:            $$(git --version)"

## ==================== Ngrok (для тестирования вебхуков) ====================
ngrok-start: ## Start ngrok tunnel
	@echo "${PURPLE}Starting ngrok tunnel...${RESET}"
	@docker run -d --rm --name ngrok --network $(PROJECT_NAME)_dev_network \
		-p 4040:4040 \
		ngrok/ngrok:latest http bot:8000
	@sleep 2
	@echo "${GREEN}Ngrok tunnel started!${RESET}"
	@echo "${BLUE}Dashboard: http://localhost:4040${RESET}"

ngrok-stop: ## Stop ngrok tunnel
	@docker stop ngrok || true
	@echo "${GREEN}Ngrok tunnel stopped${RESET}"

ngrok-url: ## Get ngrok public URL
	@curl -s http://localhost:4040/api/tunnels | python -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"

## ==================== Quick Actions ====================
start: local-bg urls ## Quick start (background + show URLs)

quicktest: format lint test ## Quick validation

watch: ## Watch and auto-reload (requires watchdog)
	@echo "${PURPLE}Watching for changes...${RESET}"
	watchmedo auto-restart --patterns="*.py" --recursive --signal SIGTERM \
		$(DOCKER_COMPOSE) restart bot