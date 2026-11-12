"""Register of Deeds adapters and lien-priority engine.

Per-vendor adapters in this package query each county's ROD system and return
a normalized list of recorded documents. The priority engine (priority.py)
combines documents from a property, applies state super-priority rules, and
computes the position of the foreclosing lien.
"""
