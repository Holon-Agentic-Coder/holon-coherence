import logging
from typing import Any

from holon_coherence.settings import (
    DEFAULT_ARCHITECT_MODEL as DEFAULT_ARCHITECT_MODEL,
)
from holon_coherence.settings import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_EXECUTOR_MODEL,
)
from holon_coherence.settings import (
    CoherenceSettings,
)

logger = logging.getLogger(__name__)


def get_default_architect_model() -> str:
    return CoherenceSettings.from_env().architect_model


def get_default_executor_model() -> str:
    return CoherenceSettings.from_env().executor_model


class SubtaskResult:
    def __init__(self, task_id: str, success: bool, raw_output: str, summary: str | None = None):
        self.task_id = task_id
        self.success = success
        self.raw_output = raw_output
        self.summary = summary if summary is not None else self._summarize(raw_output)

    def _summarize(self, raw_output: str) -> str:
        lines = raw_output.splitlines()
        if len(lines) <= 5:
            return raw_output.strip()

        status_str = "SUCCESS" if self.success else "FAILURE"
        first_lines = "\n".join(lines[:3])
        last_lines = "\n".join(lines[-3:])
        return (
            f"[Subtask {self.task_id} {status_str} | Total lines: {len(lines)}]\n"
            f"Start: {first_lines}\n...\nEnd: {last_lines}"
        )


class RingerOrchestrator:
    def __init__(
        self,
        architect_model: str | None = None,
        executor_model: str | None = None,
    ):
        self.architect_model = architect_model or get_default_architect_model()
        self.executor_model = executor_model or get_default_executor_model()
        self.subtasks: list[dict[str, Any]] = []
        self.results: list[SubtaskResult] = []

    def plan_subtask(self, task_id: str, description: str, commands: list[str]) -> dict[str, Any]:
        subtask = {
            "task_id": task_id,
            "description": description,
            "commands": commands,
            "assigned_model": self.executor_model,
        }
        self.subtasks.append(subtask)
        logger.info(
            "Subtask '%s' registered for Executor model '%s'",
            task_id,
            self.executor_model,
        )
        return subtask

    def record_execution_outcome(self, task_id: str, success: bool, raw_output: str) -> SubtaskResult:
        res = SubtaskResult(task_id=task_id, success=success, raw_output=raw_output)
        self.results.append(res)
        logger.info("Recorded outcome for subtask '%s' (success=%s)", task_id, success)
        return res

    def build_architect_summary(self) -> str:
        if not self.results:
            return "No subtasks executed yet."

        lines = ["### 🤖 Ringer Executor Subtask Results Summary\n"]
        for res in self.results:
            icon = "✅" if res.success else "❌"
            lines.append(f"#### {icon} Subtask `{res.task_id}`")
            lines.append(res.summary)
            lines.append("")

        return "\n".join(lines)
