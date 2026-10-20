"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API } from "../lib/api";
import { RepositoryDetailDialog } from "../components/RepositoryDetailDialog";

type User = {
  id: number; login: string; name: string | null; avatar_url: string | null; bio: string | null;
  html_url: string; public_repos: number; followers: number; following: number; updated_at: string;
  sns_followers?: number; sns_following?: number; sns_posts?: number; sns_bookmarks?: number;
};
type Repo = {
  id: number; full_name: string; owner_login: string; name: string; description: string | null;
  html_url: string; language: string | null; topics: string[]; stars: number; forks: number;
  pushed_at: string | null; fetched_at: string; source: string; reasons?: string[]; score?: number; bookmarked?: boolean;
};
type Sync = { status: string; detail?: string | null; completed_at?: string | null; embedded_repositories?: number };
type PostItem = {
  id: number; title: string; body: string; tags: string[]; ai_assisted: boolean;
  like_count: number; comment_count: number; liked: boolean; bookmarked: boolean; created_at: string;
  author: { id: number; login: string; name: string | null; avatar_url: string | null } | null;
  repository: { id: number; full_name: string; name: string; owner_login: string; html_url: string; language: string | null; stars: number; topics: string[] } | null;
};
type CommentItem = { id: number; post_id: number; body: string; created_at: string; author: { id: number; login: string; name: string | null } | null };
type StoryItem = {
  id: number; kind: string; title: string; summary: string; source_url: string | null;
  created_at: string; expires_at: string; viewed: boolean; view_count: number;
  author: { id: number; login: string; name: string | null; avatar_url: string | null } | null;
  repository: { id: number; full_name: string; html_url: string } | null;
};
type SocialUser = {
  id: number; login: string; name: string | null; avatar_url: string | null; bio: string | null;
  html_url: string; github_followers: number; sns_followers: number; sns_following: number; sns_posts: number;
  is_following: boolean; is_self: boolean;
};
type ConversationItem = {
  id: number; peer: { id: number; login: string; name: string | null; avatar_url: string | null };
  peer_last_read_message_id: number | null; unread_count: number; updated_at: string;
  last_message: DmMessage | null;
};
type DmMessage = {
  id: number; conversation_id: number; body: string; created_at: string;
  sender: { id: number; login: string; name: string | null } | null;
  shared_repository: { id: number; full_name: string; html_url: string; stars: number } | null;
};
type NotificationItem = { id: number; kind: string; message: string; is_read: boolean; created_at: string };
type UserSettings = {
  theme: "dark" | "light"; language: "ko" | "en"; personalized_recommendations: boolean;
  auto_story_enabled: boolean; notifications_enabled: boolean;
};
type AiStatus = { available: boolean; model: string; embedding_available: boolean; embedding_model: string; embedding_dimensions: number };
type Tab = "home" | "explore" | "profile" | "dm";
type ExploreMode = "for-you" | "trending" | "following";
type ExploreCategory = "all" | "ai-ml" | "frontend" | "backend" | "devops-tools";

function Icon({ name, size = 22 }: { name: string; size?: number }) {
  const shared = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<string, React.ReactNode> = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path d="M9 21v-7h6v7" /></>,
    explore: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    profile: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
    dm: <path d="M20 11.5a8.5 8.5 0 0 1-8.5 8.5H4l1.7-4.1A8.5 8.5 0 1 1 20 11.5Z" />,
    star: <path d="m12 2 2.9 6.2 6.8.9-5 4.8 1.2 6.8L12 17.5l-5.9 3.2 1.2-6.8-5-4.8 6.8-.9z" />,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    refresh: <><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 12.4-2l2 5M4 12l2 5a7 7 0 0 0 12.4-2" /></>,
    code: <><path d="m8 8-4 4 4 4M16 8l4 4-4 4m-3-11-2 22" /></>,
    close: <><path d="M5 5 19 19M19 5 5 19" /></>,
  };
  return <svg {...shared} aria-hidden="true">{paths[name]}</svg>;
}

