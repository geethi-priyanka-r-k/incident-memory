import sqlite3

DB = "incidents.db"
KEEP_IDS = (34,)  # the taught fix

con = sqlite3.connect(DB)
cur = con.cursor()

keep_list = ",".join(str(i) for i in KEEP_IDS)
where = f"COALESCE(reported_by,'') <> 'Demo seed' AND id NOT IN ({keep_list})"

to_delete = cur.execute(
    f"SELECT id, source, substr(report,1,50) FROM incidents WHERE {where} ORDER BY id"
).fetchall()

kept = cur.execute(
    f"SELECT COUNT(*) FROM incidents WHERE NOT ({where})"
).fetchone()[0]

print("\n=== PREVIEW (nothing deleted yet) ===")
print(f"Incidents that will be KEPT: {kept}")
print(f"Incidents that will be DELETED: {len(to_delete)}")
for row in to_delete:
    print("  ", row)

if not to_delete:
    print("Nothing to delete. Done.")
    raise SystemExit

ids = [r[0] for r in to_delete]
marks = ",".join("?" for _ in ids)

# find child tables that have an incident_id column
child_tables = []
tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in tables:
    if t in ("incidents", "sqlite_sequence"):
        continue
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    if "incident_id" in cols:
        n = cur.execute(
            f"SELECT COUNT(*) FROM {t} WHERE incident_id IN ({marks})", ids
        ).fetchone()[0]
        child_tables.append(t)
        print(f"Rows in {t} that will be deleted: {n}")

answer = input("\nType YES to delete these, anything else to cancel: ")
if answer.strip() != "YES":
    print("Cancelled. Nothing was changed.")
    raise SystemExit

for t in child_tables:
    cur.execute(f"DELETE FROM {t} WHERE incident_id IN ({marks})", ids)
cur.execute(f"DELETE FROM incidents WHERE id IN ({marks})", ids)
con.commit()

print("\nDone. Rows now:")
for t in ["incidents"] + child_tables:
    n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n}")
con.close()