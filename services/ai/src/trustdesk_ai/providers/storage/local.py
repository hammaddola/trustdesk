"""Local-disk file storage. Keys are generated server-side; paths are confined to the base directory."""

from __future__ import annotations

import re
from pathlib import Path

import anyio

_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,250}$")


class LocalStorage:
    name = "local"

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir).resolve()

    def _path(self, key: str) -> Path:
        if not _KEY.match(key) or ".." in key:
            raise ValueError("invalid storage key")
        path = (self._base / key).resolve()
        if not path.is_relative_to(self._base):
            raise ValueError("invalid storage key")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await anyio.to_thread.run_sync(write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        return await anyio.to_thread.run_sync(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))
