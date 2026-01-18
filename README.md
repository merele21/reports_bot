# Report Bot - VPS Tier Edition 🆓

Полностью бесплатное решение без AWS и Terraform. Все работает на одном VPS!

## 🎯 Что включено

### ✅ Бесплатные сервисы
- **GitHub** - репозиторий, CI/CD (2000 минут/месяц), Container Registry (500MB)
- **VPS варианты** (выберите один):
  - Oracle Cloud Always Free (2 CPU, 12GB RAM, 200GB SSD)
  - Google Cloud ($300 на 90 дней)
  - Hetzner Cloud ($20 стартовый кредит)
  - DigitalOcean ($200 на 60 дней для новых пользователей)
  - Любой дешевый VPS от $3-5/месяц

### ✅ Что работает
- ✨ Telegram Bot (полный функционал)
- 📊 Prometheus + Grafana (мониторинг)
- 🔔 Alertmanager (уведомления)
- 📝 Централизованные логи (опционально Loki)
- 🔄 CI/CD через GitHub Actions
- 📦 Автоматический деплой через Ansible
- 💾 Автоматические бэкапы
- 🗄️ SQLite база данных (вместо PostgreSQL)

### ❌ Чего нет (по сравнению с AWS версией)
- ❌ Managed RDS (используем SQLite)
- ❌ ECS/Fargate (используем Docker Compose)
- ❌ CloudWatch (используем Prometheus/Grafana)
- ❌ Secrets Manager (используем .env файлы)
- ❌ Auto-scaling (один контейнер)

---

## 🚀 Быстрый старт

### 1️⃣ Выбор VPS провайдера

#### Oracle Cloud (рекомендуется для начала)

```bash
# Always Free включает:
- 2 VM instances (AMD, 1/8 OCPU, 1 GB RAM each)
- 4 ARM Ampere CPU + 24 GB RAM (можно использовать вместо AMD)
- 200 GB Block Volume
- 10 TB outbound transfer/month

# Регистрация
https://www.oracle.com/cloud/free/
```

#### Другие варианты

```bash
# DigitalOcean - $200 на 60 дней
https://try.digitalocean.com/

# Hetzner - от €3.29/месяц
https://www.hetzner.com/cloud

# Contabo - от €3.99/месяц
https://contabo.com/
```

### 2️⃣ Настройка VPS

```bash
# SSH подключение
ssh root@your-vps-ip

# Создание пользователя
adduser deploy
usermod -aG sudo deploy

# Настройка SSH ключа
mkdir -p /home/deploy/.ssh
cat >> /home/deploy/.ssh/authorized_keys << EOF
# Вставьте ваш публичный SSH ключ
EOF

chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

### 3️⃣ Локальная настройка

```bash
# Клонирование репозитория
git clone https://github.com/your_name/report-bot.git
cd report-bot

# Переключение на vps ветку
git checkout vps

# Установка зависимостей
make install

# Копирование примера .env
cp .env.example .env
nano .env
```

### 4️⃣ Настройка Ansible Inventory

```ini
# ansible/inventory/vps.ini
[vps]
your-vps-ip ansible_user=deploy ansible_port=22

[vps:vars]
git_repo=https://github.com/your_name/report-bot.git
git_branch=vps
```

### 5️⃣ Настройка секретов

```bash
# Создание vault файла
ansible-vault create ansible/group_vars/vault.yml

# Содержимое vault.yml:
---
vault_bot_token: "YOUR_BOT_TOKEN"
vault_admin_ids: "ADMIN,IDS"
vault_grafana_password: "strong_password"
vault_slack_webhook: "https://hooks.slack.com/..."
```

### 6️⃣ Деплой

```bash
# Проверка подключения
ansible vps -i ansible/inventory/vps.ini -m ping

# Dry-run
make deploy-check

# Реальный деплой
make deploy-vps
```

### 7️⃣ Настройка GitHub Actions

```bash
# GitHub Secrets (Settings → Secrets → Actions)
VPS_HOST=your-vps-ip
VPS_USER=deploy
VPS_SSH_KEY=<содержимое приватного SSH ключа>
VPS_PORT=22
SLACK_WEBHOOK=https://hooks.slack.com/...
```

---

## 📊 Мониторинг

### Доступ к сервисам

После деплоя будут доступны:

```bash
# Grafana (визуализация)
http://your-vps-ip:3000
Login: admin
Password: (из vault_grafana_password)

# Prometheus (метрики)
http://your-vps-ip:9090

# Alertmanager (алерты)
http://your-vps-ip:9093

# Bot Metrics
http://your-vps-ip:8000/metrics
```

### Импорт дашбордов в Grafana

1. Перейдите в Grafana → Dashboards → Import
2. Используйте готовые дашборды:
   - **Node Exporter**: ID `1860`
   - **Docker**: ID `893`
   - **Bot Custom**: используйте файлы из `monitoring/grafana/dashboards/`

---

## 💾 Бэкапы

### Автоматические бэкапы

Ansible настраивает ежедневные бэкапы в 3:00 утра:

```bash
# Скрипт создан в /usr/local/bin/backup-bot.sh
# Логи: /var/log/bot-backup.log
# Бэкапы: /opt/report-bot/backups/
```

### Ручной бэкап

```bash
# Через Makefile
make backup-full

# Или на VPS
ssh deploy@your-vps-ip
cd /opt/report-bot
./backups.sh
```

### Восстановление

```bash
# Локально
make restore-full file=backups/full_backup_20240118.tar.gz

