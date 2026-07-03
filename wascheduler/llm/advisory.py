"""
Stage 1 advisory layer for V2 "heavy" mode: LLM examines the decision
schedule_job() already made and flags whether it thinks the decision
should be reconsidered -- WITHOUT changing the decision itself.

This is deliberately non-authoritative. It's a first, cautious step
toward a possible future V2 mode where an LLM might eventually be
allowed to override scoring in narrow, guardrailed cases. Nothing here
does that yet -- advisory_reconsideration() only returns a flag + reason
for a human to look at. schedule_job()'s actual output is never read
back into or modified by this module; call it separately, after
scheduling, if you want the advisory opinion.

Why this needs its own fail-safe default (separate from reasoning.py's
guard): the fabrication guard imported below only catches one specific
known failure mode (inventing a job location). This module asks a
different kind of question ("should this be reconsidered?") and could
fail in different, not-yet-observed ways -- e.g. inventing a drought
severity that isn't in the given text, or fabricating a comparison
that doesn't match the actual numbers. Rather than write new
pattern-specific regexes for failure modes that haven't been observed
yet, this module takes the conservative default throughout: any
ambiguity, parse failure, or fabrication-guard hit collapses to
should_reconsider=False. An advisory layer that fails toward "no
concern" is far less dangerous than one that fails toward inventing a
concern -- especially as a stepping-stone toward a mode where
"reconsider" might eventually change real decisions.

DEPENDS ON: reasoning.py's _contains_fabricated_location_claim(),
NIM_BASE_URL, DEFAULT_MODEL. Written from a screenshot of that file,
not a verified upload -- confirm these names/signatures match the real
reasoning.py (as of commit 6c1b230) before trusting this import line.
"""

import os
import re

from ..models import Job, SignalReading
from ..scheduler.optimizer import _ensure_water, _normalize
from .drought_context import (
    get_drought_context_for_region,
    fetch_current_drought_bulletin,
    _REGION_COUNTRY_NAMES,
)
from .reasoning import _contains_fabricated_location_claim, NIM_BASE_URL, DEFAULT_MODEL

_RECONSIDER_PATTERN = re.compile(r"RECONSIDER:\s*(yes|no)", re.IGNORECASE)
_REASON_PATTERN = re.compile(r"REASON:\s*(.+)", re.IGNORECASE | re.DOTALL)
_DROUGHT_SEVERITY_WORDS = re.compile(r"\b(alert|warning|watch|recovery|drought)\b", re.IGNORECASE)

# Splits a sentence into finer clauses on commas/semicolons. Applied AFTER
# sentence splitting, as a fallback, because a single sentence can still
# bundle multiple unrelated clauses -- e.g. "FR is in Alert, ... compared
# to the runner-up region NO." is one sentence, but the Alert claim and
# the NO mention belong to different, unrelated clauses within it.
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT_PATTERN = re.compile(r"[,;]\s*")


def _split_into_clauses(reason_text: str) -> list:
    """
    Splits reason_text into small, independently-checkable units so
    _reason_claims_unsupported_drought_status() can require a
    drought-severity word and a region mention to co-occur in the SAME
    clause, not just anywhere in the whole reason text.

    Two-level split: sentences first (on . ! ?), then each sentence is
    further split on commas/semicolons as a fallback. Example:
    "The chosen region FR is experiencing Alert drought conditions,
    which may be exacerbated by its relatively high water usage of
    1.82 L/kWh, compared to the runner-up region NO."
    -> one sentence, three clauses:
      1. "The chosen region FR is experiencing Alert drought conditions"
      2. "which may be exacerbated by its relatively high water usage of 1.82 L/kWh"
      3. "compared to the runner-up region NO."
    Clause 1 has "FR" + "Alert" together (a real, grounded claim about
    France). Clause 3 has "NO" but no severity word at all -- naming the
    runner-up region is not a drought-severity claim about it.
    """
    sentences = _SENTENCE_SPLIT_PATTERN.split(reason_text.strip())
    clauses = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        clauses.extend(
            part.strip() for part in _CLAUSE_SPLIT_PATTERN.split(sentence) if part.strip()
        )
    return clauses


