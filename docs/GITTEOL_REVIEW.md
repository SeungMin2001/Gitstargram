# GitTeol 참고 분석과 반영 계획

확인일: 2026-10-20. 참고 저장소: [SeungMin2001/GitTeol](https://github.com/SeungMin2001/GitTeol).
분석 기준 커밋: `e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89`.

GitTeol의 루트 README는 Expo 기본 템플릿 상태다. 제품 구조와 기능 판단에는 `ARCHITECTURE.md`와 관련 구현 파일을 사용했으며, 문서에 적힌 상태를 동작 검증으로 간주하지 않았다.

사용자가 과거에 개발한 동일 주제의 프로젝트를 참고해 현재 Gitstargram을 보완하도록 요청했다. 소스와 설계 문서를 읽고 기능의 의도를 비교했다. GitTeol의 데이터베이스 덤프·캐시·사용자 기록·이미지·런타임 설정을 현재 서비스에 가져오지 않았고, 해당 서비스를 직접 실행하거나 기능 성공을 검증한 것은 아니다. 아래 구현 상태는 GitTeol 소스에서 확인한 구조와 현재 프로젝트의 변경을 구분한다.

## 참고 가치와 이번 결정

| GitTeol에서 확인한 요소 | 현재 프로젝트와의 차이 | 반영 결정 |
|---|---|---|
| [`repoDetail.js`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/app/home/repoDetail.js): 저장소 상세, README 요약, 프로젝트별 활용 제안 | 기존 카드는 GitHub 링크와 개별 AI 작업만 제공 | **반영:** 상세 다이얼로그, 실제 언어별 bytes 비율·라이선스·README·수집 시각·원본 링크. 공개 여부를 GitHub에서 재확인한다. |
| [`usage_suggestion.py`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/backend/routers/usage_suggestion.py): 내 프로젝트와 발견한 저장소를 비교해 적용 방안 생성 | 기존 AI 기능은 저장소 하나의 요약·번역·게시물 초안 | **반영:** 로그인 사용자 소유 프로젝트의 DB 관계·GitHub 소유권을 확인하고 두 저장소의 공개 메타데이터와 README를 근거로 로컬 Qwen에 제안 요청. 클라이언트가 보낸 설명을 사실로 신뢰하지 않는다. |
| [`recommendation_engine.py`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/backend/services/recommendation_engine.py): 추천 이유 생성 및 저장 | 현재 API도 reasons를 반환하지만 화면에서는 해시태그처럼 표시 | **반영:** 상세 화면에서 관심 Topic·언어, 임베딩 유사도, 팔로잉, 관측 스냅샷의 신호를 문장으로 표시. AI가 새로운 추천 이유를 만들어내지 않는다. |
| [`user_activity_timeline.py`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/backend/services/user_activity_timeline.py), [`analytics.py`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/backend/routers/analytics.py): 검색·체류·상호작용 통합 | 현재 클릭/북마크/관심없음/노출 로그가 있으나 수집 정책은 보강 필요 | **후속:** 동의, 보유 기간, 사용자 식별 검증, 삭제를 먼저 정하고 가시성·활성 시간만 수집. 사용자 이름 입력만으로 다른 사용자의 로그를 조회하는 API는 이식하지 않는다. |
| [`llm_prediction_service.py`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/backend/services/llm_prediction_service.py): 활동 이야기를 LLM에 보내 관심사 예측 | 현재 pgvector와 해석 가능한 랭킹 사용 | **보류:** 실제 평가 데이터·추론 비용·로그 동의가 준비된 뒤 비교 실험. 예측이 정확하다는 실측은 이 코드 분석으로 확인되지 않는다. |
| [`ARCHITECTURE.md`](https://github.com/SeungMin2001/GitTeol/blob/e60bcaa92f786b09bb893222c4d5d1c3a4d5ef89/ARCHITECTURE.md): 페이지네이션·캐시·README 이미지 추출 및 S3 썸네일 | 현재 목록 상한과 API 호출 비용, 메타데이터 카드가 있음 | **후속:** cursor/ETag 캐시 우선. 이미지 자동 다운로드·S3 복제는 저작권·외부 URL 검증·비용 승인 없이 이식하지 않는다. |

## 현재 프로젝트에 추가한 계약

### `GET /api/repositories/{repository_id}`

- 로그인 필요. 캐시된 공개 저장소를 찾은 후 GitHub의 실제 공개 여부와 고유 ID를 다시 확인한다.
- 반환: 공개 메타데이터, Star/Fork/Open issues, 라이선스, 언어별 코드 bytes와 비율, README 원문 최대 12,000자, 출처·SHA·확인 시각.
- README 없음(`missing`)과 불러오기 실패(`unavailable`)를 구분한다. 언어 조회 실패도 별도로 표시한다. 선택 섹션의 실패가 나머지 실제 메타데이터를 가리지 않는다.
- HTML/Markdown을 실행하지 않고 React 텍스트와 `<pre>`로 표시한다. 이미지 다운로드·외부 HTML 렌더링은 없다.
- 추천 설명은 요청 시의 실제 랭킹 신호만 사용한다. Trending에서 관심 기술·팔로잉을 순위 근거로 주장하지 않으며, 소셜 점수가 없는 메타데이터 fallback에서도 팔로잉을 순위 이유로 추가하지 않는다. 카드 해시태그는 실제 저장소 Topic만 표시한다.
- 서버 모듈: `apps/api/app/repository_details.py`. UI: `apps/web/components/RepositoryDetailDialog.tsx`.

### `POST /api/ai/usage-suggestion`

```json
{"project_repository_id": 123, "target_repository_id": 456}
```

- 로그인과 Origin 검사 필요. 서로 다른 공개 저장소여야 한다.
- 기준 프로젝트는 로그인 사용자의 `owned` 관계가 있어야 하며 DB의 `owner_github_id`와 GitHub에서 조회한 실제 소유자 ID가 사용자 GitHub ID와 같아야 한다.
- 요청마다 실제 GitHub 메타데이터와 README를 읽고 각 README 최대 1,500자를 사용한다. 누락된 README는 메타데이터만 사용했다는 사실을 응답에 기록한다. 외부 API 장애는 근거가 없다는 상태로 실패하며 임의 자료로 대체하지 않는다.
- 기존 `call_chat_model`과 로컬 Qwen 엔드포인트를 사용한다. 자료에서 확인된 기능과 적용 가설을 구분하고, 관련성이 낮으면 그렇게 설명하도록 지시한다.
- 응답: `suggestion`, 두 `sources`, 모델, 지연, 사용량, `generated=true`, `requires_user_review=true`. 자동 게시·설치·라이선스 승인 동작은 없다.

## 이번 범위의 한계와 다음 작업

1. GitHub App 자격증명이 없으므로 실제 사용자 로그인, 상세 화면의 로그인 E2E, 실제 프로젝트 간 모델 추론은 미검증이다. 테스트 대역의 모델 응답을 실제 추론으로 보고하지 않는다.
2. 상세 조회마다 최대 3개, 활용 제안마다 최대 4개의 GitHub 요청이 발생한다. 다음 단계에서 세션/토큰을 노출하지 않는 ETag 캐시와 호출 제한을 추가한다. AI 결과 캐시는 양쪽 README SHA·모델·프롬프트 버전별로 무효화해야 한다.
3. README는 일부 원문만 표시/사용한다. 문서 전체에 대한 이해나 번역 보존을 보증하지 않는다. 기존 번역 API의 Markdown 보존 검증과 출력 잘림 감지도 별도 보완이 필요하다.
4. 새 UI는 native `<dialog>`를 사용해 키보드 Esc와 기본 포커스 처리를 제공하고, 닫을 때 진행 중인 브라우저 요청을 취소한다. 서버에서 이미 시작한 모델 계산까지 취소되는 것은 보장하지 않는다.
5. 현재 `owned` 목록 API는 최대 100개다. 전체 프로젝트 선택과 무한 스크롤을 위해 cursor 페이지네이션을 추가해야 한다.
6. 체류 시간과 관심사 예측, 이미지 수집은 개인정보·권한 설계 후 확장한다. 이번 변경으로 추천 품질이 향상됐다는 수치는 제시하지 않는다.

## 공식 API 근거

- [GitHub 언어 목록](https://docs.github.com/en/rest/repos/repos#list-repository-languages): 값은 언어별 코드 bytes다. 표시하는 비율은 서버가 그 합계로 계산한다.
- [GitHub README API](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme): Base64 응답을 서버에서 해독하며 원본 링크를 유지한다.

실행 명령과 실제 결과는 `DEVELOPMENT_STATUS.md`의 최신 세션 기록을 확인한다.
