# Monitoring Setup Guide 📊

Полное руководство по настройке мониторинга с уведомлениями в Telegram.

## 📋 Что включено

- ✅ **Prometheus** - сбор метрик
- ✅ **Grafana** - визуализация
- ✅ **Loki** - централизованные логи
- ✅ **Promtail** - сбор логов
- ✅ **Alertmanager** - управление алертами
- ✅ **Telegram интеграция** - уведомления в личку

---

## 🚀 Быстрый старт

### 1. Создание Telegram бота для алертов

```bash
# Автоматическая настройка
make monitoring-setup

# Или вручную:
# 1. Откройте @BotFather в Telegram
# 2. Отправьте /newbot
# 3. Следуйте инструкциям
# 4. Скопируйте Bot Token
```

### 2. Получение вашего Telegram ID

```bash
# Откройте @userinfobot в Telegram
# Отправьте /start
# Скопируйте ваш ID
```

### 3. Обновление конфигурации

```bash
# Откройте monitoring/alertmanager.yml
nano monitoring/alertmanager.yml

# Замените:
bot_token: 'YOUR_ALERTMANAGER_BOT_TOKEN'  # На ваш токен
chat_id: YOUR_TELEGRAM_ID                  # На ваш ID
```

### 4. Запуск

```bash
# Через docker-compose
docker-compose -f docker-compose.local.yml up -d

# Или через Makefile
make monitoring-up
```

### 5. Тест

```bash
# Отправить тестовый алерт
make test-alert

# Проверьте Telegram!
```

---

## 📊 Доступные сервисы

После запуска:

| Сервис | URL | Credentials |
|--------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin |
| Prometheus | http://localhost:9090 | - |
| Alertmanager | http://localhost:9093 | - |
| Loki | http://localhost:3100 | - |

---

## 🔔 Типы алертов

### Критические (Immediate)

- 🚨 **BotDown** - бот недоступен
- 🚨 **CriticalErrorRate** - критический уровень ошибок
- 🚨 **CriticalCPUUsage** - CPU > 95%
- 🚨 **CriticalMemoryUsage** - Memory > 95%
- 🚨 **DiskSpaceLow** - диск < 10%
- 🚨 **DatabaseErrors** - ошибки БД

### Предупреждения (Warning)

- ⚠️ **HighErrorRate** - высокий уровень ошибок
- ⚠️ **ReportValidationFailures** - проблемы с валидацией
- ⚠️ **NoMessagesReceived** - бот не получает сообщения
- ⚠️ **SlowMessageProcessing** - медленная обработка
- ⚠️ **HighCPUUsage** - CPU > 80%
- ⚠️ **HighMemoryUsage** - Memory > 85%

### Информационные (Info)

- ℹ️ **UnusualReminderRate** - необычный паттерн напоминаний
- ℹ️ **BotRestarting** - частые перезапуски

---

## 🧪 Тестирование алертов

### Базовые тесты

```bash
# Обычный тест
make test-alert

# Критический алерт
make test-critical

# Алерт бота
make test-bot

# Системный алерт
make test-system

# Resolved алерт
make test-resolved
```

### Вручную через curl

```bash
# Отправить кастомный алерт
curl -X POST http://localhost:9093/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {
      "alertname": "MyCustomAlert",
      "severity": "warning",
      "service": "test"
    },
    "annotations": {
      "summary": "Custom test alert",
      "description": "This is my custom alert"
    },
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'"
  }]'
```

---

## 📝 Формат Telegram сообщений

### Critical Alert

```
🚨🚨🚨 CRITICAL ALERT 🚨🚨🚨

BotDown

Summary: Report Bot is down
Description: Bot has been down for more than 2 minutes

Labels:
• severity: critical
• service: bot
• instance: report-bot

Started: 2024-01-18 10:05:00

⚠️ IMMEDIATE ACTION REQUIRED ⚠️

[Alertmanager] [Silence]
```

### Bot Alert

```
🤖 Bot Alert - FIRING

HighErrorRate

🔴 High error rate in bot
📝 Error rate is 0.15 errors/second

⏰ Started: 10:05:00

[View Details]
```

### Resolved

```
✅ RESOLVED

BotDown has been resolved.

Duration: 10:05 - 10:07

Bot is back online
```

---

## ⚙️ Настройка алертов

### Создание нового правила

Откройте `monitoring/alerts.yml`:

```yaml
groups:
  - name: my_custom_alerts
    interval: 30s
    rules:
      - alert: MyCustomAlert
        expr: my_metric > 10
        for: 5m
        labels:
          severity: warning
          service: bot
        annotations:
          summary: "My custom alert"
          description: "Value is {{ $value }}"
```

### Настройка маршрутизации

Откройте `monitoring/alertmanager.yml`:

```yaml
route:
  routes:
    - match:
        alertname: MyCustomAlert
      receiver: 'telegram-custom'
      repeat_interval: 1h
```

### Создание нового receiver

```yaml
receivers:
  - name: 'telegram-custom'
    telegram_configs:
      - bot_token: 'YOUR_BOT_TOKEN'
        chat_id: YOUR_CHAT_ID
        message: |
          🔔 Custom Alert
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          {{ end }}
```

