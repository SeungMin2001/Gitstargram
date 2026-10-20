# Contributing to Gitstargram

Thank you for your interest in contributing to Gitstargram!

## Core Development Principles

1. **No Fake Data or Mock Success Screens**: Never hardcode fake GitHub profiles, repositories, star counts, or fabricated benchmark metrics in user-facing code or documentation.
2. **No Secrets in Code or Commits**: Never commit `.env` files, GitHub App Client Secrets, or session keys.
3. **Separate Code Implementation from Live Verification**: Update `DEVELOPMENT_STATUS.md` honestly whenever adding features or running benchmarks.

## Local Checks Before Submitting a PR

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web npm run typecheck
```
