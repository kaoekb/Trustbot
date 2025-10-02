import aiosqlite

DB_PATH = "state.db"

CREATE = """CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE)
        await db.commit()

async def kv_get(k: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT v FROM kv WHERE k=?", (k,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def kv_set(k: str, v: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO kv(k,v) VALUES(?,?)", (k, v))
        await db.commit()
