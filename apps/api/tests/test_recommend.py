from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.ai import strip_thinking_blocks
from app.database import SessionLocal
from app.models import Follow, Post, Repository, RepositoryEmbedding, Story, User
from app.recommend import (
    average_vector,
    content_hash_for_repo,
    cosine_similarity,
    diversify_ranked,
    evaluate_ranking,
    interest_weights,
    score_repository,
)
from app.sync import repository_values


def repo(language, topics, stars=10, days_ago=2, owner_login="owner", repo_id=1, name="project", description="desc"):
    return SimpleNamespace(
        id=repo_id,
        owner_login=owner_login,
        name=name,
        full_name=f"{owner_login}/{name}",
        description=description,
        language=language,
        topics=topics,
        stars=stars,
        pushed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def test_starred_technology_changes_cold_start_ranking():
    interests = interest_weights([repo("Python", ["rag", "agents"])])
    relevant, reasons = score_repository(repo("Python", ["rag"], stars=10), interests)
    unrelated, _ = score_repository(repo("Rust", ["terminal"], stars=10), interests)
    assert relevant > unrelated
    assert "python" in reasons


def test_trending_does_not_pretend_to_use_star_growth_without_snapshots():
    interests = interest_weights([])
    popular, _ = score_repository(repo("Go", [], stars=1000), interests, "trending")
    quiet, _ = score_repository(repo("Go", [], stars=2), interests, "trending")
    assert popular > quiet

    growing, reasons = score_repository(repo("Go", [], stars=50), interests, "trending", star_delta=25)
    static, _ = score_repository(repo("Go", [], stars=50), interests, "trending", star_delta=0)
    assert growing > static
    assert any("stars (snapshot)" in r for r in reasons)


def test_github_normalization_keeps_id_and_public_visibility():
    item = {
        "id": 42,
        "owner": {"id": 7, "login": "owner"},
        "name": "project",
        "full_name": "owner/project",
        "html_url": "https://github.com/owner/project",
        "stargazers_count": 12,
        "topics": ["python"],
        "private": False,
    }
    values = repository_values(item)
    assert values["id"] == 42 and values["stars"] == 12 and values["is_public"]
    assert repository_values({**item, "private": True})["is_public"] is False


def test_hybrid_semantic_similarity_and_diversity_reranking():
    interests = interest_weights([repo("Python", ["fastapi"])])
    vec_user = average_vector([[1.0, 0.0, 0.0], [0.8, 0.2, 0.0]])
    assert vec_user is not None
    sim_high = cosine_similarity(vec_user, [1.0, 0.0, 0.0])
    sim_low = cosine_similarity(vec_user, [0.0, 1.0, 0.0])
    assert sim_high > sim_low

    high_score, reasons = score_repository(
        repo("Python", [], stars=20), interests, "for-you", semantic_similarity=sim_high
    )
    low_score, _ = score_repository(
        repo("Python", [], stars=20), interests, "for-you", semantic_similarity=sim_low
    )
    assert high_score > low_score
    assert "semantic-match" in reasons

    ranked = [
        (0.95 - i * 0.01, repo("Python", [], owner_login="same_owner", repo_id=100 + i), [])
        for i in range(5)
    ] + [(0.60, repo("Rust", [], owner_login="other_owner", repo_id=200), [])]
    diversified = diversify_ranked(ranked, limit=4, max_per_owner=3)
    owners = [r[1].owner_login for r in diversified]
    assert owners.count("same_owner") == 3
    assert "other_owner" in owners


def test_honest_evaluation_metrics_and_thinking_strip():
    empty_eval = evaluate_ranking([1, 2, 3], set(), k=3)
    assert empty_eval["insufficient_data"] is True
    assert empty_eval["recall_at_k"] is None

    real_eval = evaluate_ranking([10, 20, 30], {10, 30}, k=3)
    assert real_eval["insufficient_data"] is False
    assert real_eval["recall_at_k"] == 1.0
    assert real_eval["ndcg_at_k"] > 0.9

    assert strip_thinking_blocks("<think>internal</think>\n핵심 요약입니다.") == "핵심 요약입니다."


@pytest.mark.asyncio
async def test_pgvector_and_sns_persistence_roundtrip():
    async with SessionLocal() as db:
        test_repo_id = 999_999_001
        await db.execute(delete(Repository).where(Repository.id == test_repo_id))
        await db.execute(delete(User).where(User.github_id.in_([999_999_101, 999_999_102])))
        await db.commit()

        u1 = User(github_id=999_999_101, login="test_dev_a", html_url="https://github.com/test_dev_a")
        u2 = User(github_id=999_999_102, login="test_dev_b", html_url="https://github.com/test_dev_b")
        r1 = Repository(
            id=test_repo_id,
            owner_github_id=999_999_101,
            owner_login="test_dev_a",
            name="pgvector-demo",
            full_name="test_dev_a/pgvector-demo",
            description="Vector search test repo",
            html_url="https://github.com/test_dev_a/pgvector-demo",
            language="Python",
            topics=["pgvector", "fastapi"],
            stars=42,
            is_public=True,
        )
        db.add_all([u1, u2, r1])
        await db.flush()

        vec = [0.5] + [0.0] * 1023
        db.add(
            RepositoryEmbedding(
                repository_id=r1.id,
                model_name="Qwen/Qwen3-Embedding-0.6B",
                dimensions=1024,
                content_hash=content_hash_for_repo(r1),
                embedding=vec,
            )
        )
        db.add(Follow(follower_id=u2.id, following_id=u1.id))
        db.add(Post(author_id=u1.id, repository_id=r1.id, title="출시 공유", body="실제 DB 저장 검증", tags=["python"]))
        db.add(
            Story(
                author_id=u1.id,
                repository_id=r1.id,
                kind="release",
                title="v0.2.0",
                summary="pgvector 연동 완료",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        await db.commit()

        nearest = await db.scalar(
            select(RepositoryEmbedding.repository_id)
            .where(RepositoryEmbedding.repository_id == test_repo_id)
            .order_by(RepositoryEmbedding.embedding.cosine_distance(vec))
            .limit(1)
        )
        assert nearest == test_repo_id

        await db.execute(delete(Repository).where(Repository.id == test_repo_id))
        await db.execute(delete(User).where(User.id.in_([u1.id, u2.id])))
        await db.commit()
