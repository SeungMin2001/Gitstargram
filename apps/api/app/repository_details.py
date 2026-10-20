"""Public GitHub evidence shared by repository details and AI assistance."""

import asyncio
import base64
import binascii

from fastapi import HTTPException

from .github import GitHubClient, GitHubError
from .models import Repository, utcnow


async def public_metadata(github: GitHubClient, repo: Repository) -> dict:
    try:
        metadata = await github.get(f"/repos/{repo.full_name}")
    except GitHubError as exc:
        raise HTTPException(404 if exc.status_code == 404 else 502, "Repository is unavailable on GitHub") from exc
    if (not isinstance(metadata, dict) or metadata.get("id") != repo.id
            or metadata.get("private") is not False or metadata.get("visibility", "public") != "public"):
        # A previously public cached repository may have become private.
        raise HTTPException(404, "Public repository not found")
    return metadata


async def readme_evidence(github: GitHubClient, full_name: str, limit: int = 12000) -> dict:
    try:
        readme = await github.get(f"/repos/{full_name}/readme")
    except GitHubError as exc:
        if exc.status_code == 404:
            return {"status": "missing", "text": "", "source_url": f"https://github.com/{full_name}", "truncated": False}
        raise HTTPException(502, "README could not be retrieved from GitHub") from exc
    if not isinstance(readme, dict) or readme.get("encoding") != "base64":
        raise HTTPException(502, "Unsupported GitHub README response")
    encoded = readme.get("content")
    if not isinstance(encoded, str) or len(encoded) > 2_000_000:
        raise HTTPException(502, "Invalid or oversized GitHub README response")
    try:
        text = base64.b64decode("".join(encoded.split()), validate=True).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(502, "Invalid README content") from exc
    return {
        "status": "available", "text": text[:limit], "source_url": readme.get("html_url") or f"https://github.com/{full_name}",
        "truncated": len(text) > limit, "sha": readme.get("sha"),
    }


async def repository_detail(github: GitHubClient, repo: Repository) -> dict:
    metadata = await public_metadata(github, repo)
    # Optional sections fail independently; a missing README never becomes invented content.
    results = await asyncio.gather(
        readme_evidence(github, metadata["full_name"]),
        github.get(f"/repos/{metadata['full_name']}/languages"),
        return_exceptions=True,
    )
    readme, languages = results
    if isinstance(readme, Exception):
        readme = {"status": "unavailable", "text": "", "source_url": metadata["html_url"], "truncated": False}
    languages_available = isinstance(languages, dict) and all(
        isinstance(name, str) and isinstance(value, int) and value >= 0 for name, value in languages.items()
    )
    total = sum(languages.values()) if languages_available else 0
    license_data = metadata.get("license") or {}
    return {
        "id": metadata["id"], "full_name": metadata["full_name"], "html_url": metadata["html_url"],
        "description": metadata.get("description"), "stars": metadata.get("stargazers_count", 0),
        "forks": metadata.get("forks_count", 0), "open_issues": metadata.get("open_issues_count", 0),
        "topics": metadata.get("topics") or [], "pushed_at": metadata.get("pushed_at"),
        "archived": bool(metadata.get("archived")),
        "license": {"name": license_data.get("name"), "spdx_id": license_data.get("spdx_id")},
        "languages_status": "available" if languages_available else "unavailable",
        "languages": [{"name": name, "bytes": count, "percentage": round(count / total * 100, 1) if total else 0}
                      for name, count in sorted(languages.items(), key=lambda pair: -pair[1])] if languages_available else [],
        "readme": readme, "source": "github_rest", "fetched_at": utcnow().isoformat(),
    }
