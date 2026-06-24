import asyncio
import json

import pytest

from pier.environments.daytona import DaytonaEnvironment
from pier.environments.docker import write_capabilities_compose_file
from pier.environments.modal import ModalEnvironment


def test_write_capabilities_compose_file_emits_cap_add(tmp_path):
    path = tmp_path / "docker-compose-capabilities.json"

    write_capabilities_compose_file(
        path,
        cap_add=["SYS_PTRACE"],
        security_opt=["seccomp:unconfined"],
    )

    compose = json.loads(path.read_text())
    assert compose == {
        "services": {
            "main": {
                "cap_add": ["SYS_PTRACE"],
                "security_opt": ["seccomp:unconfined"],
            }
        }
    }


@pytest.mark.parametrize("env_class", [ModalEnvironment, DaytonaEnvironment])
def test_capture_requires_docker_backend(monkeypatch, env_class):
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")

    env = env_class.__new__(env_class)

    with pytest.raises(RuntimeError, match="only supported on the Docker backend"):
        asyncio.run(env.start(force_build=False))
