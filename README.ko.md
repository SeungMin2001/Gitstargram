# Gitstargram

실제 GitHub 데이터를 기반으로 한 개발자 SNS입니다. GitHub App 사용자 OAuth(PKCE), 공개 저장소·Star·스냅샷 동기화, 24시간 스토리, 개발 게시물 및 댓글·북마크, `Qwen/Qwen3-Embedding-0.6B`(pgvector 1024차원) 기반 하이브리드 추천, `Qwen/Qwen3.5-4B`(vLLM Metal) 기반 README 요약·번역·게시물 초안 생성, 그리고 PostgreSQL + WebSocket 기반 1:1 DM을 포함합니다.

전체 요구사항은 [PROJECT_SPEC.md](PROJECT_SPEC.md), 현재 코드 구현 범위와 실측 벤치마크·미검증 항목(실계정 자격증명 대기 항목)은 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)에 분리되어 기록되어 있습니다.

## 아키텍처 및 포트 구성

- **Frontend (`apps/web`, `:3000`)**: Next.js 15, React 19, TypeScript, 반응형 3열 Explore 격자 및 Dark/Light 모드
- **Backend API & Worker (`apps/api`, `:8000`)**: FastAPI, SQLAlchemy Async, Alembic, Redis 작업 큐, WebSocket (`/api/dm/ws`)
- **Database (`db`, `:5432`)**: PostgreSQL 17 + `pgvector` (`vector(1024)` HNSW 코사인 인덱스)
- **Generative AI Server (`:8001`, 호스트 네이티브)**: Apple Silicon `vLLM Metal` (`Qwen/Qwen3.5-4B`)
- **Embedding Server (`:8002`, 호스트 네이티브)**: Apple Silicon MPS 기반 `scripts/embedding_server.py` (`Qwen/Qwen3-Embedding-0.6B`, 1024차원)

## 로컬 실행 방법

1. `.env.example`을 `.env`로 복사하고 32자 이상의 무작위 `SESSION_SECRET`과 `POSTGRES_PASSWORD`를 설정합니다.
2. [GitHub Developer Settings](https://github.com/settings/apps/new)에서 GitHub App을 생성합니다.
   - Homepage URL: `http://localhost:3000`
   - Callback URL: `http://localhost:8000/api/auth/callback`
   - User permissions → **Starring: Read-only**
   - 발급받은 `GITHUB_CLIENT_ID`와 `GITHUB_CLIENT_SECRET`을 `.env`에 직접 입력합니다. (채팅이나 Git 커밋에 절대 포함하지 마세요.)
3. 호스트 macOS에서 로컬 AI 서버 2개를 실행합니다:
   ```bash
   /Users/shin/.venv-vllm-metal/bin/vllm serve Qwen/Qwen3.5-4B --host 127.0.0.1 --port 8001 --max-model-len 4096 --language-model-only
   /Users/shin/.venv-vllm-metal/bin/python scripts/embedding_server.py
   ```
4. Docker 서비스를 빌드 및 기동합니다:
   ```bash
   docker compose up -d --build
   ```
5. `http://localhost:8000/health`와 `http://localhost:3000`을 열고 GitHub 계정으로 로그인합니다.

## 테스트 실행

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web npm run typecheck
```

## 라이선스

아직 프로젝트 라이선스를 선택하지 않았습니다. 프로젝트 소유자가 라이선스를 확정하고 `LICENSE` 파일을 추가하기 전에는 재사용 권한을 추정하지 마세요.
