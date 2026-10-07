"""The intake sheet (HTML, then PDF) and the exhibit pictures.

PICTURES WITHOUT NETWORK. Each exhibit picture is a rendering of the SAVED copy, drawn by headless
Chrome from a local file with every script, stylesheet link, image and frame removed, so drawing
it makes no request to the county (the PoliteFetcher's spacing holds for every request this tool
makes). The picture says so in a banner. A data response (the county layer's JSON) is drawn as a
table of its fields.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from .intake import NOT_FETCHED, later_summary, tax_rows
from .model import EASTERN, Exhibit, IntakeResult, fmt_both

CHROME = os.environ.get("CHROME_BIN") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

e = html.escape


# ---------------------------------------------------------------------------------------------
# headless Chrome
# ---------------------------------------------------------------------------------------------

def chrome_available() -> bool:
    return Path(CHROME).exists() or bool(shutil.which(CHROME))


def _chrome(args: list[str], out: Path, timeout: float = 60.0) -> bool:
    if not chrome_available():
        return False
    out.unlink(missing_ok=True)
    prof = tempfile.mkdtemp(prefix="qt_chrome_")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", "--disable-background-networking", "--disable-sync",
           "--disable-component-update", "--no-pings", "--hide-scrollbars", f"--user-data-dir={prof}", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0, last = time.time(), -1
    try:
        while time.time() - t0 < timeout:
            time.sleep(0.5)
            if out.exists():
                sz = out.stat().st_size
                if sz > 0 and sz == last:
                    break
                last = sz
            if proc.poll() is not None and out.exists():
                break
            if proc.poll() is not None and not out.exists():
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(prof, ignore_errors=True)
    return out.exists() and out.stat().st_size > 0


def screenshot(src_html: Path, out_png: Path, width: int = 1200, height: int = 1400) -> bool:
    ok = _chrome([f"--window-size={width},{height}", "--virtual-time-budget=2000",
                  f"--screenshot={out_png}", src_html.resolve().as_uri()], out_png)
    if ok:
        _trim(out_png)
    return ok


def _trim(png: Path, margin: int = 16) -> None:
    """Cut the blank space below the content (the window is sized generously)."""
    try:
        from PIL import Image, ImageChops
        im = Image.open(png).convert("RGB")
        bbox = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
        if bbox and bbox[3] + margin < im.size[1]:
            im.crop((0, 0, im.size[0], bbox[3] + margin)).save(png)
    except Exception:  # noqa: BLE001 - an untrimmed picture is still a picture
        pass


def print_pdf(src_html: Path, out_pdf: Path) -> bool:
    return _chrome(["--no-pdf-header-footer", "--virtual-time-budget=4000", f"--print-to-pdf={out_pdf}",
                    src_html.resolve().as_uri()], out_pdf, timeout=120)


# ---------------------------------------------------------------------------------------------
# exhibit renderings (local, no network)
# ---------------------------------------------------------------------------------------------

_SHOT_CSS = """
body{margin:14px;font:13px/1.35 Arial,Helvetica,sans-serif;color:#111;background:#fff}
.ban{background:#fff8d6;border:1px solid #c9a400;padding:8px 10px;margin:0 0 10px;font-size:12.5px}
table{border-collapse:collapse;margin:4px 0 10px;font-size:12px}
th,td{border:1px solid #9aa4b2;padding:3px 6px;vertical-align:top;text-align:left}
th{background:#e9edf3} b{color:#7a1f1f}
a{color:#0b2545;text-decoration:none}
"""


def _banner(ex: Exhibit, what: str) -> str:
    return (f"<div class='ban'><b>{e(what)}</b> Saved copy fetched {e(fmt_both(ex.fetched))}, HTTP {ex.http_status}. "
            f"Source: {e(ex.url)}. Drawn from the local file {e(', '.join(ex.files))}; drawing it made no request "
            f"to the source.</div>")


def _clean_copy(html_text: str) -> BeautifulSoup:
    s = BeautifulSoup(html_text or "", "lxml")
    for x in s(["script", "style", "link", "img", "iframe", "noscript", "svg", "video", "audio", "source",
                "input", "select", "button", "meta", "base", "form"]):
        if x.name == "form":
            x.unwrap()
        else:
            x.decompose()
    for x in s.select(".modal, .modal-backdrop, nav, footer, .d-md-none"):
        x.decompose()
    for a in s.find_all("a"):
        a.attrs = {}
    for t in s.find_all(True):
        if t.has_attr("style"):
            del t["style"]
        if t.has_attr("onclick"):
            del t["onclick"]
    return s


def _gis_page(ex: Exhibit, j: dict) -> tuple[str, int]:
    feats = [f.get("attributes") or {} for f in j.get("features") or []]
    body = f"<p>Records returned: {len(feats)}. Fields in the layer: {len(j.get('fields') or [])}.</p>"
    n = 0
    for a in feats:
        rows = []
        for k, v in a.items():
            if v is None or v == "":
                continue
            rows.append(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>")
        n += len(rows)
        body += "<table>" + "".join(rows) + "</table>"
    return (f"<html><head><meta charset='utf-8'><style>{_SHOT_CSS}</style></head><body>"
            f"{_banner(ex, 'Rendering of the saved county layer response (every non-empty field).')}{body}</body></html>",
            min(4000, 260 + 24 * max(n, 4)))


def _tax_page(ex: Exhibit, text: str) -> tuple[str, int]:
    s = _clean_copy(text)
    main = s.find("main") or s.body or s
    return (f"<html><head><meta charset='utf-8'><style>{_SHOT_CSS}</style></head><body>"
            f"{_banner(ex, 'Rendering of the saved county tax page (scripts, styles and the user-agreement pop-up removed).')}"
            f"{main.decode_contents() if hasattr(main, 'decode_contents') else str(main)}</body></html>", 2000)


def _rod_page(ex: Exhibit, text: str, kind: str) -> tuple[str, int]:
    s = BeautifulSoup(text or "", "lxml")
    parts = []
    if kind == "rod_detail":
        for tid in ("ctl00_cphMain_gvDetails1", "ctl00_cphMain_gvParties1", "ctl00_cphMain_gvParties2"):
            t = s.find(id=tid)
            if t is not None:
                parts.append(str(t))
        h = 700
    else:
        grid = None
        for t in s.find_all("table"):
            if (t.get("id") or "").endswith("cpgvInstruments"):
                grid = t
                break
        txt = s.get_text(" ", strip=True)
        import re as _re
        m = _re.search(r"\b\d+\s*-\s*\d+\s+of\s+\d+\b", txt)
        cov = _re.findall(r"[A-Z][A-Z0-9 ,&\-]*?\s+Valid From\s+\S+\s+Thru\s+\S+", txt)
        parts.append(f"<p>Results: {e(m.group(0)) if m else 'none shown'}. {e(cov[0]) if cov else ''}</p>")
        if grid is not None:
            parts.append(str(grid))
            nrows = len([tr for tr in grid.find_all("tr", recursive=True)])
        else:
            parts.append("<p>The page shows no results grid.</p>")
            nrows = 2
        h = min(5000, 300 + 30 * nrows)
    frag = _clean_copy("<html><body>" + "".join(parts) + "</body></html>")
    what = ("Excerpt of the saved Register of Deeds page: the Document Details tables." if kind == "rod_detail" else
            "Excerpt of the saved Register of Deeds page: the results grid (bold = the names the search matched).")
    return (f"<html><head><meta charset='utf-8'><style>{_SHOT_CSS}</style></head><body>{_banner(ex, what)}"
            f"{frag.body.decode_contents() if frag.body else ''}</body></html>", h)


def take_screenshots(res: IntakeResult, out_dir: Path) -> None:
    exd = out_dir / "exhibits"
    tmp = out_dir / ".render"
    tmp.mkdir(parents=True, exist_ok=True)
    for ex in res.exhibits.values():
        if not ex.files or not ex.shot_kind:
            continue
        src = exd / ex.files[0]
        try:
            raw = src.read_text(encoding="utf-8", errors="ignore")
            if ex.shot_kind == "gis_json":
                page, h = _gis_page(ex, json.loads(raw))
            elif ex.shot_kind == "tax_html":
                page, h = _tax_page(ex, raw)
            else:
                page, h = _rod_page(ex, raw, ex.shot_kind)
        except Exception as exc:  # noqa: BLE001
            res.notes.append(f"Picture of {ex.key} not drawn: {type(exc).__name__}")
            continue
        page_path = tmp / f"{ex.key}.html"
        page_path.write_text(page, encoding="utf-8")
        name = f"{res.pin}_{ex.key}_screenshot.png"
        if screenshot(page_path, exd / name, 1200, h):
            ex.screenshot = name
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------
# the sheet
# ---------------------------------------------------------------------------------------------

_CSS = """
@page { size: Letter; margin: 0.7in 0.65in 0.75in 0.65in;
  @bottom-left { content: "Private and confidential. Prepared for the owner and the owner's attorney. Not for publication."; font: 8pt Georgia, serif; color: #666; }
  @bottom-right { content: "Page " counter(page); font: 8pt Georgia, serif; color: #666; } }
:root { color-scheme: light; }
* { box-sizing: border-box; }
html { background: #fff; }
body { margin: 0 auto; max-width: 8.2in; padding: 0 0.2in; font: 10.3pt/1.42 Georgia, "Times New Roman", serif; color: #111; background: #fff; }
h1, h2, h3, h4 { break-after: avoid; font-family: "Helvetica Neue", Arial, sans-serif; color: #0b2545; line-height: 1.2; }
h1 { font-size: 19pt; margin: 0 0 6pt; border-bottom: 2px solid #0b2545; padding-bottom: 4pt; }
h2 { font-size: 13.5pt; margin: 16pt 0 5pt; border-bottom: 1px solid #c3cad5; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; }
p { margin: 0 0 6pt; }
.kicker { font: 600 9pt "Helvetica Neue", Arial, sans-serif; letter-spacing: 1.2pt; text-transform: uppercase; color: #666; }
.small { font-size: 8.8pt; color: #333; }
.url { font-family: Menlo, Consolas, monospace; font-size: 8pt; word-break: break-all; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt; font-size: 8.8pt; }
th, td { border: 1px solid #9aa4b2; padding: 3pt 5pt; vertical-align: top; text-align: left; }
thead th { background: #e9edf3; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.3pt; }
table.kv th { width: 30%; background: #f3f5f8; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.3pt; }
tr { break-inside: avoid; }
tr.pick td { background: #f1f8f4; }
ol.steps { margin: 2pt 0 4pt 16pt; padding: 0; } ol.steps li { margin-bottom: 2pt; }
.vd { font: 700 7.8pt "Helvetica Neue", Arial, sans-serif; padding: 1.5pt 6pt; border-radius: 8pt; white-space: nowrap; }
.vd-ok { background: #e1f3e4; color: #1d5c2c; border: 1px solid #62a373; }
.vd-part { background: #fdf0d2; color: #6b4a00; border: 1px solid #c9a04a; }
.vd-no { background: #f8dede; color: #7a1f1f; border: 1px solid #c58080; }
.vd-na { background: #eee; color: #444; border: 1px solid #aaa; }
.box, .bind, .src, .warn { border-left: 4px solid #0b2545; background: #f5f7fa; padding: 6pt 9pt; margin: 6pt 0 8pt; font-size: 9.5pt; break-inside: avoid; }
.src { border-left-color: #888; background: #fafafa; font-size: 8.6pt; }
.warn { border-left-color: #b5651d; background: #fdf6ee; }
.box.no { border: 1px solid #9aa4b2; border-left: 4px solid #666; background: #fafafa; }
figure.shot { margin: 8pt 0 10pt; break-inside: avoid; }
figure.shot img { width: 96%; max-height: 8.6in; object-fit: contain; object-position: top left; border: 1px solid #9aa4b2; display: block; }
figcaption { font-size: 8.3pt; color: #333; margin-top: 3pt; }
.exhibits { break-before: page; }
@media print { body { padding: 0; max-width: none; } a { color: #000; } }
"""


def _money(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"(${-v:,.2f})" if v < 0 else f"${v:,.2f}"


def _few(names: list[str], n: int = 6) -> str:
    return "; ".join(names[:n]) + (f"; and {len(names) - n} more (all in the exhibit)" if len(names) > n else "")


def _x(key: Optional[str]) -> str:
    return f"<a href='#ex-{e(key)}'>{e(key)}</a>" if key else ""


def _src(res: IntakeResult, *keys: Optional[str]) -> str:
    bits = []
    for k in keys:
        ex = res.exhibits.get(k or "")
        if ex is None:
            continue
        w = f" <b>Walled: {e(ex.wall_reason or '')}</b>" if ex.walled else ""
        bits.append(f"Exhibit {_x(ex.key)}: {e(ex.source)}, <span class='url'>{e(ex.url)}</span>"
                    f"{' (' + e(ex.method) + ' form)' if ex.method != 'GET' else ''}, fetched {e(fmt_both(ex.fetched))}, "
                    f"HTTP {ex.http_status if ex.http_status is not None else 'none'}.{w}")
    return "<div class='src'>" + "<br>".join(bits) + "</div>" if bits else ""


def _tag(text: str, cls: str) -> str:
    return f"<span class='vd {cls}'>{e(text)}</span>"


def _inst_rows(rows, pick=None, cols=("date", "bp", "idx", "kind", "grantors", "grantees", "desc", "pages")) -> str:
    head = {"date": "Filed", "bp": "Book / page", "idx": "Index", "kind": "Type", "grantors": "Grantor(s)",
            "grantees": "Grantee(s)", "desc": "Index description (not warranted)", "pages": "Pages",
            "fit": "Name fit", "ex": "Exhibit"}
    out = "<table><thead><tr>" + "".join(f"<th>{head[c]}</th>" for c in cols) + "</tr></thead><tbody>"
    for r in rows:
        cells = {"date": r.date, "bp": r.book_page, "idx": r.index_code, "kind": r.kind,
                 "grantors": "; ".join(r.grantors), "grantees": "; ".join(r.grantees), "desc": r.description,
                 "pages": str(r.pages or ""), "fit": r.name_fit or "", "ex": r.exhibit or ""}
        cls = " class='pick'" if pick is not None and r is pick else ""
        out += f"<tr{cls}>" + "".join(f"<td>{_x(cells[c]) if c == 'ex' else e(cells[c])}</td>" for c in cols) + "</tr>"
    return out + "</tbody></table>"


def _heirs_conclusion(res: IntakeResult) -> str:
    fits = [x for d in res.death_searches for x in d.entries if x.fit == "fit"]
    cands = [x for d in res.death_searches for x in d.entries if x.fit == "candidate"]
    par = [x for d in res.death_searches for x in d.entries if x.fit == "parent_only"]
    if not res.death_searches:
        return "Conclusion: the deaths index was not searched."
    counts = (f"{len(fits)} entr{'y fits' if len(fits) == 1 else 'ies fit'} the full name, {len(cands)} "
              f"candidate{'s' if len(cands) != 1 else ''} may not fit, {len(par)} name the person only as a parent")
    if res.roll_markers and fits:
        return (f"{_tag('Confirmed in part', 'vd-part')} The roll names heirs and the deaths index holds an entry "
                f"whose full name agrees ({counts}). That is a name fit, not proof of identity; who the heirs are is "
                f"not established.")
    if res.roll_markers:
        return (f"{_tag('Confirmed in part', 'vd-part')} The roll names heirs, but no deaths-index entry fits the "
                f"owner's full name ({counts}). Which death, if any, is the owner's is not established by the index.")
    if fits:
        return (f"{_tag('Name fit only', 'vd-part')} The roll shows no heirs wording; a deaths-index entry fits the "
                f"owner's full name ({counts}). Whether the owner of record has died is not established.")
    return (f"{_tag('Not shown', 'vd-na')} No heirs wording on the roll and no full-name fit in the deaths index "
            f"({counts}).")


def _legal(res: IntakeResult, p) -> tuple[str, str]:
    """(the at-a-glance words, the section-2 box) for the legal description, by where it came from."""
    bp = f"book {p.deed_book or '?'} page {p.deed_page or '?'}"
    link = (res.deed_link if res.register_fetched else res.register_link) or ""
    if p.legal_kind == "assessor_short" and p.legal_description:
        glance = (f"Short assessor legal (not the deed's full legal description): \"{p.legal_description}\" "
                  f"({p.layer_label or 'the layer'}, field {p.legal_field}). The full legal description is on the "
                  f"deed image, {bp}, at the register of deeds: {link or 'see where to look'}.")
        box = (f"<div class='box'><b>Short assessor legal (not the deed's full legal description).</b> "
               f"{e(p.legal_description)}<br>This is the assessor's one-line note on the tax roll as "
               f"{e(p.layer_label or 'the layer')} publishes it (field {e(p.legal_field or '')}, Exhibit {_x(p.exhibit)}). "
               f"It identifies the parcel; it is not the deed's legal description and is not used as one. The full "
               f"text of the legal description is on the deed image, {e(bp)}, at the register of deeds: "
               f"<span class='url'>{e(link or 'see where to look')}</span></div>")
        return glance, box
    if p.legal_description:
        return (f"From the county layer's {p.legal_field} field: {p.legal_description}",
                f"<div class='box'><b>Legal description (county layer field {e(p.legal_field or '')}).</b> "
                f"{e(p.legal_description)}</div>")
    if p.layer_label:
        why = ("holds the deed reference for this county, not a legal description"
               if p.extra.get("legdecfull_holds_deed_ref") else "is blank for this parcel")
        glance = (f"Not on {p.layer_label}: its short assessor legal field (legdecfull) {why}. Needs the deed image: "
                  f"{bp}, at the register of deeds: {link or 'see where to look'}.")
        box = (f"<div class='box'><b>Legal description: needs the deed image.</b> The short assessor legal field "
               f"(legdecfull) on {e(p.layer_label)} {e(why)} (Exhibit {_x(p.exhibit)}). The legal description is on "
               f"the deed itself, {e(bp)}, at the register of deeds: <span class='url'>{e(link or 'see where to look')}"
               f"</span></div>")
        return glance, box
    glance = (f"Not on the county layer (no legal-description field among its {len(p.field_names)} fields). "
              f"Needs the deed image: {bp} (link in section 2).")
    box = (f"<div class='box'><b>Legal description: needs the deed image.</b> The county's free parcel layer "
           f"returned {len(p.field_names)} fields for this parcel and none is a legal description (the field "
           f"list is in the saved response, Exhibit {_x(p.exhibit)}). The legal description is on the deed "
           f"itself, book {e(p.deed_book or '?')} page {e(p.deed_page or '?')}. Open it here (the register's "
           f"book/page search; it opens as a guest): <span class='url'>{e(res.deed_link or '')}</span>"
           + (f"<br>Document Details page reached in this run: <span class='url'>{e(res.vesting_detail_url)}</span> "
              f"(it may need the register's guest session; the book/page link always works)." if res.vesting_detail_url else "")
           + "<br>The register's index description below is the index clerk's short note, marked by the register "
             "as not warranted. It is not the legal description and is not used as one.</div>")
    return glance, box


def _where_block(res: IntakeResult) -> str:
    """'Where to look in this county': the county records matrix, printed for a person. Static text:
    nothing here is fetched, and the tool never fetches from a site walled to scripts."""
    w = res.where or {}
    if not w:
        return ""
    head = (f"<h2>Where to look in {e(res.county)} County</h2>"
            f"<p class='small'>From the county records matrix (docs/county_records, built "
            f"{e(w.get('matrix_date') or 'date not recorded')}{', confidence ' + e(w['confidence']) if w.get('confidence') else ''}): "
            f"where each record lives, whether it is free, and why a person is needed. ")
    if res.register_fetched:
        head += ("This tool searched this county's register index live (section 2"
                 + ("" if res.deaths_note else ", and its deaths index in section 4")
                 + "); the links below are for a person checking it again or going further back.</p>")
    else:
        head += ("This tool did not search this county's register, tax site or probate files: those sections say "
                 "'not fetched by the tool: use the link above' and point here. A site the matrix marks as walled to "
                 "scripts (a CAPTCHA, a login, a payment, a Cloudflare check) is never fetched; a person or the "
                 "attorney goes there.</p>")
    rows = "".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in (w.get("rows") or []))
    return head + f"<table class='kv'><tbody>{rows}</tbody></table>"


def render_html(res: IntakeResult) -> str:
    p = res.parcel
    gen = fmt_both(res.finished or res.started)
    title = f"Quiet-title intake sheet, PIN {res.pin}"
    H: list[str] = []
    H.append("<div class='kicker'>Private. Prepared for the owner and the owner's attorney</div>")
    H.append(f"<h1>{e(title)}</h1>")
    H.append(f"<p class='small'>{e(res.county)} County, {e(res.state)}. Every fact below was read live from a free "
             f"public page on {e(gen)}. Each fact carries its source, the address a person can open and the fetch "
             f"time (Eastern and UTC); the saved copy of every page and a picture of it are in the exhibits folder "
             f"beside this file. Facts only: nothing here is a legal conclusion.</p>")
    if res.notes:
        H.append("<div class='warn'><b>Run notes.</b><br>" + "<br>".join(e(n) for n in res.notes) + "</div>")
    if p is None or not p.found:
        H.append("<div class='warn'>No parcel record was found for this PIN; nothing else was searched."
                 + (f" {e(str(p.extra.get('join_note')))}" if p is not None and p.extra.get("join_note") else "")
                 + "</div>")
        H.append(_where_block(res))
        return _wrap(title, H, res)

    tr = (tax_rows(res.tax, (res.finished or res.started).astimezone(EASTERN).date(), res.state)
          if res.tax and not res.tax.walled and res.tax.fetched else None)
    src = p.layer_label or "the county layer"
    legal_glance, legal_box = _legal(res, p)

    # ---- at a glance
    H.append("<h2>At a glance</h2>")
    glance = []
    pin_txt = f"{p.pin} ({src}; " + (f"record revised {p.layer_updated or 'date not shown'})" if p.layer_label else
                                     f"layer updated {p.layer_updated or 'date not shown'})")
    if res.pin != p.pin:
        pin_txt += f"; searched as {res.pin}"
    glance.append(("1. Tax parcel number (PIN)", pin_txt))
    glance.append(("2. Legal description", legal_glance))
    if res.vesting:
        v = res.vesting
        glance.append(("2. Last deed the county cites",
                       f"Book {v.book} page {v.page}, filed {v.date}, {v.kind or v.index_code}: "
                       f"{_few(v.grantors)} to {_few(v.grantees)}"))
    elif not res.register_fetched:
        glance.append(("2. Last deed the record cites", (f"As written on the layer: {p.deed_ref_text}. "
                                                         if p.deed_ref_text else "") + (res.vesting_note or "")))
    else:
        glance.append(("2. Last deed the county cites",
                       f"Book {p.deed_book or '?'} page {p.deed_page or '?'}, dated {p.deed_date or '?'} on the county "
                       f"record; {res.vesting_note or ''}"))
    glance.append(("2. Earlier deeds found in the chain",
                   res.chain_note if not res.register_fetched else
                   f"{len(res.chain)} (by register name search). {res.chain_note or ''}"))
    ls = later_summary(res)
    if ls:
        glance.append(("2. Recorded after that deed (owner-name index search)", ls))
    glance.append((f"3. Taxpayer of record (as {'the county' if not p.layer_label else src} shows it)",
                   f"{p.owner or 'none shown'}" + (f", care of {p.care_of}" if p.care_of else "")))
    glance.append(("Property address (situs) / mailing address",
                   f"{p.situs or 'none'}{' (' + p.situs_note + ')' if p.situs_note else ''} / {p.mailing or 'none'}"))
    if res.tax is not None and not res.tax.fetched:
        glance.append(("3. Tax status", res.tax.note or "Not fetched by the tool for this county."))
    if tr:
        yrs = ", ".join(str(r["year"]) for r in tr["rows"])
        unpaid = tr["unpaid_years"]
        ttxt = (f"Completed levy years read: {yrs}. Unpaid: {', '.join(map(str, unpaid)) if unpaid else 'none'}"
                + (f", {_money(tr['unpaid_total'])} due on the fetch date" if unpaid else "")
                + (" (one or more amounts not shown by the county)" if tr["unpaid_amount_unknown"] else "") + ".")
        if tr["current"]:
            c = tr["current"]
            ttxt += f" Current year {c['year']}: {_money(c['due']) or c['due_text'] or c['state']} (not yet late)."
        glance.append(("3. Tax status", ttxt))
    marks = ", ".join(res.roll_markers) if res.roll_markers else "none"
    fits = sum(1 for d in res.death_searches for x in d.entries if x.fit == "fit")
    cands = sum(1 for d in res.death_searches for x in d.entries if x.fit == "candidate")
    glance.append(("4. Heirs signals", f"Heirs / estate wording on the roll: {marks}. " + (
        (f"The deaths index was not searched: {res.deaths_note}" if res.deaths_note else
         f"Death-index entries that fit the full name: {fits}; candidates that may not fit: {cands}.")
        if res.register_fetched else "The deaths index was not searched by the tool for this county.")))
    walled = [r.record for r in res.records if r.status in ("walled", "not run", "not checked", "not opened")]
    glance.append(("5. Records not reached", "; ".join(walled) or "none"))
    H.append("<table class='kv'><tbody>" + "".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in glance)
             + "</tbody></table>")

    # ---- where to look (the county records matrix; nothing fetched)
    H.append(_where_block(res))

    # ---- 1 parcel
    H.append("<h2>1. Parcel record</h2>")
    if p.layer_label:
        H.append(f"<p class='small'>Read from {e(src)}, which publishes the county assessor's roll for all 100 NC "
                 f"counties (information source on the record: {e(str(p.extra.get('information_source') or 'not stated'))}). "
                 f"{e(str(p.extra.get('join_note') or ''))}</p>")
        acre = (f"{p.acreage:.2f} acre ({p.extra.get('acreage_note')})" if p.acreage is not None
                else f"not given ({p.extra.get('acreage_note')})")
        value = ((f"{_money(p.tax_value)} (land {_money(p.land_value)}, improvements {_money(p.building_value)}). This is a "
                  f"{p.value_note}.") if p.tax_value is not None else "not given")
        deed = (f"book {p.deed_book or '?'}, page {p.deed_page or '(none given)'}, dated "
                f"{p.deed_date_text or '(no date given)'}; as written on the layer: {p.deed_ref_text or 'blank'}")
        kv = [("PIN", f"{p.pin} (parno); alternate number on the layer: {p.extra.get('altparno') or 'none'}"),
              ("Owner of record (taxpayer) as the layer shows it", p.owner or ""),
              ("Care of (written inside the owner field: a mailing contact)", p.care_of or "none"),
              ("Mailing address on the record", p.mailing or ""),
              ("Situs (house number and road) on the record",
               (p.situs or "") + (f" ({p.situs_note})" if p.situs_note else "")),
              ("Acreage", acre),
              ("Use / structure", f"{p.land_class or 'use not given'}; structure on the parcel: {p.improved or '?'}"),
              ("Tax value", value),
              ("Deed the assessor cites", deed),
              ("Plat / subdivision on the record", "; ".join(x for x in [
                  f"plat book {p.plat_book} page {p.plat_page or '?'}" if p.plat_book else "no plat reference",
                  f"map reference {p.extra['mapref']}" if p.extra.get("mapref") else "",
                  p.subdivision or ""] if x)),
              ("Last sale date on the layer", str(p.extra.get("last_sale_date") or "not given")),
              ("Record revised (statewide layer)", p.layer_updated or "not given")]
    else:
        kv = [("PIN", p.pin), ("Owner of record as the county shows it", p.owner or ""),
              ("Care of (a mailing contact on the record)", p.care_of or "none"),
              ("Mailing address on the record", p.mailing or ""),
              ("Situs (house number and road) on the record", (p.situs or "") + (f" ({p.situs_note})" if p.situs_note else "")),
              ("Acreage", f"{p.acreage:.2f} acre" if p.acreage is not None else ""),
              ("Class / improved", f"class {p.land_class or '?'}; improved: {p.improved or '?'}"),
              ("County tax value", (f"{_money(p.tax_value)} (land {_money(p.land_value)}, buildings {_money(p.building_value)}). "
                                    f"This is the county's tax value, not a market price.") if p.tax_value is not None else ""),
              ("Deed the county cites", f"book {p.deed_book or '?'}, page {p.deed_page or '?'}, dated {p.deed_date or '?'}, "
                                        f"instrument code {p.deed_instrument or '?'}"),
              ("Plat / subdivision on the record", "; ".join(x for x in [
                  f"plat book {p.plat_book} page {p.plat_page}" if p.plat_book else "no plat reference",
                  p.subdivision or "", f"township code {p.township}" if p.township else ""] if x)),
              ("Layer updated", p.layer_updated or "")]
    H.append("<table class='kv'><tbody>" + "".join(f"<tr><th>{e(a)}</th><td>{e(str(b))}</td></tr>" for a, b in kv)
             + "</tbody></table>")
    bind = f"<b>Which parcel these facts belong to.</b> Every fact on this sheet is tied to PIN {e(p.pin)}. "
    if res.mailing_check_note:
        bind += e(res.mailing_check_note) + " "
    for o in res.mailing_parcels:
        same = " (this parcel)" if o.pin == p.pin else " (a different parcel)"
        bind += (f"PIN {e(o.pin)}{same}: situs {e(o.situs)}, owner on the layer {e(o.owner or '?')}, improved "
                 f"{e(o.improved or '?')}{', deed ' + e(o.deed) if o.deed else ''}. ")
    H.append(f"<div class='bind'>{bind}</div>")
    H.append(_src(res, p.exhibit, *[k for k, ex in res.exhibits.items() if "mailing address's number" in ex.label]))

    # ---- 2 legal description and deeds
    H.append("<h2>2. Legal description, the last deed the county cites, and the chain</h2>")
    H.append(legal_box)
    if not res.register_fetched:
        H.append(f"<h3>The deed the record cites</h3><p>{e(res.vesting_note or '')}</p>")
    elif res.deed_rows:
        H.append(f"<h3>Every index entry at book {e(p.deed_book or '')} page {e(p.deed_page or '')}</h3>")
        H.append(f"<p>{e(res.vesting_note or '')} Pre-1995 deeds and deeds of trust were kept in separate book series, "
                 f"so one book and page can hold two instruments. The highlighted row is the one the county cites.</p>")
        H.append(_inst_rows(res.deed_rows, pick=res.vesting))
        H.append(_src(res, res.deed_rows[0].exhibit, res.vesting.detail_exhibit if res.vesting else None))
    else:
        H.append(f"<p>{e(res.vesting_note or 'The register was not searched for the deed.')}</p>")
    if res.plat_link:
        H.append(f"<h3>The plat the county cites (book {e(p.plat_book)} page {e(p.plat_page)})</h3>")
        H.append(_inst_rows(res.plat_rows) if res.plat_rows else "<p>No index entry was returned at that book and page.</p>")
        H.append(f"<p class='small'>Link: <span class='url'>{e(res.plat_link)}</span></p>")
    H.append("<h3>The chain before that deed (register name search)</h3>")
    if res.chain:
        rows = "".join(
            f"<tr><td>{i}</td><td>{e(r.date)}</td><td>{e(r.book_page)}</td><td>{e(r.kind or r.index_code)}</td>"
            f"<td>{e(_few(r.grantors))}</td><td>{e(_few(r.grantees))}</td><td>{e(r.description)}</td>"
            f"<td>{e(r.tie or '')}</td><td>{_x(r.exhibit)}</td></tr>" for i, r in enumerate(res.chain, 1))
        H.append("<table><thead><tr><th>Step</th><th>Filed</th><th>Book / page</th><th>Instrument</th><th>Grantor(s)</th>"
                 "<th>Grantee(s)</th><th>Index description</th><th>How it ties to the next deed</th><th>Exhibit</th>"
                 f"</tr></thead><tbody>{rows}</tbody></table>")
    if not res.register_fetched:
        H.append(f"<p>{e(res.chain_note or '')}</p>")
    else:
        H.append(f"<p>{e(res.chain_note or '')} Each step is a lead for the abstract: the tie is the name and any shared "
                 f"index-description words, never a finding that two deeds describe the same land.</p>")
    if res.searches:
        H.append(_src(res, *[ns.exhibit for ns in res.searches]))
    for ns in res.after_vesting:
        H.append(f"<h3>Instruments naming the owner of record: {e(ns.last)}, {e(ns.first)}</h3>")
        H.append(f"<p class='small'>{e(ns.purpose)}. The search returned {ns.total if ns.total is not None else 'an unknown number of'} "
                 f"rows; {ns.shown} are kept because the indexed name agrees with the owner's (full or in part). "
                 f"Other spellings and other names were not searched.</p>")
        if ls:
            H.append(f"<p>{e(ls[0].upper() + ls[1:])}.</p>")
        if ns.rows:
            H.append(_inst_rows(ns.rows[:60], cols=("date", "bp", "idx", "kind", "grantors", "grantees", "desc", "fit")))
            if len(ns.rows) > 60:
                H.append(f"<p class='small'>{len(ns.rows) - 60} more rows are in the saved page.</p>")
        H.append(_src(res, ns.exhibit))

    # ---- 3/4 tax
    H.append("<h2>3. Taxpayer of record and tax status</h2>")
    if res.tax is not None and not res.tax.fetched:
        H.append(f"<p>Taxpayer of record as {e(src)} shows it: {e(p.owner or 'none shown')} (section 1, Exhibit "
                 f"{_x(p.exhibit)}).</p>")
        H.append(f"<div class='warn'>{e(res.tax.note or 'Tax bills are not fetched by the tool for this county.')} "
                 f"{e(res.tax.interest_rule)}</div>")
    elif res.tax is None or res.tax.walled:
        H.append(f"<div class='warn'>The tax pages were not read{': ' + e(res.tax.wall_reason) if res.tax and res.tax.wall_reason else ''}.</div>")
    else:
        ts = res.tax
        owners = sorted({b.owner for b in ts.bills if b.owner})
        H.append(f"<p>Owner name on the bills: {e('; '.join(owners) or 'none shown')}. Parcel status on the tax site: "
                 f"{e(ts.parcel_status or 'not shown')}. {e(ts.interest_rule)}</p>")
        H.append("<h3>The three most recent completed levy years</h3>")
        body = ""
        for r in tr["rows"]:
            body += (f"<tr><td>{r['year']}</td><td>{e(r['bill'] or '')}</td><td>{e(r['billed'])}</td>"
                     f"<td>{_money(r['tax'])}</td><td>{_money(r['interest'])}</td><td>{_money(r['cost'])}</td>"
                     f"<td>{_money(r['total'])}</td><td>{e(r['payments'])}</td>"
                     f"<td>{_money(r['due']) if r['due'] is not None else e(r['due_text'])}</td><td>{e(r['state'])}</td>"
                     f"<td>{_x(r['exhibit'])}</td></tr>")
        H.append("<table><thead><tr><th>Levy year</th><th>Bill</th><th>Billed</th><th>Tax</th><th>Interest</th>"
                 "<th>Costs</th><th>Total billed to date</th><th>Payments</th><th>Amount due on the fetch date</th>"
                 f"<th>State</th><th>Exhibit</th></tr></thead><tbody>{body}</tbody></table>")
        unpaid = tr["unpaid_years"]
        if unpaid:
            H.append(f"<p>Unpaid completed years: {', '.join(map(str, unpaid))}; amount due on the fetch date "
                     f"{_money(tr['unpaid_total'])}"
                     + (" plus amounts the county does not show as a number" if tr["unpaid_amount_unknown"] else "")
                     + ". Interest and costs are computed by the county as of the day the page is read.</p>")
        else:
            H.append("<p>No completed levy year among the three shows an amount due.</p>")
        if tr["current"]:
            c = tr["current"]
            H.append(f"<h3>Current year, not yet late</h3><p>Levy year {c['year']}, bill {e(c['bill'] or 'not on the list')}, "
                     f"billed {e(c['billed'] or '?')}, amount due {_money(c['due']) if c['due'] is not None else e(c['due_text'] or '?')}. "
                     f"Interest on this bill does not begin until January 6, {c['year'] + 1}; it is not counted above "
                     f"(Exhibit {_x(c['exhibit'])}).</p>")
        if tr["older"]:
            if tr["older_open"]:
                lst = "; ".join(f"{b.levy_year}: {_money(b.amount_due) if b.amount_due is not None else (b.amount_due_text or '?')}"
                                for b in tr["older_open"])
                H.append(f"<p>Older levy years on the billing list (not part of the three-year table): "
                         f"{len(tr['older'])} bills; those showing an amount due: {e(lst)}.</p>")
            else:
                ys = sorted(b.levy_year for b in tr["older"])
                H.append(f"<p>Older levy years on the billing list ({ys[0]} to {ys[-1]}, {len(ys)} bills) show $0.00 due.</p>")
        if tr["other"]:
            H.append("<p>Other bills on the list (not regular annual bills): " + e("; ".join(
                f"{b.bill}: {_money(b.amount_due) if b.amount_due is not None else (b.amount_due_text or '?')}" for b in tr["other"])) + ".</p>")
        see_legal = [b.bill for b in ts.bills if (b.amount_due_text or "").lower().startswith("see legal")]
        H.append(f"<p class='small'>{'Bills showing See Legal instead of an amount: ' + e(', '.join(see_legal)) if see_legal else 'No bill on the list shows See Legal instead of an amount.'}</p>")
        H.append(_src(res, ts.exhibit, *[r["exhibit"] for r in tr["rows"]], tr["current"]["exhibit"] if tr["current"] else None))

    # ---- heirs
    H.append("<h2>4. Heirs signals</h2>")
    if res.roll_markers:
        H.append(f"<p>{_tag('Confirmed on the roll today', 'vd-ok')} The county roll's owner name carries the words "
                 f"{e(', '.join(res.roll_markers))} ('{e(p.owner or '')}'). The roll does not name the heirs.</p>")
    else:
        H.append(f"<p>{_tag('No heirs wording', 'vd-na')} The county roll's owner name ('{e(p.owner or '')}') carries "
                 f"no heirs or estate wording. Tax notices can still go to a person who has died; "
                 + (f"the deaths index was not searched: {e(res.deaths_note)}</p>" if res.register_fetched and
                    res.deaths_note else
                    "the deaths index was searched for the owner's name below.</p>" if res.register_fetched else
                    "the register's deaths index was not searched by the tool for this county (a person searches it: "
                    "see where to look).</p>"))
    if p.care_of:
        H.append(f"<p>The record names a care-of contact, {e(p.care_of)}. That is a mailing contact on the tax record, "
                 f"not a finding that the person is an heir.</p>")
    for d in res.owner_people:
        pn = d["person"]
        H.append(f"<p class='small'>Owner name '{e(d['roll'])}': "
                 + (f"searched as {e(pn.indexed())}; " if pn else "") + f"{e(d['reading'])}.</p>")
    if res.register_fetched:
        H.append(f"<p>{_heirs_conclusion(res)}</p>")
    for ds in res.death_searches:
        H.append(f"<h3>Deaths index: {e(ds.last)}, {e(ds.first)}</h3>")
        if ds.walled:
            H.append(f"<div class='warn'>Walled: {e(ds.wall_reason or '')}</div>")
            continue
        H.append(f"<p class='small'>The register's deaths index (valid, as the page states, from {e(ds.valid_from or '?')} "
                 f"through {e(ds.valid_thru or '?')}) returned {ds.total if ds.total is not None else len(ds.entries)} "
                 f"entries for surname {e(ds.last)} (exactly) and given name beginning {e(ds.first)}. Rule: an entry is "
                 f"called a fit only when the given name, the middle name and the surname all agree word for word with "
                 f"{e(ds.person)}; a fit is a name fit, not proof of identity.</p>")
        dec = [x for x in ds.entries if x.matched_as == "decedent"]
        par = [x for x in ds.entries if x.matched_as == "parent"]
        if dec:
            rows = ""
            for x in sorted(dec, key=lambda z: (z.fit != "fit", z.fit != "candidate", z.year or 0)):
                tag = {"fit": _tag("Fits the full name", "vd-ok"), "candidate": _tag("Candidate", "vd-part"),
                       "other_person": _tag("Other surname", "vd-na")}.get(x.fit, "")
                why = "; ".join(x.reasons + x.observations)
                rows += (f"<tr><td>{e(str(x.year or x.date))}</td><td>{e(x.book_page)}</td><td>{e('; '.join(x.decedent_names))}</td>"
                         f"<td>{e('; '.join(x.parents))}</td><td>{tag}</td><td>{e(why)}</td></tr>")
            H.append("<table><thead><tr><th>Filed</th><th>Book / page</th><th>Decedent as indexed</th><th>Parents on the entry</th>"
                     f"<th>Fit</th><th>Why it may not fit / what else the entry shows</th></tr></thead><tbody>{rows}</tbody></table>")
        else:
            H.append("<p>No entry names this person as the decedent.</p>")
        if par:
            H.append(f"<p class='small'>{len(par)} more entr{'ies' if len(par) != 1 else 'y'} name a person of this name only "
                     f"as a parent (years {', '.join(str(x.year) for x in par)}); those are other decedents.</p>")
        H.append(_src(res, ds.exhibit))
    if not res.register_fetched:
        H.append(f"<p>No deaths-index search was run: {e(NOT_FETCHED.lower())} "
                 f"(<span class='url'>{e(res.register_link or 'see where to look')}</span>).</p>")
    elif res.deaths_note:
        H.append(f"<p>No deaths-index search was run: {e(res.deaths_note)}</p>")
    elif not res.death_searches:
        H.append("<p>No deaths-index search was run (no owner of record could be read as a person's name).</p>")

    # ---- obituaries
    ob = res.obituary or {}
    H.append("<h2>5. Obituaries</h2>")
    if ob.get("run"):
        H.append(f"<p>{e(ob.get('summary') or '')}</p>")
    else:
        H.append(f"<p>{_tag('Not run', 'vd-na')} {e(ob.get('reason') or 'Not run.')}</p>")
    if ob.get("searches"):
        H.append("<p>Searches a person runs:</p><ol class='steps'>" + "".join(f"<li>{e(s)}</li>" for s in ob["searches"]) + "</ol>")

    # ---- records
    H.append("<h2>6. Public records checked and not checked</h2>")
    tagcls = {"checked": "vd-ok", "checked in part": "vd-part", "walled": "vd-no", "not run": "vd-na",
              "not checked": "vd-na", "not opened": "vd-na"}
    H.append("<table><thead><tr><th>Record</th><th>Status</th><th>What was done</th><th>Result</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{e(r.record)}</td><td>{_tag(r.status, tagcls.get(r.status, 'vd-na'))}</td>"
                       f"<td>{e(r.what)}</td><td>{e(r.result)}</td></tr>" for r in res.records) + "</tbody></table>")
    if res.walls:
        H.append("<div class='warn'><b>Stopped at a wall during this run.</b><br>" + "<br>".join(e(w) for w in res.walls) + "</div>")

    # ---- how to
    H.append("<h2>7. How to check it again</h2>")
    for name, steps in res.how_to:
        H.append(f"<h3>{e(name)}</h3><ol class='steps'>" + "".join(f"<li>{e(s)}</li>" for s in steps) + "</ol>")

    # ---- not established
    H.append("<h2>8. What this does not establish</h2>")
    items = [
        "No title search was run. This sheet reads indexes and county records; it is not an abstract or an opinion on title.",
        *res.not_established,
        "Name searches miss instruments indexed under other spellings or other names; only the names shown were searched.",
        "Death-index entries are name matches. A fit means the full name agrees; it is not proof that the decedent is the "
        "owner of record. The heirs' names and whereabouts are not established.",
        "Estate files and court files were not read (the court portal is walled).",
        "Records older than the online index, microfilm, and old books and maps that are not online were not checked; "
        "records older than about 70 years need an abstractor.",
        "County values are tax values, not market prices. Tax amounts move daily as the county adds interest and costs.",
        "Not legal advice.",
    ]
    H.append("<div class='box no'><ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul></div>")

    # ---- exhibits
    H.append("<section class='exhibits'><h2>Exhibits</h2>")
    H.append("<p class='small'>Every page this run read, in the order read. The saved copy and the picture are in the "
             "exhibits folder beside this file. Pictures are renderings of the saved copy, drawn with no request to the source.</p>")
    rows = ""
    for ex in res.exhibits.values():
        rows += (f"<tr id='ex-{e(ex.key)}'><td>{e(ex.key)}</td><td>{e(ex.label)}<br><span class='small'>{e(ex.source)}</span>"
                 f"{('<br><span class=small>' + e(ex.note) + '</span>') if ex.note else ''}</td>"
                 f"<td class='url'>{e(ex.url)}</td><td>{e(fmt_both(ex.fetched))}</td>"
                 f"<td>{'walled: ' + e(ex.wall_reason or '') if ex.walled else (ex.http_status or '')}</td>"
                 f"<td class='url'>{e(', '.join(ex.files + ([ex.screenshot] if ex.screenshot else [])))}</td></tr>")
    H.append("<table><thead><tr><th>No.</th><th>What</th><th>Address a person can open</th><th>Fetched (Eastern / UTC)</th>"
             f"<th>HTTP</th><th>Saved files</th></tr></thead><tbody>{rows}</tbody></table>")
    for ex in res.exhibits.values():
        if ex.screenshot:
            H.append(f"<figure class='shot'><img src='exhibits/{e(ex.screenshot)}' alt='{e(ex.label)}'>"
                     f"<figcaption>Exhibit {e(ex.key)}. {e(ex.label)}. Fetched {e(fmt_both(ex.fetched))}.</figcaption></figure>")
    H.append("<h2>Sources</h2><table><thead><tr><th>Source</th><th>Address</th><th>Access</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{e(a)}</td><td class='url'>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in res.sources)
             + "</tbody></table></section>")
    return _wrap(title, H, res)


def _wrap(title: str, body: list[str], res: IntakeResult) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{e(title)}</title><style>{_CSS}</style></head><body>" + "\n".join(body) + "</body></html>")


def write_sheet(res: IntakeResult, out_dir: Path, *, pictures: bool = True, pdf: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if pictures:
        take_screenshots(res, out_dir)
    stem = f"QuietTitle_Intake_{res.county}_{res.pin}"
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(render_html(res), encoding="utf-8")
    (out_dir / f"{stem}_facts.json").write_text(json.dumps(res.to_json(), indent=1, default=str), encoding="utf-8")
    pdf_path = out_dir / f"{stem}.pdf"
    ok = print_pdf(html_path, pdf_path) if pdf else False
    return {"html": html_path, "pdf": pdf_path if ok else None,
            "written": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
