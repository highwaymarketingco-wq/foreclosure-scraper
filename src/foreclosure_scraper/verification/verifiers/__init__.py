"""Verifier modules, auto-discovered by verification.registry.discover(): every module here whose
name does not start with "_" is one verifier. The contract (SIGNAL, VERSION, TTL_DAYS,
applies(row), async verify(row, client), optional GOVERNS/SOURCE/RETRY_DAYS/WALL) is in
registry.py's docstring; tax_lien_buncombe.py is the reference implementation; the step-by-step
is docs/HANDOFF.md item 66. Nothing in this file needs editing to add one."""
