import re
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
APP_JS = BASE_DIR / "static" / "js" / "app.js"
COMPONENTS_JS = BASE_DIR / "static" / "js" / "components.js"
TEST_RESULTS_DIR = BASE_DIR / "test_results"
TEST_RESULTS_DIR.mkdir(exist_ok=True)

def parse_javascript_features(filepath):
    if not filepath.exists():
        return {}
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Extract Handler Functions (handleXxx)
    handlers = sorted(list(set(re.findall(r'const\s+(handle[A-Za-z0-9_]+)\s*=', content) + 
                               re.findall(r'function\s+(handle[A-Za-z0-9_]+)\s*\(', content))))

    # 2. Extract API Endpoints (axios.get/post/delete/put)
    api_calls = sorted(list(set(re.findall(r'axios\.(get|post|delete|put|patch)\s*\(\s*[`\']([^`\']+)[`\']', content))))
    api_endpoints = [f"{method.upper()} {url}" for method, url in api_calls]

    # 3. Extract React State variables
    states = sorted(list(set(re.findall(r'const\s*\[\s*([A-Za-z0-9_]+)\s*,\s*set[A-Za-z0-9_]+\s*\]\s*=\s*useState', content))))

    # 4. Extract Window Globals (window.Xxx)
    globals_assigned = sorted(list(set(re.findall(r'window\.([A-Za-z0-9_]+)\s*=', content))))

    return {
        "file": str(filepath.name),
        "handlers": handlers,
        "api_endpoints": api_endpoints,
        "states": states,
        "globals": globals_assigned
    }

def main():
    app_features = parse_javascript_features(APP_JS)
    comp_features = parse_javascript_features(COMPONENTS_JS)

    all_handlers = sorted(list(set(app_features.get("handlers", []) + comp_features.get("handlers", []))))
    all_apis = sorted(list(set(app_features.get("api_endpoints", []) + comp_features.get("api_endpoints", []))))
    all_states = sorted(list(set(app_features.get("states", []) + comp_features.get("states", []))))
    all_globals = sorted(list(set(app_features.get("globals", []) + comp_features.get("globals", []))))

    report = {
        "summary": {
            "total_handlers": len(all_handlers),
            "total_api_endpoints": len(all_apis),
            "total_states": len(all_states),
            "total_globals": len(all_globals)
        },
        "app_js": app_features,
        "components_js": comp_features,
        "complete_inventory": {
            "handlers": all_handlers,
            "api_endpoints": all_apis,
            "states": all_states,
            "globals": all_globals
        }
    }

    result_file = TEST_RESULTS_DIR / "feature_matrix_report.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ Extracted Feature Matrix Successfully!")
    print(f"   - Total Event Handlers: {len(all_handlers)}")
    print(f"   - Total API Endpoints: {len(all_apis)}")
    print(f"   - Total React States: {len(all_states)}")
    print(f"   - Total Window Globals: {len(all_globals)}")
    print(f"📄 Full report saved to: {result_file}")

if __name__ == "__main__":
    main()
