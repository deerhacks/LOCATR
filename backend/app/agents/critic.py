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
import os
from app.services.snowflake import SnowflakeIntelligence

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

    top_candidates = candidates[:3]
    names = ", ".join(v.get("name", "?") for v in top_candidates)
    logger.info("[CRITIC] Risk-checking top picks: %s", names)

    if not candidates:
        return {"risk_flags": {}, "veto": False, "veto_reason": None}
    risk_flags = {}

    async def _analyze_venue(venue):
        lat = venue.get("lat")
        lng = venue.get("lng")
        venue_id = venue.get("venue_id", venue.get("name", "unknown"))
        name = venue.get("name", venue_id)

        logger.info("[CRITIC] Checking weather + events near %s...", name)

        # Parallel fetch
        weather, events = await asyncio.gather(
            get_weather(lat, lng),
            get_events(lat, lng)
        )

        condition = weather.get("condition", "unknown") if isinstance(weather, dict) else "unknown"
        n_events = len(events) if isinstance(events, list) else 0
        logger.info("[CRITIC] %s — %s, %d event%s nearby", name, condition, n_events, "s" if n_events != 1 else "")

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

        try:
            resp = await generate_content(prompt)
            if resp.startswith("```json"):
                resp = resp[7:]
            if resp.endswith("```"):
                resp = resp[:-3]

            analysis = json.loads(resp.strip())
            risks = analysis.get("risks", [])
            # ── Inject Historical Risks ── 
            # These bypass LLM hallucinations and forcefully apply risk penalties
            hist_risks = venue.get("historical_risks", [])
            for hr in hist_risks:
                risks.append({
                    "type": "historical_veto",
                    "severity": "high",
                    "detail": f"[HISTORICAL RISK] {hr}"
                })
            analysis["risks"] = risks

            logger.info("[CRITIC] %s → new_risks=%d | hist_risks=%d | fast_fail=%s%s",
                        name,
                        len(risks) - len(hist_risks),
                        len(hist_risks),
                        analysis.get("fast_fail"),
                        f" ({analysis.get('fast_fail_reason')})" if analysis.get("fast_fail") else "")
            for r in risks:
                logger.info("[CRITIC]   [%s] %s: %s", r.get("severity", "?").upper(), r.get("type", "?"), r.get("detail", ""))
            return venue_id, analysis, weather
        except Exception as e:
            logger.error("[CRITIC] Gemini call failed for %s: %s", venue_id, e)
            return venue_id, {"risks": [], "fast_fail": False, "fast_fail_reason": None}, {}

    async def _run_all():
        return await asyncio.gather(*[_analyze_venue(v) for v in top_candidates])

    # Run analysis for all top candidates
    try:
        results = asyncio.run(_run_all())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        results = asyncio.run(_run_all())

    overall_fast_fail = False
    fast_fail_reason = None

    for venue_id, analysis, weather in results:
        risk_flags[venue_id] = analysis.get("risks", [])
        if analysis.get("fast_fail") and venue_id == top_candidates[0].get("venue_id", top_candidates[0].get("name")):
            # Instead of halting the graph, log to Snowflake
            fast_fail_reason = analysis.get("fast_fail_reason")
            try:
                sf = SnowflakeIntelligence(
                    user=os.getenv('SNOWFLAKE_USER'),
                    password=os.getenv('SNOWFLAKE_PASSWORD'),
                    account=os.getenv('SNOWFLAKE_ACCOUNT')
                )
                venue_name = next((v.get("name") for v in top_candidates if v.get("venue_id", v.get("name")) == venue_id), venue_id)
                sf.log_risk_event(venue_name, venue_id, fast_fail_reason, str(weather))
                logger.info("[CRITIC] Logged veto to Snowflake for %s", venue_name)
            except Exception as e:
                logger.error("[CRITIC] Failed to log risk event to Snowflake: %s", e)

    logger.info("[CRITIC] ── DONE")
    if fast_fail_reason:
        logger.info("[CRITIC] Highest risk logged (graph proceeds): %s", fast_fail_reason)
    logger.info("[CRITIC] risk_flags:\n%s", json.dumps(risk_flags, indent=2))

    return {"risk_flags": risk_flags, "fast_fail": False, "fast_fail_reason": fast_fail_reason, "veto": False, "veto_reason": fast_fail_reason}

