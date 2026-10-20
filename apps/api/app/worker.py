import asyncio
import json
import logging

from redis.asyncio import Redis

from .config import settings
from .database import SessionLocal
from .sync import run_sync


logging.basicConfig(level=logging.INFO)


async def main() -> None:
    redis = Redis.from_url(settings().redis_url)
    try:
        while True:
            item = await redis.brpop("github_sync", timeout=5)
            if item is None:
                continue
            job_id = json.loads(item[1])["job_id"]
            async with SessionLocal() as db:
                await run_sync(db, job_id)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())

