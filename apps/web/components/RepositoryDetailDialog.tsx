"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

type RepositoryRef = { id: number; full_name: string; reasons?: string[] };
type Detail = {
  full_name: string; description: string | null; html_url: string; stars: number; forks: number;
  open_issues: number; archived: boolean; topics: string[]; fetched_at: string;
  license: { name: string | null; spdx_id: string | null };
  languages_status: string; languages: { name: string; bytes: number; percentage: number }[];
  readme: { status: string; text: string; source_url: string; truncated: boolean };
};
type Suggestion = {
  suggestion: string; model: string; sources: { repository_id: number; full_name: string; url: string; readme_status: string; truncated: boolean }[];
};

function reasonLabel(reason: string): string {
  if (reason === "semantic-match") return "관심 저장소와 임베딩 유사도가 높아요";
  if (reason === "following-author") return "팔로우하는 개발자의 프로젝트예요";
  if (reason === "github-popularity") return "현재 GitHub Star 수를 순위에 반영했어요";
  if (reason === "push-recency") return "마지막 코드 푸시 시점의 최신성을 반영했어요";
  if (/^\+\d+ stars \(snapshot\)$/.test(reason)) return `수집한 스냅샷 사이 GitHub Star ${reason.split(" ")[0]}개`;
  return `관심 언어·Topic과 일치: ${reason}`;
}

export function RepositoryDetailDialog({ repo, projects, aiAvailable, onClose }: {
  repo: RepositoryRef; projects: RepositoryRef[]; aiAvailable: boolean; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [aiError, setAiError] = useState("");
  const [generating, setGenerating] = useState(false);
  const options = projects.filter(project => project.id !== repo.id);

  useEffect(() => {
    dialog.current?.showModal();
    const controller = new AbortController();
    api<Detail>(`/api/repositories/${repo.id}`, { signal: controller.signal })
      .then(setDetail).catch(error => { if (!controller.signal.aborted) setDetailError(error.message); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [repo.id]);

  async function generateSuggestion() {
    if (!projectId || generating) return;
    setGenerating(true); setAiError(""); setSuggestion(null);
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await api<Suggestion>("/api/ai/usage-suggestion", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ project_repository_id: Number(projectId), target_repository_id: repo.id }),
      });
      setSuggestion(result);
    } catch (error) { if (!controller.signal.aborted) setAiError((error as Error).message); }
    finally { if (!controller.signal.aborted) setGenerating(false); }
  }

  return <dialog ref={dialog} className="repo-detail-dialog" aria-labelledby="repo-detail-title"
    onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="repo-detail-body">
      <button className="modal-close" type="button" onClick={onClose} aria-label="저장소 상세 닫기">✕</button>
      <div className="eyebrow">PROJECT DETAILS</div><h2 id="repo-detail-title">{detail?.full_name ?? repo.full_name}</h2>
      {!detail && !detailError && <p role="status">GitHub에서 프로젝트 정보를 가져오는 중...</p>}
      {detailError && <p className="detail-error" role="alert">{detailError}</p>}
      {detail && <>
        <p>{detail.description || "GitHub에 설명이 등록되지 않았습니다."}</p>
        {detail.archived && <p className="detail-warning">보관된 저장소입니다. 유지보수 상태를 확인하세요.</p>}
        <div className="detail-metrics"><span>GitHub Star <b>{detail.stars.toLocaleString()}</b></span><span>Fork <b>{detail.forks.toLocaleString()}</b></span><span>Open issues <b>{detail.open_issues.toLocaleString()}</b></span></div>
        <p className="detail-meta">라이선스: {detail.license.spdx_id && detail.license.spdx_id !== "NOASSERTION" ? detail.license.spdx_id : detail.license.name || "확인되지 않음"} · 확인 시각: {new Date(detail.fetched_at).toLocaleString("ko-KR")}</p>
        <a className="outline-button" href={detail.html_url} target="_blank" rel="noopener noreferrer">GitHub 원본 열기 ↗</a>
        <section className="detail-section"><h3>언어 구성</h3>
          {detail.languages_status !== "available" ? <p>언어 정보를 불러오지 못했습니다.</p> : detail.languages.length === 0 ? <p>등록된 언어 정보가 없습니다.</p> : <ul className="language-list">{detail.languages.map(language => <li key={language.name}><span>{language.name}</span><strong>{language.percentage}%</strong><small>{language.bytes.toLocaleString()} bytes</small></li>)}</ul>}
        </section>
        {!!repo.reasons?.length && <section className="detail-section"><h3>이 프로젝트를 추천한 이유</h3><ul>{repo.reasons.map(reason => <li key={reason}>{reasonLabel(reason)}</li>)}</ul><p className="detail-meta">현재 추천 응답에 기록된 신호입니다. 프로젝트의 품질이나 적용 가능성을 보증하지 않습니다.</p></section>}
        <section className="detail-section"><h3>내 프로젝트에 활용하기</h3><p>내 공개 프로젝트와 이 저장소의 실제 설명·README를 비교해 적용 아이디어를 요청할 수 있어요.</p>
          {!aiAvailable && <p className="detail-warning">AI 서버가 준비되지 않았습니다. 서버 상태를 확인한 후 다시 시도하세요.</p>}
          {options.length === 0 ? <p>먼저 내 공개 저장소를 동기화해주세요. 비교할 다른 프로젝트가 필요합니다.</p> : <div className="usage-controls"><select value={projectId} disabled={generating} onChange={event => { setProjectId(event.target.value); setSuggestion(null); setAiError(""); }} aria-label="비교할 내 공개 프로젝트"><option value="">내 프로젝트 선택</option>{options.map(project => <option key={project.id} value={project.id}>{project.full_name}</option>)}</select><button className="outline-button" type="button" onClick={generateSuggestion} disabled={!projectId || generating || !aiAvailable}>{generating ? "분석 중..." : "활용 방안 제안"}</button></div>}
          {generating && <p role="status">두 프로젝트의 공개 자료를 확인하고 제안을 생성하는 중...</p>}
          {aiError && <p role="alert" className="detail-error">{aiError}</p>}
          {suggestion && <div className="usage-result"><strong>AI 제안 · 적용 전 검토 필요</strong><p>{suggestion.suggestion}</p><ul>{suggestion.sources.map(source => <li key={source.repository_id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.full_name} 원문 ↗</a>{source.readme_status === "missing" && <small> · README 없음: 메타데이터만 사용</small>}{source.truncated && <small> · README 일부 사용</small>}</li>)}</ul><small>모델: {suggestion.model}</small></div>}
        </section>
        <section className="detail-section"><h3>README 원문</h3>
          {detail.readme.status === "missing" ? <p>GitHub에 README가 없습니다.</p> : detail.readme.status === "unavailable" ? <p>README를 불러오지 못했습니다. 원본 저장소에서 확인해주세요.</p> : <><pre className="readme-source">{detail.readme.text}</pre>{detail.readme.truncated && <p className="detail-warning">README가 길어 앞부분만 표시합니다.</p>}<a href={detail.readme.source_url} target="_blank" rel="noopener noreferrer">전체 README 원문 ↗</a></>}
        </section>
      </>}
    </div>
  </dialog>;
}
