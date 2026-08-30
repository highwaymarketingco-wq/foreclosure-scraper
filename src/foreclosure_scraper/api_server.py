"""REST API server — exposes the leads board via HTTP JSON endpoints.

Uses Python stdlib only (http.server) — no FastAPI/uvicorn dependency.
Matches Goliath Data's API access feature: external tools can query leads,
filter by grade/state/county/type, search by owner/parcel, and export CSV.

Endpoints:
  GET /                          — API info
  GET /api/leads?state=NC&...    — paginated, filterable lead list
  GET /api/leads/<dedupe_key>    — single lead detail
  GET /api/leads/search?q=...    — search by owner, address, parcel_id
  GET /api/stats                 — board statistics (counts by state/county/type/grade)
  GET /api/export?format=csv     — bulk CSV export
  GET /health                    — health check

Run:
    python -m foreclosure_scraper.api_server
    # Or programmatically:
    from foreclosure_scraper.api_server import create_server
    create_server(port=8000)
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence

import structlog

from .models import Listing
from .web_artifact import load_board

log = structlog.get_logger()

# Board loaded lazily on first request, not at import time (374MB file)
_BOARD: list[Listing] | None = None
_BOARD_INDEX: dict[str, Listing] | None = None

# Keep-list for raw fields exposed via API (sensitive internal fields hidden)
_KEEP_RAW_KEYS = frozenset({
    "grade", "calc", "equity", "tax_owed", "owner_phone", "skip_trace",
    "dnc_scrub", "marriage_license", "life_events", "flood_zone",
    "code_enforcement", "bankruptcy", "title_risk", "fema_disaster",
    "eviction_market", "data_quality", "intent", "corroboration",
    "workflow_tags", "workflow_status", "census_rent",
})


def _get_board() -> list[Listing]:
    global _BOARD, _BOARD_INDEX
    if _BOARD is None:
        log.info("api.loading_board")
        _BOARD = load_board("docs")
        _BOARD_INDEX = {li.dedupe_key(): li for li in _BOARD}
        log.info("api.board_loaded", count=len(_BOARD))
    return _BOARD


def _listing_to_dict(li: Listing) -> dict:
    """Convert a Listing to a JSON-safe dict, filtering raw to safe keys."""
    raw_out = {}
    if isinstance(li.raw, dict):
        for k in _KEEP_RAW_KEYS:
            if k in li.raw:
                raw_out[k] = li.raw[k]
    return {
        "dedupe_key": li.dedupe_key(),
        "owner_name": li.owner_name,
        "defendant": li.defendant,
        "street_address": li.street_address,
        "city": li.city,
        "state": li.state,
        "county": li.county,
        "zip_code": li.zip_code,
        "parcel_id": li.parcel_id,
        "case_number": li.case_number,
        "listing_type": li.listing_type.value if li.listing_type else None,
        "source": li.source,
        "source_url": li.source_url,
        "sale_date": li.sale_date,
        "latitude": li.latitude,
        "longitude": li.longitude,
        "market_value": li.market_value,
        "assessed_value": li.assessed_value,
        "tax_value": li.tax_value,
        "acreage": li.acreage,
        "year_built": li.year_built,
        "living_sqft": li.living_sqft,
        "bedrooms": li.bedrooms,
        "bathrooms": li.bathrooms,
        "judgment_amount": li.judgment_amount,
        "opening_bid": li.opening_bid,
        "raw": raw_out,
    }


def _filter_leads(
    board: Sequence[Listing],
    filters: dict | None = None,
) -> list[Listing]:
    """Apply filter dict to a board slice and return matching listings."""
    if not filters:
        return list(board)
    result = []
    for li in board:
        if "state" in filters and li.state not in filters["state"]:
            continue
        if "county" in filters and li.county not in filters["county"]:
            continue
        if "grade" in filters:
            raw = li.raw if isinstance(li.raw, dict) else {}
            g = raw.get("grade")
            if isinstance(g, dict):
                g = g.get("overall")
            if str(g).upper() not in [str(x).upper() for x in filters["grade"]]:
                continue
        if "type" in filters:
            lt = li.listing_type.value if li.listing_type else ""
            if lt not in filters["type"]:
                continue
        if "has_phone" in filters and filters["has_phone"]:
            raw = li.raw if isinstance(li.raw, dict) else {}
            phones = (raw.get("owner_phone") or {}).get("phone") or \
                     (raw.get("skip_trace") or {}).get("phone_numbers")
            if not phones:
                continue
        if "has_mailing" in filters and filters["has_mailing"]:
            raw = li.raw if isinstance(li.raw, dict) else {}
            if not (raw.get("skip_trace") or {}).get("owner_mailing_address"):
                continue
        if "min_equity" in filters:
            raw = li.raw if isinstance(li.raw, dict) else {}
            eq = raw.get("equity")
            try:
                if float(eq or 0) < float(filters["min_equity"]):
                    continue
            except (TypeError, ValueError):
                continue
        result.append(li)
    return result


def _search_leads(query: str, limit: int = 50) -> list[Listing]:
    """Search board by owner name, parcel_id, or address (case-insensitive)."""
    board = _get_board()
    q = query.upper().strip()
    if not q:
        return []
    results = []
    for li in board:
        owner = (li.owner_name or li.defendant or "").upper()
        addr = (li.street_address or "").upper()
        parcel = (li.parcel_id or "").upper()
        if q in owner or q in addr or q in parcel:
            results.append(li)
            if len(results) >= limit:
                break
    return results


class _RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the leads API."""

    def _send_json(self, code: int, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _send_csv(self, code: int, csv_text: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=leads.csv")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(csv_text.encode())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        # GET / — API info
        if path == "/":
            self._send_json(200, {
                "name": "foreclosure-scraper API",
                "endpoints": [
                    "GET /api/leads?state=NC&county=Wake&grade=A&limit=50&offset=0",
                    "GET /api/leads/<dedupe_key>",
                    "GET /api/leads/search?q=SMITH",
                    "GET /api/stats",
                    "GET /api/export?format=csv",
                    "GET /health",
                ],
            })
            return

        # GET /health
        if path == "/health":
            self._send_json(200, {"status": "ok", "board_size": len(_get_board())})
            return

        # GET /api/stats
        if path == "/api/stats":
            board = _get_board()
            from collections import Counter
            stats = {
                "total_leads": len(board),
                "by_state": dict(Counter(li.state or "?" for li in board)),
                "by_county": dict(Counter(f"{li.county or '?'}/{li.state or '?'}" for li in board)),
                "by_type": dict(Counter(
                    li.listing_type.value if li.listing_type else "unknown"
                    for li in board
                )),
            }
            # Grade from raw
            grade_counter = Counter()
            for li in board:
                raw = li.raw if isinstance(li.raw, dict) else {}
                g = raw.get("grade")
                if isinstance(g, dict):
                    g = g.get("overall", "ungraded")
                grade_counter[str(g or "ungraded").upper()] += 1
            stats["by_grade"] = dict(grade_counter)
            self._send_json(200, stats)
            return

        # GET /api/leads/search?q=...
        if path == "/api/leads/search":
            q = query.get("q", [""])[0]
            limit = int(query.get("limit", ["50"])[0])
            if not q:
                self._send_json(400, {"error": "Missing 'q' parameter"})
                return
            results = _search_leads(q, limit=limit)
            self._send_json(200, {
                "query": q,
                "count": len(results),
                "results": [_listing_to_dict(li) for li in results],
            })
            return

        # GET /api/leads/<dedupe_key>
        if path.startswith("/api/leads/"):
            key = path.split("/api/leads/", 1)[1]
            board = _get_board()
            index = _BOARD_INDEX or {}
            li = index.get(key)
            if li:
                self._send_json(200, _listing_to_dict(li))
            else:
                self._send_json(404, {"error": "Lead not found", "dedupe_key": key})
            return

        # GET /api/leads?state=NC&county=Wake&grade=A&type=tax_lien&...
        if path == "/api/leads":
            board = _get_board()
            filters = {}
            for key in ("state", "county", "grade", "type"):
                if key in query:
                    filters[key] = query[key][0].split(",")
            if "has_phone" in query:
                filters["has_phone"] = query["has_phone"][0].lower() == "true"
            if "has_mailing" in query:
                filters["has_mailing"] = query["has_mailing"][0].lower() == "true"
            if "min_equity" in query:
                filters["min_equity"] = query["min_equity"][0]

            filtered = _filter_leads(board, filters)
            limit = int(query.get("limit", ["50"])[0])
            offset = int(query.get("offset", ["0"])[0])
            page = filtered[offset:offset + limit]
            self._send_json(200, {
                "total": len(filtered),
                "limit": limit,
                "offset": offset,
                "count": len(page),
                "filters": filters,
                "results": [_listing_to_dict(li) for li in page],
            })
            return

        # GET /api/export?format=csv
        if path == "/api/export":
            fmt = query.get("format", ["csv"])[0]
            if fmt != "csv":
                self._send_json(400, {"error": f"Unsupported format: {fmt}"})
                return
            board = _get_board()
            # Apply same filters as /api/leads
            filters = {}
            for key in ("state", "county", "grade", "type"):
                if key in query:
                    filters[key] = query[key][0].split(",")
            if "has_phone" in query:
                filters["has_phone"] = query["has_phone"][0].lower() == "true"
            if "has_mailing" in query:
                filters["has_mailing"] = query["has_mailing"][0].lower() == "true"
            filtered = _filter_leads(board, filters)

            header = "dedupe_key,owner_name,street_address,city,state,county,zip_code,parcel_id,listing_type,source,sale_date,market_value,assessed_value,tax_value,acreage,year_built,living_sqft,bedrooms,bathrooms,judgment_amount,opening_bid\n"
            lines = [header]
            for li in filtered:
                row = [
                    li.dedupe_key(),
                    li.owner_name or "",
                    li.street_address or "",
                    li.city or "",
                    li.state or "",
                    li.county or "",
                    li.zip_code or "",
                    li.parcel_id or "",
                    li.listing_type.value if li.listing_type else "",
                    li.source or "",
                    li.sale_date or "",
                    str(li.market_value or ""),
                    str(li.assessed_value or ""),
                    str(li.tax_value or ""),
                    str(li.acreage or ""),
                    str(li.year_built or ""),
                    str(li.living_sqft or ""),
                    str(li.bedrooms or ""),
                    str(li.bathrooms or ""),
                    str(li.judgment_amount or ""),
                    str(li.opening_bid or ""),
                ]
                # Escape commas in fields
                lines.append(",".join('"' + f.replace('"', '""') + '"' if "," in f else f for f in row) + "\n")
            self._send_csv(200, "".join(lines))
            return

        # 404
        self._send_json(404, {"error": "Not found", "path": path})

    def log_message(self, format, *args):
        log.info("api.http", msg=format % args if args else format)


def create_server(port: int = 8000, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Create and return the HTTP server (does not start serving)."""
    server = ThreadingHTTPServer((host, port), _RequestHandler)
    log.info("api.server_created", host=host, port=port)
    return server


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = create_server(port=port)
    print(f"API server listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
