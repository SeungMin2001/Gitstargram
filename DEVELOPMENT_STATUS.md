# Gitstargram 개발 현황 및 AI 인계 문서

마지막 갱신: 2026-10-19 22:54 (Asia/Seoul)

> **중요 (인계 원칙):**
> 1. 이 문서는 **코드 구현 상태**와 **실측·통합 검증 완료 상태**를 엄격히 분리하여 기록한다.
> 2. 다음 작업자(또는 AI 에이전트)는 반드시 루트의 `PROJECT_SPEC.md`(원본 마스터 명세 1,727줄)와 이 문서를 먼저 읽고 이어서 진행한다.
> 3. **현재 모든 실행 프로세스(Docker Compose 컨테이너, 호스트 vLLM Metal 서버 `:8001`, 호스트 MPS 임베딩 서버 `:8002`)는 사용자 요청에 따라 안전하게 종료(`down`/종료)된 상태**이다. 단, PostgreSQL/Redis 볼륨과 다운로드된 Hugging Face 모델 캐시(`Qwen/Qwen3.5-4B`, `Qwen/Qwen3-Embedding-0.6B`), 가상환경(`/Users/shin/.venv-vllm-metal`)은 디스크에 그대로 보존되어 있어 즉시 재기동할 수 있다.

---

## 1. 세션별 작업 히스토리 요약

### 1차 세션 (이전 환경 진행분)
- `PROJECT_SPEC.md` 원본 보존 및 초기 모노레포(`apps/api`, `apps/web`, `docker-compose.yml`) 구축
- GitHub App 사용자 OAuth(`state` + PKCE `S256` 검증), Fernet 토큰 암호화, HttpOnly 세션 쿠키 인증 구현
- 기본 7개 테이블(`users`, `github_accounts`, `auth_sessions`, `repositories`, `user_repositories`, `github_sync_jobs`, `user_interactions`) 및 초기 마이그레이션(`0001_initial.py`) 작성
- 콜드스타트 추천(`metadata-coldstart-v1`) 및 단위 테스트 3개 통과 확인
- 호스트 `/Users/shin/.venv-vllm-metal`에 `vllm 0.31.0+cpu` + `vllm-metal 0.31.0` 설치 후 `Qwen/Qwen3.5-4B` 모델 다운로드 시작

### 2차 세션 (현재 인계 시점 완료분)
- **로컬 AI 모델 2종(생성형 + 임베딩) 분리 서빙 구축 및 컨테이너↔호스트 실측 완료:**
  1. **생성형 LLM (`Qwen/Qwen3.5-4B`, 포트 `8001`, vLLM Metal):** 모델 다운로드 완료 확인 후 `http://127.0.0.1:8001/v1/models` 및 Docker `api` 컨테이너(`http://host.docker.internal:8001/v1`)에서의 스트리밍 추론(`enable_thinking=False`) 검증 완료.
  2. **임베딩 모델 (`Qwen/Qwen3-Embedding-0.6B`, 포트 `8002`, Apple Silicon MPS):** 명세에 따라 생성형 서버와 엔드포인트를 분리한 네이티브 임베딩 서버 `scripts/embedding_server.py` 작성. 실제 출력 차원 **`1024`** 및 L2 정규화 확인, 컨테이너↔호스트 `/v1/embeddings` 연동 검증 완료.
- **PostgreSQL + pgvector 전체 도메인 스키마(`0002_full_domain_schema.py`) 확장 및 검증:**
  - 총 **25개 테이블**(`alembic_version` 포함)과 `repository_embeddings.embedding`(`Vector(1024)`)에 대한 HNSW 코사인 인덱스(`ix_repository_embeddings_hnsw`) 적용 완료.
- **M2/M3 백엔드 기능 확장:**
  - `apps/api/app/recommend.py` & `api.py`: `hybrid-pgvector-v2` 하이브리드 추천(사용자 관심 임베딩 평균 벡터 코사인 유사도 35% + 언어·Topic 35% + 인기도 15% + 최신성 10% + 팔로잉 보너스 5%), 동일 소유자 편중 방지 재정렬(`diversify_ranked`, 소유자당 최대 3개), 다중 스냅샷(`repository_snapshots`) 기반 Star 증가분 계산, 추천 노출 기록(`recommendation_impressions`), 검색 결과 의미 기반 재정렬(`github_search+semantic_rerank`), 오프라인 평가 함수(`evaluate_ranking` — 정답 데이터 부재 시 `insufficient_data: True` 반환) 구현.
  - `apps/api/app/social.py`: SNS 팔로우/언팔로우, 사용자 차단/해제, 게시물 작성/수정/삭제, 게시물 좋아요/댓글, 저장소·게시물 북마크, 24시간 만료 스토리 생성 및 조회수 기록, 알림 목록/읽음 처리, 사용자 설정(Dark/Light 테마, 추천 개인화 on/off, 알림 on/off), 행동·노출 로그 일괄 삭제(`DELETE /api/social/interactions`), 콘텐츠 신고 API 구현.
  - `apps/api/app/dm.py`: 1:1 대화방 생성/목록, 메시지 영속 저장(`messages`), `client_message_id` 중복 전송 방지, 읽음 상태(`last_read_message_id`) 갱신, 차단 사용자 검증, 세션 쿠키 인증 기반 FastAPI WebSocket(`/api/dm/ws`) 실시간 메시징 구현.
  - `apps/api/app/ai.py`: `/api/ai/status`(생성형 + 임베딩 서버 상태 동시 확인), `/api/ai/summary`(README 한국어 요약), `/api/ai/translate`(README 한/영 번역), `/api/ai/post-draft`(저장소 메타데이터·README 기반 SNS 게시물 초안 생성) 및 `<think>` 블록 제거·지연 시간(`latency_ms`) 반환 구현.
