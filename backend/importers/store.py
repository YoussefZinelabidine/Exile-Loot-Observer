"""On-disk store for downloaded data: ``<data_dir>/<source>/<version>/<file>``.

A version folder is written to a temporary folder first and renamed into place, so a failed
download never leaves a half-written version. ``<data_dir>/<source>/ACTIVE`` names the
version in use; it only changes through ``set_active``.
"""

import hashlib
import os
import shutil
from pathlib import Path

from backend.importers.errors import ImporterError


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(value: str) -> str:
    if not value or any(c in value for c in '/\\:*?"<>|') or value in (".", ".."):
        raise ImporterError(f"unsafe name for a folder or file: {value!r}")
    return value


class DataStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def version_dir(self, source: str, version: str) -> Path:
        return self.root / _safe_name(source) / _safe_name(version)

    def has_version(self, source: str, version: str) -> bool:
        return self.version_dir(source, version).is_dir()

    def commit(self, source: str, version: str, files: dict[str, bytes]) -> list[dict[str, str]]:
        """Write all files of one version atomically; return ``[{path, sha256}]``."""
        target = self.version_dir(source, version)
        if target.exists():
            raise ImporterError(f"{source} {version} is already stored")
        tmp = target.parent / f".tmp-{version}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            listing = []
            for name, data in sorted(files.items()):
                (tmp / _safe_name(name)).write_bytes(data)
                listing.append({"path": name, "sha256": sha256_hex(data)})
            tmp.rename(target)
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ImporterError(
                f"could not store {source} {version}: {type(exc).__name__}"
            ) from exc
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return listing

    def read(self, source: str, version: str, name: str) -> bytes:
        return (self.version_dir(source, version) / _safe_name(name)).read_bytes()

    def active_version(self, source: str) -> str | None:
        pointer = self.root / _safe_name(source) / "ACTIVE"
        if not pointer.is_file():
            return None
        return pointer.read_text(encoding="utf-8").strip() or None

    def set_active(self, source: str, version: str) -> None:
        if not self.has_version(source, version):
            raise ImporterError(f"{source} {version} is not stored")
        pointer = self.root / _safe_name(source) / "ACTIVE"
        tmp = pointer.with_name(f"ACTIVE.tmp-{os.getpid()}")
        tmp.write_text(version, encoding="utf-8")
        os.replace(tmp, pointer)
