"""
LLM-generated explanations for scheduling decisions.

Optional layer on top of the optimizer's f-string reasoning: if
NVIDIA_NIM_API_KEY is set, ask an LLM (via NVIDIA NIM's OpenAI-compatible
endpoint) to write a fresh, complete explanation grounded in the same
numbers the optimizer already computed. If the key is missing or the API
call fails for any reason, silently fall back to the plain f-string so the
scheduler never breaks because of this optional layer.

Also pulls in a small amount of retrieval-augmented context (see
drought_context.py) — a live text source the optimizer's min-max scoring
cannot see, for the LLM to mention if relevant. This does NOT change the
scheduling decision itself, same constraint as water/scarcity.py: it can
only change what the explanation SAYS, never which region/time was
already chosen by schedule_job()'s scoring.
"""

import os
import re

from ..models import Job, SignalReading
from .drought_context import get_drought_context_for_region

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.1-8b-instruct"

# Observed failure mode (meta/llama-3.1-8b-instruct, temperature=0.2): the
# model sometimes invents a "job location" -- e.g. "chosen because it's
# located in the same area as the job's demand" -- even though Job (see
# models.py) has no location/origin field and the prompt never mentions
# one. Caught twice independently on the same prompt shape (single-
# candidate NO region), so this is a real, recurring pattern, not a
# one-off. The prompt now explicitly forbids it (see _build_prompt), but
# an 8B model won't reliably honor that -- so this regex is a deterministic
# backstop: if the response still claims the job has a location/origin/home
# region, treat it the same as any other generation failure and fall back
# to the plain f-string rather than ship a fabricated claim.
#
# SCOPE -- READ BEFORE RELYING ON THIS FOR ANYTHING ELSE: this is a
# targeted backstop for the SPECIFIC "job has a location" fabrication
# pattern observed so far. It is NOT a general hallucination detector.
# An LLM can invent ungrounded claims in countless other phrasings (wrong
# numbers stated as fact, invented comparisons, fabricated reasoning about
# the drought context, confident-sounding nonsense unrelated to location)
# and none of those would match these patterns or be caught here. Don't
# read "passes this check" as "this response is grounded" -- it only means
# this one known failure mode wasn't detected in this specific phrasing.
_FABRICATED_LOCATION_PATTERNS = [
    re.compile(r"\bjob(?:'s)?\s+(?:demand\s+)?is\s+located\b", re.IGNORECASE),
    re.compile(r"\blocated\s+in\s+the\s+same\s+area\b", re.IGNORECASE),
    re.compile(r"\bwhere\s+the\s+job(?:'s)?\s+(?:demand\s+)?is\s+located\b", re.IGNORECASE),
    re.compile(r"\b(?:home|origin)\s+(?:region|location)\b", re.IGNORECASE),
]


def _contains_fabricated_location_claim(text: str) -> bool:
    return any(pattern.search(text) for pattern in _FABRICATED_LOCATION_PATTERNS)


def _build_prompt(
    job: Job,
    best: SignalReading,
    alpha: float,
    beta: float,
    c_min: float,
    c_max: float,
    w_min: float,
    w_max: float,
) -> str:
    predicted_carbon_g = best.carbon_intensity_gco2_per_kwh * job.demand_kwh
    predicted_water_l = best.water_intensity_l_per_kwh * job.demand_kwh
    drought_context = get_drought_context_for_region(best.region)
    return (
        "You are explaining a compute-scheduling decision to an engineer. "
        "Write a short, plain-English explanation (2-4 sentences) of why "
        "this region/time was chosen. Use ONLY the numbers given below - "
        "do not invent facts, sources, or context not present here. In "
        "particular: this job has NO location, origin, or home region in "
        "this data. 'Candidate regions' are simply grid options being "
        "compared for where to RUN the job -- never say the job 'is "
        "located' in a region, 'comes from' one, or has a 'home region'; "
        "explain the choice using only the carbon/water numbers below.\n\n"
        f"Job: {job.id} (demand={job.demand_kwh} kWh)\n"
        f"Chosen region: {best.region}\n"
        f"Chosen time: {best.timestamp}\n"
        f"Weights: alpha(carbon)={alpha}, beta(water)={beta}\n"
        f"Carbon intensity of chosen option: {best.carbon_intensity_gco2_per_kwh:.0f} gCO2/kWh "
        f"(candidates ranged {c_min:.0f}-{c_max:.0f} gCO2/kWh)\n"
        f"Water intensity of chosen option: {best.water_intensity_l_per_kwh:.2f} L/kWh "
        f"(candidates ranged {w_min:.2f}-{w_max:.2f} L/kWh)\n"
        f"Predicted totals for this job: {predicted_carbon_g:.1f} gCO2, {predicted_water_l:.2f} L\n\n"
        "Additional context (may or may not be relevant to this specific "
        "decision - the scheduling choice above was already made by the "
        "numbers alone, before this context was added; only mention this "
        "context if it's genuinely relevant, and be explicit that it did "
        "NOT factor into the actual decision, only into this explanation):\n"
        f"{drought_context}"
    )


def generate_reasoning_llm(
    job: Job,
    best: SignalReading,
    alpha: float,
    beta: float,
    c_min: float,
    c_max: float,
    w_min: float,
    w_max: float,
    fallback_reasoning: str,
) -> str:
    api_key = os.environ.get("NVIDIA_NIM_API_KEY")
    if not api_key:
        return fallback_reasoning

    try:
        from openai import OpenAI

        client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)
        model = os.environ.get("NVIDIA_NIM_MODEL", DEFAULT_MODEL)
        prompt = _build_prompt(job, best, alpha, beta, c_min, c_max, w_min, w_max)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=250,
        )
        text = response.choices[0].message.content
        if not text or not text.strip():
            raise ValueError("empty response from LLM")
        text = text.strip()
        if _contains_fabricated_location_claim(text):
            print(
                "[!] LLM reasoning invented a job location/origin not present "
                "in the prompt data - falling back to plain explanation."
            )
            return fallback_reasoning
        return text
    except Exception:
        print("[!] LLM reasoning call failed - falling back to plain explanation.")
        return fallback_reasoning
