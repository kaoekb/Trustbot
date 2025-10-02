# Trustbot — мониторинг майнеров Trustpool через Telegram

**Trustbot** — это Telegram-бот для мониторинга майнеров на пуле [Trustpool](https://lk.trustpool.cc/).  
Он умеет показывать статистику, доходность и присылать алерты в Telegram-чаты.  

---

## Возможности

- 📊 Отчёт о доходе за 24 часа (`/today`)  
- ⚙️ Список воркеров с текущим хешрейтом (`/hashrate`)  
- 💸 Последние выплаты по выбранной монете (`/payouts BTC|LTC`)  
- 🚨 Алерты:
  - офлайн воркеры (по таймауту `ALERT_OFFLINE_MINUTES`)  
  - выплаты (по факту получения новой выплаты)  
  - *(опционально, можно включить)* алерты по падению доходности и хешрейта  

---

## Установка и запуск

1. Склонировать репозиторий:
   ```bash
   git clone https://github.com/your-org/trustbot.git
   cd trustbot
   ```

2. Создать файл `.env` на основе примера:
   ```bash
   cp .env.example .env
   ```

3. Заполнить `.env` своими данными:
   - `TELEGRAM_TOKEN` — токен бота от [BotFather](https://t.me/BotFather)  
   - `TELEGRAM_CHAT_IDS` — список ID чатов или пользователей (через запятую)  
   - `TRUSTPOOL_ACCESS_KEY` — API-ключ Trustpool (раздел Watcher API)  
   - `COINS` — список монет для мониторинга, например `BTC,LTC`  
   - `FIAT` — валюта для пересчёта дохода (`USD`, `RUB`, `EUR` …)  
   - `ONLY_OFFLINE_ALERTS=true` — включить только офлайн-алерты (доходность и хешрейт будут игнорироваться)  

4. Собрать и запустить контейнер:
   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```

5. Проверить логи:
   ```bash
   docker compose logs -f trustbot
   ```

---

## Переменные окружения

| Переменная                | Назначение                                           | Пример                                |
|----------------------------|------------------------------------------------------|---------------------------------------|
| `TELEGRAM_TOKEN`          | Токен бота                                           | `123456:ABC-DEF...`                   |
| `TELEGRAM_CHAT_IDS`       | Список ID чатов (через запятую)                      | `111111111,222222222`                 |
| `TRUSTPOOL_ACCESS_KEY`    | API-ключ Trustpool                                   | `your_api_key`                        |
| `TRUSTPOOL_BASE`          | Базовый URL API Trustpool                            | `https://trustpool.ru/res/saas`       |
| `COINS`                   | Список монет                                         | `BTC,LTC`                             |
| `FIAT`                    | Валюта пересчёта                                    | `USD`                                 |
| `ONLY_OFFLINE_ALERTS`     | Только офлайн-алерты (`true/false`)                  | `true`                                |
| `ALERT_OFFLINE_MINUTES`   | Сколько минут без активности = офлайн                 | `10`                                  |
| `ALERT_HASHRATE_DROP_PCT` | (опц.) Порог падения хешрейта (%)                     | `35`                                  |
| `ALERT_MIN_DAILY_USD`     | (опц.) Минимальный доход в сутки в USD                | `25`                                  |
| `WORKER_ALIAS_*`          | Алиасы воркеров (coin-scoped или глобальные)          | `WORKER_ALIAS_BTC_one=Antminer T21 #1`|

---

## Алиасы воркеров

Чтобы сообщения были читаемыми, можно задать алиасы через переменные окружения:  

- Для конкретной монеты:  
  ```
  WORKER_ALIAS_BTC_one=Antminer T21 #1
  ```
- Глобально (для любого coin):  
  ```
  WORKER_ALIAS_one=Antminer #1
  ```

---

## Команды бота

- `/start` — помощь и список команд  
- `/today` — доход за последние 24 часа  
- `/hashrate` — состояние всех воркеров  
- `/payouts BTC` — последние выплаты по указанной монете  

---

## Лицензия

MIT — используй и дорабатывай свободно.  
