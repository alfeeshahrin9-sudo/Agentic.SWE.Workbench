"""Deterministic command-safety policy enforced before sandbox execution.

Provides three modes:
- ``strict``: Only explicitly allowlisted executables are permitted, shell
  chaining/redirection operators are rejected, and all denylist rules apply.
- ``standard`` (default): Blocks destructive filesystem operations, privilege
  escalation, remote code execution pipes, reverse shells, and force-pushes.
- ``off``: Disables command filtering (intended only for trusted test fixtures).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Literal

from .protocol import SandboxError

PolicyMode = Literal["strict", "standard", "off"]

DEFAULT_STRICT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "pytest",
        "python",
        "python3",
        "ruff",
        "mypy",
        "npm",
        "npx",
        "node",
        "pnpm",
        "yarn",
        "vitest",
        "jest",
        "git",
        "ls",
        "dir",
        "cat",
        "head",
        "tail",
        "find",
        "grep",
        "rg",
        "wc",
    }
)

# Shell metacharacters forbidden in strict mode (prevents chained command injection).
_STRICT_FORBIDDEN_OPS_RE = re.compile(r"(?:&&|\|\||;|\||`|\$\(|>\s*>?|<\s*<?)")

# Denylist rules evaluated against the normalized command string.
_DENY_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "deny.rm_root_or_escape",
        re.compile(
            r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|--recursive\s+--force)"
            r"\s+(?:/(?:\s|$|\*)|~|\.\./)",
            re.IGNORECASE,
        ),
        "Destructive recursive deletion outside workspace is forbidden",
    ),
    (
        "deny.privilege_escalation",
        re.compile(r"(?:^|[\s;&|])(?:sudo|su|doas|pkexec)\b", re.IGNORECASE),
        "Privilege escalation commands are forbidden in sandboxes",
    ),
    (
        "deny.remote_pipe_exec",
        re.compile(
            r"\b(?:curl|wget|fetch|Invoke-WebRequest|iwr)\b[^|\n]*\|\s*(?:sh|bash|zsh|dash|pwsh|powershell|python3?)\b",
            re.IGNORECASE,
        ),
        "Piping remote downloads directly into an interpreter is forbidden",
    ),
    (
        "deny.reverse_shell",
        re.compile(
            r"(?:/dev/tcp/|/dev/udp/|\bnc\s+.*-e\b|\bncat\s+.*-e\b|\bsocat\b.*EXEC:)",
            re.IGNORECASE,
        ),
        "Reverse-shell and raw socket execution patterns are forbidden",
    ),
    (
        "deny.disk_or_system_destroy",
        re.compile(
            r"(?:^|[\s;&|])(?:mkfs(?:\.[a-z0-9]+)?|fdisk|parted|shutdown|reboot|halt|poweroff)\b"
            r"|\bdd\s+[^\n]*\bof=/dev/",
            re.IGNORECASE,
        ),
        "System-level disk or power commands are forbidden",
    ),
    (
        "deny.fork_bomb",
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:"),
        "Fork bomb pattern detected",
    ),
    (
        "deny.git_force_push",
        re.compile(
            r"\bgit\s+push\b[^\n]*(?:--force|-f\b|--force-with-lease)",
            re.IGNORECASE,
        ),
        "Force-pushing git history from a sandbox is forbidden",
    ),
    (
        "deny.chmod_world_root",
        re.compile(r"\bchmod\s+(?:-R\s+)?777\s+/", re.IGNORECASE),
        "Changing permissions on root filesystem paths is forbidden",
    ),
    (
        "deny.path_traversal_exec",
        re.compile(r"(?:^|\s)\.\./\.\./"),
        "Multi-level parent path traversal in commands is forbidden",
    ),
    (
        "deny.credential_exfil",
        re.compile(
            r"\b(?:curl|wget)\b[^\n]*(?:\$OPENAI_API_KEY|\$E2B_API_KEY|\$AWS_SECRET_ACCESS_KEY|/etc/shadow|\.ssh/id_)",
            re.IGNORECASE,
        ),
        "Potential credential or secret exfiltration command is forbidden",
    ),
)


class PolicyViolationError(SandboxError):
    """Raised when a sandbox command violates the deterministic safety policy."""

    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        super().__init__(
            f"Command blocked by safety policy [{decision.rule_id}]: "
            f"{decision.reason} (command={decision.command!r})"
        )


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    rule_id: str | None = None
    command: str = ""


@dataclass(frozen=True)
class CommandPolicy:
    """Deterministic pre-execution command policy for sandbox runners."""

    mode: PolicyMode = "standard"
    allowlist: frozenset[str] = field(default_factory=lambda: DEFAULT_STRICT_ALLOWLIST)
    extra_deny_patterns: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mode(
        cls,
        mode: str = "standard",
        extra_allowlist: list[str] | None = None,
    ) -> CommandPolicy:
        normalized = (mode or "standard").strip().lower()
        if normalized not in {"strict", "standard", "off"}:
            raise SandboxError(
                f"Unknown command policy mode '{mode}'. Supported: strict, standard, off"
            )
        merged = DEFAULT_STRICT_ALLOWLIST | frozenset(
            item.strip().lower() for item in (extra_allowlist or []) if item.strip()
        )
        return cls(mode=normalized, allowlist=merged)  # type: ignore[arg-type]

    def evaluate(self, command: str | list[str]) -> PolicyDecision:
        cmd_str = _normalize_command(command)
        if not cmd_str:
            return PolicyDecision(
                allowed=False,
                reason="Empty command is not permitted",
                rule_id="deny.empty_command",
                command=cmd_str,
            )

        if self.mode == "off":
            return PolicyDecision(
                allowed=True,
                reason="Policy disabled (mode=off)",
                rule_id=None,
                command=cmd_str,
            )

        for rule_id, pattern, reason in _DENY_PATTERNS:
            if pattern.search(cmd_str):
                return PolicyDecision(
                    allowed=False,
                    reason=reason,
                    rule_id=rule_id,
                    command=cmd_str,
                )

        for idx, (pattern_str, reason) in enumerate(self.extra_deny_patterns, start=1):
            if re.search(pattern_str, cmd_str, re.IGNORECASE):
                return PolicyDecision(
                    allowed=False,
                    reason=reason,
                    rule_id=f"deny.custom_{idx}",
                    command=cmd_str,
                )

        if self.mode == "strict":
            if _STRICT_FORBIDDEN_OPS_RE.search(cmd_str):
                return PolicyDecision(
                    allowed=False,
                    reason="Shell chaining, piping, or redirection is forbidden in strict mode",
                    rule_id="strict.shell_operator",
                    command=cmd_str,
                )
            exe = _extract_executable(command, cmd_str)
            if exe not in self.allowlist:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Executable '{exe}' is not in the strict allowlist",
                    rule_id="strict.executable_not_allowed",
                    command=cmd_str,
                )

        return PolicyDecision(
            allowed=True,
            reason=f"Allowed under mode={self.mode}",
            rule_id=None,
            command=cmd_str,
        )

    def check(self, command: str | list[str]) -> PolicyDecision:
        decision = self.evaluate(command)
        if not decision.allowed:
            raise PolicyViolationError(decision)
        return decision


def _normalize_command(command: str | list[str]) -> str:
    if isinstance(command, list):
        return " ".join(str(part) for part in command).strip()
    return str(command).strip()


def _extract_executable(command: str | list[str], cmd_str: str) -> str:
    if isinstance(command, list) and command:
        raw = str(command[0])
    else:
        try:
            tokens = shlex.split(cmd_str, posix=True)
            raw = tokens[0] if tokens else ""
        except ValueError:
            raw = cmd_str.split(None, 1)[0] if cmd_str else ""
    # Strip any path prefix (e.g. /usr/bin/pytest -> pytest, python.exe -> python)
    base = raw.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base
