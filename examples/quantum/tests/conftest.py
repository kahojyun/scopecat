from __future__ import annotations

import os
import shutil
import socket
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import cast

import pytest
import uvicorn

from quantum_lab_demo import DAEMON_URL_ENV, quantum_lab_application
from scopecat.project import load_project
from scopecat_server import LocalDaemonRuntime

EXAMPLE_ROOT = Path(__file__).parents[1]
if str(EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_ROOT))


@dataclass(frozen=True, slots=True)
class DemoDaemon:
    url: str
    runtime: LocalDaemonRuntime


@pytest.fixture(scope="session", autouse=True)
def demo_daemon(tmp_path_factory: pytest.TempPathFactory) -> Generator[DemoDaemon]:
    """Run every notebook against one real HTTP daemon instance."""

    project_root = tmp_path_factory.mktemp("quantum-project")
    shutil.copytree(EXAMPLE_ROOT / "config", project_root / "config")
    shutil.copy2(EXAMPLE_ROOT / "scopecat.toml", project_root / "scopecat.toml")
    project = load_project(project_root / "scopecat.toml")
    runtime = LocalDaemonRuntime(
        project.root,
        application_factory=quantum_lab_application,
        bootstrap_config=project.bootstrap_config,
    )
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = cast("tuple[str, int]", listener.getsockname())[1]
    server = uvicorn.Server(
        uvicorn.Config(
            runtime.app(static_dir=None),
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            lifespan="off",
        )
    )
    thread = Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="quantum-demo-daemon",
        daemon=True,
    )
    previous_url = os.environ.get(DAEMON_URL_ENV)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=10)
        runtime.close()
        raise RuntimeError("quantum demo daemon failed to start")

    url = f"http://127.0.0.1:{port}"
    os.environ[DAEMON_URL_ENV] = url
    try:
        yield DemoDaemon(url=url, runtime=runtime)
    finally:
        if previous_url is None:
            os.environ.pop(DAEMON_URL_ENV, None)
        else:
            os.environ[DAEMON_URL_ENV] = previous_url
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        runtime.close()
