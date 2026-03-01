import os
import sys
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.append(os.getcwd())

from app.services.snowflake import SnowflakeIntelligence

# Load from current dir if in backend
load_dotenv(dotenv_path='.env')

try:
    sf = SnowflakeIntelligence(
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        account=os.getenv('SNOWFLAKE_ACCOUNT')
    )

    # Mimic Scout's call for Scotiabank Arena
    venue_id = "gp_ChIJQdhOZvjL1IkR" # Example ID
    venue_name = "Scotiabank Arena"
    
    print(f"--- FETCHING RISKS FOR {venue_name} ---")
    risks = sf.get_historical_risks(venue_id, venue_name)
    print(f"Found {len(risks)} risks: {risks}")
    
    # Try lowercase to test ILIKE
    print(f"--- FETCHING RISKS FOR 'scotiabank arena' (lowercase) ---")
    risks_lc = sf.get_historical_risks(venue_id, "scotiabank arena")
    print(f"Found {len(risks_lc)} risks: {risks_lc}")

except Exception as e:
    print(f"ERROR: {e}")
