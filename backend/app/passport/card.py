"""Accessible Passport card views built from the exact signed claim projection."""

from __future__ import annotations

from html import escape


def card_facts(passport: dict[str, object], *, payload_digest: str) -> list[tuple[str, str]]:
    """One ordered text projection shared by SVG, HTML and the verifier."""
    claims = passport["claims"]
    signer = passport["signer"]
    assert isinstance(claims, dict) and isinstance(signer, dict)
    diff = claims["diff_coverage"]
    assert isinstance(diff, dict)
    checks = diff["checks_passed"]
    checks_text = "PASS" if checks is True else "FAIL" if checks is False else "UNKNOWN"
    changed = diff["changed_executable_lines"]
    executed = diff["executed_changed_lines"]
    counts = (f"{executed}/{changed} changed executable lines" if
              isinstance(changed, int) and isinstance(executed, int) else "counts UNKNOWN")
    facts = [
        ("Change", str(claims["change_id"])),
        ("Signer", str(signer["identity"])),
        ("Signer fingerprint", str(signer["fingerprint"])),
        ("Payload SHA-256", payload_digest),
        ("Checks passed", checks_text),
        ("Diff exercised", f"{diff['diff_exercised']} — {counts}"),
        ("Freshness", str(diff["freshness"])),
        ("Execution boundary", str(claims["execution_boundary"])),
        ("Runs later", str(claims["runs_later"])),
        ("Journal integrity", str(claims["journal_integrity"])),
        ("Assertion quality", str(diff["assertion_quality"])),
        ("Caveat", str(diff["caveat"])),
    ]
    if "policy_decision" in claims:
        name = claims.get("policy_preset_name") or "UNSELECTED"
        version = claims.get("policy_preset_version") or "UNKNOWN"
        facts.extend([
            ("Policy preset", f"{name} {version}"),
            ("Policy change type", str(claims.get("policy_change_type") or "UNKNOWN")),
            ("Policy decision", str(claims["policy_decision"])),
        ])
        denials = claims.get("policy_denials")
        if isinstance(denials, list):
            facts.extend(("Policy denial", str(reason)) for reason in denials)
    return facts


def render_html(passport: dict[str, object], *, payload_digest: str) -> bytes:
    facts = card_facts(passport, payload_digest=payload_digest)
    claims = passport["claims"]
    assert isinstance(claims, dict)
    limitations = claims["limitations"]
    assert isinstance(limitations, list)
    rows = "".join(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>"
                   for label, value in facts)
    items = "".join(f"<li>{escape(str(item))}</li>" for item in limitations)
    content = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Sentinel Change Passport</title><style>"
        "body{font:16px system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;"
        "color:#142536;background:#fff}h1{font-size:1.7rem}dl{display:grid;grid-template-columns:"
        "11rem 1fr;gap:.6rem 1rem}dt{font-weight:700}dd{margin:0;overflow-wrap:anywhere}"
        "section{border-top:2px solid #142536;margin-top:1.5rem;padding-top:.5rem}"
        "@media print{body{margin:.3in;max-width:none}}"
        "</style></head><body><main><h1>Sentinel / Change Passport</h1>"
        "<p>Verify the signed .sentinel bundle before relying on these claims.</p>"
        f"<section aria-label=\"Claims\"><h2>Claims</h2><dl>{rows}</dl></section>"
        f"<section aria-label=\"Limitations\"><h2>Limitations</h2><ul>{items}</ul></section>"
        "</main></body></html>"
    )
    return content.encode("utf-8")


def render_svg(passport: dict[str, object], *, payload_digest: str) -> bytes:
    facts = card_facts(passport, payload_digest=payload_digest)
    claims = passport["claims"]
    assert isinstance(claims, dict)
    limitations = claims["limitations"]
    assert isinstance(limitations, list)
    lines = ["Sentinel / Change Passport", "Verify the signed .sentinel bundle"]
    lines += [f"{label}: {value}" for label, value in facts]
    lines += ["Limitations:"] + [f"• {item}" for item in limitations]
    height = 48 + 23 * len(lines)
    texts = "".join(f'<text x="20" y="{42 + index * 23}">{escape(line)}</text>'
                    for index, line in enumerate(lines))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{height}" '
            f'viewBox="0 0 1100 {height}" role="img" '
            'aria-label="Sentinel Change Passport claims and limitations">'
            '<title>Sentinel Change Passport</title>'
            '<rect width="100%" height="100%" fill="#ffffff"/>'
            '<g fill="#142536" font-family="sans-serif" font-size="16">'
            f'{texts}</g></svg>').encode("utf-8")
