"""Metric collectors for hosts, Docker containers, and Kubernetes pods."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import platform
import shutil
import subprocess
import time
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Small wrapper around subprocess to keep command execution testable."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(self, command: list[str], timeout: int = 12) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, command, "dry-run", "", 0)
        if not command or shutil.which(command[0]) is None:
            return CommandResult(False, command, "", f"{command[0]} not found", 127)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            completed.returncode == 0,
            command,
            completed.stdout.strip(),
            completed.stderr.strip(),
            completed.returncode,
        )


class HostMetricsCollector:
    """Collect real host metrics without requiring third-party packages."""

    def __init__(self) -> None:
        self._last_cpu_sample: tuple[float, float] | None = None

    def collect(self) -> dict[str, Any]:
        cpu = _round_or_zero(self._cpu_percent())
        memory = _round_or_zero(self._memory_percent())
        disk = _round_or_zero(self._disk_percent())
        return {
            "cpu_percent": cpu,
            "memory_percent": memory,
            "disk_percent": disk,
            "source": "host",
        }

    def _cpu_percent(self) -> float:
        psutil_metrics = _try_psutil_cpu()
        if psutil_metrics is not None:
            return psutil_metrics
        if platform.system().lower() == "windows":
            value = _powershell_float(
                "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"
            )
            return value if value is not None else 0.0
        if os.path.exists("/proc/stat"):
            current = _read_proc_cpu_sample()
            if current is None:
                return 0.0
            if self._last_cpu_sample is None:
                self._last_cpu_sample = current
                time.sleep(0.05)
                current = _read_proc_cpu_sample() or current
            idle_delta = current[1] - self._last_cpu_sample[1]
            total_delta = current[0] - self._last_cpu_sample[0]
            self._last_cpu_sample = current
            if total_delta <= 0:
                return 0.0
            return max(0.0, min(100.0, 100.0 * (1 - idle_delta / total_delta)))
        try:
            load1, _, _ = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            return max(0.0, min(100.0, (load1 / cpu_count) * 100))
        except (AttributeError, OSError):
            return 0.0

    def _memory_percent(self) -> float:
        psutil_metrics = _try_psutil_memory()
        if psutil_metrics is not None:
            return psutil_metrics
        if platform.system().lower() == "windows":
            script = (
                "$m=Get-CimInstance Win32_OperatingSystem;"
                "[math]::Round((($m.TotalVisibleMemorySize-$m.FreePhysicalMemory)/"
                "$m.TotalVisibleMemorySize)*100,2)"
            )
            value = _powershell_float(script)
            return value if value is not None else 0.0
        if os.path.exists("/proc/meminfo"):
            data: dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) >= 2:
                        data[parts[0].rstrip(":")] = int(parts[1])
            total = data.get("MemTotal", 0)
            available = data.get("MemAvailable", data.get("MemFree", 0))
            if total:
                return max(0.0, min(100.0, 100.0 * (total - available) / total))
        return 0.0

    def _disk_percent(self) -> float:
        usage = shutil.disk_usage(PathLikeRoot.root())
        return max(0.0, min(100.0, usage.used / usage.total * 100))


class DockerMetricsCollector:
    """Collect Docker stats when the Docker CLI is reachable."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def collect(self, workloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for workload in workloads:
            container_name = f"{workload['deployment']}-{workload['container']}"
            stats = self.runner.run(
                [
                    "docker",
                    "stats",
                    container_name,
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                ],
                timeout=8,
            )
            if not stats.ok or not stats.stdout:
                continue
            try:
                payload = json.loads(stats.stdout.splitlines()[0])
            except json.JSONDecodeError:
                continue
            cpu = _percent_value(payload.get("CPUPerc"))
            memory = _percent_value(payload.get("MemPerc"))
            result[workload["id"]] = {
                "cpu": cpu,
                "memory": memory,
                "status": "running",
                "metrics_source": "docker",
            }
        return result


class KubernetesMetricsCollector:
    """Collect Kubernetes workload metrics when kubectl is reachable."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def collect(self, workloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        metrics: dict[str, dict[str, Any]] = {}
        for workload in workloads:
            metrics.update(self._collect_one(workload))
        return metrics

    def _collect_one(self, workload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        pods = self.runner.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                workload["namespace"],
                "-l",
                f"app={workload['deployment']}",
                "-o",
                "json",
            ],
            timeout=10,
        )
        if not pods.ok or not pods.stdout:
            return {}
        try:
            payload = json.loads(pods.stdout)
        except json.JSONDecodeError:
            return {}
        items = payload.get("items", [])
        ready = 0
        running = 0
        for pod in items:
            phase = pod.get("status", {}).get("phase")
            if phase == "Running":
                running += 1
            statuses = pod.get("status", {}).get("containerStatuses", [])
            if statuses and all(item.get("ready") for item in statuses):
                ready += 1
        status = "running" if ready == max(1, workload["desired_replicas"]) else "degraded"
        result: dict[str, Any] = {
            "replicas": len(items) or workload["replicas"],
            "status": status if running else "maintenance",
            "metrics_source": "kubernetes",
        }
        top = self.runner.run(
            [
                "kubectl",
                "top",
                "pods",
                "-n",
                workload["namespace"],
                "-l",
                f"app={workload['deployment']}",
                "--no-headers",
            ],
            timeout=10,
        )
        cpu_values = []
        memory_values = []
        if top.ok and top.stdout:
            for line in top.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    cpu_values.append(_parse_k8s_cpu(parts[1]))
                    memory_values.append(_parse_k8s_memory(parts[2]))
        if cpu_values:
            result["cpu"] = round(sum(cpu_values) / len(cpu_values), 1)
        if memory_values:
            result["memory"] = round(sum(memory_values) / len(memory_values), 1)
        return {workload["id"]: result}


class PathLikeRoot:
    """Pick a disk root that works on Windows and POSIX."""

    @staticmethod
    def root() -> str:
        return os.environ.get("SystemDrive", "C:") + "\\" if platform.system().lower() == "windows" else "/"


def _try_psutil_cpu() -> float | None:
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    return float(psutil.cpu_percent(interval=0.05))


def _try_psutil_memory() -> float | None:
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    return float(psutil.virtual_memory().percent)


def _powershell_float(script: str) -> float | None:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [executable, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return None


def _read_proc_cpu_sample() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            parts = handle.readline().split()[1:]
    except OSError:
        return None
    values = [float(part) for part in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0.0)
    return sum(values), idle


def _percent_value(value: object) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace("%", "")
    try:
        return round(float(text), 1)
    except ValueError:
        return 0.0


def _parse_k8s_cpu(value: str) -> float:
    if value.endswith("m"):
        return min(100.0, float(value[:-1]) / 10)
    return min(100.0, float(value) * 100)


def _parse_k8s_memory(value: str) -> float:
    normalized = value.lower()
    factor = 1.0
    for suffix, candidate in {"ki": 1 / 1024, "mi": 1, "gi": 1024}.items():
        if normalized.endswith(suffix):
            factor = candidate
            normalized = normalized[: -len(suffix)]
            break
    try:
        mib = float(normalized) * factor
    except ValueError:
        return 0.0
    return min(100.0, round(mib / 16_384 * 100, 1))


def _round_or_zero(value: float | None) -> float:
    return round(float(value or 0.0), 1)

