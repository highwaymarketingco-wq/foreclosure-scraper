#!/usr/bin/env python3
"""Cross-reference 294 scrapers against 509-cell spreadsheet"""
import pandas as pd
import sys
from pathlib import Path
import importlib
import inspect

sys.path.insert(0, 'src')

SPREADSHEET = "/Users/cashhigh/Desktop/hermes_handoffs/Hermes_Handoff_Walled_Declined_NA_2026-11-23.xlsx"

def load_spreadsheet():
    """Load and parse spreadsheet"""
    df = pd.read_excel(SPREADSHEET, sheet_name="1 Hermes Lane (CAPTCHA_login)", skiprows=1)
    df.columns = ["State", "County", "Signal", "Rows", "Reason", "Source", "Status", "Notes"]
    return df

def find_all_scrapers():
    """Find all scraper classes with metadata"""
    scrapers = []
    base_path = Path("src/foreclosure_scraper/scrapers")
    
    for py_file in base_path.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
            
        rel_path = py_file.relative_to("src")
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        
        try:
            mod = importlib.import_module(module_name)
            
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if name != "BaseScraper" and hasattr(obj, "fetch"):
                    doc = obj.__doc__ or ""
                    
                    scrapers.append({
                        "class": name,
                        "module": module_name,
                        "file": str(py_file),
                        "doc": doc[:200],
                    })
        except:
            continue
    
    return scrapers

def match_scrapers_to_spreadsheet(df, scrapers):
    """Find which scrapers likely cover spreadsheet sources"""
    
    # Create lookup by keywords
    matches = []
    
    for idx, row in df.iterrows():
        source = str(row["Source"]).lower()
        county = str(row["County"]).lower()
        state = str(row["State"]).lower()
        signal = str(row["Signal"]).lower()
        rows = row["Rows"]
        
        # Find matching scrapers
        matched = []
        for s in scrapers:
            class_lower = s["class"].lower()
            file_lower = s["file"].lower()
            doc_lower = s["doc"].lower()
            
            # Match logic
            score = 0
            
            # County name match
            if county in class_lower or county in file_lower:
                score += 10
            
            # Signal type match
            if "probate" in source and "probate" in class_lower:
                score += 5
            elif "tyler" in source and "tyler" in class_lower:
                score += 5
            elif "tax" in source and "tax" in class_lower:
                score += 5
            elif "rod" in source and ("rod" in class_lower or "deed" in class_lower):
                score += 5
            elif "sos" in source and "sos" in class_lower:
                score += 5
            
            # Platform match
            if "countyfusion" in source and "countyfusion" in class_lower:
                score += 10
            elif "avenu" in source and "avenu" in class_lower:
                score += 10
            elif "ccs" in source or "courthouse computer" in source:
                if "cchs" in class_lower or "ccs" in class_lower:
                    score += 10
            
            if score >= 5:
                matched.append((s["class"], s["module"], score))
        
        if matched:
            # Sort by score
            matched.sort(key=lambda x: x[2], reverse=True)
            best = matched[0]
            
            matches.append({
                "state": state.upper(),
                "county": county.title(),
                "signal": signal,
                "rows": rows,
                "source": source[:60],
                "scraper": best[0],
                "module": best[1],
                "confidence": best[2],
            })
    
    return matches

def main():
    print("🔍 Cross-referencing 294 scrapers → 509 spreadsheet cells\n")
    
    # Load data
    print("Loading spreadsheet...")
    df = load_spreadsheet()
    print(f"   {len(df)} spreadsheet rows")
    
    print("\nFinding scrapers...")
    scrapers = find_all_scrapers()
    print(f"   {len(scrapers)} scrapers found")
    
    print("\nMatching...")
    matches = match_scrapers_to_spreadsheet(df, scrapers)
    print(f"   {len(matches)} potential matches\n")
    
    # Group by confidence
    high_conf = [m for m in matches if m["confidence"] >= 15]
    med_conf = [m for m in matches if 10 <= m["confidence"] < 15]
    low_conf = [m for m in matches if 5 <= m["confidence"] < 10]
    
    print(f"📊 MATCH SUMMARY:")
    print(f"   High confidence (≥15): {len(high_conf)} matches")
    print(f"   Medium confidence (10-14): {len(med_conf)} matches")
    print(f"   Low confidence (5-9): {len(low_conf)} matches")
    print(f"   No match: {len(df) - len(matches)} cells")
    
    # Calculate row coverage
    matched_rows = sum(m["rows"] for m in matches)
    total_rows = df["Rows"].sum()
    
    print(f"\n📈 ROW COVERAGE:")
    print(f"   Matched: {matched_rows:,} / {total_rows:,} ({matched_rows/total_rows*100:.1f}%)")
    
    # Show top matches
    print(f"\n✅ TOP 20 HIGH-CONFIDENCE MATCHES:")
    for m in sorted(high_conf, key=lambda x: x["rows"], reverse=True)[:20]:
        print(f"   {m['county']} {m['state']} - {m['signal']}: {m['rows']:,} rows")
        print(f"      → {m['scraper']} (confidence: {m['confidence']})")
    
    # Save full results
    output = pd.DataFrame(matches)
    output_path = "docs/scraper_spreadsheet_matches.csv"
    output.to_csv(output_path, index=False)
    print(f"\n💾 Full results saved to {output_path}")

if __name__ == "__main__":
    main()
