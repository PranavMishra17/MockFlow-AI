"""
Compatibility shim — re-exports the new Neon-backed `db_client` under the
legacy name `supabase_client`. Lets `agent.py` and `agent_worker.py` keep
their existing imports during the migration. Delete this file once those
two callers have been moved to `from db import db_client`.
"""

from db import db_client as supabase_client  # noqa: F401
from db import DB as SupabaseClient  # noqa: F401
