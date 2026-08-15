import json
from pathlib import Path

import pytest

from vpnmy.models import Source


@pytest.fixture
def source():
    return Source("test", "Тест", "https://example.com/sub", "universal")


@pytest.fixture
def countries_file(tmp_path: Path):
    p = tmp_path / "countries.json"
    p.write_text(json.dumps({"DE": "🇩🇪 Германия", "RU": "🇷🇺 Россия"}))
    return p
