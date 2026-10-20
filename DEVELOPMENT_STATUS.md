# Gitstargram 개발 현황 및 AI 인계 문서

마지막 갱신: 2026-10-20 (Asia/Seoul)

> **중요 (인계 원칙):**
> 1. 이 문서는 **코드 구현 상태**와 **실측·통합 검증 완료 상태**를 엄격히 분리하여 기록한다.
> 2. 다음 작업자(또는 AI 에이전트)는 반드시 루트의 `PROJECT_SPEC.md`(원본 마스터 명세 1,727줄)와 이 문서를 먼저 읽고 이어서 진행한다.
> 3. **현재 작업 재개에 따라 Docker Desktop과 Compose 서비스를 재기동했다.** 아래 3차 세션 기록이 이전의 프로세스 종료 기록보다 우선한다. 호스트 AI 서버는 이번 작업에서 재기동하지 않았다. 기존 모델 캐시와 가상환경은 삭제하거나 변경하지 않았다.

## 현재 인계: 3차 세션 (2026-10-20)

### 시작점과 이번 작업의 선택 이유

- 시작 커밋: `4365dd6` (`10/20`), `main` 브랜치. 시작 시 작업 트리는 깨끗했다. 기존 명세, 진행 문서, API/모델/마이그레이션/CI/프론트엔드를 확인하고 이어서 작업했다.
- 사용자가 이번 대화에서 **GitHub App 자격증명은 아직 설정하지 않았다**고 확인했다. 실제 로그인, GitHub 사용자 데이터 동기화, 실계정 AI README 처리, 두 실제 계정 간 DM은 계속 미검증이다. 테스트용 사용자를 실제 GitHub 사용자라고 간주하지 않는다.
- 코드에서 DM WebSocket Origin 검증 누락, 차단 후 메시지 조회 허용, 연결 후 세션 폐기 미반영, 전송 키 재사용 시 다른 대화방 메시지 반환 문제를 확인했다. 실계정 설정과 독립적으로 수정할 수 있는 권한 경계를 이번 작업 범위로 정했다.

### 변경 파일과 구현 내용

| 파일 | 이번 변경 |
|---|---|
| `apps/api/app/dm.py` | WebSocket 접속 시 `FRONTEND_URL`과 Origin을 정확히 비교하고 잘못된 출처를 4403으로 거절. 세션 없거나 폐기되면 4401. 연결 중에는 최대 30초 간격과 각 메시지 수신 반복에서 세션을 재검사하며, **서버가 이벤트를 전달하기 직전에도** DB 세션의 사용자·해시·만료를 확인해 로그아웃한 연결에 새 DM을 보내지 않는다. 잘못된 JSON·객체가 아닌 JSON·4,096자를 넘는 제어 메시지는 4400으로 종료. |
| `apps/api/app/dm.py` | 대화 참여 검증에 양방향 차단 검사를 통합해 조회와 전송 모두 403 처리. 공백뿐인 메시지는 Pydantic 검증에서 거절. 같은 전송 키의 정상 재시도는 원래 메시지를 반환하고, 대화방·본문·공유 대상이 다르면 409. 동시 재시도는 DB 고유 제약과 `INSERT ... ON CONFLICT DO NOTHING RETURNING`으로 처리하여 중복 알림/전송을 방지하도록 구현. |
| `apps/api/tests/conftest.py` | 외부 트랜잭션과 SAVEPOINT를 사용하는 `isolated_db` 추가. 서비스가 내부에서 `commit()`해도 테스트 종료 시 전체 데이터 롤백. 각 테스트용 엔진도 dispose. |
| `apps/api/tests/test_recommend.py` | 기존 DB 테스트의 고정 ID 선삭제와 실제 커밋 후 수동 삭제를 제거하고 격리 fixture 적용. 기존 데이터와 ID가 충돌하면 실패하며 기존 데이터를 삭제하지 않는다. |
| `apps/api/tests/test_dm.py` | 새 회귀 테스트 7개: 외부 Origin, 쿠키 없는 접속, 공백 본문, 폐기된 WebSocket 세션, 이벤트 전달 전 세션 폐기, 비참여자 및 양방향 차단, 정상 재시도/다른 대화방·본문의 전송 키 재사용. DB 테스트의 사용자는 합성 fixture이고 외부 트랜잭션에서 롤백한다. |
| `AGENTS.md` | 다음 AI가 명세와 이 문서를 먼저 읽고, 변경 이유·명령·결과·미검증·다음 작업을 지속 기록하도록 루트 작업 지침 추가. |

### 이번 검증 결과

