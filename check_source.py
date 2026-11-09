import sqlite3
c = sqlite3.connect("incidents.db")
for row in c.execute("select source, count(*) from incidents group by source"):
    print(row)