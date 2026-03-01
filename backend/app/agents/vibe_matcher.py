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

VIBE_KEYWORDS = [
    "aesthetic", "cozy", "chill", "trendy", "hipster", "romantic", "classy", 
    "upscale", "fancy", "elegant", "modern", "rustic", "bohemian", "artsy", 
    "quirky", "retro", "vintage", "minimalist", "industrial", "dark academia", 
    "cottagecore", "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
    "charming", "intimate", "lively", "energetic", "fun", "exciting", "relaxing",
    "peaceful", "calm", "serene", "warm", "inviting", "atmosphere", "ambiance",
    "mood", "theme", "decor", "design", "beautiful", "pretty", "gorgeous",
    "stunning", "spacious", "unique"
]

_VIBE_PROMPT = f"""You are a spatial aesthetic analyst. Analyze the following cafe based on its reviews and photos.
Assign a score from 0.0 to 1.0 for each of the following {len(VIBE_KEYWORDS)} dimensions:
{", ".join(VIBE_KEYWORDS)}

Venue: {{name}}
Address: {{address}}
Category: {{category}}

INPUT HANDLING:

You will receive 1-3 image descriptions or metadata.

If an image failed to load (e.g., Redirect Error or 404), do not penalize the venue. Instead, rely on the Review Sentiment provided in the text metadata.

Return ONLY a JSON array of {len(VIBE_KEYWORDS)} floats in the exact order listed above.
Example: [0.9, 0.1, 0.4, ...]
"""

_NEUTRAL_VIBE = "a welcoming, enjoyable atmosphere suitable for groups"


async def _score_venue(venue: dict, vibe_preference: str) -> dict | None:
    """Score a single venue's vibe using Gemini 2.5 Flash multimodal."""
    name = venue.get("name", "Unknown")
    photos = venue.get("photos", [])
    logger.info("[VIBE] Scoring %r...", name)

    prompt = _VIBE_PROMPT.format(
        name=name,
        address=venue.get("address", ""),
        category=venue.get("category", "")
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

        # The result is now expected to be a list of 52 floats
        result = json.loads(cleaned)
        if not isinstance(result, list) or len(result) != len(VIBE_KEYWORDS):
            logger.warning("[VIBE] Expected list of %s floats, got %s of length %s", len(VIBE_KEYWORDS), type(result), len(result) if isinstance(result, list) else 0)
            return None
        
        # We will package it in a dict to match the rest of the code structure
        output = {
            "vibe_score": result[0],  # Give it a generic score for the overall filtering
            "vibe_dimensions": result,
            "primary_style": vibe_preference,
            "confidence": 1.0
        }
        
        logger.info("[VIBE] %r → scored %s dimensions", name, len(VIBE_KEYWORDS))
        return output
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

    logger.info("[VIBE] Matching vibe: %s", vibe_pref)
    logger.info("[VIBE] Scoring %d venues with Gemini...", len(candidates))

    if not candidates:
        return {"vibe_scores": {}}

    # Score all venues concurrently
    async def _score_all():
        return await asyncio.gather(*[_score_venue(v, vibe_pref) for v in candidates])
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
                rejected_candidates.append((score, venue))
            else:
                passed_candidates.append(venue)
        else:
            # Graceful fallback — don't crash, just mark as unscored
            vibe_scores[vid] = {
                "vibe_score": None,
                "vibe_dimensions": [0.0] * len(VIBE_KEYWORDS),
                "primary_style": "unknown",
                "visual_descriptors": [],
                "confidence": 0.0,
            }
            passed_candidates.append(venue)

    # Backup mechanism: ensure we pass at least 3 venues if Scout provided enough.
    rejected_candidates.sort(key=lambda x: x[0], reverse=True)
    while len(passed_candidates) < 3 and rejected_candidates:
        score, venue = rejected_candidates.pop(0)
        passed_candidates.append(venue)

    logger.info("[VIBE] Kept %d of %d venues by vibe fit", len(passed_candidates), len(candidates))

    return {"vibe_scores": vibe_scores, "candidate_venues": passed_candidates}
