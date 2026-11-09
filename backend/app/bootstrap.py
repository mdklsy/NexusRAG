"""首次启动初始化：创建管理员账号。幂等，可重复执行。"""

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_session
from app.models.platform import User

logger = logging.getLogger(__name__)


async def bootstrap() -> None:
    s = get_settings()
    async with get_session() as session:
        existing = await session.execute(select(User).where(User.email == s.admin_email))
        if existing.scalar_one_or_none() is None:
            session.add(
                User(
                    email=s.admin_email,
                    name="Admin",
                    hashed_password=hash_password(s.admin_password),
                    is_admin=True,
                )
            )
            await session.commit()
            logger.info("Bootstrap: admin user created (%s)", s.admin_email)
        else:
            logger.info("Bootstrap: admin user exists, skip")


if __name__ == "__main__":
    import asyncio

    asyncio.run(bootstrap())
