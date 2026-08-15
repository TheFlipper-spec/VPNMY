#!/usr/bin/env python3
"""Загружает закреплённый Xray Core и проверяет SHA-256 до распаковки."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


class InstallError(RuntimeError):
    pass


def asset_name() -> str:
    if platform.system().lower() != "linux":
        raise InstallError("автоустановка поддерживает только Linux")
    mapping = {
        "x86_64": "Xray-linux-64.zip",
        "amd64": "Xray-linux-64.zip",
        "aarch64": "Xray-linux-arm64-v8a.zip",
        "arm64": "Xray-linux-arm64-v8a.zip",
    }
    try:
        return mapping[platform.machine().lower()]
    except KeyError as exc:
        raise InstallError(f"неподдерживаемая архитектура: {platform.machine()}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "VPNMY-Xray-Installer/2.0"})
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
    raise InstallError(f"архив не загрузился после трёх попыток: {last_error}")


def install(version: str, expected_sha256: str, output: Path) -> None:
    if (
        not version.startswith("v")
        or len(expected_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256)
    ):
        raise InstallError("версия или SHA-256 имеют некорректный формат")
    asset = asset_name()
    url = f"https://github.com/XTLS/Xray-core/releases/download/{version}/{asset}"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xray-install-") as directory:
        archive = Path(directory) / asset
        download(url, archive)
        actual = sha256(archive)
        if actual.lower() != expected_sha256.lower():
            raise InstallError(f"SHA-256 не совпал: ожидался {expected_sha256}, получен {actual}")
        with zipfile.ZipFile(archive) as package:
            try:
                member = package.getinfo("xray")
            except KeyError as exc:
                raise InstallError("в архиве отсутствует файл xray") from exc
            if member.file_size > 100_000_000:
                raise InstallError("исполняемый файл Xray имеет подозрительный размер")
            temporary = output.with_suffix(".tmp")
            with package.open(member) as source, temporary.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.replace(temporary, output)
    check = subprocess.run([str(output), "version"], capture_output=True, text=True, timeout=10)
    if check.returncode != 0 or "Xray" not in check.stdout:
        output.unlink(missing_ok=True)
        raise InstallError("установленный Xray не запускается")
    print(check.stdout.splitlines()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        install(args.version, args.sha256, args.output)
    except (InstallError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Ошибка установки Xray: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
