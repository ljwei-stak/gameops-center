"""Operation adapters for Docker and Kubernetes."""

from __future__ import annotations

import os
import shutil
from typing import Any, Protocol

from .collectors import CommandResult, CommandRunner


class RuntimeAdapter(Protocol):
    name: str

    def restart_workload(self, workload: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    def deploy_image(self, workload: dict[str, Any], image: str) -> list[dict[str, Any]]:
        ...

    def scale_workload(self, workload: dict[str, Any], replicas: int) -> list[dict[str, Any]]:
        ...


class DockerAdapter:
    """Run workload operations against Docker containers."""

    name = "docker"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(dry_run=not _has_binary("docker"))

    def restart_workload(self, workload: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._run(["docker", "restart", _container_name(workload)])]

    def deploy_image(self, workload: dict[str, Any], image: str) -> list[dict[str, Any]]:
        name = _container_name(workload)
        commands = [
            ["docker", "pull", image],
            ["docker", "rm", "-f", name],
            [
                "docker",
                "run",
                "-d",
                "--restart",
                "unless-stopped",
                "--name",
                name,
                "--label",
                f"gameops.workload={workload['id']}",
                "--label",
                f"app={workload['deployment']}",
                image,
            ],
        ]
        return [self._run(command) for command in commands]

    def scale_workload(self, workload: dict[str, Any], replicas: int) -> list[dict[str, Any]]:
        results = []
        image = workload["image"]
        base_name = _container_name(workload)
        current = int(workload["replicas"])
        if replicas > current:
            for index in range(current + 1, replicas + 1):
                results.append(
                    self._run(
                        [
                            "docker",
                            "run",
                            "-d",
                            "--restart",
                            "unless-stopped",
                            "--name",
                            f"{base_name}-{index}",
                            "--label",
                            f"gameops.workload={workload['id']}",
                            "--label",
                            f"app={workload['deployment']}",
                            image,
                        ]
                    )
                )
        elif replicas < current:
            for index in range(current, replicas, -1):
                suffix = "" if index == 1 else f"-{index}"
                results.append(self._run(["docker", "rm", "-f", f"{base_name}{suffix}"]))
        else:
            results.append(
                _as_dict(CommandResult(True, ["docker", "scale", base_name, str(replicas)], "no-op", "", 0))
            )
        return results

    def _run(self, command: list[str]) -> dict[str, Any]:
        return _as_dict(self.runner.run(command))


class KubernetesAdapter:
    """Run workload operations against Kubernetes Deployments."""

    name = "kubernetes"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(dry_run=not _has_binary("kubectl"))

    def restart_workload(self, workload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._run(
                [
                    "kubectl",
                    "rollout",
                    "restart",
                    f"deployment/{workload['deployment']}",
                    "-n",
                    workload["namespace"],
                ]
            ),
            self._run(
                [
                    "kubectl",
                    "rollout",
                    "status",
                    f"deployment/{workload['deployment']}",
                    "-n",
                    workload["namespace"],
                    "--timeout=120s",
                ]
            ),
        ]

    def deploy_image(self, workload: dict[str, Any], image: str) -> list[dict[str, Any]]:
        return [
            self._run(
                [
                    "kubectl",
                    "set",
                    "image",
                    f"deployment/{workload['deployment']}",
                    f"{workload['container']}={image}",
                    "-n",
                    workload["namespace"],
                ]
            ),
            self._run(
                [
                    "kubectl",
                    "rollout",
                    "status",
                    f"deployment/{workload['deployment']}",
                    "-n",
                    workload["namespace"],
                    "--timeout=180s",
                ]
            ),
        ]

    def scale_workload(self, workload: dict[str, Any], replicas: int) -> list[dict[str, Any]]:
        return [
            self._run(
                [
                    "kubectl",
                    "scale",
                    f"deployment/{workload['deployment']}",
                    "-n",
                    workload["namespace"],
                    f"--replicas={replicas}",
                ]
            ),
            self._run(
                [
                    "kubectl",
                    "rollout",
                    "status",
                    f"deployment/{workload['deployment']}",
                    "-n",
                    workload["namespace"],
                    "--timeout=120s",
                ]
            ),
        ]

    def _run(self, command: list[str]) -> dict[str, Any]:
        return _as_dict(self.runner.run(command))


class CompositeAdapter:
    """Choose Docker or Kubernetes based on configuration and availability."""

    def __init__(self, mode: str | None = None, runner: CommandRunner | None = None) -> None:
        configured = (mode or os.environ.get("GAMEOPS_RUNTIME", "auto")).lower()
        dry_run_requested = os.environ.get("GAMEOPS_DRY_RUN", "true").lower() not in {"0", "false", "no"}
        trusted_runtime = os.environ.get("GAMEOPS_TRUSTED_RUNTIME", "").lower() in {"1", "true", "yes"}
        dry_run = dry_run_requested or not trusted_runtime
        runner = runner or CommandRunner(dry_run=dry_run)
        if configured == "kubernetes":
            self.adapter: RuntimeAdapter = KubernetesAdapter(runner)
        elif configured == "docker":
            self.adapter = DockerAdapter(runner)
        elif _has_binary("kubectl"):
            self.adapter = KubernetesAdapter(runner)
        elif _has_binary("docker"):
            self.adapter = DockerAdapter(runner)
        else:
            self.adapter = KubernetesAdapter(CommandRunner(dry_run=True))
        self.name = self.adapter.name

    def restart_workload(self, workload: dict[str, Any]) -> list[dict[str, Any]]:
        return self.adapter.restart_workload(workload)

    def deploy_image(self, workload: dict[str, Any], image: str) -> list[dict[str, Any]]:
        return self.adapter.deploy_image(workload, image)

    def scale_workload(self, workload: dict[str, Any], replicas: int) -> list[dict[str, Any]]:
        return self.adapter.scale_workload(workload, replicas)


def _container_name(workload: dict[str, Any]) -> str:
    return f"{workload['deployment']}-{workload['container']}"


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _as_dict(result: CommandResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }

