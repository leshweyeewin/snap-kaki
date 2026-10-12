"""Measure the accessibility claims instead of asserting them.

The challenge theme is Information Accessibility and the named beneficiaries
are elderly people and their caregivers. "Large text, big targets, high
contrast" is easy to write in a README and easy to drift away from, so it is
checked against the running page the same way everything else here is.

What is checked, and against what:

  CONTRAST      WCAG 2.2 AA: 4.5:1 for body text, 3:1 for large text
                (>=24px, or >=18.66px bold). Computed from the real painted
                colours, walking up for the effective background.
  TAP TARGETS   WCAG 2.2 AA 2.5.8 requires 24x24 CSS px. The product's own
                floor is 44px, which is the stricter AAA-era guidance and
                the right one for the user we claim.
  TEXT SIZE     the product's own floor of 16px for body copy.
  NAMES         every interactive element reachable has an accessible name.
  FOCUS         a visible focus indicator that is not merely `outline: none`.

Run through run_eval (--a11y) or standalone:

    python -m evals.a11y --url https://snapkaki.web.app
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import List

# Collected in the page: computed styles are the only honest source, since
# the question is what was actually painted, not what the stylesheet said.
PROBE = r"""
() => {
  const parse = (c) => {
    const m = (c || "").match(/[\d.]+/g);
    if (!m) return null;
    let [r, g, b, a] = m.map(Number);
    // color-mix() resolves to CSS Color 4 "color(srgb 0.99 0.97 0.93)",
    // whose components are 0-1, not 0-255. Treating those as 8-bit turned
    // near-white into near-black and invented four contrast failures.
    if (/^\s*color\(/.test(c)) { r *= 255; g *= 255; b *= 255; }
    return { r, g, b, a: a === undefined ? 1 : a };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  // The painted background: the first ancestor that is not transparent.
  //
  // Gradients have to be handled or this is worthless: a solid-colour read
  // of background-color on a gradient button returns transparent, the walk
  // continues to the page behind, and white-on-teal is reported as 1.1:1.
  // For a gradient we take the WORST of its colour stops, which is the
  // honest bound - some part of the text really does sit on that stop.
  const stopsOf = (css) => {
    const found = (css || "").match(/rgba?\([^)]+\)/g) || [];
    return found.map(parse).filter((c) => c && c.a > 0.5);
  };
  const bgOf = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const s = getComputedStyle(n);
      const grad = stopsOf(s.backgroundImage);
      if (grad.length) return grad;               // several candidates
      const c = parse(s.backgroundColor);
      if (c && c.a > 0.95) return [c];
      n = n.parentElement;
    }
    return [{ r: 255, g: 255, b: 255, a: 1 }];
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== "none" && s.visibility !== "hidden" &&
           s.opacity !== "0" && r.width > 0 && r.height > 0;
  };

  const out = { contrast: [], targets: [], small: [], unnamed: [], focus: [] };

  // --- contrast + text size -------------------------------------------
  document.querySelectorAll("p, span, b, h1, h2, a, button, li, label, option, textarea")
    .forEach((el) => {
      if (!visible(el)) return;
      const own = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3 && n.textContent.trim())
        .map((n) => n.textContent.trim()).join(" ");
      if (!own) return;

      const s = getComputedStyle(el);
      const fg = parse(s.color);
      if (!fg) return;
      const size = parseFloat(s.fontSize);
      const weight = parseInt(s.fontWeight, 10) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const need = large ? 3.0 : 4.5;
      // Worst stop wins: the text has to be legible on all of them.
      const got = Math.min(...bgOf(el).map((bg) => ratio(fg, bg)));

      const row = { text: own.slice(0, 44), size, weight, got: +got.toFixed(2), need };
      if (got < need) out.contrast.push(row);
      // The 16px floor applies to body COPY - paragraphs, list items,
      // the things someone reads. Micro-labels ("YOUR PROGRESS") and the
      // provenance chips are supplementary and were never claimed to meet
      // it. Contrast still applies to them, and still must pass.
      const copy = ["P", "LI", "TEXTAREA"].includes(el.tagName) &&
                   !el.closest(".sources, .progress-head, .kind, .card-kicker, .list-title");
      if (copy && size < 16 && own.length > 12) out.small.push(row);
    });

  // --- tap targets + accessible names ----------------------------------
  // A screen-reader-only label is 1x1 by design. It is not a tap target,
  // and flagging it as one buries the real findings.
  const srOnly = (el) => {
    const r = el.getBoundingClientRect();
    return r.width <= 2 || r.height <= 2;
  };
  // The accessible name can come from a separate <label for>, or from
  // aria-labelledby - not only from the element's own text.
  const nameOf = (el) => {
    const byAria = el.getAttribute("aria-label");
    if (byAria && byAria.trim()) return byAria.trim();
    const ref = el.getAttribute("aria-labelledby");
    if (ref) {
      const t = ref.split(/\s+/).map((id) => {
        const n = document.getElementById(id);
        return n ? n.textContent : "";
      }).join(" ").trim();
      if (t) return t;
    }
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab && lab.textContent.trim()) return lab.textContent.trim();
    }
    const wrapLabel = el.closest("label");
    if (wrapLabel && wrapLabel.textContent.trim()) return wrapLabel.textContent.trim();
    return (el.innerText || el.getAttribute("title") ||
            el.getAttribute("placeholder") || el.value || "").trim();
  };

  document.querySelectorAll('button, a[href], select, input, textarea, [role="button"], label[for]')
    .forEach((el) => {
      if (!visible(el)) return;
      if (srOnly(el)) return;
      // The hit area is the control OR a wrapping label, whichever is
      // bigger: a 20px checkbox inside a 44px <label> is a 44px target,
      // and reporting the input alone is a false alarm.
      let r = el.getBoundingClientRect();
      const wrap = el.closest("label");
      if (wrap && wrap !== el) {
        const w = wrap.getBoundingClientRect();
        if (Math.min(w.width, w.height) > Math.min(r.width, r.height)) r = w;
      }
      const name = nameOf(el);
      const label = (name || el.tagName).slice(0, 40);
      if (Math.min(r.width, r.height) < 44) {
        out.targets.push({ label, w: +r.width.toFixed(0), h: +r.height.toFixed(0) });
      }
      if (!name) out.unnamed.push({ tag: el.tagName, id: el.id || "(no id)" });
    });

  // Focus is checked separately, with real keyboard focus - see focus_check
  // in this module. getComputedStyle after .focus() does not see
  // :focus-visible, and a permanent drop shadow is not a focus ring.
  return out;
}
"""


def focus_check(page, limit: int = 12) -> list:
    """Tab through the page and confirm each stop paints a focus ring.

    Real keyboard focus, because :focus-visible does not apply to
    element.focus(), and an always-on drop shadow is not an indicator.
    """
    failures = []
    seen = set()
    for _ in range(limit):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => {
              const el = document.activeElement;
              if (!el || el === document.body) return null;
              const s = getComputedStyle(el);
              return {
                id: el.id || el.tagName,
                outline: parseFloat(s.outlineWidth) || 0,
                style: s.outlineStyle,
              };
            }"""
        )
        if not info or info["id"] in seen:
            break
        seen.add(info["id"])
        if info["style"] == "none" or info["outline"] <= 0:
            failures.append({"id": info["id"]})
    return failures


@dataclass
class A11yResult:
    name: str = "Accessibility — WCAG AA on the live page"
    passed: int = 0
    total: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def audit(url: str, image: str = "evals/fixtures/chas_p2.jpg") -> A11yResult:
    """Audit the start screen AND a working screen.

    Auditing only the start screen is close to worthless: it has no step
    card, no source chips, no field list and no progress bar - which is
    most of the interface and all of the small text. So the probe runs
    again after a real scan, and the findings are merged.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        r = A11yResult()
        r.notes.append("playwright not installed; skipped")
        return r

    import pathlib as _pl

    result = A11yResult()
    merged: dict[str, list] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_context(
            viewport={"width": 390, "height": 844}, color_scheme="light"
        ).new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(900)

        states = {"start": page.evaluate(PROBE)}
        focus_failures = focus_check(page)

        shot = _pl.Path(image)
        if shot.exists():
            page.set_input_files("#camera", str(shot))
            page.wait_for_function(
                "() => document.getElementById('busy').hidden", timeout=120_000
            )
            page.wait_for_timeout(600)
            states["step"] = page.evaluate(PROBE)

            field = page.locator("#fields button").first
            if field.count():
                field.click()
                page.wait_for_function(
                    "() => document.getElementById('busy').hidden", timeout=120_000
                )
                page.wait_for_timeout(500)
                states["explain"] = page.evaluate(PROBE)
        else:
            result.notes.append(f"(no {shot}; start screen only)")

        browser.close()

    if focus_failures:
        states["start"]["focus"] = focus_failures

    for state, findings in states.items():
        for key, rows in findings.items():
            for row in rows or []:
                merged.setdefault(key, []).append({**row, "on": state})

    findings = merged
    checks = [
        ("contrast", "text below its WCAG AA contrast minimum"),
        ("targets", "tap targets under 44px"),
        ("small", "body text under 16px"),
        ("unnamed", "interactive elements with no accessible name"),
        ("focus", "controls with no visible focus indicator"),
    ]
    for key, description in checks:
        result.total += 1
        rows = findings.get(key) or []
        if not rows:
            result.passed += 1
        else:
            result.notes.append(f"{len(rows)} {description}: {rows[:3]}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="https://snapkaki.web.app")
    ap.add_argument("--image", default="evals/fixtures/chas_p2.jpg")
    args = ap.parse_args()
    r = audit(args.url, args.image)
    print(f"{r.name}: {r.passed}/{r.total} ({r.rate:.0f}%)")
    for n in r.notes:
        print(f"  - {n}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
