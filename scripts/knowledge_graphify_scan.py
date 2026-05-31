#!/usr/bin/env python3
"""Create ATR project graph artifacts using Graphify-compatible fallback scan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge.graphify_bridge import DEFAULT_SCAN_PATHS, scan_project_graph  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ATR repo into Graphify-compatible project graph artifacts")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--out-dir", default="memory/knowledge/graphify")
    parser.add_argument("--source", action="append", dest="sources", help="source path to scan; may be repeated")
    parser.add_argument("--max-file-bytes", type=int, default=256_000)
    parser.add_argument("--external-graphify", action="store_true", help="try external graphify CLI first, then fallback if unavailable/failing")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    sources = args.sources or list(DEFAULT_SCAN_PATHS)
    result = scan_project_graph(
        root,
        out_dir=(root / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir).resolve(),
        source_paths=sources,
        max_file_bytes=args.max_file_bytes,
        run_external_graphify=args.external_graphify,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
