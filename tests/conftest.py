import json
from pathlib import Path

import pytest

from vpnmy.models import Source


@pytest.fixture(autouse=True)
def _no_globalping_token(monkeypatch):
    """Тесты не должны зависеть от GLOBALPING_TOKEN и реального API.

    В workflow «Обновление VPN-подписки» секрет доступен job'у; если тест
    случайно пойдёт в настоящий Globalping, результат будет зависеть от
    реальных IP (тестовые «узлы» — публичные DNS-серверы с разными
    открытыми портами) и CI станет флейковым. Обрезаем токен для каждого
    теста: RU-этап в таких тестах честно пропускается.
    """
    monkeypatch.delenv("GLOBALPING_TOKEN", raising=False)


@pytest.fixture
def source():
    return Source("test", "Тест", "https://example.com/sub", "universal")


@pytest.fixture
def countries_file(tmp_path: Path):
    p = tmp_path / "countries.json"
    p.write_text(json.dumps({"DE": "🇩🇪 Германия", "RU": "🇷🇺 Россия"}))
    return p