- `docker compose up -d --build`: 성공. PostgreSQL/Redis/API healthy, web/worker 기동, 마이그레이션 성공. 처음에는 Docker Desktop이 꺼져 있어 실행한 후 진행했다.
- 최신 호스트 소스를 읽기 전용 마운트한 API 테스트 컨테이너:
  ```bash
  docker compose run --rm --no-deps \
    -v /Users/shin/Documents/2026-2/Gitstargram/apps/api:/app:ro \
    api pytest -q -p no:cacheprovider
  ```
  **13 passed**, 0.33초. Starlette TestClient의 AnyIO `BlockingPortal` alias deprecation 경고 1개. 경고를 숨기거나 의존성을 임의로 업그레이드하지 않았다.
- `docker compose exec -T web npm run typecheck`: 성공.
- 수정 후 API/worker/migrate 이미지를 다시 빌드해 실행에 반영했다. 최종 `docker compose exec -T api pytest -q`: **13 passed, 1 warning in 0.28s**.
- 최종 연결 확인: 컨테이너 내부에서 API `/health` HTTP 200, web `/` HTTP 200. 호스트 `:8001` 생성형·`:8002` 임베딩 엔드포인트는 연결 불가(현재 꺼짐). DB의 이번 합성 테스트 사용자 수는 **0**으로 확인했다. 개발용 DB/Redis/API/worker/web은 실행 상태로 남겼다.
- `git diff --check`: 통과. 이번 작업은 커밋·push하지 않았다.
- 의미와 한계: PostgreSQL에서 대화 참여/차단/저장/재시도 경로를 호출했다. WebSocket Origin/폐기 테스트는 실제 ASGI WebSocket 처리기를 호출하되, 폐기 상태의 DB 조회는 단위 테스트 대역을 사용했다. **실제 로그인한 두 브라우저의 WebSocket E2E나 동시 HTTP 요청 경합 시험은 수행하지 않았다.**
- 이번 작업에서 로컬 AI 추론과 이전 세션의 성능 수치는 재측정하지 않았다. 아래 2차 세션 수치는 이전 기록으로 유지하며 현재 성능으로 보증하지 않는다.

### 다음 작업 순서와 아직 남은 결함

1. GitHub App 설정을 사용자가 로컬 `.env`에 완료하면 아래 Step 3 순서로 로그인부터 실제 GitHub 데이터와 DB·화면의 일치를 검증한다. Secret을 채팅이나 로그에 출력하지 않는다.
2. 두 실제 GitHub 계정으로 DM 연결·수신·로그아웃 후 이벤트 차단·사용자 차단·읽음·재연결을 확인한다. 정상 재시도의 동시 HTTP 요청 경합도 별도로 검증한다.
3. **DM 조회 GET이 읽음 상태를 변경하는 기존 설계가 남아 있다.** 조회와 명시적 읽음 갱신 API를 분리하고 Origin 검증을 적용하는 작업이 필요하다. 프론트엔드도 새 API를 호출해야 한다.
4. **1:1 대화 생성은 사용자 쌍의 DB 고유 제약이 없어 동시 생성 시 중복 대화방이 생길 수 있다.** 마이그레이션과 원자적 생성이 필요하다. 기존 데이터의 중복 처리 정책을 먼저 정해야 한다.
5. 기존 `0001`/`0002` 마이그레이션은 현재 `Base.metadata.create_all()`에 의존한다. 모델 변경에 따라 과거 마이그레이션 동작이 달라지고 `0002` downgrade가 테이블을 복구하지 않는다. 공개 배포 전에 명시적인 불변 스키마 마이그레이션으로 수정하고 빈 DB upgrade/downgrade를 시험해야 한다.
6. 게시물·댓글·북마크·공유 게시물 API의 차단 정책을 전체 점검한다. 현재 DM 검증만으로 모든 SNS 접근 경계가 검증됐다고 말하지 않는다. 개인화 off의 로그 수집 정책·보존기간·삭제도 별도 점검이 필요하다.
7. 이후 GitHub ETag/작업 큐 복구, Playwright E2E, 모델 비교 벤치마크, 의존성/보안 검사, S3·운영 배포를 진행한다. 라이선스와 유료 AWS 리소스는 소유자 결정이 필요하다.

이번 변경은 로컬 작업 트리에 있으며 원격으로 push하지 않았다. 작업 종료 시 `git status --short`와 아래 서비스 상태를 다시 확인한다.

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
| Docker / Compose | Engine 29.8.2, Compose v5.6.0 (3차 세션에서 재기동, DB/Redis 볼륨 보존) |
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

중지된 서비스를 재개할 때 아래 순서를 사용한다. 현재 실행 상태는 상단의 최신 세션 기록을 우선 확인한다:

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
