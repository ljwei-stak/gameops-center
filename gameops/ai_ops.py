"""AI-assisted diagnosis, operation logging, and report generation."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import request


class AIOpsAssistant:
    """Use an OpenAI-compatible chat API when configured, with a local fallback."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("GAMEOPS_LLM_API_KEY", "")
        self.api_base = os.environ.get("GAMEOPS_LLM_API_BASE", "https://api.openai.com/v1")
        self.model = os.environ.get("GAMEOPS_LLM_MODEL", "gpt-4.1-mini")
        self.user_agent = os.environ.get("GAMEOPS_LLM_USER_AGENT", "GameOps-Center/1.0")

    def diagnose(self, alerts: list[dict[str, Any]], workloads: list[dict[str, Any]]) -> dict[str, Any]:
        if self.api_key:
            response = self._chat(
                "你是资深 SRE。请根据告警和工作负载状态输出 JSON，包含 summary、root_causes、actions、risk。",
                {"alerts": alerts[:8], "workloads": workloads[:12]},
            )
            parsed = _try_json(response)
            if isinstance(parsed, dict):
                return parsed
        return self._fallback_diagnosis(alerts, workloads)

    def write_operation_log(
        self,
        action: str,
        actor: str,
        target: str,
        result: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> str:
        if self.api_key:
            response = self._chat(
                "请把运维操作写成一条简洁中文审计日志，包含操作者、动作、目标、结果和风险提示。",
                {"action": action, "actor": actor, "target": target, "result": result},
            )
            if response:
                return response.strip()
        status = "成功" if _result_ok(result) else "已记录"
        return f"{actor} 执行 {action}，目标 {target}，结果 {status}。"

    def write_report(
        self,
        overview: dict[str, Any],
        alerts: list[dict[str, Any]],
        deployments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.api_key:
            response = self._chat(
                "请生成自动化运维日报 JSON，包含 title、summary、highlights、risks、next_actions。",
                {"overview": overview, "alerts": alerts[:10], "deployments": deployments[:8]},
            )
            parsed = _try_json(response)
            if isinstance(parsed, dict):
                return parsed
        return {
            "title": "GameOps 自动化运维报告",
            "summary": (
                f"当前在线 {overview['summary']['online_players']} 人，"
                f"活跃告警 {overview['summary']['active_alerts']} 条，"
                f"平均 P95 延迟 {overview['summary']['avg_latency_p95']}ms。"
            ),
            "highlights": [
                f"健康工作负载 {overview['summary']['healthy_workloads']}/{overview['summary']['total_workloads']}",
                f"宿主机 CPU {overview['host']['cpu_percent']}%，内存 {overview['host']['memory_percent']}%",
                f"最近发布 {len(deployments[:5])} 次",
            ],
            "risks": [f"{item['severity']} - {item['title']} - {item['workload_name']}" for item in alerts[:5]]
            or ["暂无高优先级风险"],
            "next_actions": self._fallback_diagnosis(alerts, [])["actions"],
        }

    def _fallback_diagnosis(
        self, alerts: list[dict[str, Any]], workloads: list[dict[str, Any]]
    ) -> dict[str, Any]:
        actions = []
        root_causes = []
        for alert in alerts[:6]:
            metric = alert["metric"]
            if metric == "cpu":
                root_causes.append(f"{alert['workload_name']} CPU 压力过高，可能是战斗同步或匹配流量集中。")
                actions.append(f"对 {alert['workload_id']} 执行扩容，并观察 5 分钟 P95 延迟。")
            elif metric == "memory":
                root_causes.append(f"{alert['workload_name']} 内存水位过高，可能存在房间对象或会话缓存堆积。")
                actions.append(f"滚动重启 {alert['workload_id']}，同时检查最近版本的内存分配变化。")
            elif metric == "latency_p95":
                root_causes.append(f"{alert['workload_name']} P95 延迟升高，可能与跨区链路或 Pod 负载有关。")
                actions.append(f"降低 {alert['region']} 流量权重或切换到健康战区。")
            elif metric == "capacity":
                root_causes.append(f"{alert['workload_name']} 玩家容量接近上限。")
                actions.append(f"把 {alert['workload_id']} 副本数扩到当前值 +1。")
            else:
                actions.append(alert["runbook"])
        if not actions:
            actions = ["保持自动巡检，继续观察容量、延迟和发布窗口。"]
        return {
            "summary": f"发现 {len(alerts)} 条活跃告警。" if alerts else "当前没有活跃告警。",
            "root_causes": root_causes or ["未发现明确异常，系统处于稳定区间。"],
            "actions": _unique(actions)[:6],
            "risk": "critical" if any(item["severity"] == "critical" for item in alerts) else "normal",
        }

    def _chat(self, system_prompt: str, payload: dict[str, Any]) -> str:
        url = self.api_base.rstrip("/") + "/chat/completions"
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                "temperature": 0.2,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return ""
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _try_json(text: str) -> Any:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _result_ok(result: dict[str, Any] | list[dict[str, Any]] | None) -> bool:
    if result is None:
        return False
    if isinstance(result, list):
        return all(item.get("ok") for item in result)
    return bool(result.get("ok", True))


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

