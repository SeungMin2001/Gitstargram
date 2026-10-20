import base64
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app import ai
from app.ai import PostDraftInput, UsageSuggestionInput, generate_post_draft, usage_suggestion
from app.github import GitHubClient, GitHubError
from app.main import app
from app.models import Repository, User, UserRepository
from app.repository_details import public_metadata, readme_evidence, repository_detail


def readme(text):
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode(),
            "html_url": "https://github.com/fixture/project/blob/main/README.md", "sha": "fixture-sha"}


class FakeGithub:
    def __init__(self, responses):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, path, params=None):
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.asyncio
async def test_github_client_keeps_http_status_and_rejects_invalid_json():
    async with GitHubClient("unit-test-token") as github:
        await github.client.aclose()
        github.client = httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={"message": "Not Found"})
        ))
        with pytest.raises(GitHubError) as exc:
            await github.get("/repos/missing/project")
        assert exc.value.status_code == 404
        await github.client.aclose()
        github.client = httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="invalid json")
        ))
        with pytest.raises(GitHubError, match="invalid JSON"):
            await github.get("/repos/missing/project")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"private": True}, {"id": 999}, {"visibility": "private"}])
async def test_cached_public_repository_is_rechecked_upstream(change):
    github = FakeGithub({"/repos/fixture/project": {"id": 7, "private": False, **change}})
    with pytest.raises(HTTPException) as exc:
        await public_metadata(github, SimpleNamespace(id=7, full_name="fixture/project"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_readme_is_bounded_and_missing_is_not_an_outage():
    evidence = await readme_evidence(FakeGithub({"/repos/a/b/readme": readme("abcdef")}), "a/b", limit=3)
    assert evidence["text"] == "abc" and evidence["truncated"]
    missing = await readme_evidence(FakeGithub({"/repos/a/b/readme": GitHubError("missing", 404)}), "a/b")
    assert missing["status"] == "missing" and missing["text"] == ""
    with pytest.raises(HTTPException) as exc:
        await readme_evidence(FakeGithub({"/repos/a/b/readme": GitHubError("rate limited", 403)}), "a/b")
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_malformed_readme_and_optional_language_failure():
    with pytest.raises(HTTPException) as exc:
        await readme_evidence(FakeGithub({"/repos/a/b/readme": {"encoding": "base64", "content": "%%%"}}), "a/b")
    assert exc.value.status_code == 502
    result = await repository_detail(FakeGithub({
        "/repos/a/b": {"id": 7, "private": False, "full_name": "a/b", "html_url": "https://github.com/a/b", "license": None},
        "/repos/a/b/readme": GitHubError("missing", 404),
        "/repos/a/b/languages": GitHubError("unavailable", 503),
    }), SimpleNamespace(id=7, full_name="a/b"))
    assert result["readme"]["status"] == "missing"
    assert result["languages_status"] == "unavailable" and result["languages"] == []
    assert result["license"]["spdx_id"] is None


@pytest.mark.asyncio
async def test_detail_language_percentages_come_from_actual_byte_counts():
    result = await repository_detail(FakeGithub({
        "/repos/a/b": {"id": 7, "private": False, "full_name": "a/b", "html_url": "https://github.com/a/b"},
        "/repos/a/b/readme": readme("# Documentation"),
        "/repos/a/b/languages": {"Python": 300, "JavaScript": 100},
    }), SimpleNamespace(id=7, full_name="a/b"))
    assert result["languages"] == [{"name": "Python", "bytes": 300, "percentage": 75.0},
                                    {"name": "JavaScript", "bytes": 100, "percentage": 25.0}]


@pytest.mark.asyncio
async def test_repository_detail_requires_authentication():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/repositories/1")
    assert response.status_code == 401


async def comparison_fixture(db):
    suffix = uuid4().hex[:10]
    user = User(github_id=secrets.randbits(52), login=f"fixture_{suffix}", html_url="https://github.com")
    db.add(user)
    await db.flush()
    repositories = []
    for index in range(2):
        repo = Repository(id=secrets.randbits(52), owner_github_id=user.github_id if index == 0 else user.github_id + 1,
                          owner_login=f"fixture_{suffix}_{index}", name="project", full_name=f"fixture_{suffix}_{index}/project",
                          html_url="https://github.com", language="Python", topics=["rag"], is_public=True)
        db.add(repo)
        repositories.append(repo)
    await db.flush()
    return user, repositories


@pytest.mark.asyncio
async def test_usage_requires_owned_relation_and_github_owner(isolated_db, monkeypatch):
    db = isolated_db
    user, (project, target) = await comparison_fixture(db)
    model = AsyncMock()
    monkeypatch.setattr(ai, "call_chat_model", model)
    payload = UsageSuggestionInput(project_repository_id=project.id, target_repository_id=target.id)
    with pytest.raises(HTTPException) as exc:
        await usage_suggestion(payload, user=user, db=db)
    assert exc.value.status_code == 403
    db.add(UserRepository(user_id=user.id, repository_id=project.id, kind="owned"))
    project.owner_github_id += 1
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await usage_suggestion(payload, user=user, db=db)
    assert exc.value.status_code == 403
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_usage_uses_two_sources_and_reports_model_outage(isolated_db, monkeypatch):
    db = isolated_db
    user, (project, target) = await comparison_fixture(db)
    db.add(UserRepository(user_id=user.id, repository_id=project.id, kind="owned"))
    await db.flush()
    responses = {}
    for repo in (project, target):
        responses[f"/repos/{repo.full_name}"] = {"id": repo.id, "private": False, "full_name": repo.full_name,
            "owner": {"id": repo.owner_github_id}, "description": "Evidence from GitHub", "topics": ["rag"]}
        responses[f"/repos/{repo.full_name}/readme"] = readme("Documented capability. " * 150)
    monkeypatch.setattr(ai, "get_valid_token", AsyncMock(return_value="unit-test-token"))
    monkeypatch.setattr(ai, "GitHubClient", lambda token: FakeGithub(responses))
    model = AsyncMock(return_value=("검토할 활용 아이디어", 12.0, {}))
    monkeypatch.setattr(ai, "call_chat_model", model)
    payload = UsageSuggestionInput(project_repository_id=project.id, target_repository_id=target.id)
    result = await usage_suggestion(payload, user=user, db=db)
    assert result["requires_user_review"] and len(result["sources"]) == 2
    assert all(source["truncated"] for source in result["sources"])
    prompt = model.await_args.kwargs["user_prompt"]
    assert project.full_name in prompt and target.full_name in prompt and "Documented capability" in prompt
    model.side_effect = HTTPException(503, "AI unavailable")
    with pytest.raises(HTTPException) as exc:
        await usage_suggestion(payload, user=user, db=db)
    assert exc.value.status_code == 503
    model.reset_mock()
    responses[f"/repos/{project.full_name}"]["private"] = True
    with pytest.raises(HTTPException) as exc:
        await usage_suggestion(payload, user=user, db=db)
    assert exc.value.status_code == 404
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_project_is_not_a_comparison(isolated_db):
    user, (project, _) = await comparison_fixture(isolated_db)
    with pytest.raises(HTTPException) as exc:
        await usage_suggestion(UsageSuggestionInput(project_repository_id=project.id,
            target_repository_id=project.id), user=user, db=isolated_db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_post_draft_does_not_hide_github_or_visibility_failure(isolated_db, monkeypatch):
    user, (project, _) = await comparison_fixture(isolated_db)
    model = AsyncMock(return_value=("Draft", 1.0, {}))
    fetch = AsyncMock(side_effect=HTTPException(404, "Repository became private"))
    monkeypatch.setattr(ai, "fetch_repo_readme", fetch)
    monkeypatch.setattr(ai, "call_chat_model", model)
    with pytest.raises(HTTPException) as exc:
        await generate_post_draft(PostDraftInput(repository_id=project.id), user=user, db=isolated_db)
    assert exc.value.status_code == 404
    model.assert_not_awaited()
    fetch.side_effect = HTTPException(422, "Repository has no readable README")
    result = await generate_post_draft(PostDraftInput(repository_id=project.id), user=user, db=isolated_db)
    assert result["requires_user_review"]
    model.assert_awaited_once()
