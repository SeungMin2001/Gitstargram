import json
from datetime import datetime, timedelta, timezone

import httpx
from redis.asyncio import Redis
from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .github import GitHubClient, GitHubError, expiry_from_seconds, parse_time, refresh_access_token
from .models import (
    GitHubAccount,
    Repository,
    RepositoryEmbedding,
    RepositorySnapshot,
    SyncJob,
    User,
    UserRepository,
    utcnow,
)
from .recommend import content_hash_for_repo, repository_embedding_text
from .security import decrypt, encrypt


async def enqueue_sync(db: AsyncSession, user_id: int) -> int:
    job = SyncJob(user_id=user_id, status="queued")
    db.add(job)
    await db.flush()
    job_id = job.id
    await db.commit()
    redis = Redis.from_url(settings().redis_url)
    try:
        await redis.lpush("github_sync", json.dumps({"job_id": job_id}))
    except Exception as exc:
        job.status = "failed"
        job.detail = "Queue unavailable"
        await db.commit()
        raise RuntimeError("Sync queue unavailable") from exc
    finally:
        await redis.aclose()
    return job_id


def repository_values(item: dict) -> dict:
    return {
        "id": item["id"],
        "owner_github_id": item["owner"]["id"],
        "owner_login": item["owner"]["login"],
        "name": item["name"],
        "full_name": item["full_name"],
        "description": item.get("description"),
        "html_url": item["html_url"],
        "language": item.get("language"),
        "topics": item.get("topics") or [],
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "pushed_at": parse_time(item.get("pushed_at")),
        "github_updated_at": parse_time(item.get("updated_at")),
        "fetched_at": utcnow(),
        "source": "github_rest",
        "is_public": item.get("visibility", "public") == "public" and not item.get("private", False),
    }


async def upsert_repositories(db: AsyncSession, items: list[dict]) -> None:
    now = utcnow()
    seen_ids: set[int] = set()
    for item in items:
        values = repository_values(item)
        if not values["is_public"] or values["id"] in seen_ids:
            continue
        seen_ids.add(values["id"])
        statement = insert(Repository).values(**values)
        statement = statement.on_conflict_do_update(index_elements=[Repository.id], set_=values)
        await db.execute(statement)

        latest_snap = await db.scalar(
            select(RepositorySnapshot)
            .where(RepositorySnapshot.repository_id == values["id"])
            .order_by(desc(RepositorySnapshot.captured_at))
            .limit(1)
        )
        if (
            not latest_snap
            or latest_snap.stars != values["stars"]
            or latest_snap.captured_at < now - timedelta(hours=6)
        ):
            db.add(
                RepositorySnapshot(
                    repository_id=values["id"],
                    stars=values["stars"],
                    forks=values["forks"],
                    captured_at=now,
                )
            )


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if not texts:
        return []
    cfg = settings()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{cfg.embedding_base_url.rstrip('/')}/embeddings",
                json={"model": cfg.embedding_model_name, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
            data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
            vectors = [row["embedding"] for row in data if isinstance(row.get("embedding"), list)]
            if len(vectors) != len(texts):
                return None
            return vectors
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def sync_repository_embeddings(db: AsyncSession, limit: int = 32) -> int:
    cfg = settings()
    repos = list(
        await db.scalars(
            select(Repository)
            .where(Repository.is_public.is_(True))
            .order_by(desc(Repository.fetched_at))
            .limit(limit * 2)
        )
    )
    if not repos:
        return 0
    existing = {
        row.repository_id: row
        for row in await db.scalars(
            select(RepositoryEmbedding).where(
                RepositoryEmbedding.repository_id.in_([r.id for r in repos])
            )
        )
    }
    pending: list[tuple[Repository, str, str]] = []
    for repo in repos:
        content_hash = content_hash_for_repo(repo)
        current = existing.get(repo.id)
        if current and current.content_hash == content_hash and current.model_name == cfg.embedding_model_name:
            continue
        pending.append((repo, content_hash, repository_embedding_text(repo)))
        if len(pending) >= limit:
            break
    if not pending:
        return 0
    vectors = await embed_texts([row[2] for row in pending])
    if not vectors:
        return 0
    now = utcnow()
    for (repo, content_hash, _), vec in zip(pending, vectors):
        if len(vec) != cfg.embedding_dimensions:
            continue
        stmt = insert(RepositoryEmbedding).values(
            repository_id=repo.id,
            model_name=cfg.embedding_model_name,
            dimensions=len(vec),
            content_hash=content_hash,
            embedding=vec,
            created_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RepositoryEmbedding.repository_id],
            set={
                "model_name": cfg.embedding_model_name,
                "dimensions": len(vec),
                "content_hash": content_hash,
                "embedding": vec,
                "created_at": now,
            },
        )
        await db.execute(stmt)
    await db.commit()
    return len(pending)


