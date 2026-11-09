"""Load the 15 fake past incidents into Hindsight. Run once: python seed.py"""
import os

from settings import load_env, missing_message

load_env()

from hindsight_client import Hindsight
from seed_data import INCIDENTS, as_memory

BANK = os.environ.get("HINDSIGHT_BANK", "incident-memory")
missing = missing_message(("HINDSIGHT_URL", "HINDSIGHT_API_KEY"), "the seed script")
if missing:
    raise SystemExit(missing)
client = Hindsight(base_url=os.environ["HINDSIGHT_URL"], api_key=os.environ["HINDSIGHT_API_KEY"])

for i, inc in enumerate(INCIDENTS, 1):
    client.retain(bank_id=BANK, content=as_memory(inc), context="incident resolution")
    print(f"[{i}/{len(INCIDENTS)}] saved: {inc['type']} - {inc['report'][:55]}")

print("Done. Memory is seeded.")
