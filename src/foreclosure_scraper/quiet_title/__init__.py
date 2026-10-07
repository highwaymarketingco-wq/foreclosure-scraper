"""Quiet-title intake sheets: one parcel, fetched live, written as a private HTML + PDF sheet.

What an attorney asked for before starting a quiet-title action on a lead, per property:
  1. the tax parcel number (PIN);
  2. the legal description off the MOST RECENT deed, plus a couple of deeds in the chain;
  3. the taxpayer of record;
  4. the potential heirs (tax notices often go to a dead person);
  5. which public records were checked (register of deeds, tax, probate, obituaries).
Records older than about 70 years need an abstractor, and some old books and maps are not online,
so the sheet says plainly what it could not reach.

LAYOUT
  model.py      dataclasses the adapters fill and the renderer reads; time formatting (EDT + UTC)
  fetch.py      PoliteFetcher: >= 1.6 s between requests to one host, an ordinary browser
                User-Agent, every response saved as an exhibit and logged; a CAPTCHA, login or
                block page raises Walled and is never retried or worked around
  names.py      pure name logic: owner-of-record markers (HEIRS / ESTATE), "LAST, FIRST MIDDLE"
                parsing, the full-name fit rule for death-index entries
  taxyears.py   pure: which levy years are complete (NC: interest begins January 6)
  adapters/     one class per county (adapters/base.py is the contract; Buncombe NC first)
  intake.py     the county-independent steps: deed chain, heirs analysis, records table
  render.py     the HTML sheet, exhibit screenshots (headless Chrome, no network) and the PDF
  layups.py     ranking rules for 'layup' candidates read from the board + ledgers

Nothing here sends anything anywhere: the sheet and its exhibits are local files only.
"""
