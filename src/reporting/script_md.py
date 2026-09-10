"""script.md (plan §16, §17) -- the plain, human-readable spoken script.

Not a design artifact: no claim ids, no sentence_type, no grounding
metadata -- exactly what a narrator would read, in scene order. The
machine-readable counterpart is final/narration.json (the raw
SceneNarration list); this is the "just let me read the script" version.
"""
from __future__ import annotations

from narration.models import SceneNarration
from planning.models import StoryPlan


def render_script_md(plan: StoryPlan, narration: list[SceneNarration]) -> str:
    lines = [f"# {plan.title.chosen}", ""]

    for scene in narration:
        lines.append(f"## {scene.scene_id}")
        lines.append("")
        text = " ".join(s.text for s in scene.sentences)
        lines.append(text if text else "*(no narration)*")
        lines.append("")

    return "\n".join(lines)