# На VPS
ssh deploy@your-vps-ip
cd /opt/report-bot
tar -xzf backups/full_backup_20240118.tar.gz
docker-compose restart
```

### Бэкап в облако (опционально)

#### Rclone + Google Drive (бесплатно 15GB)

```bash
# Установка rclone
curl https://rclone.org/install.sh | sudo bash

# Настройка
rclone config
# Выберите: Google Drive

# Добавить в backup скрипт
rclone copy /opt/report-bot/backups/ gdrive:report-bot-backups/
```

---

## 🔄 CI/CD Workflow

### GitHub Actions Pipeline

При push в `vps`:

1. **Lint & Test** ✅
2. **Build Docker Image** → GitHub Container Registry
3. **Deploy to VPS** via SSH
4. **Health Check**
5. **Slack Notification**

### Ручной деплой

```bash
# Локально
git push origin vps

# Или через Ansible
make deploy-vps
```

---

## 🛠 Управление

### Полезные команды

```bash
# На локальной машине
make up              # Запустить локально
make logs            # Логи
make metrics         # Метрики
make backup-full     # Бэкап

# На VPS
ssh deploy@your-vps
cd /opt/report-bot

# Управление сервисами
docker-compose ps                    # Статус
docker-compose logs -f bot          # Логи бота
docker-compose restart bot          # Перезапуск
docker-compose down && docker-compose up -d  # Полный перезапуск

# Мониторинг ресурсов
htop                 # CPU/Memory
df -h               # Диск
docker stats        # Контейнеры
```

### Systemd Service

Автоматический запуск после перезагрузки:

```bash
# Проверка статуса
sudo systemctl status report-bot

# Управление
sudo systemctl start report-bot
sudo systemctl stop report-bot
sudo systemctl restart report-bot

# Логи
sudo journalctl -u report-bot -f
```

---

## 📈 Оптимизация ресурсов

### Минимальные требования

```
CPU:     1 ядро
RAM:     1GB (рекомендуется 2GB)
Disk:    10GB
Network: 1TB/месяц
```

### Снижение потребления памяти

```yaml
# docker-compose.vps.yml
services:
  bot:
    deploy:
      resources:
        limits:
          memory: 256M
  
  # Отключить необязательные сервисы
  # cadvisor:  # Закомментировать
  # loki:      # Закомментировать
```

### Очистка дискового пространства

```bash
# Автоматическая очистка
make clean-docker

# Ручная очистка
docker system prune -af --volumes
```

---

## 🔒 Безопасность

### Настройка Firewall

```bash
# UFW уже настроен Ansible
sudo ufw status

# Дополнительно
sudo ufw allow from YOUR_IP to any port 3000  # Grafana только с вашего IP
```

### Обновления

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Обновление Docker образов
cd /opt/report-bot
docker-compose pull
docker-compose up -d
```

### Ротация логов

Настроена через logrotate (7 дней хранения):

```bash
# Проверка
sudo logrotate -d /etc/logrotate.d/report-bot

# Ручной запуск
sudo logrotate -f /etc/logrotate.d/report-bot
```

---

## 🆘 Troubleshooting

### Проблема: Бот не запускается

```bash
# Проверить логи
docker-compose logs bot

# Проверить .env
cat .env

# Перезапустить
docker-compose restart bot
```

### Проблема: Мало места на диске

```bash
# Проверить использование
df -h
du -sh /opt/report-bot/*

# Очистить логи
find /opt/report-bot/data -name "*.log" -mtime +7 -delete

# Очистить старые бэкапы
find /opt/report-bot/backups -mtime +30 -delete

# Очистить Docker
docker system prune -af
```

### Проблема: Высокая нагрузка

```bash
# Проверить ресурсы
htop
docker stats

# Уменьшить retention Prometheus
# monitoring/prometheus.yml
--storage.tsdb.retention.time=7d  # Вместо 15d
```

### Проблема: Grafana не открывается

```bash
# Проверить firewall
sudo ufw status
sudo ufw allow 3000/tcp

# Проверить контейнер
docker-compose ps grafana
docker-compose logs grafana
```

---

## 💰 Стоимость

### Полностью бесплатно

**Oracle Cloud Always Free:**
- VPS: $0
- Storage: $0
- Transfer: $0 (10TB/месяц)
- **Total: $0/месяц** 🎉

### Минимальная стоимость

**Самый дешевый VPS (Contabo):**
- VPS (2 vCPU, 4GB RAM): €3.99/месяц
- **Total: ~$4-5/месяц**

### Сравнение с AWS версией

| Компонент | AWS | Free Tier |
|-----------|-----|-----------|
| Compute | ECS Fargate $30/мес | VPS $0-5/мес |
| Database | RDS $30/мес | SQLite $0 |
| Monitoring | CloudWatch $10/мес | Grafana $0 |
| Logs | CloudWatch $5/мес | Loki $0 |
| **TOTAL** | **~$75/мес** | **$0-5/мес** |

**Экономия: до $900/год!** 💸

---

## 🎓 Дальнейшее развитие

### Когда стоит перейти на AWS версию?

- 📈 Более 1000 пользователей
- 🔄 Нужен auto-scaling
- 💾 База данных > 10GB
- 🌍 Нужна geo-распределенность
- 🔒 Compliance требования

### Миграция на AWS

```bash
# Переключиться на AWS ветку
git checkout aws

# Следовать README.md
# Terraform создаст всю инфраструктуру
```

---

## 📚 Полезные ссылки

- [Docker Compose Docs](https://docs.docker.com/compose/)
- [Prometheus Docs](https://prometheus.io/docs/)
- [Grafana Docs](https://grafana.com/docs/)
- [Ansible Docs](https://docs.ansible.com/)
- [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/)

---

## 🤝 Поддержка
