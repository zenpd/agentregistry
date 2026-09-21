import asyncio
import os
import secrets

import asyncpg

HOST = "zaf-postgres-01.postgres.database.azure.com"
APP_USER = "agentregistry_app"


async def main():
    admin_pw = os.environ["PGADMINPW"]
    new_pw = secrets.token_urlsafe(24)

    conn = await asyncpg.connect(
        host=HOST, port=5432, user="zafadmin", password=admin_pw,
        database="postgres", ssl="require",
    )
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", APP_USER)
    if exists:
        await conn.execute(f"ALTER ROLE {APP_USER} WITH PASSWORD '{new_pw}'")
        print("ROLE_UPDATED")
    else:
        await conn.execute(f"CREATE ROLE {APP_USER} WITH LOGIN PASSWORD '{new_pw}'")
        print("ROLE_CREATED")
    await conn.close()

    conn2 = await asyncpg.connect(
        host=HOST, port=5432, user="zafadmin", password=admin_pw,
        database="agentregistry", ssl="require",
    )
    await conn2.execute(f"GRANT ALL PRIVILEGES ON DATABASE agentregistry TO {APP_USER}")
    await conn2.execute(f"GRANT ALL ON SCHEMA public TO {APP_USER}")
    await conn2.execute(f"ALTER SCHEMA public OWNER TO {APP_USER}")
    await conn2.close()

    print("PROVISIONED_OK::" + new_pw)


asyncio.run(main())
