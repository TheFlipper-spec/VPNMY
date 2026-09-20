# Шаблоны workflows

> GitHub App Arena не имеет права `workflows`, поэтому напрямую менять
> `.github/workflows/` нельзя. Шаблоны из этой папки ставятся владельцем
> вручную через веб-интерфейс GitHub.

## Активные шаблоны

- `ci.yml` — проверка кода (`ruff`, `pytest`, проверка Hysteria `v2.12.2` с SHA-256).
- `update.yml` — production-обновление каждые 30 минут (cron `7,37 * * * *`), кэш Xray/Hysteria, сборка подписки (всё на `ubuntu-latest`). Российская проверка узлов встроена в саму сборку через Globalping (локация `RU`, секрет `GLOBALPING_TOKEN`) — отдельный job для этого не нужен.
- `update-ru.yml` (опциональное расширение) — дополнительный сигнал «из реальной российской сети» через собственный прокси/опрашиваемый сервис, **тоже на `ubuntu-latest`** (см. `docs/RUSSIAN-PROBE-PLAN.md`). Без российского прокси/сервиса (`RU_PROXY_URL`/`RU_PROBE_API`) job пропускается. Никаких self-hosted runner. Globalping-проверку не заменяет: ловит SNI-DPI и поведение пользовательских сетей, чего чистый TCP-connect из дата-центров не видит.

## Установка/обновление workflow

1. На GitHub выберите ветку с нужным PR (например, `arena/01a0a6c0-vpnmy`).
2. Скопируйте содержимое `workflow-templates/ci.yml` → `.github/workflows/ci.yml`.
3. Скопируйте содержимое `workflow-templates/update.yml` → `.github/workflows/update.yml`.
4. Создайте секрет `GLOBALPING_TOKEN` (Settings → Secrets and variables → Actions): токен генерируется на <https://dash.globalping.io/tokens>. Без него российская проверка просто пропускается.
5. Если есть российский выход и нужен второй замер (SNI-DPI/пользовательские сети), скопируйте `workflow-templates/update-ru.yml` → `.github/workflows/update-ru.yml` и задайте секреты `RU_PROXY_URL` (или `RU_PROBE_API`) + `RU_PROBE_TOKEN` для подписи. Всё исполняется на `ubuntu-latest` — скрипты срабатывают на серверах Actions, не на self-hosted.

## Примечания к релизу отбора (2026-09)

Отбор теперь:
- без географии как бонуса к качеству (страна — только для разнообразия);
- с лимитами `max_per_country=3`, `max_per_asn=2`, `max_per_ip=1`, `max_per_subnet=2`, дедуп по `egress_ip`, `/24` IPv4 и `/48` IPv6;
- с тремя измерениями задержки через туннель (медиана/максимум/разброс), порог 1500 мс, скользящее окно 10 циклов;
- с бюджетом исследования 70% известные / 30% новые-или-давно-не-проверявшиеся (ротация по часовому слоту, Hysteria2 сохраняет долю).

## Российская проверка (2026-09-20)

- Второй этап фильтрации: после локальной предпроверки с GitHub-раннера узлы проверяются **из российских узлов Globalping** (TCP-порт для классических протоколов, ICMP для Hysteria2). Заблокированные в РФ узлы исключаются до Xray/Hysteria-проверки.
- Конфигурация в `config/subscription.json`: `ru_check_budget` (125), `ru_check_concurrency` (12), `ru_check_probes` (3), `ru_check_packets` (2), `ru_check_poll_seconds` (0.7), `ru_check_deadline_seconds` (420), `ru_check_enabled` (true/false; по умолчанию — авто по наличию токена).
- Диагностика публикуется в `stats.json` (`ru_check`, плюс `ru_ms` у каждого узла) и на страницу статуса. Логи не содержат секретов; токен — только в секрете `GLOBALPING_TOKEN`.

Диагностика публикуется в `stats.json` (`diversity`, `asn`, `verification.measurements_per_node`, `ru_check`). Логи не содержат секретов.