function relativeDate(value: string | null) {
  if (!value) return "업데이트 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

function RepoCard({
  repo, compact = false, onOpen, onDismiss, onSummary, onTranslate, onBookmark, onDetail,
}: {
  repo: Repo; compact?: boolean; onOpen?: (repo: Repo) => void; onDismiss?: (repo: Repo) => void;
  onSummary?: (repo: Repo) => void; onTranslate?: (repo: Repo) => void; onBookmark?: (repo: Repo) => void;
  onDetail?: (repo: Repo) => void;
}) {
  const hue = [...repo.full_name].reduce((acc, char) => acc + char.charCodeAt(0), 0) % 360;
  return <article className={`repo-card ${compact ? "compact" : ""}`}>
    <a className="repo-card-link" href={repo.html_url} target="_blank" rel="noopener noreferrer" onClick={() => onOpen?.(repo)} aria-label={`${repo.full_name} GitHub에서 열기`}>
      <div className="repo-art" style={{ "--card-hue": hue } as React.CSSProperties}>
        <div className="repo-art-grid" /><span className="repo-art-glyph"><Icon name="code" size={compact ? 26 : 34} /></span>
        <span className="repo-art-language">{repo.language ?? "Repository"}</span>
      </div>
      <div className="repo-content">
        <div className="repo-heading"><span className="repo-owner">{repo.owner_login}</span><Icon name="arrow" size={17} /></div>
        <h3>{repo.name}</h3>
        <p>{repo.description || "GitHub에 설명이 등록되지 않았습니다."}</p>
        <div className="repo-topics">
          {repo.topics.slice(0, 3).map(topic => <span key={topic}>#{topic}</span>)}
        </div>
        <div className="repo-footer"><span><Icon name="star" size={15} /> GitHub Star {repo.stars.toLocaleString()}</span><span>{relativeDate(repo.fetched_at)} 수집</span></div>
      </div>
    </a>
    <div className="card-actions">
      {onDetail && <button className="summary-btn" type="button" onClick={() => onDetail(repo)}>상세 보기</button>}
      {onSummary && <button className="summary-btn" type="button" onClick={() => onSummary(repo)}>AI 요약</button>}
      {onTranslate && <button className="summary-btn" type="button" onClick={() => onTranslate(repo)}>README 번역</button>}
      {onBookmark && <button className="summary-btn" type="button" onClick={() => onBookmark(repo)}>{repo.bookmarked ? "북마크됨" : "북마크"}</button>}
    </div>
    {onDismiss && <button className="dismiss-btn" type="button" onClick={() => onDismiss(repo)}>관심 없음</button>}
  </article>;
}

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("home");
  const [mode, setMode] = useState<ExploreMode>("for-you");
  const [category, setCategory] = useState<ExploreCategory>("all");
  const [exploreAlgo, setExploreAlgo] = useState<string>("metadata-coldstart-v1");
  const [owned, setOwned] = useState<Repo[]>([]);
  const [starred, setStarred] = useState<Repo[]>([]);
  const [explore, setExplore] = useState<Repo[]>([]);
  const [searchResults, setSearchResults] = useState<Repo[] | null>(null);
  const [query, setQuery] = useState("");
  const [sync, setSync] = useState<Sync | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hiddenIds, setHiddenIds] = useState<number[]>([]);
  const [aiModal, setAiModal] = useState<{ title: string; subtitle: string; text: string; source: string; truncated: boolean; latencyMs?: number } | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [detailRepo, setDetailRepo] = useState<Repo | null>(null);

  // Social & Feed state
  const [feedMode, setFeedMode] = useState<"following" | "recommended">("following");
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [stories, setStories] = useState<StoryItem[]>([]);
  const [activeStory, setActiveStory] = useState<StoryItem | null>(null);
  const [socialUsers, setSocialUsers] = useState<SocialUser[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [showNotifications, setShowNotifications] = useState(false);

  // Composer state
  const [postTitle, setPostTitle] = useState("");
  const [postBody, setPostBody] = useState("");
  const [postRepoId, setPostRepoId] = useState<string>("");
  const [postTags, setPostTags] = useState("");
  const [postAiAssisted, setPostAiAssisted] = useState(false);
  const [storyTitle, setStoryTitle] = useState("");
  const [storySummary, setStorySummary] = useState("");
  const [showStoryForm, setShowStoryForm] = useState(false);
  const [activeCommentsPostId, setActiveCommentsPostId] = useState<number | null>(null);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [commentText, setCommentText] = useState("");

  // Settings & Profile state
  const [userSettings, setUserSettings] = useState<UserSettings>({
    theme: "dark", language: "ko", personalized_recommendations: true, auto_story_enabled: false, notifications_enabled: true,
  });
  const [editName, setEditName] = useState("");
  const [editBio, setEditBio] = useState("");

  // DM state
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [dmMessages, setDmMessages] = useState<DmMessage[]>([]);
  const [dmInput, setDmInput] = useState("");

  const loadData = useCallback(async () => {
    const [ownedData, starredData, exploreData, syncData, postsData, storiesData, usersData, notifData, settingsData, aiData, convData] = await Promise.all([
      api<{ items: Repo[] }>("/api/repositories?kind=owned"),
      api<{ items: Repo[] }>("/api/repositories?kind=starred"),
      api<{ items: Repo[]; algorithm: string }>(`/api/explore?mode=${mode}&category=${category}`),
      api<Sync>("/api/sync/status"),
      api<{ items: PostItem[] }>(`/api/social/posts?feed=${feedMode}`),
      api<{ items: StoryItem[] }>("/api/social/stories"),
      api<{ items: SocialUser[] }>("/api/social/users"),
      api<{ unread_count: number; items: NotificationItem[] }>("/api/social/notifications"),
      api<UserSettings>("/api/social/settings"),
      api<AiStatus>("/api/ai/status").catch(() => null),
      api<{ items: ConversationItem[] }>("/api/dm/conversations"),
    ]);
    setOwned(ownedData.items);
    setStarred(starredData.items);
    setExplore(exploreData.items);
    setExploreAlgo(exploreData.algorithm);
    setSync(syncData);
    setPosts(postsData.items);
    setStories(storiesData.items);
    setSocialUsers(usersData.items);
    setNotifications(notifData.items);
    setUnreadNotifications(notifData.unread_count);
    setUserSettings(settingsData);
    document.documentElement.setAttribute("data-theme", settingsData.theme);
    if (aiData) setAiStatus(aiData);
    setConversations(convData.items);
  }, [mode, category, feedMode]);

  useEffect(() => {
    api<User>("/api/me").then(u => { setUser(u); setEditName(u.name || ""); setEditBio(u.bio || ""); }).catch(() => setUser(null)).finally(() => setAuthLoading(false));
  }, []);
  useEffect(() => { if (user) loadData().catch(err => setError(err.message)); }, [user, loadData]);
  useEffect(() => {
    if (!user || (sync?.status !== "queued" && sync?.status !== "running")) return;
    const id = window.setInterval(() => loadData().catch(err => setError(err.message)), 4000);
    return () => window.clearInterval(id);
  }, [user, sync?.status, loadData]);

  useEffect(() => {
    if (!user || !activeConversationId) return;
    api<{ items: DmMessage[] }>(`/api/dm/conversations/${activeConversationId}/messages`)
      .then(d => setDmMessages(d.items))
      .catch(err => setError(err.message));
  }, [user, activeConversationId]);

  useEffect(() => {
    if (!user) return;
    const wsUrl = API.replace(/^http/, "ws") + "/api/dm/ws";
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = event => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "message" && data.message) {
            const msg: DmMessage = data.message;
            setDmMessages(prev => (msg.conversation_id === activeConversationId && !prev.some(m => m.id === msg.id) ? [...prev, msg] : prev));
            void api<{ items: ConversationItem[] }>("/api/dm/conversations").then(c => setConversations(c.items));
          }
        } catch { /* ignore malformed ws frame */ }
      };
    } catch { /* websocket optional fallback */ }
    return () => { ws?.close(); };
  }, [user, activeConversationId]);

  const languages = useMemo(() => [...new Set([...starred, ...owned].map(repo => repo.language).filter((value): value is string => !!value))].slice(0, 6), [starred, owned]);
  const [language, setLanguage] = useState("");
  const visibleExplore = (searchResults ?? explore).filter(repo => !hiddenIds.includes(repo.id) && (!language || repo.language?.toLowerCase() === language.toLowerCase()));

  async function startSync() {
    setBusy(true); setError("");
    try { await api("/api/sync", { method: "POST" }); await loadData(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function syncEmbeddings() {
    setBusy(true); setError("");
    try { await api("/api/embeddings/sync", { method: "POST" }); await loadData(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function search(event: React.FormEvent) {
    event.preventDefault(); if (query.trim().length < 2) return;
    setBusy(true); setError("");
    try { const data = await api<{ items: Repo[] }>(`/api/search?q=${encodeURIComponent(query.trim())}`); setSearchResults(data.items); setTab("explore"); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  function track(repo: Repo, action: "click" | "not_interested" | "bookmark") {
    void api("/api/interactions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: repo.id, action }) }).catch(() => {});
  }
  function dismiss(repo: Repo) { track(repo, "not_interested"); setHiddenIds(ids => [...ids, repo.id]); }
  async function toggleRepoBookmark(repo: Repo) {
    try {
      await api("/api/social/bookmarks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: repo.id }) });
      await loadData();
    } catch (err) { setError((err as Error).message); }
  }
  async function summarize(repo: Repo) {
    setSummaryLoading(true); setError("");
    try {
      const result = await api<{ summary: string; source_url: string; source_truncated: boolean; latency_ms?: number }>("/api/ai/summary", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: repo.id }),
      });
      setAiModal({ title: repo.full_name, subtitle: "AI GENERATED SUMMARY · VERIFY WITH SOURCE", text: result.summary, source: result.source_url, truncated: result.source_truncated, latencyMs: result.latency_ms });
    } catch (err) { setError(`AI 요약을 사용할 수 없습니다: ${(err as Error).message}`); }
    finally { setSummaryLoading(false); }
  }
  async function translateReadme(repo: Repo) {
    setSummaryLoading(true); setError("");
    try {
      const result = await api<{ translation: string; source_url: string; source_truncated: boolean; latency_ms?: number }>("/api/ai/translate", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: repo.id, target_language: "ko" }),
      });
      setAiModal({ title: `${repo.full_name} (README 번역)`, subtitle: "AI README TRANSLATION · VERIFY WITH SOURCE", text: result.translation, source: result.source_url, truncated: result.source_truncated, latencyMs: result.latency_ms });
    } catch (err) { setError(`README 번역을 사용할 수 없습니다: ${(err as Error).message}`); }
    finally { setSummaryLoading(false); }
  }
  async function generateDraft() {
    if (!postRepoId) { setError("AI 초안을 생성하려면 먼저 연결할 저장소를 선택하세요."); return; }
    setSummaryLoading(true); setError("");
    try {
      const draft = await api<{ title: string; body: string; tags: string[] }>("/api/ai/post-draft", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: Number(postRepoId) }),
      });
      setPostTitle(draft.title); setPostBody(draft.body); setPostTags(draft.tags.join(", ")); setPostAiAssisted(true);
    } catch (err) { setError(`AI 초안 생성 실패: ${(err as Error).message}`); }
    finally { setSummaryLoading(false); }
  }
  async function submitPost(event: React.FormEvent) {
    event.preventDefault();
    if (!postTitle.trim() || !postBody.trim()) return;
    setBusy(true); setError("");
    try {
      await api("/api/social/posts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: postTitle, body: postBody,
          repository_id: postRepoId ? Number(postRepoId) : null,
          tags: postTags.split(",").map(s => s.trim()).filter(Boolean),
          ai_assisted: postAiAssisted,
        }),
      });
      setPostTitle(""); setPostBody(""); setPostRepoId(""); setPostTags(""); setPostAiAssisted(false);
      await loadData();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function submitStory(event: React.FormEvent) {
    event.preventDefault();
    if (!storyTitle.trim() || !storySummary.trim()) return;
    setBusy(true); setError("");
    try {
      await api("/api/social/stories", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: storyTitle, summary: storySummary, kind: "update" }),
      });
      setStoryTitle(""); setStorySummary(""); setShowStoryForm(false);
      await loadData();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function openStory(story: StoryItem) {
    setActiveStory(story);
    await api(`/api/social/stories/${story.id}/view`, { method: "POST" }).catch(() => {});
    await loadData();
  }
  async function toggleLike(post: PostItem) {
    try {
      await api(`/api/social/posts/${post.id}/like`, { method: post.liked ? "DELETE" : "POST" });
      await loadData();
    } catch (err) { setError((err as Error).message); }
  }
  async function openComments(postId: number) {
    setActiveCommentsPostId(postId);
    const data = await api<{ items: CommentItem[] }>(`/api/social/posts/${postId}/comments`);
    setComments(data.items);
  }
  async function submitComment(event: React.FormEvent) {
    event.preventDefault();
    if (!activeCommentsPostId || !commentText.trim()) return;
    await api(`/api/social/posts/${activeCommentsPostId}/comments`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: commentText }),
    });
    setCommentText("");
    await openComments(activeCommentsPostId);
    await loadData();
  }
  async function toggleFollow(target: SocialUser) {
    await api(`/api/social/follow/${target.id}`, { method: target.is_following ? "DELETE" : "POST" });
    await loadData();
  }
  async function startChatWith(targetUserId: number) {
    const res = await api<{ conversation_id: number }>("/api/dm/conversations", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recipient_user_id: targetUserId }),
    });
    await loadData();
    setActiveConversationId(res.conversation_id);
    setTab("dm");
  }
  async function sendDm(event: React.FormEvent) {
    event.preventDefault();
    if (!activeConversationId || !dmInput.trim()) return;
    const msg = await api<DmMessage>(`/api/dm/conversations/${activeConversationId}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: dmInput, client_message_id: `${Date.now()}-${Math.random()}` }),
    });
    setDmInput("");
    setDmMessages(prev => (prev.some(m => m.id === msg.id) ? prev : [...prev, msg]));
    await loadData();
  }
  async function saveSettings(next: UserSettings) {
    const saved = await api<UserSettings>("/api/social/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next),
    });
    setUserSettings(saved);
    document.documentElement.setAttribute("data-theme", saved.theme);
    await loadData();
  }
  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    await api("/api/social/profile", {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: editName, bio: editBio }),
    });
    const updated = await api<User>("/api/me");
    setUser(updated);
  }
  async function clearLogs() {
    if (!window.confirm("저장된 추천 노출 기록과 클릭/관심없음 행동 로그를 모두 삭제할까요?")) return;
    await api("/api/social/interactions", { method: "DELETE" });
    setHiddenIds([]);
    await loadData();
  }
  async function logout() { await api("/api/auth/logout", { method: "POST" }); window.location.reload(); }
  async function deleteAccount() {
    if (!window.confirm("계정을 삭제할까요? 저장된 세션, GitHub 연결, Star 관계와 사용 기록이 삭제됩니다.")) return;
    try { await api("/api/auth/account", { method: "DELETE" }); window.location.reload(); }
    catch (err) { setError((err as Error).message); }
  }

  if (authLoading) return <div className="boot-screen"><span className="brand-mark">g<span>.</span></span><p>Gitstargram을 여는 중...</p></div>;
  if (!user) return <main className="welcome"><div className="welcome-glow" /><header className="welcome-header"><span className="brand-mark">g<span>.</span></span><span>GITSTARGRAM / EARLY BUILD</span></header><section className="welcome-copy"><div className="eyebrow"><span className="live-dot" /> REAL CODE. REAL PEOPLE.</div><h1>좋은 코드는<br /><em>발견</em>되어야 하니까.</h1><p>내 GitHub 활동을 연결하고, 관심 기술을 바탕으로 실제 오픈소스 프로젝트를 탐색해보세요.</p><a className="primary-button" href={`${API}/api/auth/login`}>GitHub로 시작하기 <Icon name="arrow" size={18} /></a><small>GitHub App 사용자 인증이 필요합니다. 아직 앱 설정이 없다면 서버가 안내합니다.</small></section><div className="welcome-decoration"><span>01 / CONNECT</span><span>02 / DISCOVER</span><span>03 / CREATE</span></div></main>;

  const nav: { key: Tab; label: string; icon: string }[] = [
    { key: "home", label: "Home", icon: "home" }, { key: "explore", label: "Explore", icon: "explore" },
    { key: "profile", label: "Profile", icon: "profile" }, { key: "dm", label: "DM", icon: "dm" },
  ];
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">g<span>.</span></span><div><strong>gitstargram</strong><small>THE DEVELOPER SOCIAL</small></div></div>
      <nav aria-label="주요 메뉴">{nav.map(item => <button key={item.key} onClick={() => setTab(item.key)} className={`nav-item ${tab === item.key ? "active" : ""}`}><Icon name={item.icon} /><span>{item.label}</span></button>)}</nav>
      <div className="sidebar-bottom">
        <div className="sidebar-user">{user.avatar_url && <img src={user.avatar_url} alt="" />}<div><strong>{user.name || user.login}</strong><span>@{user.login}</span></div></div>
        <div className="composer-actions">
          <button className="text-button" onClick={() => saveSettings({ ...userSettings, theme: userSettings.theme === "dark" ? "light" : "dark" })}>{userSettings.theme === "dark" ? "Light 모드" : "Dark 모드"}</button>
          <button className="text-button" onClick={ async () => { setShowNotifications(v => !v); if (unreadNotifications > 0) { await api("/api/social/notifications/read-all", { method: "POST" }); setUnreadNotifications(0); } }}>알림 ({unreadNotifications})</button>
          <button className="text-button" onClick={logout}>로그아웃</button>
        </div>
      </div>
    </aside>
    <main className="main-area">
      <header className="mobile-top"><div className="brand"><span className="brand-mark">g<span>.</span></span><strong>gitstargram</strong></div><span className="mobile-username">@{user.login}</span></header>
      {error && <div role="alert" className="error-banner">{error}<button onClick={() => setError("")} aria-label="오류 닫기"><Icon name="close" size={16} /></button></div>}
      {showNotifications && <div className="composer-card" style={{ margin: "18px 48px 0" }}>
        <div className="post-meta"><strong>알림 목록</strong><button className="text-button" onClick={() => setShowNotifications(false)}>닫기</button></div>
        {notifications.length ? notifications.map(n => <p key={n.id} style={{ fontSize: 13, margin: "6px 0" }}>• {n.message} <small>({relativeDate(n.created_at)})</small></p>) : <p style={{ fontSize: 13 }}>새로운 알림이 없습니다.</p>}
      </div>}

      {tab === "home" && <section className="page-content">
        <div className="section-head">
          <div><div className="eyebrow">YOUR DEVELOPER SPACE</div><h1>안녕하세요, {user.name || user.login}님<span className="accent-dot">.</span></h1><p>24시간 개발 스토리, 팔로잉 피드, GitHub 프로젝트를 한곳에서 확인하세요.</p></div>
          <div className="composer-actions">
            <button className="outline-button" onClick={() => setShowStoryForm(v => !v)}>+ 24h 스토리</button>
            <button className="outline-button" onClick={startSync} disabled={busy || sync?.status === "running"}><Icon name="refresh" size={17} /> GitHub 동기화</button>
          </div>
        </div>

        <div className="stories-strip" aria-label="24시간 스토리 목록">
          {stories.map(st => <button key={st.id} type="button" className={`story-bubble ${st.viewed ? "viewed" : ""}`} onClick={() => openStory(st)}>
            <strong>@{st.author?.login ?? "dev"}</strong>
            <span>{st.title}</span>
          </button>)}
          {!stories.length && <small style={{ color: "var(--muted)" }}>현재 활성화된 24시간 스토리가 없습니다. 상단 `+ 24h 스토리`로 릴리스나 업데이트를 공유해보세요.</small>}
        </div>

        {showStoryForm && <form className="composer-card" onSubmit={submitStory}>
          <strong>새 24시간 개발 스토리 게시</strong>
          <input value={storyTitle} onChange={e => setStoryTitle(e.target.value)} placeholder="스토리 제목 (예: v0.2.0 릴리스)" required />
          <textarea rows={2} value={storySummary} onChange={e => setStorySummary(e.target.value)} placeholder="변경 사항이나 마일스톤 요약" required />
          <div className="composer-actions"><button className="outline-button" type="submit" disabled={busy}>24시간 스토리 올리기</button></div>
        </form>}

        {sync && <div className={`sync-status ${sync.status}`}><span className="status-dot" /><div><strong>GitHub 동기화: {sync.status === "complete" ? "완료" : sync.status === "running" ? "진행 중" : sync.status === "queued" ? "대기 중" : sync.status === "failed" ? "실패" : "아직 실행 전"} · 임베딩 {sync.embedded_repositories ?? 0}개 · AI {aiStatus?.available ? "연결됨" : "오프라인"}</strong><small>{sync.detail || (sync.status === "complete" ? `마지막 수집 ${relativeDate(sync.completed_at ?? null)}` : "실제 GitHub API에서 데이터를 가져옵니다.")}</small></div></div>}

        <form className="composer-card" onSubmit={submitPost}>
          <strong>새 개발 게시물 작성</strong>
          <select value={postRepoId} onChange={e => setPostRepoId(e.target.value)} aria-label="연결할 GitHub 저장소">
            <option value="">연결할 공개 Repository 선택 (선택사항)</option>
            {[...owned, ...starred].slice(0, 60).map(r => <option key={r.id} value={r.id}>{r.full_name} (★ {r.stars})</option>)}
          </select>
          <input value={postTitle} onChange={e => setPostTitle(e.target.value)} placeholder="게시물 제목" required />
          <textarea rows={3} value={postBody} onChange={e => setPostBody(e.target.value)} placeholder="무엇을 만들거나 개선했나요? AI 초안을 생성한 뒤 직접 수정할 수도 있습니다." required />
          <input value={postTags} onChange={e => setPostTags(e.target.value)} placeholder="태그 (쉼표로 구분: python, rag, fastapi)" />
          <div className="composer-actions">
            <button className="outline-button" type="button" onClick={generateDraft} disabled={!postRepoId || summaryLoading}>AI 초안 생성 (수정 후 게시)</button>
            <button className="outline-button" type="submit" disabled={busy}>게시물 발행</button>
          </div>
        </form>

        <div className="section-title">
          <div><span className="section-index">01 /</span><h2>개발자 피드</h2></div>
          <div className="filter-group">
            <button type="button" className={feedMode === "following" ? "selected" : ""} onClick={() => setFeedMode("following")}>Following</button>
            <button type="button" className={feedMode === "recommended" ? "selected" : ""} onClick={() => setFeedMode("recommended")}>Recommended</button>
          </div>
        </div>
        {posts.length ? posts.map(post => <article key={post.id} className="post-card">
          <div className="post-meta">
            <span><strong>@{post.author?.login}</strong> · {relativeDate(post.created_at)} {post.ai_assisted && "· AI 초안 편집됨"}</span>
            {post.repository && <a href={post.repository.html_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>{post.repository.full_name} (GitHub ★ {post.repository.stars})</a>}
          </div>
          <h3 style={{ margin: "6px 0" }}>{post.title}</h3>
          <p style={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.6 }}>{post.body}</p>
          <div className="repo-topics">{post.tags.map(t => <span key={t}>#{t}</span>)}</div>
          <div className="post-actions">
            <button type="button" className="summary-btn" onClick={() => toggleLike(post)}>{post.liked ? "♥ SNS 좋아요 취소" : "♡ SNS 좋아요"} ({post.like_count})</button>
            <button type="button" className="summary-btn" onClick={() => openComments(post.id)}>댓글 ({post.comment_count})</button>
          </div>
        </article>) : <div className="empty-state"><Icon name="code" size={32} /><h3>아직 작성된 SNS 게시물이 없어요</h3><p>위의 작성 창에서 첫 개발 업데이트를 공유하거나 다른 개발자를 팔로우해보세요.</p></div>}

        <div className="section-title spaced"><div><span className="section-index">02 /</span><h2>내 GitHub 공개 프로젝트</h2></div><span className="count-label">{owned.length} repositories</span></div>
        {owned.length ? <div className="home-grid">{owned.slice(0, 6).map(repo => <RepoCard key={repo.id} repo={repo} onOpen={item => track(item, "click")} onSummary={summarize} onTranslate={translateReadme} onBookmark={toggleRepoBookmark} onDetail={setDetailRepo} />)}</div> : <div className="empty-state"><Icon name="code" size={32} /><h3>표시할 공개 저장소가 없어요</h3><p>동기화가 진행 중이거나 GitHub에 공개 저장소가 없을 수 있습니다.</p></div>}

        <div className="section-title spaced"><div><span className="section-index">03 /</span><h2>당신을 위한 발견</h2></div><button className="link-button" onClick={() => setTab("explore")}>Explore 보기 <Icon name="arrow" size={16} /></button></div>
        {explore.length ? <div className="home-grid">{explore.slice(0, 3).map(repo => <RepoCard key={repo.id} repo={repo} compact onOpen={item => track(item, "click")} onDismiss={dismiss} onSummary={summarize} onTranslate={translateReadme} onBookmark={toggleRepoBookmark} onDetail={setDetailRepo} />)}</div> : <div className="empty-state"><Icon name="explore" size={32} /><h3>추천 후보를 모으고 있어요</h3><p>GitHub Star와 공개 저장소가 동기화되면 실제 프로젝트가 표시됩니다.</p></div>}
      </section>}

      {tab === "explore" && <section className="page-content">
        <div className="section-head">
          <div><div className="eyebrow">FIND YOUR NEXT IDEA</div><h1>Explore<span className="accent-dot">.</span></h1><p>실제 GitHub 메타데이터, 사용자 관심사, Qwen3-Embedding-0.6B(pgvector) 하이브리드 랭킹으로 탐색합니다.</p></div>
          <button className="outline-button" onClick={syncEmbeddings} disabled={busy}>임베딩 갱신</button>
        </div>
        <form className="search-form" onSubmit={search}><Icon name="explore" size={20} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Repository, 기술, 자연어 아이디어 검색 (예: Python AI Agent)" aria-label="GitHub 저장소 검색" /><button type="submit" disabled={busy || query.trim().length < 2}>검색</button></form>
        <div className="filter-bar">
          <div className="filter-group">
            <button className={!searchResults && mode === "for-you" ? "selected" : ""} onClick={() => { setSearchResults(null); setMode("for-you"); }}>For You</button>
            <button className={!searchResults && mode === "trending" ? "selected" : ""} onClick={() => { setSearchResults(null); setMode("trending"); }}>Trending</button>
            <button className={!searchResults && mode === "following" ? "selected" : ""} onClick={() => { setSearchResults(null); setMode("following"); }}>Following</button>
            {searchResults && <button className="selected" onClick={() => setSearchResults(null)}>검색 결과 ×</button>}
          </div>
          <div className="filter-group">
            {(["all", "ai-ml", "frontend", "backend", "devops-tools"] as ExploreCategory[]).map(cat => (
              <button key={cat} className={category === cat ? "selected" : ""} onClick={() => setCategory(cat)}>{cat === "all" ? "전체 분야" : cat.toUpperCase()}</button>
            ))}
          </div>
          <select value={language} onChange={event => setLanguage(event.target.value)} aria-label="언어 필터"><option value="">모든 언어</option>{languages.map(item => <option key={item} value={item}>{item}</option>)}</select>
        </div>
        <div className="explore-summary"><span>{searchResults ? "GITHUB + SEMANTIC SEARCH RESULTS" : `ALGORITHM: ${exploreAlgo.toUpperCase()} · MODE: ${mode.toUpperCase()}`}</span><strong>{visibleExplore.length} projects</strong></div>
        {visibleExplore.length ? <div className="explore-grid">{visibleExplore.map(repo => <RepoCard key={repo.id} repo={repo} compact onOpen={item => track(item, "click")} onDismiss={searchResults ? undefined : dismiss} onSummary={summarize} onTranslate={translateReadme} onBookmark={toggleRepoBookmark} onDetail={setDetailRepo} />)}</div> : <div className="empty-state"><Icon name="explore" size={32} /><h3>일치하는 프로젝트가 없어요</h3><p>다른 검색어/카테고리를 선택하거나 GitHub 데이터를 동기화해보세요.</p></div>}
        <p className="data-note">추천은 수집된 공개 GitHub 메타데이터, 내 Star·클릭 기록, pgvector 코사인 유사도(임베딩 활성화 시)를 결합하며 동일 소유자 편중을 최대 3개로 제한합니다. Trending은 다중 스냅샷이 있을 때만 Star 증가분을 반영합니다.</p>
      </section>}

      {tab === "profile" && <section className="page-content">
        <div className="eyebrow">YOUR GITHUB & SNS IDENTITY</div>
        <div className="profile-panel">{user.avatar_url && <img src={user.avatar_url} alt={`${user.login} 프로필`} />}<div><span className="profile-kicker">GITHUB + GITSTARGRAM PROFILE</span><h1>{user.name || user.login}<span className="accent-dot">.</span></h1><p className="profile-handle">@{user.login}</p><p>{user.bio || "GitHub에 소개가 등록되지 않았습니다."}</p><a className="outline-button" href={user.html_url} target="_blank" rel="noopener noreferrer">GitHub 프로필 열기 <Icon name="arrow" size={16} /></a></div></div>
        <div className="profile-stats">
          <div><strong>{user.public_repos}</strong><span>GitHub 공개 저장소 (외부)</span></div>
          <div><strong>{user.followers}</strong><span>GitHub 팔로워 (외부)</span></div>
          <div><strong>{starred.length}</strong><span>동기화된 GitHub Star</span></div>
          <div><strong>{user.sns_posts ?? 0}</strong><span>SNS 게시물 (내부)</span></div>
          <div><strong>{user.sns_followers ?? 0}</strong><span>SNS 팔로워 (내부)</span></div>
          <div><strong>{user.sns_bookmarks ?? 0}</strong><span>SNS 북마크 (내부)</span></div>
        </div>
        <div className="section-title spaced"><div><span className="section-index">STARRED /</span><h2>관심 프로젝트</h2></div></div>
        {starred.length ? <div className="home-grid">{starred.slice(0, 30).map(repo => <RepoCard key={repo.id} repo={repo} compact onOpen={item => track(item, "click")} onSummary={summarize} onTranslate={translateReadme} onBookmark={toggleRepoBookmark} onDetail={setDetailRepo} />)}</div> : <div className="empty-state"><Icon name="star" size={32} /><h3>가져온 Star가 없어요</h3><p>동기화 상태와 GitHub App의 Starring 읽기 권한을 확인해주세요.</p></div>}

        <div className="settings-panel">
          <h3>프로필 및 개인화 설정</h3>
          <form className="settings-grid" onSubmit={saveProfile}>
            <input value={editName} onChange={e => setEditName(e.target.value)} placeholder="표시 이름" />
            <input value={editBio} onChange={e => setEditBio(e.target.value)} placeholder="자기소개 (Bio)" />
            <button className="outline-button" type="submit">프로필 저장</button>
          </form>
          <div className="composer-actions">
            <label style={{ fontSize: 12 }}>
              <input type="checkbox" checked={userSettings.personalized_recommendations} onChange={e => saveSettings({ ...userSettings, personalized_recommendations: e.target.checked })} /> 추천 개인화 사용
            </label>
            <label style={{ fontSize: 12 }}>
              <input type="checkbox" checked={userSettings.notifications_enabled} onChange={e => saveSettings({ ...userSettings, notifications_enabled: e.target.checked })} /> 알림 수신
            </label>
            <button className="text-button" type="button" onClick={clearLogs}>추천/행동 로그 전체 삭제</button>
          </div>
          <hr style={{ borderColor: "var(--line)", margin: "18px 0" }} />
          <h3>연결 및 계정 관리</h3>
          <p>연결 해제는 저장된 GitHub 토큰, Star 관계와 사용 기록을 삭제합니다. DM 대화 내용은 추천 입력으로 절대 사용되지 않습니다.</p>
          <div className="composer-actions">
            <button className="text-button" onClick={async () => { if (window.confirm("GitHub 연결을 해제할까요?")) { try { await api("/api/auth/disconnect", { method: "POST" }); setOwned([]); setStarred([]); setExplore([]); setError("GitHub 연결이 해제되었습니다. 다시 로그인하면 연결할 수 있습니다."); } catch (err) { setError((err as Error).message); } } }}>GitHub 연결 해제</button>
            <button className="text-button danger" onClick={deleteAccount}>서비스 계정 완전히 삭제</button>
          </div>
        </div>
      </section>}

      {tab === "dm" && <section className="page-content">
        <div className="eyebrow">DIRECT MESSAGES (POSTGRESQL + WEBSOCKET)</div>
        <h1>DM<span className="accent-dot">.</span></h1>
        <p>PostgreSQL 영속 저장, 읽음 상태, 차단 검증 및 FastAPI WebSocket 실시간 전달이 연결되어 있습니다. (종단 간 암호화 E2EE는 미적용)</p>
        <div className="dm-layout">
          <div className="dm-sidebar">
            <strong>대화 목록 ({conversations.length})</strong>
            <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
              {conversations.map(c => (
                <button key={c.id} type="button" className="outline-button" style={{ justifyContent: "space-between" }} onClick={() => setActiveConversationId(c.id)}>
                  <span>@{c.peer.login}</span>
                  {c.unread_count > 0 && <b>{c.unread_count}</b>}
                </button>
              ))}
            </div>
            <strong style={{ marginTop: 20 }}>개발자 디렉터리</strong>
            <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
              {socialUsers.filter(u => !u.is_self).map(u => (
                <div key={u.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12 }}>
                  <span>@{u.login}</span>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button type="button" className="summary-btn" onClick={() => toggleFollow(u)}>{u.is_following ? "언팔로우" : "팔로우"}</button>
                    <button type="button" className="summary-btn" onClick={() => startChatWith(u.id)}>DM</button>
                  </div>
                </div>
              ))}
              {socialUsers.filter(u => !u.is_self).length === 0 && <small style={{ color: "var(--muted)" }}>아직 이 서버에 로그인한 두 번째 실제 GitHub 계정이 없습니다. 다른 실제 계정으로 로그인하면 1:1 DM을 시작할 수 있습니다.</small>}
            </div>
          </div>
          <div className="dm-chat">
            {activeConversationId ? <>
              <div className="dm-messages">
                {dmMessages.map(m => (
                  <div key={m.id} className={`dm-bubble ${m.sender?.id === user.id ? "mine" : ""}`}>
                    <strong>@{m.sender?.login}</strong>
                    <p style={{ margin: "4px 0" }}>{m.body}</p>
                    <small style={{ color: "var(--muted)", fontSize: 10 }}>{relativeDate(m.created_at)}</small>
                  </div>
                ))}
                {!dmMessages.length && <p style={{ color: "var(--muted)", fontSize: 13 }}>첫 메시지를 보내 대화를 시작하세요.</p>}
              </div>
              <form className="dm-input-row" onSubmit={sendDm}>
                <input value={dmInput} onChange={e => setDmInput(e.target.value)} placeholder="메시지 입력..." />
                <button className="outline-button" type="submit">전송</button>
              </form>
            </> : <div className="empty-state tall"><Icon name="dm" size={42} /><h2>대화를 선택하세요</h2><p>왼쪽 목록에서 대화를 선택하거나 두 번째 실제 GitHub 계정과 새 1:1 대화를 시작하세요.</p></div>}
          </div>
        </div>
      </section>}
    </main>

    {detailRepo && <RepositoryDetailDialog key={detailRepo.id} repo={detailRepo} projects={owned} aiAvailable={aiStatus?.available ?? false} onClose={() => setDetailRepo(null)} />}
    {summaryLoading && <div className="modal-backdrop"><div className="summary-modal" role="status">실제 README를 읽고 로컬 Qwen3.5-4B (vLLM Metal) 추론을 수행하는 중...</div></div>}
    {aiModal && <div className="modal-backdrop" onClick={() => setAiModal(null)}><div className="summary-modal" role="dialog" aria-modal="true" aria-label={aiModal.title} onClick={event => event.stopPropagation()}><button className="modal-close" onClick={() => setAiModal(null)} aria-label="닫기"><Icon name="close" size={20} /></button><div className="eyebrow">{aiModal.subtitle}</div><h2>{aiModal.title}</h2><p>{aiModal.text}</p>{aiModal.truncated && <small>README가 길어 앞부분만 사용했습니다.</small>}{aiModal.latencyMs !== undefined && <small>추론 소요 시간: {aiModal.latencyMs} ms ({aiStatus?.model ?? "Qwen/Qwen3.5-4B"})</small>}<a href={aiModal.source} target="_blank" rel="noopener noreferrer">원본 README 확인 <Icon name="arrow" size={15} /></a></div></div>}
    {activeStory && <div className="modal-backdrop" onClick={() => setActiveStory(null)}><div className="summary-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}><button className="modal-close" onClick={() => setActiveStory(null)} aria-label="닫기"><Icon name="close" size={20} /></button><div className="eyebrow">24H DEVELOPER STORY · @{activeStory.author?.login}</div><h2>{activeStory.title}</h2><p>{activeStory.summary}</p><small>조회 {activeStory.view_count}회 · 만료 {relativeDate(activeStory.expires_at)}</small>{activeStory.source_url && <a href={activeStory.source_url} target="_blank" rel="noopener noreferrer">관련 링크 열기 <Icon name="arrow" size={15} /></a>}</div></div>}
    {activeCommentsPostId !== null && <div className="modal-backdrop" onClick={() => setActiveCommentsPostId(null)}><div className="summary-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}><button className="modal-close" onClick={() => setActiveCommentsPostId(null)} aria-label="닫기"><Icon name="close" size={20} /></button><div className="eyebrow">POST COMMENTS</div><h2>댓글</h2>{comments.map(c => <p key={c.id}><strong>@{c.author?.login}:</strong> {c.body}</p>)}{!comments.length && <p>아직 댓글이 없습니다.</p>}<form className="dm-input-row" onSubmit={submitComment}><input value={commentText} onChange={e => setCommentText(e.target.value)} placeholder="댓글 작성..." required /><button className="outline-button" type="submit">등록</button></form></div></div>}
    <nav className="mobile-nav" aria-label="모바일 주요 메뉴">{nav.map(item => <button key={item.key} onClick={() => setTab(item.key)} className={tab === item.key ? "active" : ""} aria-label={item.label}><Icon name={item.icon} /><span>{item.label}</span></button>)}</nav>
  </div>;
}
