import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv('.env.development')

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')

supabase = create_client(url, key)



try:
    response = supabase.table('users').select('*').limit(1).execute()
    print("[SUCCESS] Supabase connection successful!")
    print(f"Tables accessible: users, user_api_keys, interviews, feedback")
except Exception as e:
    print(f"[ERROR] Supabase connection failed: {e}")