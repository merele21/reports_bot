.PHONY: help build up down restart logs shell test lint format

# colors
GREEN := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
BLUE := $(shell tput -Txterm setaf 4)
RESET := $(shell tput -Txterm sgr0)

# variables
DOCKER_COMPOSE := docker-compose -f docker.compose.vps.yml

help: ## show this help
 @echo '${GREEN}Report Bot - VPS edition${RESET}'
 @echo ''
 @echo 'Usage:'
 @echo ' ${YELLOW}make${RESET} ${GREEN}<target>${RESET}'
 @echo ''
 @awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?##.*$$/{printf "  ${YELLOW}%-20s${RESET} %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## --- development
build: ## build docker images
 $(DOCKER_COMPOSE) build

up: ## start all services
 $(DOCKER_COMPOSE) up -d
 @echo "${GREEN}Services started!${RESET}"
 @echo "${BLUE}Grafana:${RESET}    http://localhost:3000 (admin/admin)"
 @echo "${BLUE}Prometheus:${RESET} http://localhost:9090"

down: ## stop all services
 $(DOCKER_COMPOSE) down

restart: ## restart bot
 $(DOCKER_COMPOSE) restart bot

logs: ## show all logs
 $(DOCKER_COMPOSE) logs -f

logs-bot: ## show bot logs
 (DOCKER_COMPOSE) logs -f bot

shell: ## open shell in bot container
 $(DOCKER_COMPOSE) exec bot /bin/bash

ps: ## show running containers
 $(DOCKER_COMPOSE) ps

stats: ## show container resource usage
 docker stats --no-stream

# --- database (sqlite) ---
db-shell: ## open sqlite shell
 $(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db

db-backup: ## backup sqlite database
 @mkdir -p backups
 $(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db ".backup '/app/data/backup_$$(date +%Y%m%d_%H%M%S).db'"
 @echo "${GREEN}Backup created in data/ directory${RESET}"

db-restore: ## restore database (arg: file=backup.db)
 $(DOCKER_COMPOSE) exec bot sqlite3 /app/data/bot_data.db ".restore '$(file)'"
 @echo "${GREEN}Database restored from $(file)${RESET}"

migrate: ## run migrations
 $(DOCKER_COMPOSE) run --rm bot python migrate_db.py

## --- testing & quality ---
test: ## run tests
 pytest tests/ -v --cov=bot --cov-report=html

lint: ## run linters
 ruff check bot/
 mypy bot/ --ignore-missing-imports

format: ## format code
 black bot/
 isort bot/

security: ## security scan
 bandit -r bot/ -ll
 safety check --json

## --- monitoring ---
metrics: ## show bot metrics
 @curl -s http://localhost:8000/metrics | grep -v '^#' | head -20

health: ## health check
 @curl -s http://localhost:8000/health

grafana-open: ## open grafana in browser
 @python -m webbrowser http://localhost:3000

prometheus-open: ## open prometheus in browser
 @python -m webbrowser http://localhost:9090

## --- deployment ---
deploy-vps: ## deploy to vps with ansible
 @echo "${YELLOW}Deploying to VPS...${RESET}"
 ansible-playbook -i ansible/inventory/vps.ini ansible/deploy-vps.yml \
  --ask-vault-pass

## --- utilities ---
clean: ## clean temporary files
 find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
 find . -type f -name "*.pyc" -delete
 rm -rf htmlcov/ .pytest_cache/ .mypy_cache/ .ruff_cache/

clean_docker: ## clean docker resources
 $(DOCKER_COMPOSE) down -v
 docker system prune -f

clean-all: clean clean-docker ## clean everything

prune: ## deep clean docker
 @echo "${YELLOW}WARNING: This will remove all unused Docker resources!${RESET}"
 @read -p "Continue? [y/N] " -n 1 -r; \
 if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
  docker system prune -af --volumes; \
 fi

## backup & restore
backup-full: ## full backup (database + data)
 @mkdir -p backups
 @DATE=$$(date + %Y%m%d_%H%M%S); \
 echo "Creating backup: backups/full_backup_$$DATE.tar.gz"; \
 tar -czf backups/full_backup_$$DATE.tar.gz \
  data/ .env monitoring/grafana/
 @echo "${GREEN}Full backup created!${RESET}"

restore-full: ## restore full backup (arg: file=backup.tar.gz)
 @if [ -z "$(file)" ]; then \
  echo "${YELLOW}Usage: make restore-full file=backups/full_backup_XXX.tar.gz${RESET}"; \
  exit 1; \
 fi
 tar -xzf $(file)
 @echo "${GREEN}Restored from $(file)${RESET}"

## --- git ---
git-status: ## show git status
 @git-status -s

git-log: ## show recent commits
 @git log --oneline --graph -10

## --- information ---
info: ## show system information
 @echo "${GREEN}=== System Info ===${RESET}"
 @echo "Docker version: $$(docker --version)"
 @echo "Compose version: $$(docker-compose --version)"
 @echo ""
 @echo "${GREEN}=== Disk Usage ===${RESET}"
 @df -h . | tail -1
 @echo ""
 @echo "${GREEN}=== Services ===${RESET}"
 @$(DOCKER_COMPOSE) ps
 @echo ""
 @echo "${GREEN}=== Resource Usage ===${RESET}"
 @docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

urls: ## show service URLs
 @echo "${GREEN}Service URLs:${RESET}"
 @echo "${BLUE}Grafana:${RESET}       http://localhost:3000"
 @echo "${BLUE}Prometheus:${RESET}    http://localhost:9090"
 @echo "${BLUE}Alertmanager:${RESET}  http://localhost:9093"
 @echo "${BLUE}Node Exporter:${RESET} http://localhost:9100"
 @echo "${BLUE}Bot Metrics:${RESET}   http://localhost:8000/metrics"
 @echo "${BLUE}Bot Health:${RESET}    http://localhost:8000/health"

## --- quick commands ---
start: up logs ## start and show logs

stop: down ## stop all services

reload: restart logs-bot ## restart and show logs

dev: up logs-bot ## development (start + bot logs)
all: format lint test ## run all checks