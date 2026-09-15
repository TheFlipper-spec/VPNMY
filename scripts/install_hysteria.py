#!/usr/bin/env python3
"""Загружает закреплённый официальный клиент Hysteria и проверяет SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


class InstallError(RuntimeError):
    pass


def asset_name() -> str:
    import platform

    if platform.system().lower() != "linux":
        raise InstallError("автоустановка поддерживает только Linux")
    mapping = {
        "x86_64": "hysteria-linux-amd64",
        "amd64": "hysteria-linux-amd64",
        "aarch64": "hysteria-linux-arm64",
        "arm64": "hysteria-linux-arm64",
    }
    try:
        return mapping[platform.machine().lower()]
    except KeyError as exc:
        raise InstallError(f"неподдерживаемая архитектура: {platform.machine()}") from exc


def normalize_tag(version: str) -> str:
    return version if version.startswith("app/") else f"app/{version}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "VPNMY-Hysteria-Installer/1.0"})
    last_error: OSError | None = None
    for attempt in range(3):
        try:
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                target.open("wb") as output,
            ):
                if response.status != 200:
                    raise InstallError(f"сервер вернул HTTP {response.status}")
                shutil.copyfileobj(response, output)
            return
        except OSError as exc:
            last_error = exc
            target.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2**attempt)
    raise InstallError(f"бинарный файл не загрузился после трёх попыток: {last_error}")


def install(version: str, expected_sha256: str, output: Path) -> None:
    if len(expected_sha256) != 64 or any(
        c not in "0123456789abcdefABCDEF" for c in expected_sha256
    ):
        raise InstallError("SHA-256 имеет некорректный формат")
    tag = normalize_tag(version)
    asset = asset_name()
    url = f"https://github.com/apernet/hysteria/releases/download/{tag}/{asset}"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hysteria-install-") as directory:
        archive = Path(directory) / asset
        download(url, archive)
        actual = sha256(archive)
        if actual.lower() != expected_sha256.lower():
            raise InstallError(f"SHA-256 не совпал: ожидался {expected_sha256}, получен {actual}")
        if archive.stat().st_size > 100_000_000:
            raise InstallError("исполняемый файл Hysteria имеет подозрительный размер")
        temporary = output.with_suffix(".tmp")
        shutil.copyfile(archive, temporary)
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temporary, output)
    check = subprocess.run(
        [str(output), "version"], capture_output=True, text=True, timeout=10
    )
    combined = (check.stdout or "") + (check.stderr or "")
    if check.returncode != 0 or "hysteria" not in combined.lower():
        output.unlink(missing_ok=True)
        raise InstallError("установленный клиент Hysteria не запускается")
    print(combined.splitlines()[0] if combined.strip() else "Hysteria installed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="тег релиза, например app/v2.12.2")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        install(args.version, args.sha256, args.output)
    except (InstallError, OSError) as exc:
        parser.exit(1, f"Ошибка установки Hysteria: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
