import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.vibe_matcher import _score_venue, _NEUTRAL_VIBE
from app.services.google_places import search_places

async def main():
    venues = await search_places(query="cafe", location="Downtown Toronto", max_results=2)
    for v in venues:
        print(f"Scoring {v.get('name')}...")
        res = await _score_venue(v, _NEUTRAL_VIBE)
        if res:
            dims = res.get("vibe_dimensions", [])
            print(f"Dims length: {len(dims)}")
            if len(dims) == 50:
                sf = SnowflakeIntelligence(
                    os.getenv("SNOWFLAKE_USER"),
                    os.getenv("SNOWFLAKE_PASSWORD"),
                    os.getenv("SNOWFLAKE_ACCOUNT")
                )
                try:
                    sf.save_vibe_vector(
                        venue_id=v.get("venue_id"),
                        name=v.get("name"),
                        lat=v.get("lat"),
                        lng=v.get("lng"),
                        vector=dims,
                        primary_vibe=res.get("primary_style", "unknown")
                    )
                    print("Successfully saved to Snowflake")
                except Exception as e:
                    print(f"Error saving: {e}")
        print("---")

asyncio.run(main())
