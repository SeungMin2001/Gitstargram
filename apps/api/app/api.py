import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import session_scope
from .github import GitHubClient, GitHubError
from .models import (
    Bookmark,
    Follow,
    Interaction,
    Post,
    RecommendationImpression,
    Repository,
    RepositoryEmbedding,
    RepositorySnapshot,
    SyncJob,
    User,
    UserRepository,
    UserSetting,
)
from .recommend import (
    ALGORITHM_VERSION,
    HYBRID_ALGORITHM_VERSION,
    average_vector,
    cosine_similarity,
    diversify_ranked,
    interest_weights,
    score_repository,
)
from .security import current_user, require_same_origin
from .repository_details import repository_detail
from .sync import embed_texts, enqueue_sync, get_valid_token, sync_repository_embeddings, upsert_repositories


router = APIRouter(prefix="/api", tags=["data"])

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "ai-ml": {"ai", "ml", "llm", "rag", "agent", "agents", "deep-learning", "machine-learning", "pytorch", "transformers", "vllm", "openai"},
    "frontend": {"react", "nextjs", "vue", "svelte", "typescript", "javascript", "css", "tailwind", "ui", "frontend", "web"},
    "backend": {"fastapi", "django", "flask", "go", "rust", "java", "spring", "postgresql", "redis", "graphql", "api", "backend"},
    "devops-tools": {"docker", "kubernetes", "terraform", "cli", "terminal", "devops", "linux", "ci", "monitoring", "git"},
}


def user_json(user: User, sns_stats: dict | None = None) -> dict:
    base = {
        "id": user.id,
        "github_id": user.github_id,
        "login": user.login,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "html_url": user.html_url,
        "public_repos": user.public_repos,
        "followers": user.followers,
        "following": user.following,
        "updated_at": user.updated_at,
    }
    if sns_stats:
        base.update(sns_stats)
    return base


def repo_json(repo: Repository) -> dict:
    return {
        "id": repo.id,
        "owner_login": repo.owner_login,
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description,
        "html_url": repo.html_url,
        "language": repo.language,
        "topics": repo.topics,
        "stars": repo.stars,
        "forks": repo.forks,
        "pushed_at": repo.pushed_at,
        "fetched_at": repo.fetched_at,
        "source": repo.source,
    }


def matches_category(repo: Repository, category: str | None) -> bool:
    if not category or category == "all":
        return True
    keywords = CATEGORY_KEYWORDS.get(category)
    if not keywords:
        return True
    tokens = set(t.lower() for t in (repo.topics or []))
    if repo.language:
        tokens.add(repo.language.lower())
    desc_text = (repo.description or "").lower()
    return bool(tokens & keywords) or any(k in desc_text for k in keywords)


@router.get("/me")
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    sns_followers = int(
        await db.scalar(select(func.count()).select_from(Follow).where(Follow.following_id == user.id)) or 0
    )
    sns_following = int(
        await db.scalar(select(func.count()).select_from(Follow).where(Follow.follower_id == user.id)) or 0
    )
    sns_posts = int(
        await db.scalar(select(func.count()).select_from(Post).where(Post.author_id == user.id)) or 0
    )
    sns_bookmarks = int(
        await db.scalar(select(func.count()).select_from(Bookmark).where(Bookmark.user_id == user.id)) or 0
    )
    return user_json(
        user,
        {
            "sns_followers": sns_followers,
            "sns_following": sns_following,
            "sns_posts": sns_posts,
            "sns_bookmarks": sns_bookmarks,
        },
    )


