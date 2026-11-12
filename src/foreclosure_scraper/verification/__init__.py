"""Per-listing verification (phase 2 of docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md).

    core.py       VerificationResult, verdicts, row identity, the read side the scorer uses
    registry.py   auto-discovers verifier modules in verifiers/ (no shared registry to edit)
    verifiers/    one module per (signal, source): SIGNAL, VERSION, TTL_DAYS, applies(), verify()
    ledger.py     the cumulative per-signal ledger docs/handoff/verification/<signal>.json
    apply.py      no-network step (main.py, VM) that attaches raw['verification'] to rows

The Mac runs scripts/verification_sweep.py (live checks, read-only board, pushes the ledger);
the VM's nightly run applies the ledger before scoring. How to add a verifier: docs/HANDOFF.md
item 66, and verifiers/tax_lien_buncombe.py is the reference implementation.

Import-light on purpose: distress_score imports verification.core, so nothing here pulls in
the network stack at import time.
"""
