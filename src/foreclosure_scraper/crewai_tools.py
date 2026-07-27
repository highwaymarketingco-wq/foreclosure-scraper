"""CrewAI BaseTool wrappers for the foreclosure scraper engine.

These wrappers allow a local LLM (Qwen 2.5 via Ollama) to trigger individual
scrapers and enrichment modules on demand as CrewAI tools.

Usage in CrewAI:
    from foreclosure_scraper.crewai_tools import (
        RunScraperTool,
        RunEnrichmentTool,
        MergeLeadsTool,
        ParseSavedHTMLTool,
    )

    tools = [
        RunScraperTool(),
        RunEnrichmentTool(),
        MergeLeadsTool(),
        ParseSavedHTMLTool(),
    ]

Each tool takes a JSON string argument and returns a JSON string result.
The local model (Qwen) calls these tools with natural-language parameters
and receives structured results.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure src is on the path
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _try_import_crewai():
    """Import CrewAI BaseTool, or provide a fallback if not installed."""
    try:
        from crewai.tools import BaseTool
        return BaseTool
    except ImportError:
        try:
            from crewai.tools.tool import BaseTool
            return BaseTool
        except ImportError:
            # Fallback: minimal BaseTool shim
            class BaseTool:
                name: str = ""
                description: str = ""

                def _run(self, *args, **kwargs):
                    raise NotImplementedError

                def run(self, *args, **kwargs):
                    return self._run(*args, **kwargs)

            return BaseTool


BaseTool = _try_import_crewai()


class RunScraperTool(BaseTool):
    """Trigger a single scraper by slug and return the leads as JSON."""

    name: str = "run_scraper"
    description: str = (
        "Run a single foreclosure-scraper module by its slug. "
        "Input: a JSON string with 'slug' (required) e.g. "
        '{"slug": "national.landwatch"}. '
        "Returns: JSON string with 'count', 'outcome', and first 5 lead summaries."
    )

    def _run(self, query: str = "") -> str:
        try:
            params = json.loads(query) if query else {}
        except json.JSONDecodeError:
            params = {"slug": query.strip()}

        slug = params.get("slug", "").strip()
        if not slug:
            return json.dumps({"error": "slug is required"})

        try:
            from foreclosure_scraper.scrapers._registry import all_scrapers
            all_sc = {s.slug: s for s in all_scrapers()}
            if slug not in all_sc:
                available = sorted(all_sc.keys())
                return json.dumps({
                    "error": f"slug '{slug}' not found",
                    "available": available[:30],
                })

            scraper = all_sc[slug]

            async def _run():
                results = await scraper.safe_run()
                data = [json.loads(li.model_dump_json()) for li in results]
                return results, data

            results, data = asyncio.run(_run())

            summaries = []
            for li in results[:5]:
                summaries.append({
                    "county": li.county,
                    "state": li.state,
                    "case_number": li.case_number,
                    "description": (li.description or "")[:100],
                })

            return json.dumps({
                "slug": slug,
                "count": len(results),
                "outcome": scraper.last_outcome,
                "sample": summaries,
            }, default=str)

        except Exception as exc:
            return json.dumps({"error": str(exc)[:200]})


class RunEnrichmentTool(BaseTool):
    """Run an enrichment module on a set of listings.

    Loads listings from docs/listings.json, runs the named enrichment
    module, and saves back. Input: JSON with 'module' name.
    """

    name: str = "run_enrichment"
    description: str = (
        "Run an enrichment module on the current board. "
        "Input: JSON string with 'module' (required) e.g. "
        '{"module": "flood_zone"}. '
        "Available modules: flood_zone, fema_disaster, opportunity_zone, "
        "usps_vacancy, owner_mailing, jail_bookings, buyer_match, "
        "lis_pendens_resolver, gis_attrs, equity, distress_score."
    )

    MODULE_MAP = {
        "flood_zone": "enrichment_flood_zone",
        "fema_disaster": "enrichment_fema_disaster",
        "opportunity_zone": "enrichment_opportunity_zone",
        "usps_vacancy": "enrichment_usps_vacancy",
        "owner_mailing": "enrichment_owner_mailing",
        "jail_bookings": "enrichment_jail_bookings",
        "buyer_match": "enrichment_buyer_match",
        "lis_pendens_resolver": "enrichment_lis_pendens_resolver",
        "gis_attrs": "enrichment_gis_attrs",
        "equity": "enrichment_equity",
        "distress_score": "distress_score",
    }

    def _run(self, query: str = "") -> str:
        try:
            params = json.loads(query) if query else {}
        except json.JSONDecodeError:
            params = {"module": query.strip()}

        module_name = params.get("module", "").strip()
        if not module_name:
            return json.dumps({
                "error": "module is required",
                "available": list(self.MODULE_MAP.keys()),
            })

        module_key = self.MODULE_MAP.get(module_name)
        if not module_key:
            return json.dumps({
                "error": f"module '{module_name}' not found",
                "available": list(self.MODULE_MAP.keys()),
            })

        try:
            from foreclosure_scraper.web_artifact import load_board, write_artifact
            docs = _REPO / "docs"
            listings = load_board(docs)
            if not listings:
                return json.dumps({"error": "no listings in board"})

            mod = __import__(f"foreclosure_scraper.{module_key}", fromlist=[module_key])

            async def _enrich():
                if hasattr(mod, "enrich_flood_zones"):
                    return await mod.enrich_flood_zones(listings)
                elif hasattr(mod, "enrich_opportunity_zones"):
                    return await mod.enrich_opportunity_zones(listings)
                elif hasattr(mod, "enrich_usps_vacancy"):
                    return mod.enrich_usps_vacancy(listings)
                elif hasattr(mod, "fetch_helene_disaster_data"):
                    data = await mod.fetch_helene_disaster_data()
                    return {"declarations": len(data) if data else 0}
                elif hasattr(mod, "enrich_owner_mailing"):
                    return await mod.enrich_owner_mailing(listings)
                elif hasattr(mod, "enrich_jail_bookings"):
                    return await mod.enrich_jail_bookings(listings)
                elif hasattr(mod, "enrich_buyer_match"):
                    return mod.enrich_buyer_match(listings)
                elif hasattr(mod, "enrich_lis_pendens_addresses"):
                    return await mod.enrich_lis_pendens_addresses(listings)
                elif hasattr(mod, "enrich_gis_attrs"):
                    return await mod.enrich_gis_attrs(listings)
                elif hasattr(mod, "score_board"):
                    return mod.score_board(listings)
                else:
                    return {"error": f"no enrich function found in {module_key}"}

            stats = asyncio.run(_enrich())

            # Save back
            write_artifact(listings, {"enrichment": module_name}, docs_dir=docs)

            return json.dumps({
                "module": module_name,
                "listings_processed": len(listings),
                "stats": stats if isinstance(stats, dict) else str(stats),
            }, default=str)

        except Exception as exc:
            return json.dumps({"error": str(exc)[:200]})


class MergeLeadsTool(BaseTool):
    """Merge a JSON file of leads into the board.

    Loads leads from a file path, dedupes against the board, and saves.
    Input: JSON with 'file' path.
    """

    name: str = "merge_leads"
    description: str = (
        "Merge a JSON file of leads into the board. "
        "Input: JSON string with 'file' (required) e.g. "
        '{"file": "docs/fresh_court_leads.json"}. '
        "Returns: JSON with total, new, duplicate counts."
    )

    def _run(self, query: str = "") -> str:
        try:
            params = json.loads(query) if query else {}
        except json.JSONDecodeError:
            params = {"file": query.strip()}

        file_path = params.get("file", "").strip()
        if not file_path:
            return json.dumps({"error": "file is required"})

        try:
            from foreclosure_scraper.web_artifact import load_board, write_artifact
            from foreclosure_scraper.models import Listing

            full_path = _REPO / file_path if not os.path.isabs(file_path) else Path(file_path)
            if not full_path.exists():
                return json.dumps({"error": f"file not found: {full_path}"})

            with open(full_path) as f:
                new_data = json.load(f)

            docs = _REPO / "docs"
            board = load_board(docs)
            existing_keys = {(li.case_number, li.source_url, li.source) for li in board}

            new_count = 0
            dup_count = 0
            for item in new_data:
                key = (item.get("case_number"), item.get("source_url"), item.get("source"))
                if key in existing_keys:
                    dup_count += 1
                    continue
                try:
                    li = Listing.model_validate(item)
                    board.append(li)
                    existing_keys.add(key)
                    new_count += 1
                except Exception:
                    continue

            write_artifact(board, {"merged": new_count}, docs_dir=docs)

            return json.dumps({
                "file": str(full_path),
                "total_in_file": len(new_data),
                "new_merged": new_count,
                "duplicates": dup_count,
                "board_total": len(board),
            }, default=str)

        except Exception as exc:
            return json.dumps({"error": str(exc)[:200]})


class ParseSavedHTMLTool(BaseTool):
    """Parse saved HTML files (SC PublicIndex or NC eCourts exports).

    Scans a directory for saved .html files, parses them, and returns
    the extracted leads. Input: JSON with 'directory' and 'type'.
    """

    name: str = "parse_saved_html"
    description: str = (
        "Parse saved HTML files from court portal exports. "
        "Input: JSON string with 'directory' (default: repo root) and "
        "'type' ('sc_publicindex' or 'nc_ecourts', default: auto-detect). "
        "Returns: JSON with count and sample leads."
    )

    def _run(self, query: str = "") -> str:
        try:
            params = json.loads(query) if query else {}
        except json.JSONDecodeError:
            params = {}

        directory = params.get("directory", str(_REPO))
        parse_type = params.get("type", "auto")
        dir_path = Path(directory)

        try:
            html_files = sorted(list(dir_path.glob("*.html")) + list(dir_path.glob("*.htm")))
            if not html_files:
                return json.dumps({"error": "no HTML files found", "directory": str(dir_path)})

            all_leads = []

            for f in html_files:
                html = f.read_text(encoding="utf-8", errors="replace")

                if parse_type == "auto":
                    if "ContentPlaceHolder1_SearchResults" in html or "publicindex" in html.lower():
                        parse_type = "sc_publicindex"
                    elif "caseLink" in html or "tylertech" in html.lower():
                        parse_type = "nc_ecourts"

                if parse_type == "sc_publicindex":
                    from foreclosure_scraper.ingest_sc_publicindex_export import parse_publicindex_html
                    leads = parse_publicindex_html(html, default_county=None)
                    all_leads.extend(leads)
                elif parse_type == "nc_ecourts":
                    # NC eCourts parser is in scripts/
                    sys.path.insert(0, str(_REPO / "scripts"))
                    from parse_nc_ecourts_export import parse_nc_ecourts_html
                    records = parse_nc_ecourts_html(html)
                    all_leads.extend(records)

            return json.dumps({
                "directory": str(dir_path),
                "files_scanned": len(html_files),
                "leads_parsed": len(all_leads),
                "sample": [
                    {
                        "case_number": getattr(l, "case_number", None) or (l.get("case_number") if isinstance(l, dict) else None),
                        "county": getattr(l, "county", None) or (l.get("county") if isinstance(l, dict) else None),
                    }
                    for l in all_leads[:5]
                ],
            }, default=str)

        except Exception as exc:
            return json.dumps({"error": str(exc)[:200]})


class ListScrapersTool(BaseTool):
    """List all available scrapers and their status."""

    name: str = "list_scrapers"
    description: str = (
        "List all available scrapers in the engine. "
        "No input required. Returns JSON with all scraper slugs, names, and categories."
    )

    def _run(self, query: str = "") -> str:
        try:
            from foreclosure_scraper.scrapers._registry import all_scrapers
            scrapers = all_scrapers()
            return json.dumps({
                "total": len(scrapers),
                "scrapers": [
                    {
                        "slug": s.slug,
                        "name": s.name,
                        "category": getattr(s, "category", ""),
                    }
                    for s in sorted(scrapers, key=lambda x: x.slug)
                ],
            }, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)[:200]})


# Convenience: all tools as a list
def get_all_tools():
    """Return all available CrewAI tools."""
    return [
        RunScraperTool(),
        RunEnrichmentTool(),
        MergeLeadsTool(),
        ParseSavedHTMLTool(),
        ListScrapersTool(),
    ]


if __name__ == "__main__":
    # Quick test
    list_tool = ListScrapersTool()
    result = list_tool._run()
    data = json.loads(result)
    print(f"Total scrapers: {data.get('total', 0)}")
    for s in data.get("scrapers", [])[:5]:
        print(f"  {s['slug']}: {s['name']}")
