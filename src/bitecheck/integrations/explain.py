"""`bitecheck explain CODE`: what a finding means and what to do about it."""

from __future__ import annotations

import sys

DOCS = {
    "LINES_UNCHECKED": (
        "bitecheck changed one of your changed lines on purpose (a 'mutant': `<` to `>=`, a removed call, a "
        "different constant…) and re-ran the whole test suite. Every test still passed, so no test checks what "
        "that line does. Coverage tools would call the line 'covered'; this is the stronger question.",
        "Add an assertion on the value or effect the line produces. If the mutant really is equivalent (it "
        "cannot change behaviour), mark the line `# bitecheck: ignore` and say why in review. Pragmas added in "
        "the same change are reported by the tamper probe."),
    "GOALPOST_MOVED": (
        "Tests that passed before the change fail when run against the new code, and the change only passes "
        "with edited versions of those tests.",
        "Either restore the original assertions and fix the code, or explain exactly why the old expectation "
        "was wrong. Legitimate fixes to wrong tests trigger this too; it asks for a human decision."),
    "VACUOUS_TESTS": ("New tests pass on the old code as well, so they cannot detect this change.",
                      "Write a test that fails without your change and passes with it."),
    "CLAIM_CONTRADICTED": ("The agent's final message claims something bitecheck's own execution disproves.",
                           "Make the claim true (e.g. strengthen tests) or correct the claim."),
    "TESTS_FOCUSED": ("`.only` / `fit` was added: most of the suite silently stops running.", "Remove it."),
    "TESTS_SKIPPED": ("Skip/xfail markers were added to tests.", "Un-skip and fix, or justify in review."),
    "SPECIAL_CASE_SUSPECT": (
        "New code branches on a literal from the tests and returns another literal from the tests, e.g. "
        "`if year == 1900: return 29`. This is how agents hard-code expected answers.",
        "Implement the general rule."),
    "GATE_LOOSENED": ("CI or test gates were weakened (`|| true`, `continue-on-error`, lower thresholds…).",
                      "Revert the gate change."),
    "DEPENDENCY_NOT_FOUND": ("A newly added dependency does not exist on its registry: a hallucinated name that "
                             "an attacker could register (slopsquatting).", "Use the real package name."),
    "TYPOSQUAT_SUSPECT": ("A new dependency name is one edit away from a popular package.", "Check the spelling."),
    "HEAD_FAILS": ("The full test suite fails on the change itself.", "Make it pass."),
    "MUTANTS_NOT_JUDGED": ("Mutants need a passing suite as a baseline; the suite did not pass.",
                           "Fix the failing tests first."),
    "INVALID_MUTANTS": ("Some mutants did not compile. They prove nothing about the tests and are not counted.",
                        "Set check_cmd (e.g. `go vet ./...`, `tsc --noEmit`) to classify them faster."),
}


def main(code: str | None) -> int:
    if not code:
        for k in sorted(DOCS):
            print(f"{k:<24} {DOCS[k][0][:90]}…")
        return 0
    doc = DOCS.get(code.upper())
    if doc is None:
        print(f"bitecheck: no explanation for {code!r}; run `bitecheck explain` for the list", file=sys.stderr)
        return 2
    print(f"{code.upper()}\n\n{doc[0]}\n\nWhat to do: {doc[1]}")
    return 0