def _reason_claims_unsupported_drought_status(
    reason_text: str,
    chosen: SignalReading,
    runner_up: SignalReading,
) -> bool:
    """
    Catches a DIFFERENT fabrication pattern than
    _contains_fabricated_location_claim(): the LLM asserting a drought
    severity (Alert/Warning/etc) for a region whose name never actually
    appears in the bulletin text it was given for that region -- e.g.
    claiming "Norway is in Alert... part of the Baltic Sea regions"
    when the real bulletin never mentions Norway at all and Norway
    is not, geographically, a Baltic state. This was an observed live
    failure (not hypothetical) during Stage 1 testing.

    Approach: split the reason text into clauses (see
    _split_into_clauses) and, for each tracked region, check whether a
    drought-severity word and that region's name/code co-occur in the
    SAME clause. Only if so is the region's country name checked against
    the RAW bulletin text -- if the country isn't actually in the
    bulletin, the claim isn't grounded, regardless of how confident or
    specific-sounding the wording is.

    Clause-level (not whole-text) attribution matters: an earlier version
    of this guard checked severity-word-present-anywhere AND
    region-mentioned-anywhere independently across the whole reason text,
    which meant a completely legitimate sentence like "FR is in Alert
    drought conditions, ... compared to the runner-up region NO" got
    discarded -- NO was merely named as the comparison point, never
    claimed to be in any drought state, but the whole-text check saw
    "Alert" and "NO" both present somewhere and flagged it anyway. Scoping
    the check to individual clauses fixes that false positive while still
    catching the original Norway/Baltic case, since that fabrication put
    "NO" and "drought" together in the same clause ("The chosen region NO
    is located in a drought-affected area...").

    IMPORTANT, and the reason this doesn't take drought_ctx strings as
    parameters (an earlier version of this function did, and it was a
    no-op bug): get_drought_context_for_region()'s return value is NOT
    the raw bulletin -- it's that text wrapped in instructional prose
    that ALWAYS names the country regardless of whether the actual
    bulletin mentions it (e.g. "Check whether Norway is mentioned...
    If Norway is not mentioned by name..."). Checking containment
    against that wrapped string meant country_name.lower() was always
    found, so the guard could never fire for FR/DE/NO -- confirmed via
    fetch_current_drought_bulletin() directly: "norway" is present in
    get_drought_context_for_region("NO")'s output but NOT in the raw
    bulletin text itself. Fetching the raw bulletin here directly sidesteps
    that wrapper entirely.

    Like _contains_fabricated_location_claim, this is a targeted guard
    for an observed failure mode, not a general fabrication detector.
    """
    clauses = _split_into_clauses(reason_text)
    raw_bulletin = None  # fetched lazily, only if a candidate match is found

    for region_code in (chosen.region, runner_up.region):
        country_name = _REGION_COUNTRY_NAMES.get(region_code)
        if country_name is None:
            continue  # no source for this region at all -- separate case

        for clause in clauses:
            clause_lower = clause.lower()
            if not _DROUGHT_SEVERITY_WORDS.search(clause_lower):
                continue

            mentions_this_region = (
                country_name.lower() in clause_lower
                or region_code.lower() in clause_lower
            )
            if not mentions_this_region:
                continue

            if raw_bulletin is None:
                raw_bulletin = fetch_current_drought_bulletin() or ""
            if country_name.lower() not in raw_bulletin.lower():
                return True

    return False


def _find_runner_up(job: Job, signals: list, chosen: SignalReading, alpha: float, beta: float):
    """
    Re-derives the candidate set and scores the same way
    optimizer.py's schedule_job() does, to find the best alternative to
    the chosen candidate. Reuses optimizer.py's own _ensure_water/
    _normalize helpers so this can't silently drift from the actual
    decision logic over time.
    """
    candidates = [
        s for s in signals
        if s.region in job.candidate_regions
        and job.earliest_start <= s.timestamp <= job.deadline
    ]
    for s in candidates:
        _ensure_water(s)

    carbon_vals = [s.carbon_intensity_gco2_per_kwh for s in candidates]
    water_vals = [s.water_intensity_l_per_kwh for s in candidates]
    c_min, c_max = min(carbon_vals), max(carbon_vals)
    w_min, w_max = min(water_vals), max(water_vals)

    def score(s):
        c_score = _normalize(s.carbon_intensity_gco2_per_kwh, c_min, c_max)
        w_score = _normalize(s.water_intensity_l_per_kwh, w_min, w_max)
        return alpha * c_score + beta * w_score

    scored = sorted(candidates, key=score)
    chosen_score = score(chosen)
    # Deliberately requires a DIFFERENT region, not just a different
    # timestamp in the same region. The whole point of this advisory
    # check is comparing across regions with potentially different
    # environmental risk profiles (e.g. drought context) -- a same-region
    # runner-up at a different hour has identical drought context to the
    # chosen candidate, making the comparison uninteresting for this
    # specific question.
    runner_up = None
    for s in scored:
        if s.region != chosen.region:
            runner_up = s
            break
    runner_up_score = score(runner_up) if runner_up else None
    return runner_up, chosen_score, runner_up_score


