import hashlib
from collections import Counter
from datetime import datetime, timezone
from math import log1p, log2, sqrt

from .models import Repository


ALGORITHM_VERSION = "metadata-coldstart-v1"
HYBRID_ALGORITHM_VERSION = "hybrid-pgvector-v2"


def repository_embedding_text(repo: Repository) -> str:
    topics = ", ".join(repo.topics or [])
    return (
        f"Repository: {repo.full_name}\n"
        f"Owner: {repo.owner_login}\n"
        f"Language: {repo.language or 'unknown'}\n"
        f"Topics: {topics or 'none'}\n"
        f"Description: {repo.description or 'none'}"
    )


def content_hash_for_repo(repo: Repository) -> str:
    return hashlib.sha256(repository_embedding_text(repo).encode("utf-8")).hexdigest()


def cosine_similarity(vec_a: list[float] | None, vec_b: list[float] | None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sqrt(sum(a * a for a in vec_a))
    norm_b = sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(min(dot / (norm_a * norm_b), 1.0), -1.0)


def average_vector(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    dim = len(vectors[0])
    summed = [0.0] * dim
    count = 0
    for vec in vectors:
        if len(vec) != dim:
            continue
        for idx, val in enumerate(vec):
            summed[idx] += float(val)
        count += 1
    if count == 0:
        return None
    norm = sqrt(sum(v * v for v in summed))
    if norm == 0.0:
        return [v / count for v in summed]
    return [v / norm for v in summed]


def interest_weights(repositories: list[Repository], clicked_repositories: list[Repository] | None = None) -> Counter[str]:
    weights: Counter[str] = Counter()
    for repo in repositories:
        if repo.language:
            weights[repo.language.lower()] += 2
        for topic in repo.topics:
            weights[topic.lower()] += 1
    for repo in clicked_repositories or []:
        if repo.language:
            weights[repo.language.lower()] += 1
        for topic in repo.topics:
            weights[topic.lower()] += 1
    return weights


def score_repository(
    repo: Repository,
    interests: Counter[str],
    mode: str = "for-you",
    semantic_similarity: float | None = None,
    social_owner_logins: set[str] | None = None,
    star_delta: int = 0,
) -> tuple[float, list[str]]:
    labels = ([repo.language.lower()] if repo.language else []) + [topic.lower() for topic in (repo.topics or [])]
    affinity = sum(interests[label] for label in labels)
    affinity_norm = min(affinity, 12) / 12
    popularity = min(log1p(max(repo.stars, 0)), 12) / 12
    growth = min(log1p(max(star_delta, 0)), 6) / 6 if star_delta > 0 else 0.0
    freshness = 0.0
    if repo.pushed_at:
        days = max((datetime.now(timezone.utc) - repo.pushed_at).days, 0)
        freshness = 1 / (1 + days / 30)
    social_boost = 1.0 if (social_owner_logins and repo.owner_login.lower() in social_owner_logins) else 0.0

    reasons = [label for label in labels if interests[label] > 0][:3]
    if social_boost > 0 and "following-author" not in reasons:
        reasons.insert(0, "following-author")

    if mode == "trending":
        if growth > 0:
            score = popularity * 0.5 + growth * 0.25 + freshness * 0.25
            reasons = [f"+{star_delta} stars (snapshot)", *reasons][:3]
        else:
            score = popularity * 0.7 + freshness * 0.3
    elif mode == "following":
        score = social_boost * 0.55 + affinity_norm * 0.25 + freshness * 0.20
    elif semantic_similarity is not None:
        sem_norm = max(0.0, (semantic_similarity + 1.0) / 2.0)
        score = (
            sem_norm * 0.35
            + affinity_norm * 0.35
            + popularity * 0.15
            + freshness * 0.10
            + social_boost * 0.05
        )
        if semantic_similarity >= 0.45 and "semantic-match" not in reasons:
            reasons = ["semantic-match", *reasons][:3]
    else:
        score = affinity_norm * 0.7 + popularity * 0.2 + freshness * 0.1

    return score, reasons[:3]


def diversify_ranked(
    ranked: list[tuple[float, Repository, list[str]]],
    limit: int = 60,
    max_per_owner: int = 3,
) -> list[tuple[float, Repository, list[str]]]:
    owner_counts: Counter[str] = Counter()
    selected: list[tuple[float, Repository, list[str]]] = []
    deferred: list[tuple[float, Repository, list[str]]] = []
    for row in ranked:
        owner = (row[1].owner_login or "").lower()
        if owner_counts[owner] < max_per_owner:
            owner_counts[owner] += 1
            selected.append(row)
            if len(selected) >= limit:
                return selected
        else:
            deferred.append(row)
    for row in deferred:
        if len(selected) >= limit:
            break
        selected.append(row)
    return selected


def evaluate_ranking(recommended_ids: list[int], relevant_ids: set[int], k: int = 10) -> dict:
    if not relevant_ids:
        return {
            "insufficient_data": True,
            "k": k,
            "recall_at_k": None,
            "precision_at_k": None,
            "ndcg_at_k": None,
            "note": "No ground-truth positive interactions available yet.",
        }
    top_k = recommended_ids[:k]
    hits = [1 if item_id in relevant_ids else 0 for item_id in top_k]
    hit_count = sum(hits)
    recall = hit_count / len(relevant_ids)
    precision = hit_count / max(len(top_k), 1)
    dcg = sum(rel / log2(idx + 2) for idx, rel in enumerate(hits))
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / log2(idx + 2) for idx in range(ideal_hits))
    ndcg = dcg / idcg if idcg > 0 else 0.0
    return {
        "insufficient_data": False,
        "k": k,
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "ndcg_at_k": round(ndcg, 4),
    }
