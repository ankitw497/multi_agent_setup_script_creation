"""Shared factual-safety rules injected into every narration-writing pass (B1, B2, and the
shorts narrator) (STORY_IMPROVEMENT_PLAN.md Phase 12).

B1 (`narration/generator.py`) already carried detailed hedge/verification-status rules of its
own (kept there, unchanged) -- but a targeted rewrite (B2) or a short's own narrator had no
equivalent language at all, so either could silently reintroduce exactly the kind of overclaim
B1 was told to avoid. One shared fragment, injected into all three, means fixing an overclaim
pattern here fixes it everywhere at once, instead of B1's own prompt slowly drifting out of
sync with what B2/shorts actually enforce.

2026-09-16, found on review: this fragment only ever ported HALF of what B1's own rules cover
-- the "never upgrade certainty" direction, not B1's own "never hedge a VERIFIED claim with
'is believed to'" direction, despite this docstring's own claim of "equivalent language." B2
and the shorts narrator could silently under-claim a settled fact just as easily as they could
over-claim one; both directions are now covered.
"""
from __future__ import annotations

NARRATION_FACTUAL_INVARIANTS = """\
FACTUAL SAFETY (applies to every sentence you write here):

Any sentence containing a checkable factual proposition must cite real
claim_refs from the registry given, regardless of how you classify its
sentence_type -- a fact hiding inside an explanatory_inference, a payoff,
or a transition is still a fact, and still needs grounding.

NEVER UPGRADE a claim's actual certainty or scope when you write it:
  possible                -> actual
  may / weighted          -> does / selected
  illustrative            -> literal
  conditional             -> universal
  one contributor         -> sole cause
  correlated              -> causal
  conceptual descendant   -> identical mechanism
  assumption              -> guaranteed property
If the claim registry states something as conditional, weighted, or one of
several contributing factors, your sentence must preserve that -- reducing
words is fine, quietly promoting its certainty is not.

The failure runs the other way too: state a claim whose `verification_status`
is VERIFIED as plain, direct fact -- never hedge a verified technical claim
with "is believed to", "is thought to", or "seems to"; that phrasing belongs
to genuine uncertainty, not to a fact the pipeline has already confirmed.
Under-claiming a settled fact is not a safer choice than over-claiming one --
both misstate what the registry actually says.

An EXPLANATION of why or how a mechanism behaves a certain way is itself new
technical content, not a free-form elaboration exempt from grounding just
because it "explains" rather than "asserts" -- confirmed live: a real
explanation confused two genuinely different technical properties of the
same mechanism (stating one when the source/claims actually supported the
other), and a separate explanation described one specific technique as if
it were representative of an entire category of techniques that actually
work in materially different ways. If you cannot ground the SPECIFIC
mechanism you are explaining in what the claim registry actually supports,
either stay at the level of detail the registry backs, or make clear you
are giving one illustrative case, not the general rule.
"""
