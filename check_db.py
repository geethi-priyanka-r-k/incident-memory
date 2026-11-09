import sqlite3

c = sqlite3.connect("incidents.db")

tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
print("Tables:", tables)

for t in tables:
    count = c.execute(f"select count(*) from {t}").fetchone()[0]
    print(f"  {t}: {count} rows")