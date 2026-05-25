import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

_INCLUDE_RE = re.compile(r"\{include:([A-Za-z0-9_\-]+)\}")


def load(name: str) -> str:
    """Load a prompt template and expand `{include:partial}` directives.

    A directive like ``{include:_rules_telegram_html}`` is replaced with the
    contents of ``_rules_telegram_html.md`` in the same directory. One level of
    expansion only — partials may not themselves include other partials.
    """
    raw = (PROMPTS_DIR / name).read_text(encoding="utf-8")

    def _expand(m: re.Match[str]) -> str:
        partial = (PROMPTS_DIR / f"{m.group(1)}.md").read_text(encoding="utf-8")
        return partial.rstrip()

    return _INCLUDE_RE.sub(_expand, raw)
