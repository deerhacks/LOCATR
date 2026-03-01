"""
Node 3 — The VIBE MATCHER (Qualitative Analysis)
Aesthetic reasoning engine using Gemini 1.5 Pro multimodal.
Scores each venue's vibe against the user's desired aesthetic.
"""

import asyncio
import json
import logging

from app.models.state import PathfinderState
from app.services.gemini import generate_content

logger = logging.getLogger(__name__)

_VIBE_PROMPT = """You are the PATHFINDER Vibe Matcher. You are analyzing a cafe for a {vibe_preference} vibe.

Venue: {name}
Address: {address}
Category: {category}

INPUT HANDLING:

You will receive 1-3 image descriptions or metadata.

If an image failed to load (e.g., Redirect Error or 404), do not penalize the venue. Instead, rely on the Review Sentiment provided in the text metadata.

AESTHETIC SCORING:

Score the venue from 0.0 to 1.0 based on how well it fits the "{vibe_preference}" request.

Cyberpunk Criteria: Neon lighting, high-contrast colors (pinks/purples/blues), industrial materials, tech-heavy decor.

OUTPUT:
Respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "vibe_score": <float 0.0 to 1.0, how well this venue matches the desired vibe>,
  "primary_style": "<one-word style label, e.g. cozy, minimalist, industrial, vibrant>",
  "visual_descriptors": ["<descriptor 1>", "<descriptor 2>", "<descriptor 3>"],
  "confidence": <float 0.0 to 1.0, how confident you are in this assessment>
}}
"""

_NEUTRAL_VIBE = "a welcoming, enjoyable atmosphere suitable for groups"


async def _score_venue(venue: dict, vibe_preference: str) -> dict | None:
    """Score a single venue's vibe using Gemini 2.5 Flash multimodal."""
    name = venue.get("name", "Unknown")
    photos = venue.get("photos", [])
    logger.info("[VIBE] Scoring: %r  (photos=%d, vibe_pref=%r)", name, len(photos), vibe_preference)

    prompt = _VIBE_PROMPT.format(
        name=name,
        address=venue.get("address", ""),
        category=venue.get("category", ""),
        vibe_preference=vibe_preference,
    )

    try:
        raw = await generate_content(
            prompt=prompt,
            model="gemini-2.5-flash",
            image_urls=photos if photos else None,
        )
        if not raw:
            logger.warning("[VIBE] Empty response for %r", name)
            return None

        # Strip markdown fences if Gemini wraps the JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        result = json.loads(cleaned)
        logger.info("[VIBE] %r → score=%.2f | style=%s | confidence=%.2f",
                    name,
                    result.get("vibe_score", 0),
                    result.get("primary_style", "?"),
                    result.get("confidence", 0))
        return result
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("[VIBE] Scoring failed for %r: %s", name, exc)
        return None


def vibe_matcher_node(state: PathfinderState) -> PathfinderState:
    """
    Score each candidate venue on subjective vibe / aesthetic match.

    Steps
    -----
    1. Get vibe preference from parsed_intent (or use neutral default).
    2. For each candidate, call Gemini 2.5 Flash with photos + prompt.
    3. Parse JSON response into vibe scores.
    4. Write vibe_scores dict to state.
    """
    intent = state.get("parsed_intent", {})
    vibe_pref = intent.get("vibe") or _NEUTRAL_VIBE
    candidates = state.get("candidate_venues", [])

    logger.info("\n" + "─" * 60)
    logger.info("[VIBE] ── STARTING")
    logger.info("[VIBE] vibe_preference : %r", vibe_pref)
    logger.info("[VIBE] candidates      : %d venues to score", len(candidates))

    if not candidates:
        logger.info("[VIBE] No candidates to score — skipping")
        return {"vibe_scores": {}}

    # Score all venues concurrently
    async def _score_all():
        return await asyncio.gather(*[_score_venue(v, vibe_pref) for v in candidates])

    logger.info("[VIBE] Scoring all %d venues concurrently via Gemini 2.5 Flash...", len(candidates))
    try:
        results = asyncio.run(_score_all())
    except Exception as exc:
        logger.error("[VIBE] Batch scoring failed: %s", exc)
        results = [None] * len(candidates)

    # Build vibe_scores dict keyed by venue_id and filter candidates
    vibe_scores = {}
    passed_candidates = []
    
    rejected_candidates = []
    
    for venue, result in zip(candidates, results):
        vid = venue.get("venue_id", "")
        if result:
            vibe_scores[vid] = result
            score = result.get("vibe_score", 0.5)
            
            # If the user explicitly requested a vibe (i.e. not the default neutral vibe)
            # and the score is below our threshold (0.4), filter it out.
            if vibe_pref != _NEUTRAL_VIBE and score < 0.4:
                logger.info("[VIBE] REJECTED : %s (score=%.2f < 0.4 threshold)", venue.get('name'), score)
                rejected_candidates.append((score, venue))
            else:
                logger.info("[VIBE] PASSED   : %s (score=%.2f)", venue.get('name'), score)
                passed_candidates.append(venue)
        else:
            # Graceful fallback — don't crash, just mark as unscored
            logger.info("[VIBE] UNSCORED : %s — using fallback entry", venue.get('name'))
            vibe_scores[vid] = {
                "vibe_score": None,
                "primary_style": "unknown",
                "visual_descriptors": [],
                "confidence": 0.0,
            }
            passed_candidates.append(venue)

    # Backup mechanism: ensure we pass at least 3 venues if Scout provided enough.
    rejected_candidates.sort(key=lambda x: x[0], reverse=True)
    while len(passed_candidates) < 3 and rejected_candidates:
        score, venue = rejected_candidates.pop(0)
        logger.info("[VIBE] RECOVERED: %s (score=%.2f) — restored to maintain minimum 3 options", venue.get('name'), score)
        passed_candidates.append(venue)

    scored_count = sum(1 for v in vibe_scores.values() if v.get("vibe_score") is not None)
    logger.info("[VIBE] ── DONE — scored=%d, kept=%d/%d candidates",
                scored_count, len(passed_candidates), len(candidates))
    logger.info("[VIBE] vibe_scores:\n%s", json.dumps(vibe_scores, indent=2))

    return {"vibe_scores": vibe_scores, "candidate_venues": passed_candidates}
