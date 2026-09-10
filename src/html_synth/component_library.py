"""The channel component library (plan §7). Deterministic rendering only --
the LLM (html_synth/synthesizer.py's H pass) decides WHICH component and
WHAT content; this module turns that decision into markup. No component
here ever executes model-provided text as HTML/JS -- every slot is a plain
string substitution into a fixed skeleton, so a component can't smuggle in
an unexpected tag the way raw LLM-authored HTML could.
"""
from __future__ import annotations

import html
from functools import lru_cache

from config.loader import load_yaml

BASE_STYLESHEET = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{font-family:var(--sans);background:var(--bg);color:var(--text);line-height:1.6;font-size:16px;overflow-x:hidden;}

section{padding:64px 40px;max-width:1100px;margin:0 auto;}
.sec-wrap{background:var(--bg);}
.sec-alt{background:var(--bg3);}
.section-title{font-family:var(--serif);font-size:clamp(28px,4vw,42px);line-height:1.15;color:var(--text);margin-bottom:16px;}
.section-sub{font-size:16px;color:var(--text3);max-width:720px;line-height:1.7;margin-bottom:32px;}

#hero-story{padding:0;}
.hero-inner{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:96px 40px 72px;}
.hero-badge2{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:var(--accent3);background:rgba(255,59,48,0.08);padding:6px 14px;border-radius:20px;margin-bottom:24px;}
.hero-title{font-family:var(--serif);font-size:clamp(34px,6vw,58px);line-height:1.1;color:var(--text);margin-bottom:20px;max-width:820px;}
.hero-subtitle{font-size:17px;color:var(--text3);max-width:640px;line-height:1.7;margin:0 auto;}

.card{background:var(--bg2);border-radius:var(--r);border:1px solid var(--border);box-shadow:var(--shadow);padding:24px 28px;}
.card-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--text3);margin-bottom:8px;}
.card-value{font-family:var(--serif);font-size:30px;color:var(--text);line-height:1;margin-bottom:6px;}
.card-desc{font-size:14px;color:var(--text3);line-height:1.5;}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px;}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:28px;}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}

.callout{border-radius:14px;padding:18px 22px;margin-bottom:18px;}
.callout-info{background:rgba(0,113,227,0.06);border:1px solid rgba(0,113,227,0.15);}
.callout-warn{background:rgba(255,159,10,0.06);border:1px solid rgba(255,159,10,0.2);}
.callout-danger{background:rgba(255,59,48,0.06);border:1px solid rgba(255,59,48,0.15);}
.callout-success{background:rgba(52,199,89,0.06);border:1px solid rgba(52,199,89,0.2);}
.callout-text{font-size:14px;line-height:1.7;}
.callout-info .callout-text{color:#003d9e;}
.callout-warn .callout-text{color:#6b3c00;}
.callout-danger .callout-text{color:#7a0000;}
.callout-success .callout-text{color:#1a5c2a;}

.step-list{display:flex;flex-direction:column;gap:0;margin-bottom:24px;}
.step-item{display:flex;gap:14px;padding:16px 0;border-bottom:1px solid var(--border);}
.step-item:last-child{border-bottom:none;}
.step-num{width:26px;height:26px;border-radius:50%;background:var(--accent);font-size:12px;font-weight:600;color:white;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.step-title{font-size:15px;font-weight:500;color:var(--text);margin-bottom:4px;}
.step-desc{font-size:14px;color:var(--text3);line-height:1.6;}

.defbox{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:16px 20px;margin-bottom:14px;}
.defbox-term{font-weight:600;font-size:14px;color:var(--accent);margin-bottom:5px;}
.defbox-body{font-size:14px;color:var(--text3);line-height:1.6;}

.math-block{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r_sm);padding:20px 26px;margin:18px 0;font-size:16px;text-align:center;}
.math-block-label{font-size:10.5px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--text3);margin-bottom:10px;text-align:left;}
.math-block-equation{font-family:'JetBrains Mono',monospace;}

.diagram-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:24px;margin:20px 0;}
.diagram-placeholder{background:var(--bg3);border-radius:var(--r_sm);min-height:160px;}
.diagram-caption{text-align:center;font-size:12.5px;color:var(--text3);margin-top:12px;}

.metric-table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px;}
.metric-table th{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text3);padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);}
.metric-table td{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text3);}

