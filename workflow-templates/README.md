# Шаблоны workflows

> GitHub App Arena не имеет права `workflows`, поэтому напрямую менять
> `.github/workflows/` нельзя. Шаблоны из этой папки ставятся владельцем
> вручную через веб-интерфейс GitHub.

## Активные шаблоны

- `ci.yml` — проверка кода (`ruff`, `pytest`, проверка Hysteria `v2.12.2` с SHA-256).
- `update.yml` — production-обновление каждые 10 минут, кэш Xray/Hysteria, сборка подписки (всё на `ubuntu-latest`).
- `update-ru.yml` (предложение) — опциональная российская точка проверки, **тоже на `ubuntu-latest`** (см. `docs/RUSSIAN-PROBE-PLAN.md`). Без российского прокси/сервиса (`RU_PROXY_URL`/`RU_PROBE_API`) job пропускается. Никаких self-hosted runner.

## Установка/обновление workflow

1. На GitHub выберите ветку с нужным PR (например, `arena/01a0a6c0-vpnmy`).
2. Скопируйте содержимое `workflow-templates/ci.yml` → `.github/workflows/ci.yml`.
3. Скопируйте содержимое `workflow-templates/update.yml` → `.github/workflows/update.yml`.
4. Если есть российский выход и нужен второй замер, скопируйте `workflow-templates/update-ru.yml` → `.github/workflows/update-ru.yml` и задайте секреты `RU_PROXY_URL` (или `RU_PROBE_API`) + `RU_PROBE_TOKEN` для подписи. Всё исполняется на `ubuntu-latest` — скрипты срабатывают на серверах Actions, не на self-hosted.

## Примечания к релизу отбора (2026-09)

Отбор теперь:
- без географии как бонуса к качеству (страна — только для разнообразия);
- с лимитами `max_per_country=3`, `max_per_asn=2`, `max_per_ip=1`, `max_per_subnet=2`, дедуп по `egress_ip`, `/24` IPv4 и `/48` IPv6;
- с тремя измерениями задержки через туннель (медиана/максимум/разброс), порог 1500 мс, скользящее окно 10 циклов;
- с бюджетом исследования 70% известные / 30% новые-или-давно-не-проверявшиеся (ротация по часовому слоту, Hysteria2 сохраняет долю).

Диагностика публикуется в `stats.json` (`diversity`, `asn`, `verification.measurements_per_node`). Логи не содержат секретов.