---

## 🔇 Silences (Заглушки)

### Создание silence

```bash
# Заглушить test алерты на 1 час
make silence-test

# Заглушить ВСЕ алерты на 10 минут (экстренно)
make silence-all
```

### Через UI

1. Откройте http://localhost:9093/#/silences
2. Нажмите "New Silence"
3. Добавьте matchers:
   - `alertname` = `BotDown`
4. Укажите время
5. Добавьте комментарий
6. Create

### Через API

```bash
curl -X POST http://localhost:9093/api/v1/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{
      "name": "alertname",
      "value": "BotDown",
      "isRegex": false
    }],
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'",
    "endsAt": "'$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S.000Z)'",
    "comment": "Maintenance window",
    "createdBy": "admin"
  }'
```

---

## 🔍 Логи через Loki

### Просмотр в Grafana

1. Откройте Grafana: http://localhost:3000
2. Explore → Data Source: Loki
3. Запросы:

```logql
# Все логи бота
{job="bot"}

# Только ошибки
{job="bot"} |= "ERROR"

# Конкретный пользователь
{job="bot"} |= "user=123456789"

# За последний час
{job="bot"} |= "ERROR" | json | created_at > ago(1h)

# Rate ошибок
rate({job="bot"} |= "ERROR" [5m])
```

### Через API

```bash
# Последние 10 логов
curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={job="bot"}' \
  --data-urlencode 'limit=10' | jq

# Логи с фильтром
curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={job="bot"} |= "ERROR"' \
  --data-urlencode 'limit=50'
```

---

## 📊 Полезные Prometheus запросы

### Статус сервисов

```promql
# Какие сервисы работают
up

# Uptime бота
bot_uptime_seconds

# Количество активных контейнеров
count(container_last_seen{name=~"report_bot.*"})
```

### Bot метрики

```promql
# Сообщений в секунду
rate(bot_messages_total[5m])

# Ошибок в секунду
rate(bot_errors_total[5m])

# Время обработки (p95)
histogram_quantile(0.95, rate(bot_message_processing_duration_seconds_bucket[5m]))

# Отчеты в день
increase(bot_reports_submitted_total[1d])
```

### Системные метрики

```promql
# CPU usage
100 - (avg(irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Memory usage
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100

# Disk usage
(node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_avail_bytes{mountpoint="/"}) / node_filesystem_size_bytes{mountpoint="/"} * 100
```

---

## 🛠 Troubleshooting

### Проблема: Алерты не приходят в Telegram

```bash
# 1. Проверьте Alertmanager
curl http://localhost:9093/-/healthy

# 2. Проверьте конфигурацию
make validate-alertmanager

# 3. Проверьте активные алерты
make alerts-status

# 4. Проверьте логи
docker-compose logs alertmanager

# 5. Тест отправки
make test-alert
```

### Проблема: Неверный bot token

```bash
# Проверить токен
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"

# Должен вернуть:
# {"ok":true,"result":{"id":...,"is_bot":true,...}}

# Если ошибка - токен неверный
```

### Проблема: Неверный chat_id

```bash
# Получить ID через бота
# 1. Отправьте сообщение боту
# 2. Проверьте updates:

curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | jq

# Найдите: .result[].message.from.id
```

### Проблема: Алерты не срабатывают

```bash
# 1. Проверьте правила
make validate-alerts

# 2. Проверьте Prometheus targets
curl http://localhost:9090/api/v1/targets | jq

# 3. Проверьте метрику вручную
curl -s 'http://localhost:9090/api/v1/query?query=up{job="bot"}' | jq

# 4. Проверьте правила в UI
open http://localhost:9090/rules
```

---

## 📈 Retention & Storage

### Prometheus

```yaml
# В prometheus.yml
storage:
  tsdb:
    retention.time: 30d    # Хранить 30 дней
    retention.size: 10GB   # Или до 10GB
```

### Loki

```yaml
# В loki-local.yml
limits_config:
  retention_period: 168h  # 7 дней
```

### Очистка старых данных

```bash
# Prometheus (API)
curl -X POST http://localhost:9090/api/v1/admin/tsdb/delete_series \
  -d 'match[]={job="old-job"}'

# Или удалить вручную
rm -rf prometheus_data/*
```

---

## 🔐 Security

### Базовая аутентификация

```yaml
# alertmanager.yml
receivers:
  - name: 'webhook'
    webhook_configs:
      - url: 'http://receiver:5001/alerts'
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'secret'
```

### Защита Telegram бота

- ✅ Используйте отдельного бота только для алертов
- ✅ Не публикуйте токен в git
- ✅ Используйте `.env` файлы
- ✅ Регулярно ротируйте токены
- ✅ Проверяйте chat_id в сообщениях

---

## 📚 Дополнительные ресурсы

- [Prometheus Docs](https://prometheus.io/docs/)
- [Alertmanager Docs](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Loki Docs](https://grafana.com/docs/loki/latest/)
- [LogQL Docs](https://grafana.com/docs/loki/latest/logql/)
- [Telegram Bot API](https://core.telegram.org/bots/api)