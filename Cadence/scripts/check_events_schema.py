import sqlite3
con = sqlite3.connect(r'C:\Revive\Cadence\data\revive.db')
for r in con.execute("PRAGMA table_info(events)").fetchall():
    print(r)
print('---')
for r in con.execute("SELECT * FROM events LIMIT 1").fetchall():
    print(r)
