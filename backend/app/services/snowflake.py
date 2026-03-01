import snowflake.connector
import json

class SnowflakeIntelligence:
    def __init__(self, user, password, account):
        self.conn = snowflake.connector.connect(
            user=user,
            password=password,
            account=account,
            warehouse="PATHFINDER_WH",
            database="PATHFINDER_DB",
            schema="INTELLIGENCE",
            autocommit=True
        )

    def get_historical_risks(self, venue_id, venue_name):
        query = """
        SELECT RISK_DESCRIPTION
        FROM VENUE_RISK_EVENTS
        WHERE VENUE_ID = %s OR VENUE_NAME = %s
        ORDER BY VETO_TIMESTAMP DESC
        """
        with self.conn.cursor() as cur:
            try:
                cur.execute(query, (venue_id, venue_name))
                results = cur.fetchall()
                # Deduplicate exact strings in Python while preserving order
                seen = set()
                risks = []
                for row in results:
                    desc = row[0]
                    if desc and desc not in seen:
                        seen.add(desc)
                        risks.append(desc)
                return risks
            except Exception as e:
                print(f"❌ Snowflake error fetching historical risks for {venue_name}: {e}")
                return []

    def log_risk_event(self, venue_name, venue_id, description, weather):
        import uuid
        from datetime import datetime
        
        # 1. Prevent exact duplicates for this venue
        check_query = """
        SELECT 1 FROM VENUE_RISK_EVENTS
        WHERE VENUE_ID = %s AND RISK_DESCRIPTION = %s
        LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(check_query, (venue_id, description))
            if cur.fetchone() is not None:
                print(f"✅ Duplicate risk ignored for {venue_name}: {description[:30]}...")
                return

        # 2. Insert new risk event
        event_id = uuid.uuid4().hex
        veto_timestamp = datetime.utcnow()
        insert_query = """
        INSERT INTO VENUE_RISK_EVENTS (EVENT_ID, VENUE_NAME, VENUE_ID, RISK_DESCRIPTION, WEATHER_CONTEXT, VETO_TIMESTAMP)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        with self.conn.cursor() as cur:
            cur.execute(insert_query, (event_id, venue_name, venue_id, description, str(weather), veto_timestamp))

    def save_vibe_vector(self, venue_id, name, lat, lng, vector, primary_vibe):
        # 1. Ensure 'vector' is a list of exactly 50 floats
        if isinstance(vector, str):
            vector = json.loads(vector)
        if len(vector) != 50:
            vector = (vector + [0.0] * 50)[:50]

        # 2. Stringify as JSON to avoid parameter flattening
        vector_json_str = json.dumps(vector)
        
        # 3. Use SELECT with explicit type casting to prevent 'Unsupported data type TEXT' errors
        query = """
        INSERT INTO CAFE_VIBE_VECTORS (VENUE_ID, NAME, LATITUDE, LONGITUDE, H3_INDEX, VIBE_VECTOR, PRIMARY_VIBE)
        SELECT 
            %s::VARCHAR, 
            %s::VARCHAR, 
            %s::FLOAT, 
            %s::FLOAT, 
            H3_LATLNG_TO_CELL(%s::FLOAT, %s::FLOAT, 8), 
            PARSE_JSON(%s)::VECTOR(FLOAT, 50), 
            %s::VARCHAR
        """
        
        params = (venue_id, name, lat, lng, lat, lng, vector_json_str, primary_vibe)

        with self.conn.cursor() as cur:
            try:
                cur.execute(query, params)
            except Exception as e:
                print(f"❌ Snowflake error for {name}: {e}")


    # SEARCH: Find venues similar to a specific vibe
    def find_similar_vibes(self, target_vector, limit=5):
        query = """
        SELECT NAME, PRIMARY_VIBE, VECTOR_L2_DISTANCE(VIBE_VECTOR, %s::VECTOR(FLOAT, 50)) as dist
        FROM CAFE_VIBE_VECTORS
        ORDER BY dist ASC
        LIMIT %s
        """
        with self.conn.cursor() as cur:
            cur.execute(query, (target_vector, limit))
            return cur.fetchall()

    def verify_population(self):
        query = """
        SELECT 
            COUNT(*) as total_cafes,
            COUNT(DISTINCT PRIMARY_VIBE) as unique_styles,
            AVG(VECTOR_L2_NORM(VIBE_VECTOR)) as avg_vibe_intensity
        FROM CAFE_VIBE_VECTORS
    """
        with self.conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchone()
            print(f"--- 🚀 PATHFINDER DATA STATS ---")
            print(f"Total Cafes Vectorized: {res[0]}")
            print(f"Unique Aesthetic Styles: {res[1]}")
            print(f"Average Vibe Intensity: {round(res[2], 2)}")

# Call this at the very end of your main() function