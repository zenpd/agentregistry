import sqlite3

conn = sqlite3.connect('data/airegistry.db')
c = conn.cursor()
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("Tables:", [t[0] for t in tables])
for t in tables:
    tname = t[0]
    if not tname.startswith('sqlite_') and not tname.startswith('alembic'):
        count = c.execute(f'SELECT COUNT(*) FROM {tname}').fetchone()[0]
        print(f'  {tname}: {count} rows')
        if count > 0 and tname in ('agents', 'users', 'governance_reviews'):
            cols = [col[1] for col in c.execute(f'PRAGMA table_info({tname})').fetchall()]
            print(f'    columns: {cols}')
            samples = c.execute(f'SELECT * FROM {tname} LIMIT 2').fetchall()
            for s in samples:
                print(f'    sample: {s}')
conn.close()
