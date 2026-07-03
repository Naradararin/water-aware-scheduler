"""
LLM-generated explanations for scheduling decisions.

Optional layer on top of the optimizer's f-string reasoning: if
NVIDIA_NIM_API_KEY is set, ask an LLM (via NVIDIA NIM's OpenAI-compatible
endpoint) to write a fresh, complete explanation grounded in the same
numbers the optimizer already computed. If the key is missing or the API
call fails for any reason, silently fall back to the plain f-string so the
scheduler never breaks because of this optional layer.
"""

import os

from ..models import Job, SignalReading

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.1-8b-instruct"


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
    return (
        "You are explaining a compute-scheduling decision to an engineer. "
        "Write a short, plain-English explanation (2-4 sentences) of why "
        "this region/time was chosen. Use ONLY the numbers given below - "
        "do not invent facts, sources, or context not present here.\n\n"
        f"Job: {job.id} (demand={job.demand_kwh} kWh)\n"
        f"Chosen region: {best.region}\n"
        f"Chosen time: {best.timestamp}\n"
        f"Weights: alpha(carbon)={alpha}, beta(water)={beta}\n"
        f"Carbon intensity of chosen option: {best.carbon_intensity_gco2_per_kwh:.0f} gCO2/kWh "
        f"(candidates ranged {c_min:.0f}-{c_max:.0f} gCO2/kWh)\n"
        f"Water intensity of chosen option: {best.water_intensity_l_per_kwh:.2f} L/kWh "
        f"(candidates ranged {w_min:.2f}-{w_max:.2f} L/kWh)\n"
        f"Predicted totals for this job: {predicted_carbon_g:.1f} gCO2, {predicted_water_l:.2f} L"
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
            max_tokens=200,
        )
        text = response.choices[0].message.content
        if not text or not text.strip():
            raise ValueError("empty response from LLM")
        return text.strip()
    except Exception:
        print("[!] LLM reasoning call failed - falling back to plain explanation.")
        return fallback_reasoning
