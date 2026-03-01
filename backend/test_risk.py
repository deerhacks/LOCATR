import os
from dotenv import load_dotenv

import snowflake.connector
import h3

load_dotenv()

conn = snowflake.connector.connect(
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    warehouse="PATHFINDER_WH",
    database="PATHFINDER_DB",
    schema="INTELLIGENCE",
    autocommit=True
)

def insert_test_risk():
    # Insert a fake risk event for Scotiabank Arena (approx 43.6435, -79.3791)
    # We need a VENUE_ID that exists in CAFE_VIBE_VECTORS to join successfully
    
    # First get a real venue to attach the risk to
    with conn.cursor() as cur:
        cur.execute("SELECT VENUE_ID, NAME FROM CAFE_VIBE_VECTORS LIMIT 1")
        res = cur.fetchone()
        if not res:
            print("No cafes in DB to attach risk to.")
            return
            
        vid, vname = res[0], res[1]
        
        # Insert risk
        query = """
        INSERT INTO VENUE_RISK_EVENTS (VENUE_NAME, VENUE_ID, RISK_DESCRIPTION, WEATHER_CONTEXT)
        VALUES (%s, %s, %s, %s)
        """
        cur.execute(query, (vname, vid, "High Crowding Risk (Event Day)", "Clear"))
        print(f"Inserted Mock Risk Event for {vname}")

insert_test_risk()
