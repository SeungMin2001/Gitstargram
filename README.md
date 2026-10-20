# Gitstargram

A developer social network built on real GitHub data, featuring GitHub App user OAuth (with PKCE), public repository & star synchronization, 24-hour developer stories, SNS posts/likes/comments/bookmarks, hybrid discovery powered by `Qwen/Qwen3-Embedding-0.6B` + PostgreSQL `pgvector`, local README summarization/translation/drafting via `Qwen/Qwen3.5-4B` on Apple Silicon `vLLM Metal`, and 1:1 Direct Messaging over FastAPI WebSockets.

See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the full specification and [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) for the strict separation between implemented code, measured benchmarks on Mac mini M4 (24GB), and validations awaiting live GitHub App user credentials.

Repository cards include a detail dialog with live GitHub metadata, language byte proportions, license information, README source, and recorded recommendation signals. Select one of your synchronized public projects to request an AI suggestion about using the discovered repository, with evidence links for both projects. This flow still requires validation with GitHub App sign-in and a running local model. The design decisions drawn from the owner's earlier GitTeol project are recorded in [the reference review](docs/GITTEOL_REVIEW.md). Start and stop commands are in [RUNBOOK.md](RUNBOOK.md).

## Architecture

- **Frontend (`apps/web`, `:3000`)**: Next.js 15, React 19, TypeScript, responsive 3-column Explore grid, Dark/Light themes
- **Backend & Worker (`apps/api`, `:8000`)**: FastAPI modular monolith, SQLAlchemy Async, Alembic, Redis background worker, WebSocket DM hub
- **Database (`db`, `:5432`)**: PostgreSQL 17 + `pgvector` (`vector(1024)` with HNSW cosine index)
- **Generative LLM Server (`:8001`, native macOS)**: `vLLM Metal` serving `Qwen/Qwen3.5-4B`
- **Embedding Server (`:8002`, native macOS)**: `scripts/embedding_server.py` serving `Qwen/Qwen3-Embedding-0.6B` (1024-dim L2-normalized vectors on MPS)

## Quick Start

1. Copy `.env.example` to `.env` and set a random 32+ character `SESSION_SECRET` and `POSTGRES_PASSWORD`.
2. Create a GitHub App at [GitHub Developer Settings](https://github.com/settings/apps/new):
   - Homepage URL: `http://localhost:3000`
   - Callback URL: `http://localhost:8000/api/auth/callback`
   - User permissions: **Starring: Read-only**
   - Put `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env` locally (never commit or paste secrets into chat).
3. Start the native Apple Silicon AI servers on the host:
   ```bash
   /Users/shin/.venv-vllm-metal/bin/vllm serve Qwen/Qwen3.5-4B --host 127.0.0.1 --port 8001 --max-model-len 4096 --language-model-only
   /Users/shin/.venv-vllm-metal/bin/python scripts/embedding_server.py
   ```
4. Build and start the Docker Compose stack:
   ```bash
   docker compose up -d --build
   ```

## Running Tests

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web npm run typecheck
```

## License

No open-source license has been selected yet. Do not assume reuse permissions until the project owner chooses a license and adds a `LICENSE` file.
