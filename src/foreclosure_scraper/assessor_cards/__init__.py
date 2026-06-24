"""Per-parcel assessor-CARD adapters (on-demand, low-volume, grade-gated).

Each county adapter resolves ONE parcel's PUBLIC assessor card and returns a
normalized CardResult carrying the two fields the bulk CAMA/GIS feed omits in SC:
heated/finished living sqft and recorded SALE PRICE (+ sale history). Adapters are
invoked only for graded-B+ leads (dozens per run), so per-subject volume stays far
below any bulk-distribution or WAF rate threshold. See enrichment_assessor_card.py.
"""