async def get_valid_token(db: AsyncSession, user_id: int) -> str:
    account = await db.get(GitHubAccount, user_id)
    if not account:
        raise GitHubError("GitHub account disconnected")
    now = datetime.now(timezone.utc)
    if account.token_expires_at and account.token_expires_at <= now + timedelta(minutes=5):
        if not account.refresh_token:
            raise GitHubError("GitHub token expired; reconnect account")
        data = await refresh_access_token(decrypt(account.refresh_token))
        account.encrypted_token = encrypt(data["access_token"])
        account.token_expires_at = expiry_from_seconds(data.get("expires_in"))
        if data.get("refresh_token"):
            account.refresh_token = encrypt(data["refresh_token"])
            account.refresh_token_expires_at = expiry_from_seconds(data.get("refresh_token_expires_in"))
        account.updated_at = utcnow()
        await db.commit()
    return decrypt(account.encrypted_token)


async def run_sync(db: AsyncSession, job_id: int) -> None:
    job = await db.get(SyncJob, job_id)
    if not job or job.status != "queued":
        return
    job.status = "running"
    job.started_at = utcnow()
    await db.commit()
    try:
        token = await get_valid_token(db, job.user_id)
        async with GitHubClient(token) as github:
            profile = await github.get("/user")
            owned = await github.pages("/user/repos", {"visibility": "public", "affiliation": "owner", "sort": "updated"})
            starred = await github.pages("/user/starred", {"sort": "created"})
            interests = list(dict.fromkeys(
                [repo.get("language") for repo in starred + owned if repo.get("language")]
                + [topic for repo in starred for topic in repo.get("topics", [])]
            ))[:3]
            discovered: list[dict] = []
            for interest in interests:
                result = await github.get("/search/repositories", {"q": f"{interest} in:name,description,topics stars:>=5", "sort": "updated", "per_page": 30})
                discovered.extend(result.get("items", []))
        user = await db.get(User, job.user_id)
        user.login = profile["login"]
        user.name = profile.get("name")
        user.avatar_url = profile.get("avatar_url")
        user.bio = profile.get("bio")
        user.html_url = profile["html_url"]
        user.public_repos = profile.get("public_repos", 0)
        user.followers = profile.get("followers", 0)
        user.following = profile.get("following", 0)
        user.updated_at = utcnow()
        await upsert_repositories(db, owned + starred + discovered)
        await db.execute(delete(UserRepository).where(UserRepository.user_id == user.id))
        for kind, repos in (("owned", owned), ("starred", starred)):
            seen: set[int] = set()
            for repo in repos:
                if repo.get("private", False) or repo["id"] in seen:
                    continue
                seen.add(repo["id"])
                db.add(UserRepository(user_id=user.id, repository_id=repo["id"], kind=kind))
        embedded_count = await sync_repository_embeddings(db, limit=32)
        owned_note = " (reached 1,000-item pagination cap)" if len(owned) >= 1000 else ""
        starred_note = " (reached 1,000-item pagination cap)" if len(starred) >= 1000 else ""
        job.status = "complete"
        job.detail = (
            f"{len(owned)} owned{owned_note}, {len(starred)} starred{starred_note}, "
            f"{len(discovered)} discovery results, {embedded_count} embeddings updated"
        )
        job.completed_at = utcnow()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        job = await db.get(SyncJob, job_id)
        job.status = "failed"
        job.detail = str(exc)[:300]
        job.completed_at = utcnow()
        await db.commit()
