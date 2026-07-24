"""Assemble server distributions from Python sources and a built UI."""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-server"
UI_DIST = REPOSITORY_ROOT / "apps" / "scopecat-ui" / "dist"
DIST_ROOT = REPOSITORY_ROOT / "dist" / "scopecat-server"
STATIC_INDEX = "scopecat_server/static/index.html"
ASSET_RE = re.compile(r'(?:src|href)="(/assets/[^"]+)"')


def main() -> None:
    if not (UI_DIST / "index.html").is_file():
        raise RuntimeError("UI bundle is missing; run `pnpm run build` first")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build server distributions")

    with tempfile.TemporaryDirectory(prefix="scopecat-server-build-") as temporary:
        staged_server = Path(temporary) / "scopecat-server"
        shutil.copytree(SERVER_ROOT, staged_server)
        staged_static = staged_server / "src" / "scopecat_server" / "static"
        shutil.rmtree(staged_static, ignore_errors=True)
        shutil.copytree(UI_DIST, staged_static)
        subprocess.run(  # noqa: S603 - resolved executable and fixed arguments
            [
                uv,
                "build",
                str(staged_server),
                "--out-dir",
                str(DIST_ROOT),
                "--clear",
                "--no-sources",
            ],
            check=True,
        )

    _verify_distributions()


def _verify_distributions() -> None:
    wheel = _only(DIST_ROOT.glob("scopecat_server-*.whl"), "server wheel")
    source = _only(DIST_ROOT.glob("scopecat_server-*.tar.gz"), "server sdist")

    with zipfile.ZipFile(wheel) as archive:
        _verify_bundle(
            names=set(archive.namelist()),
            index=archive.read(STATIC_INDEX).decode(),
            prefix="scopecat_server/static/",
        )
    with tarfile.open(source, "r:gz") as archive:
        names = set(archive.getnames())
        index_name = _only_name_ending(names, f"/src/{STATIC_INDEX}")
        extracted = archive.extractfile(index_name)
        if extracted is None:
            raise RuntimeError(f"cannot read {index_name} from {source.name}")
        _verify_bundle(
            names=names,
            index=extracted.read().decode(),
            prefix=index_name.removesuffix("index.html"),
        )

    print(f"verified GUI bundle in {wheel.name} and {source.name}")


def _verify_bundle(*, names: set[str], index: str, prefix: str) -> None:
    assets = {match.group(1).removeprefix("/") for match in ASSET_RE.finditer(index)}
    if not assets:
        raise RuntimeError("GUI index does not reference any built assets")
    missing = sorted(
        f"{prefix}{asset}" for asset in assets if f"{prefix}{asset}" not in names
    )
    if missing:
        raise RuntimeError(f"GUI bundle is missing referenced assets: {missing}")


def _only(paths: Iterable[Path], label: str) -> Path:
    selected = tuple(paths)
    if len(selected) != 1:
        raise RuntimeError(f"expected exactly one {label}, found {len(selected)}")
    return selected[0]


def _only_name_ending(names: set[str], suffix: str) -> str:
    selected = tuple(name for name in names if name.endswith(suffix))
    if len(selected) != 1:
        raise RuntimeError(
            f"expected exactly one archive member ending in {suffix}, "
            f"found {len(selected)}"
        )
    return selected[0]


if __name__ == "__main__":
    main()
