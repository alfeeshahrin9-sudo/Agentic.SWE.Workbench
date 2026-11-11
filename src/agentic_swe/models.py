from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "run") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class RunStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    CODING = "coding"
    TESTING = "testing"
    HEALING = "healing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


class Ticket(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ticket"))
    title: str
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    description: str
    target_files: list[str] = Field(default_factory=list)
    rationale: str = ""


class EditPlan(BaseModel):
    summary: str
    steps: list[PlanStep] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    test_command: str = "pytest -q"
    approved: bool = False


class FilePatch(BaseModel):
    path: str
    content: str
    action: str = "write"  # write | delete


class TestResult(BaseModel):
    __test__ = False  # prevent pytest from collecting this model as a test class

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    passed: bool = False
    duration_sec: float = 0.0

    @classmethod
    def from_process(
        cls,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_sec: float,
    ) -> TestResult:
        return cls(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            passed=exit_code == 0,
            duration_sec=duration_sec,
        )


class HealAttempt(BaseModel):
    attempt: int
    diagnosis: str
    repair_brief: str
    patches: list[FilePatch] = Field(default_factory=list)
    test_result: TestResult | None = None


class RunState(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    status: RunStatus = RunStatus.PENDING
    ticket: Ticket
    repo_path: str
    work_dir: str | None = None
    plan: EditPlan | None = None
    patches: list[FilePatch] = Field(default_factory=list)
    test_results: list[TestResult] = Field(default_factory=list)
    heal_attempts: list[HealAttempt] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    graph_summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def note(self, message: str) -> None:
        self.messages.append(message)
        self.updated_at = utcnow()
