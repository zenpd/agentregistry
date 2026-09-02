from api.auth import hash_password
from db.base import get_db_session
from db.models import User
import asyncio

async def reset_admin_password():
    async with get_db_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.email == "admin@airegistry.local"))
        user = result.scalar_one_or_none()
        if user:
            user.password_hash = hash_password("admin123")
            print(f"Updated password for {user.email}")
            print(f"Hash: {user.password_hash}")
        else:
            print("Admin user not found")
    print("Done")

asyncio.run(reset_admin_password())
