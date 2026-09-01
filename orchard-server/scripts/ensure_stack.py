"""Bring the data-layer containers up if they aren't already.

Used by ``tests/conftest.py`` (before the suite runs) and importable for any
other pre-flight need. ``dev.ps1`` does the equivalent in PowerShell.

Everything - ``docker compose up`` for the full stack, ``./dev.ps1`` for
bare-metal app processes, and ``pytest`` - talks to the *same* ``postgres``
and ``chromadb`` containers; there is no SQLite/embedded fallback.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"

DEFAULT_SERVICES = ("postgres", "chromadb")


class StackUnavailable(RuntimeError):
    """Docker isn't installed / running, or the containers failed to start."""


def ensure_stack(services: tuple[str, ...] = DEFAULT_SERVICES, *, timeout: int = 180) -> None:
    """``docker compose up -d --wait`` the given services (idempotent).

    ``--wait`` blocks until each service's healthcheck passes (both are
    defined in docker-compose.yml). Raises :class:`StackUnavailable` with an
    actionable message if Docker isn't there or the services never got healthy.
    """
    if shutil.which("docker") is None:
        raise StackUnavailable(
            "The `docker` CLI was not found. Install Docker Desktop and start "
            "it - Postgres + Chroma run in containers and are required for "
            "both the app and the test suite."
        )

    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "up", "-d", "--wait", "--wait-timeout", str(timeout), *services,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout + 30)
    except FileNotFoundError as exc:  # pragma: no cover - shutil.which already guards
        raise StackUnavailable(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise StackUnavailable(
            f"`{' '.join(cmd)}` timed out after {timeout}s waiting for healthchecks."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise StackUnavailable(
            "Could not start the data-layer containers. Is the Docker daemon "
            f"running?\n\n$ {' '.join(cmd)}\n{exc.stderr or exc.stdout}"
        ) from exc


if __name__ == "__main__":  # `python -m scripts.ensure_stack`
    ensure_stack()
    print("postgres + chromadb are up and healthy.")
