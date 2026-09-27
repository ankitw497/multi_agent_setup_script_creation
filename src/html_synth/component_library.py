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

/* Page chrome (STORY_IMPROVEMENT_PLAN.md Phase 31 item 1): a sticky nav with one
   progress-tracker entry per beat -- pure CSS, no JS dependency (unlike an
   IntersectionObserver-based "current section" highlight, which would go
   silently inert in a static preview/non-JS viewer, the same class of gap the
   .reveal fade-in fix below already avoided). Renders nothing when there are no
   beats (assembler.py's own _render_nav already returns "" in that case). */
nav{position:sticky;top:0;z-index:100;background:var(--bg);border-bottom:1px solid var(--border);}
.nav-main{display:flex;align-items:center;padding:0 24px;height:44px;}
.nav-logo{font-family:var(--sans);font-weight:600;font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.progress-tracker{display:flex;align-items:stretch;border-top:1px solid var(--border);overflow-x:auto;}
.prog-step{flex:1 0 auto;display:flex;align-items:center;justify-content:center;gap:5px;text-decoration:none;padding:6px 10px;border-right:1px solid var(--border);white-space:nowrap;}
.prog-step:last-child{border-right:none;}
.prog-step:hover{background:var(--bg3);}
.prog-dot{width:5px;height:5px;border-radius:50%;background:var(--text3);flex-shrink:0;}
.prog-label{font-size:10.5px;color:var(--text3);font-weight:500;}

section{padding:64px 40px;max-width:1100px;margin:0 auto;}
.sec-wrap{background:var(--bg);}
.sec-alt{background:var(--bg3);}
.section-title{font-family:var(--sans);font-weight:700;letter-spacing:-0.8px;font-size:clamp(28px,4vw,42px);line-height:1.15;color:var(--text);margin-bottom:16px;}
.section-sub{font-size:16px;color:var(--text3);max-width:720px;line-height:1.7;margin-bottom:32px;}

#hero-story{padding:0;}
.hero-inner{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:96px 40px 72px;}
.hero-badge2{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:var(--accent3);background:rgba(255,59,48,0.08);padding:6px 14px;border-radius:20px;margin-bottom:24px;}
.hero-title{font-family:var(--sans);font-weight:700;letter-spacing:-1.2px;font-size:clamp(34px,6vw,58px);line-height:1.1;color:var(--text);margin-bottom:20px;max-width:820px;}
.hero-subtitle{font-size:17px;color:var(--text3);max-width:640px;line-height:1.7;margin:0 auto;}

.card{background:var(--bg2);border-radius:var(--r);border:1px solid var(--border);box-shadow:var(--shadow);padding:24px 28px;}
.card-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--text3);margin-bottom:8px;}
.card-value{font-family:var(--sans);font-weight:700;font-size:30px;color:var(--text);line-height:1;margin-bottom:6px;}
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

.math-block{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r-sm);padding:20px 26px;margin:18px 0;font-size:16px;text-align:center;}
.math-block-label{font-size:10.5px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--text3);margin-bottom:10px;text-align:left;}
.math-block-equation{font-family:'JetBrains Mono',monospace;}

.diagram-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:24px;margin:20px 0;}
.diagram-pre{font-family:'JetBrains Mono','SF Mono','Fira Code',monospace;font-size:13px;line-height:1.7;color:var(--text2);white-space:pre;overflow-x:auto;text-align:center;}
.diagram-caption{text-align:center;font-size:12.5px;color:var(--text3);margin-top:12px;}

.metric-table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px;}
.metric-table th{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text3);padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);}
.metric-table td{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text3);}

/* Phase 31 item 3: suspect_board (mystery/investigation lineup), solution_grid (a payoff
   resolving into several concrete options), case_card (one concrete scenario/example). */
.suspect-board{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:24px;}
.suspect{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r-sm);padding:16px 18px;}
.suspect-name{font-weight:600;font-size:14px;color:var(--text);margin-bottom:4px;}
.suspect-note{font-size:13px;color:var(--text3);line-height:1.5;}

.solution-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px;}
.solution-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;}
.solution-name{font-weight:600;font-size:14px;color:var(--accent);margin-bottom:6px;}
.solution-body{font-size:13.5px;color:var(--text3);line-height:1.6;}

.case-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:20px 24px;margin-bottom:20px;}
.case-title{font-weight:600;font-size:15px;color:var(--text);margin-bottom:4px;}
.case-sub{font-size:13px;color:var(--text3);margin-bottom:10px;}

/* 2026-09-11 fix (user-reported "lot of empty space"): `.reveal` elements
   used to start at opacity:0 and only become visible once an
   IntersectionObserver saw them scroll into view -- every screen past the
   first was genuinely blank at rest in any viewer that doesn't run/scroll
   the page (a static preview, a thumbnail, a non-JS viewer). A pure-CSS
   fade-in plays automatically on load with no JS/scroll dependency at
   all, and the base `opacity:1` means content is visible even if
   animations are unsupported or reduced-motion disables the animation. */
.reveal{opacity:1;animation:revealIn 0.5s ease;}
@keyframes revealIn{from{opacity:0;transform:translateY(16px);}to{opacity:1;transform:none;}}
@media (prefers-reduced-motion: reduce){.reveal{animation:none;}}
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