def advisory_reconsideration(
    job: Job,
    signals: list,
    chosen: SignalReading,
    alpha: float = 0.5,
    beta: float = 0.5,
) -> dict:
    """
    Returns {"should_reconsider": bool, "reason": str, "checked": bool}.
    "checked" is False if the LLM call was skipped or failed entirely
    (no key, network error, parse failure, no runner-up to compare) --
    this distinguishes "we asked and the answer was no" from "we
    couldn't ask," which matters if you're later deciding how much to
    trust an aggregate of these flags.

    Never raises. Never modifies the actual decision in any way --
    purely advisory. Safe to call after schedule_job() has already run.
    """
    default_result = {"should_reconsider": False, "reason": "", "checked": False}

    api_key = os.environ.get("NVIDIA_NIM_API_KEY")
    if not api_key:
        default_result["reason"] = "No NVIDIA_NIM_API_KEY set -- advisory check skipped."
        return default_result

    runner_up, chosen_score, runner_up_score = _find_runner_up(job, signals, chosen, alpha, beta)
    if runner_up is None:
        default_result["reason"] = "No alternative candidate to compare against."
        return default_result

    chosen_drought = get_drought_context_for_region(chosen.region)
    runner_up_drought = get_drought_context_for_region(runner_up.region)

    prompt = (
        "A compute-scheduling optimizer already picked a region/time for a job, "
        "using only carbon and water intensity numbers (min-max normalized, "
        f"alpha(carbon)={alpha}, beta(water)={beta}). Your job is ONLY to say "
        "whether this decision is worth a second look, based SOLELY on the "
        "data given below. You are NOT authorized to change the decision -- "
        "only to flag a concern for a human to review, or say there's none.\n\n"
        f"CHOSEN: {chosen.region} at {chosen.timestamp}, "
        f"carbon={chosen.carbon_intensity_gco2_per_kwh:.0f} gCO2/kWh, "
        f"water={chosen.water_intensity_l_per_kwh:.2f} L/kWh, "
        f"combined score={chosen_score:.3f} (lower is better)\n"
        f"Drought context for {chosen.region}: {chosen_drought}\n\n"
        f"RUNNER-UP: {runner_up.region} at {runner_up.timestamp}, "
        f"carbon={runner_up.carbon_intensity_gco2_per_kwh:.0f} gCO2/kWh, "
        f"water={runner_up.water_intensity_l_per_kwh:.2f} L/kWh, "
        f"combined score={runner_up_score:.3f}\n"
        f"Drought context for {runner_up.region}: {runner_up_drought}\n\n"
        "Respond in EXACTLY this format, nothing else:\n"
        "RECONSIDER: yes or no\n"
        "REASON: one sentence, using only the numbers/context above, "
        "explicitly citing which piece of data drove your answer"
    )

    try:
        from openai import OpenAI

        client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)
        model = os.environ.get("NVIDIA_NIM_MODEL", DEFAULT_MODEL)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=150,
        )
        text = (response.choices[0].message.content or "").strip()

        reconsider_match = _RECONSIDER_PATTERN.search(text)
        reason_match = _REASON_PATTERN.search(text)
        if not reconsider_match or not reason_match:
            default_result["reason"] = (
                f"Could not parse LLM response into expected format: {text[:200]!r}"
            )
            return default_result

        reason_text = reason_match.group(1).strip()

        # Guard 1: reuse the existing fabrication guard from reasoning.py
        # (catches invented job-location claims).
        if _contains_fabricated_location_claim(reason_text):
            return {
                "should_reconsider": False,
                "reason": "Advisory response flagged by job-location fabrication guard -- discarded.",
                "checked": True,
            }

        # Guard 2: catches unsupported drought-status claims (a region
        # asserted to be in Alert/Warning/etc. whose name never actually
        # appears in the bulletin text it was given). This is the guard
        # added after Stage 1 testing caught a live case of the LLM
        # claiming Norway was in "Baltic Sea" Alert conditions when the
        # real bulletin never mentioned Norway.
        if _reason_claims_unsupported_drought_status(reason_text, chosen, runner_up):
            return {
                "should_reconsider": False,
                "reason": "Advisory response flagged by drought-status fabrication guard -- discarded.",
                "checked": True,
            }

        should_reconsider = reconsider_match.group(1).lower() == "yes"
        return {"should_reconsider": should_reconsider, "reason": reason_text, "checked": True}

    except Exception as e:
        default_result["reason"] = f"Advisory LLM call failed: {e}"
        return default_result
