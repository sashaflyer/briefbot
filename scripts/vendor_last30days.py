"""
Vendor selected modules from mvanhorn/last30days-skill.

Run: python scripts/vendor_last30days.py [<commit-sha>]
If sha is omitted, defaults to 'main' (records actual resolved SHA in UPSTREAM.md).
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "mvanhorn/last30days-skill"
BASE_PATH = "skills/last30days/scripts/lib"
DEST = Path(__file__).resolve().parent.parent / "aggregator" / "vendor" / "last30days"

MODULES = [
    "__init__.py",
    "reddit.py",
    "reddit_public.py",
    "reddit_enrich.py",
    "polymarket.py",
    "dedupe.py",
    "cluster.py",
    "rerank.py",
    "signals.py",
    "relevance.py",
    "normalize.py",
    "schema.py",
    "http.py",
    "dates.py",
    "env.py",
    "log.py",
    "query.py",
    "providers.py",
]

# Modules vendored from paths OTHER than BASE_PATH.
# Each entry is (upstream_relative_path, local_filename).
EXTRA_MODULES = [
    ("skills/last30days/scripts/store.py", "store.py"),
]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


def resolve_sha(ref: str) -> str:
    import json
    data = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{ref}").decode())
    return data["sha"]


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    sha = resolve_sha(ref)
    print(f"Vendoring {REPO}@{sha}")
    DEST.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for mod in MODULES:
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{BASE_PATH}/{mod}"
        print(f"  fetching {mod}")
        try:
            (DEST / mod).write_bytes(fetch(url))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    SKIP: {mod} not found at upstream (404)")
                missing.append(mod)
            else:
                raise

    for upstream_rel_path, local_name in EXTRA_MODULES:
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{upstream_rel_path}"
        print(f"  fetching {upstream_rel_path}")
        try:
            (DEST / local_name).write_bytes(fetch(url))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    SKIP: {upstream_rel_path} not found at upstream (404)")
                missing.append(upstream_rel_path)
            else:
                raise

    # Surgical patch: store.py was at scripts/ in upstream and imports lib/
    # submodules via sys.path manipulation. In our flat package layout, those
    # are siblings, so rewrite `from lib import X` → `from . import X`.
    store_py = DEST / "store.py"
    if store_py.exists():
        text = store_py.read_text(encoding="utf-8")
        patched = text.replace("from lib import ", "from . import ")
        if patched != text:
            store_py.write_text(patched, encoding="utf-8")
            print("  patched store.py: `from lib import ...` -> `from . import ...`")

    license_url = f"https://raw.githubusercontent.com/{REPO}/{sha}/LICENSE"
    (DEST / "LICENSE").write_bytes(fetch(license_url))

    extra_lines = "\n".join(
        f"- `{local}` (from `{path}`)" for path, local in EXTRA_MODULES
    )
    (DEST / "UPSTREAM.md").write_text(
        f"# Upstream provenance\n\n"
        f"Source: https://github.com/{REPO}\n"
        f"Commit: {sha}\n"
        f"Path: {BASE_PATH}/\n\n"
        f"## Vendored modules (from `{BASE_PATH}/`)\n\n"
        + "\n".join(f"- `{m}`" for m in MODULES)
        + "\n\n## Vendored modules (from other paths)\n\n"
        + extra_lines
        + "\n\n## Modifications\n\n"
        f"- Import paths adjusted: any intra-package import within these modules\n"
        f"  (e.g., `from .http import ...`) continues to resolve because we kept the\n"
        f"  package layout. Imports of upstream-only modules NOT vendored here will\n"
        f"  fail and must be surgically removed or stubbed when first encountered.\n"
        f"- `store.py` was at `scripts/` upstream (parent of `lib/`) and used\n"
        f"  `sys.path.insert(SCRIPT_DIR); from lib import schema`. The vendor\n"
        f"  script rewrites this to `from . import schema` so the import resolves\n"
        f"  in our flat package layout. The orphan `sys.path.insert` lines are\n"
        f"  left in place as harmless no-ops to minimize the patch surface.\n"
        f"- No other logic changes.\n\n"
        f"## Deviations from initial vendor spec\n\n"
        f"- `store.py` does not exist at `{BASE_PATH}/` (404). It lives at\n"
        f"  `skills/last30days/scripts/store.py` (parent dir of `lib/`) and is\n"
        f"  fetched via `EXTRA_MODULES` in `scripts/vendor_last30days.py`.\n"
        f"- `query.py` and `providers.py` were added to `MODULES` after the\n"
        f"  smoke import test surfaced `ModuleNotFoundError` from `reddit.py`\n"
        f"  (imports `.query`) and `rerank.py` (imports `.providers` and\n"
        f"  `.query`).\n",
        encoding="utf-8",
    )
    total = len(MODULES) + len(EXTRA_MODULES) - len(missing)
    if missing:
        print(f"WARNING: {len(missing)} modules missing upstream: {missing}")
    print(f"Done. Wrote {total} modules + LICENSE + UPSTREAM.md to {DEST}")


if __name__ == "__main__":
    main()
