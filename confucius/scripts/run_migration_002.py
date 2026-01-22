import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def run_migration():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("DATABASE_URL not found")
        return

    print(f"Connecting to {db_url}")
    conn = await asyncpg.connect(db_url)
    
    migration_file = 'migrations/002_add_scheduled_workflows.sql'
    with open(migration_file, 'r') as f:
        sql = f.read()
    
    print(f"Running migration {migration_file}...")
    await conn.execute(sql)
    print("Migration successful")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
