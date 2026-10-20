import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings


class GitHubError(Exception):
    pass


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def exchange_code(code: str, code_verifier: str) -> dict:
    config = settings()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": f"{config.backend_url}/api/auth/callback",
                "code_verifier": code_verifier,
            },
        )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        raise GitHubError(data.get("error_description", "GitHub token exchange failed"))
    return data


async def refresh_access_token(refresh_token: str) -> dict:
    config = settings()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        raise GitHubError(data.get("error_description", "GitHub token refresh failed"))
    return data


class GitHubClient:
    def __init__(self, token: str):
        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=20,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": settings().github_api_version,
                "User-Agent": "Gitstargram-local-development",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def get(self, path: str, params: dict | None = None):
        for attempt in range(3):
            try:
                response = await self.client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise GitHubError("GitHub is unreachable") from exc
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubError("GitHub API rate limit reached")
            if response.status_code >= 400:
                raise GitHubError(f"GitHub API returned {response.status_code}")
            return response.json()
        raise GitHubError("GitHub request failed")

    async def pages(self, path: str, params: dict | None = None, max_pages: int = 10) -> list[dict]:
        items: list[dict] = []
        for page in range(1, max_pages + 1):
            data = await self.get(path, {**(params or {}), "per_page": 100, "page": page})
            if not isinstance(data, list):
                raise GitHubError("Unexpected GitHub API response")
            items.extend(data)
            if len(data) < 100:
                break
        return items


def expiry_from_seconds(seconds: int | None) -> datetime | None:
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds)) if seconds else None

