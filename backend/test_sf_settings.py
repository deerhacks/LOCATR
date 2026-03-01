import os
import sys

# Add backend directory to sys.path for proper imports
sys.path.append(os.getcwd())

# Force environment variable loading for the test if needed,
# though Settings() should handle it.
from app.services.snowflake import get_snowflake_connection

print("--- Testing Snowflake Connection via Settings ---")
conn = get_snowflake_connection()
if conn:
    print("✅ Success! Connected to Snowflake.")
    conn.close()
else:
    print("❌ Failed to connect.")
