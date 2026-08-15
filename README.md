# FL1P VPN

Автоматически обновляемая публичная VPN-подписка для русскоязычных пользователей.

> Из-за ограничения GitHub App готовые Actions временно лежат в `workflow-templates/`. После merge их нужно один раз активировать по инструкции ниже.

- **Подписка:** https://theflipper-spec.github.io/VPNMY/FL1PVPN
- **Статус:** https://theflipper-spec.github.io/VPNMY/

## Что делает сервис

1. Каждые 10 минут GitHub Actions загружает конфигурации из публичных источников для России.
2. Строгий парсер принимает VLESS, VMess и Trojan, отбрасывает битые URI и локальные адреса.
3. Кандидаты проходят DNS/TCP-проверку.
4. Для короткого списка запускается отдельный Xray-туннель и выполняется HTTPS-запрос через него.
5. Узлы оцениваются по стабильности, географии, задержке и короткому замеру скорости.
6. До 12 лучших конфигураций публикуются в base64-файле `FL1PVPN` и raw-файле `subscription.txt`.

Прежние hardcoded-подписки, «несгораемые» узлы и их адреса полностью удалены. Если источники недоступны или работает меньше трёх узлов, последняя рабочая подписка **не затирается**.

## Для российской аудитории

Пул разделён на две категории:

- 7 мест — обычный интернет;
- 5 мест — конфигурации для сценариев белых списков.

При оценке приоритет получают Россия и ближайшие европейские локации. Задержка измеряется с GitHub runner и является контрольным показателем, а не обещанием пользовательского пинга.

## Структура

```text
workflow-templates/update.yml # production-шаблон: запуск каждые 10 минут
workflow-templates/ci.yml     # шаблон линтера и тестов
config/subscription.json      # источники, квоты и таймауты
vpnmy/parser.py               # безопасный парсер
vpnmy/probe.py                # DNS/TCP-проверка
vpnmy/xray.py                 # глубокая проверка через Xray
vpnmy/selector.py             # scoring, квоты, стабильность
vpnmy/publisher.py            # fail-safe публикация
main.py                       # короткая CLI-точка входа
```

В Git больше не складываются бинарники Xray, GeoIP-базы и runtime-логи. Xray `v26.3.27` скачивается workflow отдельно, а SHA-256 архива проверяется до распаковки.

## Активация GitHub Actions после merge

GitHub App Arena не имеет системного разрешения `Workflows: write`, поэтому workflow передаются как безопасные шаблоны вне `.github/workflows/`. Активировать их нужно вашим аккаунтом через сайт GitHub:

1. Откройте `workflow-templates/update.yml` и скопируйте всё содержимое.
2. Откройте `.github/workflows/update.yml`, нажмите значок карандаша, замените содержимое и нажмите **Commit changes** в `main`.
3. Откройте `workflow-templates/ci.yml` и скопируйте содержимое.
4. Создайте `.github/workflows/ci.yml` через **Add file → Create new file**, вставьте шаблон и сделайте commit в `main`.
5. Удалите устаревший `.github/workflows/deploy.yml` через меню файла и сделайте commit.
6. Откройте вкладку **Actions → Обновление VPN-подписки → Run workflow**, чтобы выполнить первую полную Xray-проверку сразу.

После этого расписание `7,17,27,37,47,57 * * * *` будет запрашивать обновление каждые 10 минут. GitHub может запускать scheduled workflow с небольшой задержкой.

## Локальный запуск

Требуются Python 3.11+ и установленный Xray Core:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export VPNMY_XRAY_BIN=/usr/local/bin/xray
python main.py
```

Проверка без записи:

```bash
python main.py --dry-run
```

Диагностический TCP-режим без Xray:

```bash
python main.py --skip-deep-check --dry-run
```

`--skip-deep-check` не считается production-проверкой: в `stats.json` будет `check_mode: "tcp_only"` и `status: "diagnostic"`.

## Тесты

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

## Источники

Источники задаются только в `config/subscription.json`. Они должны использовать публичный HTTPS URL, не содержать токенов и иметь категорию `universal` или `whitelist`. Полные URI, UUID и пароли не попадают в `stats.json`, историю или логи.

## Telegram-бот

```bash
pip install -r requirements-bot.txt
export BOT_TOKEN="..."
python bot.py
```

## Ограничения

Это агрегатор бесплатных публичных конфигураций, а не собственная коммерческая VPN-инфраструктура. Узлы могут исчезать между проверками. Используйте HTTPS, не передавайте особо чувствительные данные через неизвестные серверы и соблюдайте применимое законодательство. Условия лицензий исходных списков принадлежат их авторам.
