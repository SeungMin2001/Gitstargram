# 로컬 서비스 시작·종료

모든 명령은 프로젝트 루트에서 실행한다.

```bash
cd /Users/shin/Documents/2026-2/Gitstargram
```

## 1. 기본 서비스 시작

```bash
open -a Docker
```

Docker Desktop이 준비될 때까지 기다린 후 다음을 실행한다. 준비 여부는 `docker info`로 확인할 수 있다.

```bash
docker compose up -d --build
docker compose ps
curl -f http://localhost:8000/health
```

| 프로세스 | 실행 위치 | 역할 / 주소 |
|---|---|---|
| web | Docker | Next.js UI: http://localhost:3000 |
| api | Docker | FastAPI: http://localhost:8000, 문서 `/docs` |
| worker | Docker | GitHub 데이터·임베딩 백그라운드 작업 |
| db | Docker | PostgreSQL + pgvector, localhost:5432 |
| redis | Docker | 작업 큐, 컨테이너 내부 6379 |
| migrate | Docker, 일회성 | Alembic 마이그레이션 후 정상 종료(exit 0) |

기본 서비스는 AI 서버 없이 시작할 수 있다. GitHub 로그인에는 `.env`의 `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` 설정이 필요하다. 실제 값은 채팅이나 Git에 남기지 않는다.

## 2. AI 기능을 사용할 때만 추가 시작

각 서버는 별도 터미널에서 실행하고 터미널을 유지한다. 최초 초기화에는 시간이 걸린다. 설치돼 있는 macOS 네이티브 가상환경과 모델 캐시를 재사용하며 Docker 안에서 모델을 실행하지 않는다.

터미널 A: 생성형 Qwen3.5-4B, README 요약·번역·게시물 초안.

```bash
cd /Users/shin/Documents/2026-2/Gitstargram
/Users/shin/.venv-vllm-metal/bin/vllm serve Qwen/Qwen3.5-4B \
  --host 127.0.0.1 --port 8001 --max-model-len 4096 --language-model-only
```

터미널 B: Qwen3-Embedding-0.6B, 저장소 임베딩·의미 검색.

```bash
cd /Users/shin/Documents/2026-2/Gitstargram
/Users/shin/.venv-vllm-metal/bin/python scripts/embedding_server.py
```

별도 터미널에서 준비 상태를 확인한다.

```bash
curl -f http://127.0.0.1:8001/v1/models
curl -f http://127.0.0.1:8002/health
```

컨테이너는 `.env`의 `AI_BASE_URL=http://host.docker.internal:8001/v1`, `EMBEDDING_BASE_URL=http://host.docker.internal:8002/v1`로 호스트에 연결한다. GitHub App 설정과 관계없이 AI 서버 자체 기동은 가능하지만 실제 GitHub README 기능 검증에는 로그인이 필요하다.

## 3. 종료

AI 서버를 실행한 각 터미널에서 `Ctrl+C`를 누른다. 이어서 프로젝트 루트에서 실행한다.

```bash
docker compose down
```

DB/Redis 볼륨, `.env`, 모델 캐시와 가상환경은 유지된다. `down -v`는 데이터를 삭제하므로 일반 종료에 사용하지 않는다. 다른 컨테이너를 실행 중이지 않다면 Docker Desktop 메뉴에서 Quit Docker Desktop으로 엔진도 종료할 수 있다. 설치된 Desktop CLI로 종료할 수도 있다.

```bash
docker desktop stop --timeout 45
```

AppleScript의 quit 요청 성공만으로 엔진까지 종료됐다고 단정하지 않는다. 재시작 때 Docker가 `_ping` HTTP 500을 반환하면 데이터 초기화 대신 다음 정상 재시작을 먼저 시도한다.

```bash
docker desktop restart --timeout 45
```

## 4. 로그와 설정 반영

```bash
docker compose logs --tail=100 api worker
```

GitHub App 설정 등 `.env`만 변경한 경우:

```bash
docker compose up -d api worker
```

코드를 변경한 경우에는 `docker compose up -d --build`로 이미지를 다시 빌드한다.

## 마지막 종료 확인: 2026-10-20

- `docker compose down` 완료, `docker compose ps --all`에 프로젝트 컨테이너 없음.
- `docker ps`에 실행 컨테이너 없음 확인 후 Docker Desktop도 종료.
- localhost 3000/5432/8000/8001/8002에 LISTEN 프로세스 없음 확인.
- AI 서버는 이미 꺼진 상태였으며 추가로 기동하지 않음. 데이터 볼륨과 모델 캐시 보존.
