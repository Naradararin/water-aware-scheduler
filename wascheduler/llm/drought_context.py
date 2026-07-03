"""
Minimal RAG layer: fetch a live text source the optimizer's pure math
cannot see, and let the LLM reasoning layer (see reasoning.py) decide
whether it's relevant to a given scheduling decision.

Scope, deliberately kept small (first RAG exercise on this project):
- ONE source: European Drought Observatory (EDO)'s "current drought
  situation" bulletin (Joint Research Centre, EU). Free, public,
  text-based, updated approximately every 10 days.
  https://joint-research-centre.ec.europa.eu/european-and-global-drought-observatories/current-drought-situation-europe_en
- Covers Europe only. FR, DE, NO (three of this project's four mock
  regions) may be mentioned in it. TH is NOT covered by this source --
  see get_drought_context_for_region() below, which says so explicitly
  rather than silently returning nothing (so the LLM doesn't fall back
  on stale training-data assumptions about Thai drought conditions).
- No vector DB, no chunking, no embeddings: this fetches ONE current
  document and hands the (truncated) raw text to the LLM, which does
  its own "is this relevant" reasoning in the prompt. That's the whole
  RAG pipeline here, intentionally as small as it can be while still
  being real retrieval-augmented generation.
- Fetched ONCE per process run (module-level cache), not once per job --
  the bulletin only changes every ~10 days, so re-fetching per job would
  be wasteful and slow for no benefit.
- This is informational context for the LLM's explanation text only.
  It does NOT change schedule_job()'s actual region/time choice -- same
  constraint as the water-scarcity weighting (see water/scarcity.py).
  Making it actually change decisions would require structured,
  validated drought data feeding back into the optimizer's scoring,
  which is out of scope here.
"""

import re

try:
    import requests
except ImportError:
    requests = None

EDO_URL = (
    "https://joint-research-centre.ec.europa.eu/european-and-global-drought-observatories/"
    "current-drought-situation-europe_en"
)

# Maps this project's mock region codes to the country name to look for
# in the EDO bulletin text. TH is deliberately absent -- EDO covers
# Europe only, and get_drought_context_for_region() handles that case
# explicitly rather than falling through silently.
_REGION_COUNTRY_NAMES = {
    "FR": "France",
    "DE": "Germany",
    "NO": "Norway",
}

_MAX_BULLETIN_CHARS = 1500  # keep the prompt addition small and bounded

# Module-level cache: fetched once per process run.
_cached_bulletin_text = None
_fetch_attempted = False


def _extract_current_bulletin(full_page_text: str) -> str:
    """
    The EDO page has the current bulletin at the top, followed by a long
    "Past drought situation" archive going back over a year. We only
    want the current one -- including the archive would bloat the
    prompt with stale dates and risk the LLM citing an old bulletin as
    current.

    Heuristic, not DOM-exact: find the "Current drought situation in
    Europe" heading and the "Past drought situation" heading that
    follows it, and slice the text between them. If either anchor isn't
    found (e.g. the page gets redesigned), fall back to the first
    _MAX_BULLETIN_CHARS of the page rather than failing outright --
    still roughly right most of the time, and never crashes.

    IMPORTANT: the start_marker string appears multiple times on the real
    page -- in <title>, the meta description, and JSON-LD structured data,
    all BEFORE the actual visible body heading. Using the first occurrence
    (str.find) grabs that metadata junk instead of the real bulletin text.
    We instead anchor on end_marker (which only appears once, right after
    the real body content) and take the LAST start_marker occurrence
    before it -- that's the actual body heading, not a <head> duplicate.
    """
    start_marker = "Current drought situation in Europe"
    end_marker = "Past drought situation in Europe"

    end_idx = full_page_text.find(end_marker)
    start_idx = (
        full_page_text.rfind(start_marker, 0, end_idx)
        if end_idx != -1
        else full_page_text.rfind(start_marker)
    )

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        section = full_page_text[start_idx:end_idx]
    elif start_idx != -1:
        section = full_page_text[start_idx:start_idx + _MAX_BULLETIN_CHARS]
    else:
        section = full_page_text[:_MAX_BULLETIN_CHARS]

    # Collapse excess whitespace/newlines from HTML-to-text conversion.
    section = re.sub(r"\n{2,}", "\n", section)
    section = re.sub(r"[ \t]{2,}", " ", section)
    return section.strip()[:_MAX_BULLETIN_CHARS]


def fetch_current_drought_bulletin():
    """
    Returns the current EDO bulletin text (truncated), or None if the
    fetch/parse failed for any reason. Caches after the first call for
    the lifetime of the process -- does not refetch on subsequent calls.
    """
    global _cached_bulletin_text, _fetch_attempted

    if _fetch_attempted:
        return _cached_bulletin_text

    _fetch_attempted = True

    if requests is None:
        return None

    try:
        response = requests.get(EDO_URL, timeout=10)
        response.raise_for_status()
        # NOTE: this is a rough HTML-to-text strip, not a proper parser.
        # Good enough to feed prose into an LLM prompt; not meant for
        # anything requiring structural precision.
        text = re.sub(r"<[^>]+>", " ", response.text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        _cached_bulletin_text = _extract_current_bulletin(text)
    except Exception:
        _cached_bulletin_text = None

    return _cached_bulletin_text


def get_drought_context_for_region(region: str) -> str:
    """
    Returns a short string to append to the LLM prompt for the given
    region code. Always returns something explicit -- never empty --
    so the LLM is never left to guess whether a lack of context means
    "no drought data source" vs. "no current drought."
    """
    country_name = _REGION_COUNTRY_NAMES.get(region)

    if country_name is None:
        return (
            f"No live drought data source is integrated for region '{region}' "
            "in this project. Do not assume any drought status for it from "
            "general knowledge -- treat it as unknown."
        )

    bulletin = fetch_current_drought_bulletin()
    if bulletin is None:
        return (
            f"A European Drought Observatory bulletin lookup for {country_name} "
            "was attempted but failed (network error or page unavailable). "
            "Treat drought status as unknown, not as 'no drought.'"
        )

    return (
        f"Current European Drought Observatory bulletin excerpt (source: "
        f"EU Joint Research Centre, updated approx. every 10 days). Check "
        f"whether {country_name} is mentioned and, if so, in which drought "
        f"category (Alert/Warning/Watch/Recovery/Normal). If {country_name} "
        f"is not mentioned by name, do not assume drought status either way "
        f"-- just note that this bulletin doesn't call it out specifically."
        f"\n\n---\n{bulletin}\n---"
    )
