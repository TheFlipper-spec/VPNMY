# FL1P VPN

Автоматически обновляемая публичная VPN-подписка для русскоязычных пользователей.

- **Подписка:** https://theflipper-spec.github.io/VPNMY/FL1PVPN#FL1P%20VPN
- **Текстовый формат:** https://theflipper-spec.github.io/VPNMY/subscription.txt
- **Статус:** https://theflipper-spec.github.io/VPNMY/

## Что делает сервис

1. Каждые 10 минут GitHub Actions загружает конфигурации из включённых публичных источников.
2. Строгий парсер принимает VLESS, VMess и Trojan, отбрасывает битые URI, повторяющиеся параметры, локальные адреса и дубликаты.
3. Кандидаты проходят DNS- и TCP-проверку. Дубликаты физических endpoint не занимают несколько мест.
4. Для каждого узла из короткого списка запускается отдельный Xray-туннель.
5. Узел публикуется только после Cloudflare trace и дополнительного независимого HTTPS-запроса через этот туннель.
6. История проверок отсекает «мёртвые» и хронически нестабильные конфигурации: узел с серией отказов не попадает в подписку после одного случайного успеха.
7. Рабочие узлы оцениваются по истории доступности, географии, задержке, совместимости транспорта и короткому замеру скорости.
8. До 12 лучших конфигураций атомарно публикуются в Base64-файле `FL1PVPN` и raw-файле `subscription.txt`.

Если все источники недоступны или работает меньше трёх узлов, последняя рабочая подписка **не затирается**. Страница статуса отдельно предупреждает, если опубликованные данные устарели.

## Для российской аудитории

Пул разделён на две категории:

- 7 мест — обычный интернет;
- 5 мест — конфигурации для сценариев белых списков.

В подписке приоритет получают иностранные и ближайшие европейские локации; российские узлы остаются резервом и ограничены максимум четырьмя из 12 мест. Поэтому при наличии рабочих кандидатов основную часть подписки составляют иностранные серверы. Широко поддерживаемые транспорты TCP, WebSocket и gRPC получают небольшой приоритет над экспериментальными. Задержка измеряется с GitHub runner и является контрольным показателем, а не обещанием пользовательского пинга.

Названия узлов формируются заново и одинаково отображаются в клиентах: флаг, `FL1P VPN`, страна, категория и HTTPS-задержка. Исходные рекламные названия не попадают в итоговый профиль. В начале `subscription.txt` и `FL1PVPN` стоят служебные строки `#profile-title`, `#profile-update-interval` и `#profile-web-page-url`, а у каждого URI имя дублируется в `#фрагменте` (для VMess ещё и в поле `ps`). Ссылку подписки можно импортировать как `.../FL1PVPN#FL1P VPN` — клиент подхватит название профиля из фрагмента URL.

## Источники

Источники живут в `config/subscription.json`: публичный HTTPS URL и категория `universal` или `whitelist`. Файл специально отформатирован так, чтобы источник можно было добавить или выключить руками. Ещё проще — через CLI:

```bash
python main.py sources
python main.py sources add https://example.com/sub.txt --name "Мой список" --category universal
python main.py sources rm example-com
python main.py sources off vedalink
python main.py sources on vedalink
```

`add` сам придумает короткий id из домена, отклонит HTTP, локальные адреса и повторяющийся URL. Выключить источник можно полем `"enabled": false` или командой `sources off`. Должен оставаться хотя бы один включённый источник.

Сейчас используются:

- списки `igareck/vpn-configs-for-russia` для обычного интернета и белых списков;
- [VlessForU — working configs](https://sub.vlessfo.ru/vlessforu/working_configs.txt);
- [VEDA VPN](https://vedalink.xyz/sub/fJXfBACAy_fPp8Hr).

Полные URI, UUID и пароли не попадают в `stats.json`, историю или логи. Публичный идентификатор подписки может находиться в пути URL источника — такой URL уже является открытой частью конфигурации репозитория.

## Структура

```text
.github/workflows/update.yml  # активное production-обновление
workflow-templates/update.yml # улучшенный шаблон production workflow
workflow-templates/ci.yml     # шаблон линтера, тестов и проверки артефактов
config/subscription.json      # источники, квоты и таймауты
vpnmy/sources.py              # CLI для добавления и удаления источников
vpnmy/parser.py               # безопасный парсер и дедупликация
vpnmy/probe.py                # DNS/TCP-проверка
vpnmy/xray.py                 # двойная HTTPS-проверка через Xray
vpnmy/selector.py             # scoring, квоты и разнообразие endpoint
vpnmy/publisher.py            # fail-safe публикация и stats.json
index.html                    # адаптивная страница статуса
main.py                       # CLI-точка входа
```

В Git не складываются бинарники Xray, GeoIP-базы и runtime-логи. Xray `v26.3.27` скачивается workflow отдельно, а SHA-256 архива проверяется до распаковки.

## GitHub Actions

Активный workflow обновления находится в `.github/workflows/update.yml`. Расписание `7,17,27,37,47,57 * * * *` запрашивает обновление каждые 10 минут; GitHub может запустить scheduled workflow с небольшой задержкой. Ручной production-запуск доступен через **Actions → Обновление VPN-подписки → Run workflow**.

GitHub App Arena не может пушить `.github/workflows/` без разрешения `workflows`. Эталонные файлы лежат в `workflow-templates/`. Чтобы включить CI и более точную проверку артефактов, скопируйте их через веб-интерфейс GitHub в `.github/workflows/update.yml` и `.github/workflows/ci.yml`.

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

`--skip-deep-check` не является production-проверкой: в `stats.json` будет `check_mode: "tcp_only"` и `status: "diagnostic"`.

## Тесты

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

## Telegram-бот

```bash
pip install -r requirements-bot.txt
export BOT_TOKEN="..."
python bot.py
```

## Ограничения

Это агрегатор бесплатных публичных конфигураций, а не собственная коммерческая VPN-инфраструктура. Узел может исчезнуть уже после успешной проверки. В таком случае обновите профиль и выберите другой узел. Используйте HTTPS, не передавайте особо чувствительные данные через неизвестные серверы и соблюдайте применимое законодательство. Условия лицензий исходных списков принадлежат их авторам.
