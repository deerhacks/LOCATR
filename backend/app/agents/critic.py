"""
Node 6 — The CRITIC (Adversarial)
Actively tries to break the plan with real-world risk checks.
Model: Gemini (Adversarial Reasoning)
Tools: OpenWeather API, PredictHQ
"""

import json
import logging
import asyncio

from app.models.state import PathfinderState
from app.services.openweather import get_weather
from app.services.predicthq import get_events
from app.services.gemini import generate_content

logger = logging.getLogger(__name__)


def critic_node(state: PathfinderState) -> PathfinderState:
    """
    Cross-reference top venues with real-world risks.

    Steps
    -----
    1. Fetch weather forecast via OpenWeather API.
    2. Fetch upcoming events / road closures via PredictHQ.
    3. Identify dealbreakers (rain-prone parks, marathon routes, …).
    4. If critical: set veto = True → triggers Commander retry.
    5. Return updated state with risk_flags, veto, veto_reason.
    """
    candidates = state.get("candidate_venues", [])

    logger.info("\n" + "─" * 60)
    logger.info("[CRITIC] ── STARTING")
    logger.info("[CRITIC] total candidates : %d  (evaluating top 3)", len(candidates))

    if not candidates:
        logger.info("[CRITIC] No candidates to evaluate — skipping")
        return {"risk_flags": {}, "veto": False, "veto_reason": None}

    # Evaluate the top 3 candidates (to save time/tokens)
    top_candidates = candidates[:3]
    logger.info("[CRITIC] venues under review: %s", [v.get("name") for v in top_candidates])
    risk_flags = {}

    async def _analyze_venue(venue):
        lat = venue.get("lat")
        lng = venue.get("lng")
        venue_id = venue.get("venue_id", venue.get("name", "unknown"))
        name = venue.get("name", venue_id)

        logger.info("[CRITIC] Fetching weather + events for: %s (lat=%.4f, lng=%.4f)", name, lat or 0, lng or 0)

        # Parallel fetch
        weather, events = await asyncio.gather(
            get_weather(lat, lng),
            get_events(lat, lng)
        )

        logger.info("[CRITIC] %s — weather: %s | events nearby: %d",
                    name,
                    weather.get("condition", "unknown") if isinstance(weather, dict) else str(weather)[:60],
                    len(events) if isinstance(events, list) else 0)

        # Prepare context for Gemini
        context = {
            "name": name,
            "category": venue.get("category"),
            "intent": state.get("parsed_intent", {}),
            "weather": weather,
            "events": events
        }

        prompt = f"""
        You are the PATHFINDER Critic Agent. Your job is to find reasons why this plan is TERRIBLE.
        Look for dealbreakers that would ruin the experience.

        Context:
        User Intent: {json.dumps(context['intent'])}
        Venue: {context['name']} ({context['category']})
        Weather Profile: {json.dumps(context['weather'])}
        Upcoming Events Nearby: {json.dumps(context['events'])}

        Evaluate the venue against Fast-Fail Conditions:
        - Condition A: Are there fewer than 3 viable venues after risk filtering? (Assume no for a single venue unless the user intent is extremely strict and this venue wildly misses it alongside weather/event risks).
        - Condition B: Is there a Top Candidate Veto? (e.g., outdoor activity + heavy rain, traffic jam due to a marathon blocking access).

        If either condition is met, trigger a fast-fail.

        Output exact JSON:
        {{
            "risks": [
                {{"type": "weather", "severity": "high/medium/low", "detail": "explanation"}}
            ],
            "fast_fail": true/false,
            "fast_fail_reason": "if true, short reason for early termination"
        }}
        """

        logger.info("[CRITIC] Calling Gemini for risk assessment on: %s", name)
        try:
            resp = await generate_content(prompt)
            if resp.startswith("```json"):
                resp = resp[7:]
            if resp.endswith("```"):
                resp = resp[:-3]

            analysis = json.loads(resp.strip())
            risks = analysis.get("risks", [])
            logger.info("[CRITIC] %s → risks=%d | fast_fail=%s%s",
                        name,
                        len(risks),
                        analysis.get("fast_fail"),
                        f" ({analysis.get('fast_fail_reason')})" if analysis.get("fast_fail") else "")
            for r in risks:
                logger.info("[CRITIC]   [%s] %s: %s", r.get("severity", "?").upper(), r.get("type", "?"), r.get("detail", ""))
            return venue_id, analysis
        except Exception as e:
            logger.error("[CRITIC] Gemini call failed for %s: %s", venue_id, e)
            return venue_id, {"risks": [], "fast_fail": False, "fast_fail_reason": None}

    async def _run_all():
        return await asyncio.gather(*[_analyze_venue(v) for v in top_candidates])

    # Run analysis for all top candidates
    logger.info("[CRITIC] Running risk analysis concurrently for %d venues...", len(top_candidates))
    try:
        results = asyncio.run(_run_all())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        results = asyncio.run(_run_all())

    overall_fast_fail = False
    fast_fail_reason = None

    for venue_id, analysis in results:
        risk_flags[venue_id] = analysis.get("risks", [])
        if analysis.get("fast_fail") and venue_id == top_candidates[0].get("venue_id", top_candidates[0].get("name")):
            overall_fast_fail = True
            fast_fail_reason = analysis.get("fast_fail_reason")

    logger.info("[CRITIC] ── DONE — fast_fail=%s", overall_fast_fail)
    if fast_fail_reason:
        logger.info("[CRITIC] fast_fail_reason: %s", fast_fail_reason)
    logger.info("[CRITIC] risk_flags:\n%s", json.dumps(risk_flags, indent=2))

    return {"risk_flags": risk_flags, "fast_fail": overall_fast_fail, "fast_fail_reason": fast_fail_reason, "veto": overall_fast_fail, "veto_reason": fast_fail_reason}