@router.get("/sync/status")
async def sync_status(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    job = await db.scalar(select(SyncJob).where(SyncJob.user_id == user.id).order_by(desc(SyncJob.id)).limit(1))
    embedded_total = int(
        await db.scalar(select(func.count()).select_from(RepositoryEmbedding)) or 0
    )
    if not job:
        return {"status": "never", "detail": None, "embedded_repositories": embedded_total}
    return {
        "id": job.id,
        "status": job.status,
        "detail": job.detail,
        "completed_at": job.completed_at,
        "embedded_repositories": embedded_total,
    }


@router.post("/sync", dependencies=[Depends(require_same_origin)])
async def sync_now(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    active = await db.scalar(
        select(SyncJob)
        .where(SyncJob.user_id == user.id, SyncJob.status.in_(["queued", "running"]))
        .order_by(desc(SyncJob.id))
        .limit(1)
    )
    if active:
        return {"job_id": active.id, "status": active.status}
    try:
        job_id = await enqueue_sync(db, user.id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"job_id": job_id, "status": "queued"}


@router.post("/embeddings/sync", dependencies=[Depends(require_same_origin)])
async def trigger_embedding_sync(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    updated = await sync_repository_embeddings(db, limit=32)
    total = int(await db.scalar(select(func.count()).select_from(RepositoryEmbedding)) or 0)
    return {"updated": updated, "total_embedded": total}


@router.get("/repositories")
async def my_repositories(
    kind: str = Query(pattern="^(owned|starred)$"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    rows = await db.scalars(
        select(Repository)
        .join(UserRepository)
        .where(UserRepository.user_id == user.id, UserRepository.kind == kind, Repository.is_public.is_(True))
        .order_by(desc(Repository.pushed_at))
        .limit(100)
    )
    return {"items": [repo_json(repo) for repo in rows], "kind": kind}


@router.get("/repositories/{repository_id}")
async def get_repository_detail(repository_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    repo = await db.get(Repository, repository_id)
    if not repo or not repo.is_public:
        raise HTTPException(404, "Public repository not found")
    try:
        token = await get_valid_token(db, user.id)
        async with GitHubClient(token) as github:
            return await repository_detail(github, repo)
    except GitHubError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/explore")
async def explore(
    mode: str = Query("for-you", pattern="^(for-you|trending|following)$"),
    category: str = Query("all", pattern="^(all|ai-ml|frontend|backend|devops-tools)$"),
    language: str | None = Query(None, max_length=50),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    setting = await db.get(UserSetting, user.id)
    effective_mode = mode
    if setting and not setting.personalized_recommendations and mode == "for-you":
        effective_mode = "trending"

    starred = list(
        await db.scalars(
            select(Repository)
            .join(UserRepository)
            .where(UserRepository.user_id == user.id, UserRepository.kind == "starred")
            .limit(1000)
        )
    )
    clicked_ids = list(
        await db.scalars(
            select(Interaction.repository_id)
            .where(Interaction.user_id == user.id, Interaction.action.in_(["click", "bookmark"]))
            .order_by(desc(Interaction.created_at))
            .limit(100)
        )
    )
    clicked_repos = (
        list(await db.scalars(select(Repository).where(Repository.id.in_(clicked_ids)))) if clicked_ids else []
    )
    interests = interest_weights(starred, clicked_repos)
    if not interests:
        owned = list(
            await db.scalars(
                select(Repository)
                .join(UserRepository)
                .where(UserRepository.user_id == user.id, UserRepository.kind == "owned")
                .limit(1000)
            )
        )
        interests = interest_weights(owned, clicked_repos)

    followed_logins = set(
        login.lower()
        for login in await db.scalars(
            select(User.login).join(Follow, Follow.following_id == User.id).where(Follow.follower_id == user.id)
        )
    )

    repos = list(
        await db.scalars(
            select(Repository).where(Repository.is_public.is_(True)).order_by(desc(Repository.fetched_at)).limit(1000)
        )
    )
    repo_ids = [r.id for r in repos]
    embedding_map: dict[int, list[float]] = {}
    if repo_ids:
        emb_rows = await db.scalars(
            select(RepositoryEmbedding).where(RepositoryEmbedding.repository_id.in_(repo_ids))
        )
        for row in emb_rows:
            embedding_map[row.repository_id] = list(row.embedding)

    positive_seed_ids = [r.id for r in (starred or clicked_repos)]
    seed_vectors = [embedding_map[rid] for rid in positive_seed_ids if rid in embedding_map]
    user_vector = average_vector(seed_vectors)

    snapshot_deltas: dict[int, int] = {}
    if repo_ids and effective_mode == "trending":
        snaps = list(
            await db.scalars(
                select(RepositorySnapshot)
                .where(RepositorySnapshot.repository_id.in_(repo_ids))
                .order_by(RepositorySnapshot.repository_id, RepositorySnapshot.captured_at)
            )
        )
        first_stars: dict[int, int] = {}
        last_stars: dict[int, int] = {}
        snap_counts: dict[int, int] = {}
        for s in snaps:
            if s.repository_id not in first_stars:
                first_stars[s.repository_id] = s.stars
            last_stars[s.repository_id] = s.stars
            snap_counts[s.repository_id] = snap_counts.get(s.repository_id, 0) + 1
        for rid, count in snap_counts.items():
            if count >= 2:
                snapshot_deltas[rid] = max(last_stars[rid] - first_stars[rid], 0)

    starred_ids = {repo.id for repo in starred}
    dismissed_ids = set(
        await db.scalars(
            select(Interaction.repository_id).where(
                Interaction.user_id == user.id, Interaction.action == "not_interested"
            )
        )
    )
    bookmarked_repo_ids = set(
        await db.scalars(
            select(Bookmark.repository_id).where(
                Bookmark.user_id == user.id, Bookmark.repository_id.is_not(None)
            )
        )
    )

    ranked = []
    used_embeddings = False
    for repo in repos:
        if repo.id in starred_ids or repo.id in dismissed_ids:
            continue
        if language and (repo.language or "").lower() != language.lower():
            continue
        if not matches_category(repo, category):
            continue
        if effective_mode == "following" and followed_logins and repo.owner_login.lower() not in followed_logins:
            continue
        sem_sim = None
        if user_vector and repo.id in embedding_map:
            sem_sim = cosine_similarity(user_vector, embedding_map[repo.id])
            used_embeddings = True
        score, reasons = score_repository(
            repo,
            interests,
            effective_mode,
            semantic_similarity=sem_sim,
            social_owner_logins=followed_logins,
            star_delta=snapshot_deltas.get(repo.id, 0),
        )
        ranked.append((score, repo, reasons))

    ranked.sort(key=lambda row: (-row[0], row[1].id))
    diversified = diversify_ranked(ranked, limit=60, max_per_owner=3)
    algo = HYBRID_ALGORITHM_VERSION if used_embeddings else ALGORITHM_VERSION
    request_id = secrets.token_hex(8)
    for pos, (score, repo, _) in enumerate(diversified[:24]):
        db.add(
            RecommendationImpression(
                request_id=request_id,
                user_id=user.id,
                repository_id=repo.id,
                position=pos,
                mode=effective_mode,
                algorithm_version=algo,
                score=float(score),
            )
        )
    await db.commit()

    items = [
        {
            **repo_json(repo),
            "score": round(score, 4),
            "reasons": reasons,
            "bookmarked": repo.id in bookmarked_repo_ids,
        }
        for score, repo, reasons in diversified
    ]
    return {
        "items": items,
        "request_id": request_id,
        "algorithm": algo,
        "interest_basis": "starred" if starred else "owned" if interests else "none",
        "mode": effective_mode,
        "category": category,
        "semantic_active": used_embeddings,
    }


@router.get("/search")
async def search(
    q: str = Query(min_length=2, max_length=80),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    items_models: list[Repository] = []
    source = "local_index"
    try:
        token = await get_valid_token(db, user.id)
        async with GitHubClient(token) as github:
            result = await github.get("/search/repositories", {"q": q, "per_page": 30})
        raw_items = [item for item in result.get("items", []) if not item.get("private", False)]
        await upsert_repositories(db, raw_items)
        await db.commit()
        await sync_repository_embeddings(db, limit=16)
        for item in raw_items:
            repo_obj = await db.get(Repository, item["id"])
            if repo_obj:
                items_models.append(repo_obj)
        source = "github_search"
    except GitHubError:
        pattern = f"%{q.lower()}%"
        items_models = list(
            await db.scalars(
                select(Repository)
                .where(
                    Repository.is_public.is_(True),
                    func.lower(Repository.full_name + " " + func.coalesce(Repository.description, "")).like(pattern),
                )
                .limit(30)
            )
        )

    query_vecs = await embed_texts([q])
    if query_vecs and query_vecs[0] and items_models:
        q_vec = query_vecs[0]
        emb_rows = {
            r.repository_id: list(r.embedding)
            for r in await db.scalars(
                select(RepositoryEmbedding).where(
                    RepositoryEmbedding.repository_id.in_([m.id for m in items_models])
                )
            )
        }
        if emb_rows:
            items_models.sort(
                key=lambda m: cosine_similarity(q_vec, emb_rows.get(m.id)),
                reverse=True,
            )
            source = f"{source}+semantic_rerank"

    return {"items": [repo_json(r) for r in items_models], "source": source}


class InteractionInput(BaseModel):
    repository_id: int
    action: str


@router.post("/interactions", dependencies=[Depends(require_same_origin)])
async def interaction(
    payload: InteractionInput,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    if payload.action not in {"click", "not_interested", "bookmark"}:
        raise HTTPException(422, "Unsupported action")
    repo = await db.get(Repository, payload.repository_id)
    if not repo or not repo.is_public:
        raise HTTPException(404, "Repository not found")
    db.add(Interaction(user_id=user.id, repository_id=repo.id, action=payload.action))
    await db.commit()
    return {"status": "recorded"}