- **프론트엔드(`apps/web`) 4대 탭 전체 UI 연결 및 Dark/Light 모드 지원:**
  - `Home`: 24시간 스토리 바·작성 폼·전체화면 뷰어, 저장소 연결 및 AI 초안 생성 지원 게시물 작성기, `Following` / `Recommended` 개발자 피드(SNS 좋아요와 GitHub Star 분리 표시, 댓글 모달), 내 공개 프로젝트 및 추천 프리뷰.
  - `Explore`: `For You` / `Trending` / `Following` 모드, 기술 카테고리(`ALL`, `AI-ML`, `FRONTEND`, `BACKEND`, `DEVOPS-TOOLS`), 언어 필터, 자연어·키워드 검색, 카드별 `AI 요약` · `README 번역` · `북마크` · `관심 없음`.
  - `Profile`: 외부 GitHub 지표와 내부 SNS 지표 분리 표시, 프로필(이름/Bio) 수정, 개인화 추천 on/off, 행동·노출 로그 전체 삭제, GitHub 연결 해제 및 계정 삭제.
  - `DM`: 대화 목록, 개발자 디렉터리(팔로우/DM 시작), WebSocket 실시간 채팅 화면.
- **테스트·CI·오픈소스 문서 구성:**
  - `apps/api/tests/test_recommend.py` 6개 테스트(pgvector 코사인 거리 `<=>` 및 SNS DB 라운드트립 통합 테스트 포함) 모두 통과(`6 passed in 0.31s`), 프론트엔드 `npm run typecheck` 통과.
  - `.github/workflows/ci.yml`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `README.md`, `README.ko.md` 작성 및 갱신.

---

## 2. 환경 및 프로세스 상태

