"""Measure the three claims SnapKaki makes, and the latency it costs.

    python -m evals.run_eval                 # everything
    python -m evals.run_eval --skip-latency  # faster, no repeated vision calls
    python -m evals.run_eval --out report.md

The point is not a score to put on a slide. It is that each claim in the
README is phrased as something falsifiable, and this runs the experiment:

  GROUNDING   in-corpus questions answered, with their source named
  REFUSAL     out-of-corpus questions declined rather than improvised
  FORM MATCH  the real demo pages recognised, other forms not
  GATE        irreversible actions stopped, every time
  LATENCY     what the user actually waits

GATE and FORM MATCH run offline and are exhaustive, because both are plain
Python. GROUNDING, REFUSAL and LATENCY call the real model and cost money,
so they run on a small fixed set.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

# --- cases ------------------------------------------------------------------

# Questions the corpus does cover. Each names the fact that must survive,
# so a fluent answer that drops the point still fails.
IN_CORPUS = [
    ("Rental Status of Residence",
     "I am still paying my HDB housing loan. Is that renting?",
     ["not rented", "own"]),
    ("Dwelling Type",
     "Which option do I tick for a 3-room flat?",
     ["hdb flat"]),
    ("Consent and Declaration by Main Applicant (Section 2B)",
     "What am I agreeing to?",
     ["iras", "cpf", "income"]),
    ("Pink NRIC / Birth Certificate Number",
     "Where do I copy this from?",
     ["card"]),
    ("Particulars of Family Members Sharing the Same NRIC Address",
     "My son moved out but is still family. Do I list him?",
     ["address"]),
]

# Questions from a different form entirely. The only correct behaviour is
# to decline: answering these from the CHAS corpus would be the exact
# failure the grounding design exists to prevent.
OUT_OF_CORPUS = [
    ("Travel medical insurance minimum coverage",
     "How much cover do I need for a Schengen visa?"),
    ("Proof of accommodation in Norway",
     "What counts as proof of accommodation?"),
    ("Purpose of the journey",
     "What should I write for a tourist visa?"),
    ("Employer CPF submission number",
     "Where do I find this?"),
]


@dataclass
class Result:
    name: str
    passed: int = 0
    total: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.passed == self.total


# --- offline, exhaustive -----------------------------------------------------

def eval_gate() -> Result:
    """Every irreversible action, at maximum confidence. No sampling: the
    set is frozen and small, so the test is the whole population."""
    from app import config
    from app.agents.confidence_gate import Stop, evaluate

    r = Result("Gate — irreversible actions stopped")
    for action in sorted(config.IRREVERSIBLE_ACTIONS):
        r.total += 1
        d = evaluate(action=action, confidence=1.0)
        if d.stopped and d.reason is Stop.IRREVERSIBLE:
            r.passed += 1
        else:
            r.notes.append(f"{action!r} was NOT stopped")

    # And the inverse: an ordinary confident step must still be allowed, or
    # a gate that stops everything would score 100% above.
    r.total += 1
    if evaluate(action="choose", confidence=0.9).allow:
        r.passed += 1
    else:
        r.notes.append("ordinary confident step was blocked")
    return r


def eval_form_match() -> Result:
    """The real demo pages, plus forms that must not be mistaken for them."""
    from app.form_match import match
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
    from test_form_match import (  # noqa: E402
        CHAS_P2_FIELDS, CHAS_P2_GUESS, CHAS_P7_FIELDS, CHAS_P7_GUESS,
        VISA_FIELDS, VISA_GUESS,
    )

    r = Result("Form match — ours recognised, others not")
    cases = [
        ("CHAS p2 (fields page)", CHAS_P2_GUESS, CHAS_P2_FIELDS, True),
        ("CHAS p7 (gate demo)", CHAS_P7_GUESS, CHAS_P7_FIELDS, True),
        ("Schengen visa", VISA_GUESS, VISA_FIELDS, False),
        ("club form, one NRIC", "Club membership", ["NRIC number"], False),
        ("blank scan", "", [], False),
    ]
    for name, guess, fields, expect_known in cases:
        r.total += 1
        m = match(guess, fields)
        if m.known == expect_known:
            r.passed += 1
        else:
            r.notes.append(
                f"{name}: known={m.known}, expected {expect_known} (score={m.score})"
            )
    return r


# --- live, costs money -------------------------------------------------------

async def eval_grounding() -> Result:
    from app.agents import field_explainer

    r = Result("Grounding — in-corpus answered and sourced")
    for label, question, must_mention in IN_CORPUS:
        r.total += 1
        e = await field_explainer.explain(label, question=question)
        # Both fields: the prompt deliberately sends "the concrete thing you
        # can look at" to how_to_decide, so checking the explanation alone
        # failed answers that were correct and well-placed.
        text = f"{e.explanation} {e.how_to_decide or ''}".lower()
        hit = any(m in text for m in must_mention)
        if e.grounded and e.sources and hit:
            r.passed += 1
        else:
            why = []
            if not e.grounded:
                why.append("not grounded")
            if not e.sources:
                why.append("no sources")
            if not hit:
                why.append(f"missing any of {must_mention}")
            r.notes.append(f"{label}: {', '.join(why)}")
    return r


async def eval_refusal() -> Result:
    from app.agents import field_explainer

    r = Result("Refusal — out-of-corpus declined, not improvised")
    for label, question in OUT_OF_CORPUS:
        r.total += 1
        e = await field_explainer.explain(label, question=question)
        declined = e.ask_someone or not e.grounded or e.confidence < 0.5
        if declined:
            r.passed += 1
        else:
            r.notes.append(
                f"{label}: ANSWERED anyway (conf={e.confidence}) — {e.explanation[:90]}"
            )
    return r


async def eval_latency(image_path: str, runs: int) -> tuple[Result, List[float]]:
    """What the user actually waits for after pressing the shutter."""
    from app.agents import vision

    r = Result(f"Latency — vision over {runs} runs")
    times: List[float] = []
    if not os.path.exists(image_path):
        r.notes.append(f"no image at {image_path}; skipped")
        return r, times

    data = open(image_path, "rb").read()
    for _ in range(runs):
        r.total += 1
        t = time.perf_counter()
        reading = await vision.extract_fields(data, image_mime="image/jpeg")
        dt = time.perf_counter() - t
        times.append(dt)
        if reading.fields:
            r.passed += 1
        else:
            r.notes.append("vision returned no fields")
    return r, times


# --- report ------------------------------------------------------------------

def render(results: List[Result], times: List[float], image_kb: Optional[int]) -> str:
    lines = [
        "# SnapKaki — evaluation",
        "",
        f"Run {time.strftime('%Y-%m-%d %H:%M')} · "
        f"`python -m evals.run_eval`",
        "",
        "| Measure | Result | |",
        "| --- | --- | --- |",
    ]
    for r in results:
        if not r.total:
            continue
        mark = "pass" if r.ok else "FAIL"
        lines.append(f"| {r.name} | {r.passed}/{r.total} ({r.rate:.0f}%) | {mark} |")

    if times:
        s = sorted(times)
        p50 = statistics.median(s)
        p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
        lines += [
            "",
            "## Latency",
            "",
            f"- image: {image_kb} KB, downscaled as the client would send it",
            f"- p50 **{p50:.1f}s** · p95 **{p95:.1f}s** · "
            f"min {s[0]:.1f}s · max {s[-1]:.1f}s over {len(s)} runs",
            "",
            "Reading a dense page is the whole cost; everything else is well "
            "under a second. See the latency note in docs/architecture.md.",
        ]

    failures = [r for r in results if r.total and not r.ok]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            for n in r.notes:
                lines.append(f"- **{r.name}** — {n}")
    else:
        lines += ["", "No failures.", ""]
    return "\n".join(lines) + "\n"


async def main_async(args) -> int:
    results = [eval_gate(), eval_form_match()]
    times: List[float] = []
    image_kb = None

    if not args.offline_only:
        results.append(await eval_grounding())
        results.append(await eval_refusal())
        if not args.skip_latency:
            lat, times = await eval_latency(args.image, args.runs)
            results.append(lat)
            if os.path.exists(args.image):
                image_kb = os.path.getsize(args.image) // 1024

    report = render(results, times, image_kb)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"written to {args.out}", file=sys.stderr)

    return 0 if all(r.ok for r in results if r.total) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", help="also write the markdown report here")
    p.add_argument("--image", default="evals/fixtures/chas_p2.jpg")
    p.add_argument("--runs", type=int, default=5, help="latency samples")
    p.add_argument("--skip-latency", action="store_true")
    p.add_argument("--offline-only", action="store_true",
                   help="gate and form match only; no model calls, no cost")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