def escape_script_json(json_text: str) -> str:
    """Make a JSON string safe to embed inside a `<script>` tag's text
    content. `<script>` content is normally never HTML-parsed (unlike
    every other tag, which is why component slots use `_esc` above,
    not this) -- EXCEPT that the raw byte sequence "</script" always
    closes the tag regardless of what's inside a JS/JSON string literal.
    Real narration text can legitimately contain that exact substring
    (e.g. a sentence discussing HTML tags), which would otherwise break
    out of the block. "</" -> "<\\/" is the standard mitigation: valid
    JSON permits escaping "/" optionally, so `JSON.parse` still decodes
    it back to "</" correctly, while the HTML parser no longer sees a
    closing tag."""
    return json_text.replace("</", "<\\/")


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

    if component_id == "card":
        # Same real bug as step_list below, but reached a different way: a
        # dict-shaped grid_2/grid_3 ITEM is rendered through this exact
        # branch too (_render_grid_item), and the model returning a
        # legitimate partial shape (e.g. title+desc, no value) used to
        # still render an empty <div class="card-value"> box. A standalone
        # top-level "card" missing a slot is ALSO caught as a real defect by
        # verification/hard/render.py::check_component_slots_filled -- this
        # is a second, independent layer (never render a visible empty box
        # even before/without a repair cycle), not a replacement for it.
        title = _esc(data.get("title", ""))
        value = _esc(data.get("value", ""))
        desc = _esc(data.get("desc", ""))
        title_block = f'<div class="card-title">{title}</div>' if title else ""
        value_block = f'<div class="card-value">{value}</div>' if value else ""
        desc_block = f'<div class="card-desc">{desc}</div>' if desc else ""
        return spec["skeleton"].format(title_block=title_block, value_block=value_block, desc_block=desc_block)

    if component_id == "step_list":
        def _step_item_html(index: int, item: object) -> str:
            desc = _esc(item.get("desc", "")) if isinstance(item, dict) else ""
            # A title-only step (no desc at all, or a plain-string item) is a
            # legitimate shape -- but the skeleton used to always emit a
            # `<div class="step-desc">` regardless, rendering a visibly blank
            # box on the page for every such step. Confirmed live: 36 empty
            # step-desc/card-* boxes in one real run. Omit the div entirely
            # when there's no real description rather than render it empty.
            desc_block = f'<div class="step-desc">{desc}</div>' if desc else ""
            # item.get("title", "") (2026-09-27, real crash): same bug class as
            # suspect_board/solution_grid just below -- a dict item missing "title" must
            # degrade to a blank slot, not KeyError the whole page.
            title = item.get("title", "") if isinstance(item, dict) else item
            return spec["item_skeleton"].format(index=index, title=_esc(title), desc_block=desc_block)

        items_html = "".join(
            _step_item_html(i, item) for i, item in enumerate(data.get("items", []), start=1)
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

    if component_id == "suspect_board":
        def _suspect_item_html(item: object) -> str:
            # item.get("name", "") (2026-09-27, real crash): a live run's first-ever
            # solution_grid use crashed with KeyError on a dict item that omitted "name"
            # -- every other field on these items already degraded to a blank slot when
            # missing (see "body"/"note" just below); "name" must match, never
            # hard-crash the whole page over one malformed item.
            name = item.get("name", "") if isinstance(item, dict) else item
            note = _esc(item.get("note", "")) if isinstance(item, dict) else ""
            note_block = f'<div class="suspect-note">{note}</div>' if note else ""
            return spec["item_skeleton"].format(name=_esc(name), note_block=note_block)
        items_html = "".join(_suspect_item_html(item) for item in data.get("items", []))
        return spec["skeleton"].format(items=items_html)

    if component_id == "solution_grid":
        def _solution_item_html(item: object) -> str:
            # item.get("name", "") (2026-09-27, real crash): same fix as suspect_board
            # just above -- a missing "name" must degrade to a blank slot, not crash.
            name = item.get("name", "") if isinstance(item, dict) else item
            body = _esc(item.get("body", "")) if isinstance(item, dict) else ""
            body_block = f'<div class="solution-body">{body}</div>' if body else ""
            return spec["item_skeleton"].format(name=_esc(name), body_block=body_block)
        items_html = "".join(_solution_item_html(item) for item in data.get("items", []))
        return spec["skeleton"].format(items=items_html)

    if component_id == "case_card":
        sub = _esc(data.get("sub", ""))
        body = _esc(data.get("body", ""))
        sub_block = f'<div class="case-sub">{sub}</div>' if sub else ""
        body_block = f'<div class="subsection-body">{body}</div>' if body else ""
        return spec["skeleton"].format(title=_esc(data.get("title", "")), sub_block=sub_block, body_block=body_block)

    if component_id == "metric_table":
        def _metric_row_html(row: object) -> str:
            # isinstance guard (2026-09-27, same audit that found the step_list/
            # suspect_board/solution_grid crashes): `metric_table` is the one component
            # whose item shape (`rows: list[list[str]]`) is documented only in a YAML
            # comment, never sent to the model via component_slots()/TASK_PROMPT (which
            # never mentions metric_table at all) -- so a model guessing the same
            # dict-per-item shape every sibling component actually uses (e.g.
            # `[{"metric": "Accuracy", "before": "62%", "after": "89%"}]`) is a real,
            # plausible response, not just a scalar row. `for cell in row` on a dict
            # silently renders its KEYS as cell values (wrong, not a crash); on a scalar
            # it raises TypeError (crashes the whole page). Handle all three shapes.
            if isinstance(row, dict):
                cells = list(row.values())
            elif isinstance(row, (list, tuple)):
                cells = row
            else:
                cells = [row]
            return "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>"
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        header_cells = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        body_rows = "".join(_metric_row_html(row) for row in rows)
        return spec["skeleton"].format(header_cells=header_cells, body_rows=body_rows)

    escaped = {slot: _esc(data.get(slot, "")) for slot in spec["slots"]}
    return spec["skeleton"].format(**escaped)