| 항목 | 상태 / 경로 |
|---|---|
| 하드웨어 / OS | Apple M4 (10-core), RAM 24 GB, macOS 26.6.2 (arm64) |
| Docker / Compose | Engine 29.8.2, Compose v5.6.0 (현재 `docker compose down`으로 컨테이너 종료됨, DB/Redis 볼륨은 보존됨) |
| 로컬 AI 가상환경 | `/Users/shin/.venv-vllm-metal` (Python 3.12.15, `vllm 0.31.0+cpu`, `vllm-metal 0.31.0`, `torch 2.13.0`, `transformers 5.17.0`) |
| 다운로드된 모델 캐시 | `/Users/shin/.cache/huggingface/hub` 내 `models--Qwen--Qwen3.5-4B` 및 `models--Qwen--Qwen3-Embedding-0.6B` 다운로드 완료 |
| 환경 변수 (`.env`) | `POSTGRES_*`, `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `AI_BASE_URL`, `EMBEDDING_BASE_URL`, `EMBEDDING_DIMENSIONS=1024` 설정 완료. **`GITHUB_CLIENT_ID`와 `GITHUB_CLIENT_SECRET`만 비어 있음.** |

---

## 3. 디렉터리 및 파일 구조

```text
.
├── .env.example                            # 환경 변수 템플릿 (비밀값 미포함)
├── .github/workflows/ci.yml                # PostgreSQL(pgvector)+Redis 백엔드 pytest 및 프론트엔드 typecheck/build CI
├── CODE_OF_CONDUCT.md                      # 오픈소스 행동 강령
├── CONTRIBUTING.md                         # 기여 가이드 및 원칙
├── DEVELOPMENT_STATUS.md                   # 본 개발 현황 및 인계 문서
├── PROJECT_SPEC.md                         # 마스터 요구사항 명세 (1,727줄 원본 보존)
├── README.ko.md                            # 한국어 실행 및 아키텍처 안내
├── README.md                               # 영문 실행 및 아키텍처 안내
├── SECURITY.md                             # 보안 정책 및 구현된 보호 조치
├── docker-compose.yml                      # db(pgvector:pg17), redis, migrate, api, worker, web
├── scripts/
│   └── embedding_server.py                 # 호스트 네이티브 MPS 기반 Qwen3-Embedding-0.6B 서버 (:8002)
├── apps/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── pytest.ini
│   │   ├── requirements.txt
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   │       ├── 0001_initial.py
│   │   │       └── 0002_full_domain_schema.py  # 전체 25개 테이블 + HNSW 벡터 인덱스
│   │   ├── app/
│   │   │   ├── main.py                     # FastAPI 앱 및 라우터 등록
│   │   │   ├── config.py                   # 환경 설정 (DB, Redis, GitHub, AI, Embedding, S3)
│   │   │   ├── database.py                 # SQLAlchemy AsyncEngine 및 세션
│   │   │   ├── models.py                   # 24개 ORM 모델 정의
│   │   │   ├── security.py                 # Fernet 암호화, SHA-256 세션 해시, CSRF Origin 검증
│   │   │   ├── auth.py                     # GitHub App OAuth (PKCE S256), 로그아웃, 연결 해제, 계정 탈퇴
│   │   │   ├── github.py                   # GitHub REST 클라이언트, 토큰 갱신, 페이지네이션, 백오프
│   │   │   ├── sync.py                     # Redis 작업 큐, 저장소/Star/스냅샷/임베딩 동기화
│   │   │   ├── worker.py                   # 백그라운드 동기화 워커
│   │   │   ├── recommend.py                # 콜드스타트 + pgvector 하이브리드 랭킹, 다양성 재정렬, 평가 지표
│   │   │   ├── api.py                      # /api/me, /sync, /embeddings/sync, /repositories, /explore, /search
│   │   │   ├── social.py                   # /api/social/* (팔로우, 차단, 게시물, 좋아요, 댓글, 북마크, 스토리, 알림, 설정)
│   │   │   ├── dm.py                       # /api/dm/* (1:1 대화, 메시지, 읽음 상태, WebSocket /api/dm/ws)
│   │   │   └── ai.py                       # /api/ai/* (상태, README 요약, README 번역, 게시물 초안)
│   │   └── tests/
│   │       └── test_recommend.py           # 단위 테스트 + PostgreSQL/pgvector/SNS 영속성 통합 테스트 (6개)
│   └── web/
│       ├── Dockerfile
│       ├── package.json
│       ├── tsconfig.json
│       └── app/
│           ├── layout.tsx
│           ├── globals.css                 # 반응형 3열 격자, Dark/Light 테마 토큰, 스토리/피드/DM 스타일
│           └── page.tsx                    # Home / Explore / Profile / DM 전체 클라이언트
```

---

## 4. 기능별 구현 및 실제 검증 상태 표

| 영역 / 기능 | 코드 상태 | 실제 검증 상태 | 비고 및 남은 검증 |
|---|---|---|---|
| Docker Compose + PostgreSQL 17(`pgvector`) + Redis | 구현 완료 | **검증 완료** | 25개 테이블 + `ix_repository_embeddings_hnsw` 인덱스 생성 및 헬스체크 통과 |
| GitHub App OAuth (`state` + PKCE `S256`) | 구현 완료 | **실계정 검증 필요** | `.env`에 `GITHUB_CLIENT_ID`/`SECRET` 입력 후 실제 로그인 테스트 필요 |
| 공개 저장소 / Star / 스냅샷 / 임베딩 동기화 (`sync.py`) | 구현 완료 | 단위/DB 검증 완료, **실계정 검증 필요** | 실계정 로그인 후 GitHub API 응답과 DB `repositories`/`repository_snapshots` 대조 필요 |
| Explore 하이브리드 추천 (`hybrid-pgvector-v2`) | 구현 완료 | **알고리즘·pgvector 연동 검증 완료** | 실계정 동기화 데이터에서 클릭/관심없음 행동에 따른 순위 변화 추가 확인 권장 |
| 로컬 생성형 AI (`Qwen/Qwen3.5-4B` on vLLM Metal `:8001`) | 구현 완료 | **실측 완료** | 컨테이너→호스트 스트리밍 TTFT `2,178.01 ms`, 전체 `8,298.14 ms` (64 청크) 확인 |
| 로컬 임베딩 AI (`Qwen/Qwen3-Embedding-0.6B` on MPS `:8002`) | 구현 완료 | **실측 완료** | 출력 차원 `1024`, L2 정규화, 컨테이너→호스트 배치(2건) `614.09 ms` 확인 |
| AI README 요약 / 번역 / 게시물 초안 API (`/api/ai/*`) | 구현 완료 | 모델 추론 검증 완료, **실계정 통합 필요** | GitHub 토큰으로 실제 저장소 README 조회 후 요약/번역 E2E 확인 필요 |
| SNS 기능 (팔로우/차단/게시물/좋아요/댓글/북마크/24h 스토리/알림) | 구현 완료 | **DB 통합 테스트 통과** | 브라우저 로그인 상태에서 UI 인터랙션 E2E 확인 필요 |
| 1:1 DM (PostgreSQL 영속 저장 + WebSocket `/api/dm/ws`) | 구현 완료 | 스키마·라우터 검증 완료, **2계정 검증 필요** | 최소 2개의 실제 GitHub 계정으로 실시간 송수신 및 읽음 상태 검증 필요 |
| 개인정보 설정 (추천 개인화 토글, 행동 로그 삭제, 계정 탈퇴) | 구현 완료 | API·UI 구현 완료 | 로그인 세션에서 삭제 동작 확인 필요 |
| AWS S3 미디어 업로드 / AWS 클라우드 배포 | 미구현 (설정 키만 분리) | 미검증 | 사용자 비용/자격증명 승인 전까지 유료 리소스 생성 금지 (`PROJECT_SPEC.md` 13, 16) |
| 오픈소스 라이선스 (`LICENSE`) | 미확정 | 미검증 | 프로젝트 소유자가 MIT 또는 Apache-2.0 등 최종 선택 필요 |

---

## 5. 다음 작업자가 바로 실행할 명령어 및 순서

### Step 1. 서비스 및 로컬 AI 서버 재기동

현재 모든 프로세스가 꺼져 있으므로 작업 재개 시 아래 순서로 기동한다:

```bash
# 1) 호스트 터미널 1: 생성형 AI 서버 (Qwen3.5-4B, 포트 8001)
/Users/shin/.venv-vllm-metal/bin/vllm serve Qwen/Qwen3.5-4B \
  --host 127.0.0.1 --port 8001 --max-model-len 4096 --language-model-only

# 2) 호스트 터미널 2: 임베딩 AI 서버 (Qwen3-Embedding-0.6B, 포트 8002)
/Users/shin/.venv-vllm-metal/bin/python scripts/embedding_server.py

# 3) 호스트 터미널 3: Docker Compose 기동 및 상태 확인
docker compose up -d
docker compose ps
curl -f http://localhost:8000/health
curl -f http://127.0.0.1:8001/v1/models
curl -f http://127.0.0.1:8002/health
```

### Step 2. 기존 테스트 및 타입체크 재확인

```bash
docker compose exec -T api pytest -q
docker compose exec -T web npm run typecheck
```

### Step 3. 실제 GitHub App 자격증명 설정 및 실계정 검증 (최우선 남은 과제)

1. 사용자가 [GitHub Developer Settings](https://github.com/settings/apps/new)에서 GitHub App을 생성한다.
   - **Homepage URL**: `http://localhost:3000`
   - **Callback URL**: `http://localhost:8000/api/auth/callback`
   - **User permissions** → **Starring**: `Read-only`
2. 루트 `.env` 파일의 `GITHUB_CLIENT_ID=`와 `GITHUB_CLIENT_SECRET=`에 값을 직접 입력한다 (채팅창이나 Git에 노출 금지).
3. `docker compose up -d api worker`로 환경 변수를 반영한 뒤 `http://localhost:3000`에서 실제 GitHub 계정으로 로그인한다.
4. 검증할 항목:
   - `/api/sync/status`가 `complete`가 되고 `embedded_repositories` 수가 증가하는지 확인
   - 프로필/소유 저장소/Star 수가 실제 GitHub 웹·API 응답과 일치하는지 대조
   - Explore에서 `For You`(`hybrid-pgvector-v2`), `Trending`, `Following`, 카테고리 필터, 자연어 검색(`github_search+semantic_rerank`) 동작 확인
   - 저장소 카드에서 `AI 요약`, `README 번역`, Home에서 `AI 초안 생성` 및 게시물·24h 스토리 작성 확인
   - 두 번째 실제 GitHub 계정으로 별도 브라우저(또는 시크릿 창)에서 로그인하여 팔로우 알림 및 1:1 WebSocket DM 송수신·읽음 처리 검증

### Step 4. 추가 고도화 후보 (실계정 검증 이후)

- GitHub API 조건부 요청(`ETag` / `If-None-Match`) 캐시 테이블 또는 Redis 캐시 추가로 Rate Limit 소모 절감
- Playwright 기반 브라우저 E2E 테스트 추가
- 동시 요청(1, 2, 4, 8) 조건에서의 `Qwen/Qwen3.5-4B` vs `Qwen/Qwen3.5-9B` 상세 처리량·메모리 비교 벤치마크 문서화
- 프로젝트 소유자의 승인 후 `LICENSE` 파일 추가 및 AWS 배포용 Terraform/ECS 작업 정의 초안(`infra/`) 추가
