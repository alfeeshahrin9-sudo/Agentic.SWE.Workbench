from __future__ import annotations

"""DSPy-facing stubs for patch-prompt refinement.

When `dspy-ai` is installed and an API key is present, `PatchRefiner` can be
wired to a real DSPy program. The groundbase always exposes a deterministic
fallback so the factory works offline.
"""

from dataclasses import dataclass


@dataclass
class PatchRefiner:
    """Placeholder for a DSPy-optimized repair brief generator."""

    use_dspy: bool = False

    def refine(self, diagnosis: str, repair_brief: str, prior_attempts: int) -> str:
        if self.use_dspy:
            try:
                return _dspy_refine(diagnosis, repair_brief, prior_attempts)
            except Exception:
                pass
        return refine_repair_brief(diagnosis, repair_brief, prior_attempts)


def refine_repair_brief(diagnosis: str, repair_brief: str, prior_attempts: int) -> str:
    """Deterministic refinement used by the offline groundbase."""
    suffix = ""
    if prior_attempts >= 1:
        suffix = (
            " Prior attempt(s) failed — narrow the change to a single function "
            "and re-run the same test command."
        )
    if prior_attempts >= 3:
        suffix += " Prefer the smallest possible one-line fix."
    return f"{repair_brief} Context: {diagnosis}.{suffix}".strip()


def _dspy_refine(diagnosis: str, repair_brief: str, prior_attempts: int) -> str:
    import dspy  # type: ignore

    class Refine(dspy.Signature):
        """Tighten a repair brief for a failing software patch."""

        diagnosis: str = dspy.InputField()
        brief: str = dspy.InputField()
        attempt: int = dspy.InputField()
        refined_brief: str = dspy.OutputField()

    predictor = dspy.Predict(Refine)
    result = predictor(diagnosis=diagnosis, brief=repair_brief, attempt=prior_attempts)
    return str(result.refined_brief)
