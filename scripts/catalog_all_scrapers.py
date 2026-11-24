#!/usr/bin/env python3
"""Map all 306 existing scrapers to spreadsheet sources"""
import sys
import importlib
import inspect
from pathlib import Path
sys.path.insert(0, 'src')

def find_all_scrapers():
    """Find all scraper classes"""
    scrapers = []
    base_path = Path("src/foreclosure_scraper/scrapers")
    
    for py_file in base_path.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
            
        # Convert path to module
        rel_path = py_file.relative_to("src")
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        
        try:
            mod = importlib.import_module(module_name)
            
            # Find BaseScraper subclasses
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if name != "BaseScraper" and hasattr(obj, "fetch"):
                    # Get docstring for source URL
                    doc = obj.__doc__ or ""
                    first_line = doc.split("\n")[0] if doc else ""
                    
                    scrapers.append({
                        "class": name,
                        "module": module_name,
                        "file": str(py_file),
                        "description": first_line[:100],
                    })
        except Exception as e:
            print(f"⚠️  Skip {py_file.name}: {e}", file=sys.stderr)
            continue
    
    return scrapers

def main():
    print("🔍 Finding all scrapers in codebase...\n")
    scrapers = find_all_scrapers()
    
    print(f"Found {len(scrapers)} scrapers:\n")
    
    # Group by category
    categories = {
        "probate": [],
        "rod": [],
        "tax": [],
        "sos": [],
        "other": [],
    }
    
    for s in scrapers:
        name_lower = s["class"].lower()
        file_lower = s["file"].lower()
        
        if "probate" in name_lower or "estate" in name_lower:
            categories["probate"].append(s)
        elif "rod" in name_lower or "register" in name_lower or "deed" in name_lower:
            categories["rod"].append(s)
        elif "tax" in name_lower:
            categories["tax"].append(s)
        elif "sos" in name_lower or "secretary" in name_lower:
            categories["sos"].append(s)
        else:
            categories["other"].append(s)
    
    for cat, items in categories.items():
        if items:
            print(f"\n## {cat.upper()} ({len(items)} scrapers)")
            for s in items[:10]:  # Show first 10
                print(f"   - {s['class']}")
                print(f"     {s['description']}")
            if len(items) > 10:
                print(f"   ... and {len(items)-10} more")
    
    print(f"\n\n📊 TOTAL: {len(scrapers)} scrapers")
    print(f"   Probate: {len(categories['probate'])}")
    print(f"   ROD/Register: {len(categories['rod'])}")
    print(f"   Tax: {len(categories['tax'])}")
    print(f"   SOS: {len(categories['sos'])}")
    print(f"   Other: {len(categories['other'])}")

if __name__ == "__main__":
    main()