.reveal{opacity:0;transform:translateY(16px);transition:opacity 0.6s ease,transform 0.6s ease;}
.reveal.visible{opacity:1;transform:none;}
"""

REVEAL_SCRIPT = """\
const revealObs=new IntersectionObserver(entries=>{
  entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('visible');}});
},{threshold:0.15});
document.querySelectorAll('.reveal').forEach(el=>revealObs.observe(el));
"""


@lru_cache
def _design_system() -> dict:
    return load_yaml("design_system.yaml")


def css_tokens() -> str:
    ds = _design_system()
    lines = [":root{"]
    for name, value in ds["tokens"]["colors"].items():
        lines.append(f"--{name}:{value};")
    for name, value in ds["tokens"]["fonts"].items():
        lines.append(f"--{name}:{value};")
    for name, value in ds["tokens"]["radii"].items():
        lines.append(f"--{name.replace('_', '-')}:{value};")
    for name, value in ds["tokens"]["shadows"].items():
        lines.append(f"--{name.replace('_', '-')}:{value};")
    lines.append("}")
    return "".join(lines)


def components_for_story_role(role: str) -> list[str]:
    """The component ids allowed for one story role (plan §7's table) --
    the H pass may only choose from this list, never invent a component."""
    return list(_design_system()["story_roles"].get(role, []))


def component_slots(component_id: str) -> list[str]:
    """The exact slot names one component needs -- told to the H pass so it
    fills in real fields, not guessed ones."""
    spec = _design_system()["components"].get(component_id)
    return list(spec["slots"]) if spec else []


def all_component_ids() -> list[str]:
    return list(_design_system()["components"].keys())


def _esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def _render_grid_item(item: object) -> str:
    if isinstance(item, dict):
        return render_component("card", item)
    return f'<div class="card"><div class="card-desc">{_esc(item)}</div></div>'


def render_component(component_id: str, data: dict) -> str:
    """Render one component instance. Every slot value is HTML-escaped --
    the H pass supplies plain text/numbers, never markup, so this can
    never become an injection vector regardless of what the model returns."""
    spec = _design_system()["components"].get(component_id)
    if spec is None:
        raise ValueError(f"unknown component_id {component_id!r} -- not in design_system.yaml")

    if component_id == "step_list":
        items_html = "".join(
            spec["item_skeleton"].format(
                index=i,
                title=_esc(item["title"]) if isinstance(item, dict) else _esc(item),
                desc=_esc(item.get("desc", "")) if isinstance(item, dict) else "",
            )
            for i, item in enumerate(data.get("items", []), start=1)
        )
        return spec["skeleton"].format(items=items_html)

    if component_id in ("grid_2", "grid_3"):
        # A real live run showed the model returns grid items as plain data,
        # never a pre-rendered HTML snippet -- which is also the safer
        # design (the LLM never has to produce markup at all). But the
        # exact SHAPE of that data varies (a second live run returned plain
        # strings for a grid_3 of short observations, not {title,value,desc}
        # dicts) since nothing pins the inner item shape -- handled for both
        # rather than assuming one, since crashing on a reasonable model
        # choice is worse than rendering it slightly differently.
        items_html = "".join(_render_grid_item(item) for item in data.get("items", []))
        return spec["skeleton"].format(items=items_html)

    if component_id == "metric_table":
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        header_cells = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        body_rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
        )
        return spec["skeleton"].format(header_cells=header_cells, body_rows=body_rows)

    escaped = {slot: _esc(data.get(slot, "")) for slot in spec["slots"]}
    return spec["skeleton"].format(**escaped)
