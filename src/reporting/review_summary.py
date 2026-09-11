"""review_summary.md -- the human-readable counterpart to review_bundle.json
(design doc §73, plan §14). The machine gets JSON; a person gets this.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from orchestration.pipeline import PipelineResult

if TYPE_CHECKING:
    from llm.usage import CostReport

_SEVERITY_HEADINGS = (("critical", "Critical"), ("major", "Major"), ("minor", "Minor"))


def render_review_summary(
    result: PipelineResult, cost_report: "CostReport | None" = None,
    degraded_capabilities: list[str] | None = None,
) -> str:
    lines = [
        f"# Review Summary",
        "",
        f"**Final status:** {result.final_status}",
        f"**Story replans used:** {result.story_replans_used}",
        f"**Targeted revisions used:** {result.major_revisions_used}",
        "",
    ]

    if degraded_capabilities:
        lines.append("## Degraded capabilities")
        lines += [f"- {d}" for d in degraded_capabilities]
        lines.append("")

    if result.review_bundle.hard_failures:
        lines.append("## Hard failures")
        lines += [f"- {f}" for f in result.review_bundle.hard_failures]
        lines.append("")
    else:
        lines.append("## Hard failures\nNone.\n")

    for severity, heading in _SEVERITY_HEADINGS:
        issues = [i for i in result.review_bundle.issues if i.severity == severity]
        lines.append(f"## {heading}")
        if not issues:
            lines.append("None.")
        else:
            for idx, issue in enumerate(issues, start=1):
                lines.append(f"{idx}. **[{issue.category}/{issue.layer}]** {issue.problem}")
                lines.append(f"   - why it matters: {issue.why_it_matters}")
                lines.append(f"   - recommended: {issue.recommended_intent}")
        lines.append("")

    lines.append("## Diagnostics")
    if not result.review_bundle.diagnostics:
        lines.append("None.")
    else:
        for d in result.review_bundle.diagnostics:
            lines.append(f"- **[{d.band}] {d.dimension}**: {d.evidence}"
                         + (f" (target: {d.target})" if d.target else ""))
    lines.append("")

    if cost_report is not None:
        lines.append("## Cost")
        lines.append(f"**Total billed:** ${cost_report.billed_usd:.4f}")
        if cost_report.by_agent:
            lines.append("")
            lines.append("| Agent | Calls | Billed USD |")
            lines.append("|---|---|---|")
            for agent, summary in cost_report.by_agent.items():
                lines.append(f"| {agent} | {summary.calls} | ${summary.billed_microusd / 1_000_000:.4f} |")
        lines.append("")

    lines.append("## Run log")
    lines += [f"- {line}" for line in result.log]

    return "\n".join(lines)
