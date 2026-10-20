from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import session_scope
from .models import (
    Block,
    Bookmark,
    Comment,
    ContentReport,
    Follow,
    Interaction,
    Notification,
    Post,
    PostLike,
    RecommendationImpression,
    Repository,
    Story,
    StoryView,
    User,
    UserSetting,
    utcnow,
)
from .security import current_user, require_same_origin


router = APIRouter(prefix="/api/social", tags=["social"])


class PostCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    repository_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=8)
    ai_assisted: bool = False


class PostUpdateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=8)


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class BookmarkInput(BaseModel):
    post_id: int | None = None
    repository_id: int | None = None


class StoryCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1000)
    kind: str = Field(default="update", pattern="^(update|release|project|milestone)$")
    repository_id: int | None = None
    source_url: str | None = Field(default=None, max_length=500)


class SettingsInput(BaseModel):
    theme: str = Field(default="dark", pattern="^(dark|light)$")
    language: str = Field(default="ko", pattern="^(ko|en)$")
    personalized_recommendations: bool = True
    auto_story_enabled: bool = False
    notifications_enabled: bool = True


class ProfileUpdateInput(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=500)


class ReportInput(BaseModel):
    target_type: str = Field(pattern="^(post|comment|message|user)$")
    target_id: int
    reason: str = Field(min_length=3, max_length=500)


async def blocked_user_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = await db.execute(
        select(Block.blocker_id, Block.blocked_id).where(
            or_(Block.blocker_id == user_id, Block.blocked_id == user_id)
        )
    )
    ids: set[int] = set()
    for blocker_id, blocked_id in rows:
        ids.add(blocked_id if blocker_id == user_id else blocker_id)
    return ids


async def create_notification(
    db: AsyncSession,
    user_id: int,
    actor_id: int,
    kind: str,
    message: str,
    reference_id: int | None = None,
) -> None:
    if user_id == actor_id:
        return
    setting = await db.get(UserSetting, user_id)
    if setting and not setting.notifications_enabled:
        return
    db.add(
        Notification(
            user_id=user_id,
            actor_id=actor_id,
            kind=kind,
            reference_id=reference_id,
            message=message,
        )
    )


async def serialize_post(db: AsyncSession, post: Post, viewer_id: int) -> dict:
    author = await db.get(User, post.author_id)
    repo = await db.get(Repository, post.repository_id) if post.repository_id else None
    like_count = int(
        await db.scalar(select(func.count()).select_from(PostLike).where(PostLike.post_id == post.id)) or 0
    )
    comment_count = int(
        await db.scalar(select(func.count()).select_from(Comment).where(Comment.post_id == post.id)) or 0
    )
    liked = bool(
        await db.scalar(
            select(PostLike.id).where(PostLike.post_id == post.id, PostLike.user_id == viewer_id)
        )
    )
    bookmarked = bool(
        await db.scalar(
            select(Bookmark.id).where(Bookmark.post_id == post.id, Bookmark.user_id == viewer_id)
        )
    )
    return {
        "id": post.id,
        "author": {
            "id": author.id,
            "login": author.login,
            "name": author.name,
            "avatar_url": author.avatar_url,
        }
        if author
        else None,
        "repository": {
            "id": repo.id,
            "full_name": repo.full_name,
            "name": repo.name,
            "owner_login": repo.owner_login,
            "html_url": repo.html_url,
            "language": repo.language,
            "stars": repo.stars,
            "topics": repo.topics,
        }
        if repo
        else None,
        "title": post.title,
        "body": post.body,
        "tags": post.tags,
        "ai_assisted": post.ai_assisted,
        "like_count": like_count,
        "comment_count": comment_count,
        "liked": liked,
        "bookmarked": bookmarked,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


@router.get("/users")
async def discover_users(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    blocked = await blocked_user_ids(db, user.id)
    following_ids = set(
        await db.scalars(select(Follow.following_id).where(Follow.follower_id == user.id))
    )
    users = list(await db.scalars(select(User).order_by(desc(User.updated_at)).limit(50)))
    items = []
    for candidate in users:
        if candidate.id in blocked:
            continue
        sns_followers = int(
            await db.scalar(select(func.count()).select_from(Follow).where(Follow.following_id == candidate.id))
            or 0
        )
        sns_following = int(
            await db.scalar(select(func.count()).select_from(Follow).where(Follow.follower_id == candidate.id))
            or 0
        )
        sns_posts = int(
            await db.scalar(select(func.count()).select_from(Post).where(Post.author_id == candidate.id))
            or 0
        )
        items.append(
            {
                "id": candidate.id,
                "login": candidate.login,
                "name": candidate.name,
                "avatar_url": candidate.avatar_url,
                "bio": candidate.bio,
                "html_url": candidate.html_url,
                "github_followers": candidate.followers,
                "sns_followers": sns_followers,
                "sns_following": sns_following,
                "sns_posts": sns_posts,
                "is_following": candidate.id in following_ids,
                "is_self": candidate.id == user.id,
            }
        )
    return {"items": items}


@router.post("/follow/{target_user_id}", dependencies=[Depends(require_same_origin)])
async def follow_user(target_user_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if target_user_id == user.id:
        raise HTTPException(422, "Cannot follow yourself")
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(404, "User not found")
    blocked = await blocked_user_ids(db, user.id)
    if target_user_id in blocked:
        raise HTTPException(403, "Cannot follow a blocked user")
    existing = await db.scalar(
        select(Follow).where(Follow.follower_id == user.id, Follow.following_id == target_user_id)
    )
    if not existing:
        db.add(Follow(follower_id=user.id, following_id=target_user_id))
        await create_notification(
            db, target_user_id, user.id, "follow", f"@{user.login}님이 회원님을 팔로우합니다.", user.id
        )
        await db.commit()
    return {"status": "following", "target_user_id": target_user_id}


@router.delete("/follow/{target_user_id}", dependencies=[Depends(require_same_origin)])
async def unfollow_user(target_user_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    await db.execute(
        delete(Follow).where(Follow.follower_id == user.id, Follow.following_id == target_user_id)
    )
    await db.commit()
    return {"status": "unfollowed", "target_user_id": target_user_id}


@router.post("/block/{target_user_id}", dependencies=[Depends(require_same_origin)])
async def block_user(target_user_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if target_user_id == user.id:
        raise HTTPException(422, "Cannot block yourself")
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(404, "User not found")
    existing = await db.scalar(
        select(Block).where(Block.blocker_id == user.id, Block.blocked_id == target_user_id)
    )
    if not existing:
        db.add(Block(blocker_id=user.id, blocked_id=target_user_id))
    await db.execute(
        delete(Follow).where(
            or_(
                (Follow.follower_id == user.id) & (Follow.following_id == target_user_id),
                (Follow.follower_id == target_user_id) & (Follow.following_id == user.id),
            )
        )
    )
    await db.commit()
    return {"status": "blocked", "target_user_id": target_user_id}


@router.delete("/block/{target_user_id}", dependencies=[Depends(require_same_origin)])
async def unblock_user(target_user_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    await db.execute(
        delete(Block).where(Block.blocker_id == user.id, Block.blocked_id == target_user_id)
    )
    await db.commit()
    return {"status": "unblocked", "target_user_id": target_user_id}


@router.get("/posts")
async def list_posts(
    feed: str = Query("following", pattern="^(following|recommended|mine)$"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    blocked = await blocked_user_ids(db, user.id)
    following_ids = set(
        await db.scalars(select(Follow.following_id).where(Follow.follower_id == user.id))
    )
    stmt = select(Post).order_by(desc(Post.created_at)).limit(40)
    if feed == "mine":
        stmt = stmt.where(Post.author_id == user.id)
    elif feed == "following":
        allowed_authors = (following_ids | {user.id}) - blocked
        stmt = stmt.where(Post.author_id.in_(allowed_authors))
    else:
        if blocked:
            stmt = stmt.where(Post.author_id.notin_(blocked))
    posts = list(await db.scalars(stmt))
    return {
        "items": [await serialize_post(db, post, user.id) for post in posts],
        "feed": feed,
    }


@router.post("/posts", dependencies=[Depends(require_same_origin)])
async def create_post(payload: PostCreateInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if payload.repository_id is not None:
        repo = await db.get(Repository, payload.repository_id)
        if not repo or not repo.is_public:
            raise HTTPException(404, "Repository not found")
    clean_tags = [t.strip().lower()[:30] for t in payload.tags if t.strip()][:8]
    post = Post(
        author_id=user.id,
        repository_id=payload.repository_id,
        title=payload.title.strip(),
        body=payload.body.strip(),
        tags=clean_tags,
        ai_assisted=payload.ai_assisted,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return await serialize_post(db, post, user.id)


@router.patch("/posts/{post_id}", dependencies=[Depends(require_same_origin)])
async def update_post(post_id: int, payload: PostUpdateInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if post.author_id != user.id:
        raise HTTPException(403, "Not allowed to edit this post")
    post.title = payload.title.strip()
    post.body = payload.body.strip()
    post.tags = [t.strip().lower()[:30] for t in payload.tags if t.strip()][:8]
    post.updated_at = utcnow()
    await db.commit()
    return await serialize_post(db, post, user.id)


@router.delete("/posts/{post_id}", dependencies=[Depends(require_same_origin)])
async def delete_post(post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if post.author_id != user.id:
        raise HTTPException(403, "Not allowed to delete this post")
    await db.delete(post)
    await db.commit()
    return {"status": "deleted", "post_id": post_id}


@router.post("/posts/{post_id}/like", dependencies=[Depends(require_same_origin)])
async def like_post(post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    existing = await db.scalar(
        select(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == user.id)
    )
    if not existing:
        db.add(PostLike(post_id=post_id, user_id=user.id))
        await create_notification(
            db, post.author_id, user.id, "like", f"@{user.login}님이 회원님의 게시물을 좋아합니다.", post.id
        )
        await db.commit()
    return await serialize_post(db, post, user.id)


@router.delete("/posts/{post_id}/like", dependencies=[Depends(require_same_origin)])
async def unlike_post(post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    await db.execute(delete(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == user.id))
    await db.commit()
    return await serialize_post(db, post, user.id)


@router.get("/posts/{post_id}/comments")
async def list_comments(post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    blocked = await blocked_user_ids(db, user.id)
    comments = list(
        await db.scalars(select(Comment).where(Comment.post_id == post_id).order_by(Comment.created_at).limit(100))
    )
    items = []
    for item in comments:
        if item.author_id in blocked:
            continue
        author = await db.get(User, item.author_id)
        items.append(
            {
                "id": item.id,
                "post_id": item.post_id,
                "body": item.body,
                "created_at": item.created_at,
                "author": {
                    "id": author.id,
                    "login": author.login,
                    "name": author.name,
                    "avatar_url": author.avatar_url,
                }
                if author
                else None,
            }
        )
    return {"items": items}


@router.post("/posts/{post_id}/comments", dependencies=[Depends(require_same_origin)])
async def create_comment(post_id: int, payload: CommentInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    comment = Comment(post_id=post_id, author_id=user.id, body=payload.body.strip())
    db.add(comment)
    await create_notification(
        db, post.author_id, user.id, "comment", f"@{user.login}님이 댓글을 남겼습니다.", post.id
    )
    await db.commit()
    await db.refresh(comment)
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "body": comment.body,
        "created_at": comment.created_at,
        "author": {
            "id": user.id,
            "login": user.login,
            "name": user.name,
            "avatar_url": user.avatar_url,
        },
    }


@router.delete("/comments/{comment_id}", dependencies=[Depends(require_same_origin)])
async def delete_comment(comment_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    comment = await db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id:
        raise HTTPException(403, "Not allowed to delete this comment")
    await db.delete(comment)
    await db.commit()
    return {"status": "deleted"}


@router.get("/bookmarks")
async def list_bookmarks(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    rows = list(
        await db.scalars(
            select(Bookmark).where(Bookmark.user_id == user.id).order_by(desc(Bookmark.created_at)).limit(100)
        )
    )
    items = []
    for row in rows:
        post_data = None
        repo_data = None
        if row.post_id:
            post = await db.get(Post, row.post_id)
            if post:
                post_data = await serialize_post(db, post, user.id)
        if row.repository_id:
            repo = await db.get(Repository, row.repository_id)
            if repo and repo.is_public:
                repo_data = {
                    "id": repo.id,
                    "full_name": repo.full_name,
                    "name": repo.name,
                    "owner_login": repo.owner_login,
                    "description": repo.description,
                    "html_url": repo.html_url,
                    "language": repo.language,
                    "topics": repo.topics,
                    "stars": repo.stars,
                    "forks": repo.forks,
                    "pushed_at": repo.pushed_at,
                    "fetched_at": repo.fetched_at,
                    "source": repo.source,
                }
        items.append(
            {
                "id": row.id,
                "post": post_data,
                "repository": repo_data,
                "created_at": row.created_at,
            }
        )
    return {"items": items}


@router.post("/bookmarks", dependencies=[Depends(require_same_origin)])
async def toggle_bookmark(payload: BookmarkInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if bool(payload.post_id) == bool(payload.repository_id):
        raise HTTPException(422, "Specify exactly one of post_id or repository_id")
    if payload.post_id:
        existing = await db.scalar(
            select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.post_id == payload.post_id)
        )
        if existing:
            await db.delete(existing)
            await db.commit()
            return {"bookmarked": False}
        post = await db.get(Post, payload.post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        db.add(Bookmark(user_id=user.id, post_id=payload.post_id))
        await db.commit()
        return {"bookmarked": True}
    existing = await db.scalar(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.repository_id == payload.repository_id)
    )
    if existing:
        await db.delete(existing)
        await db.commit()
        return {"bookmarked": False}
    repo = await db.get(Repository, payload.repository_id)
    if not repo or not repo.is_public:
        raise HTTPException(404, "Repository not found")
    db.add(Bookmark(user_id=user.id, repository_id=payload.repository_id))
    db.add(Interaction(user_id=user.id, repository_id=repo.id, action="bookmark"))
    await db.commit()
    return {"bookmarked": True}


@router.get("/stories")
async def list_stories(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    now = utcnow()
    blocked = await blocked_user_ids(db, user.id)
    stories = list(
        await db.scalars(
            select(Story).where(Story.expires_at > now).order_by(desc(Story.created_at)).limit(40)
        )
    )
    viewed_ids = set(
        await db.scalars(select(StoryView.story_id).where(StoryView.viewer_id == user.id))
    )
    items = []
    for story in stories:
        if story.author_id in blocked:
            continue
        author = await db.get(User, story.author_id)
        repo = await db.get(Repository, story.repository_id) if story.repository_id else None
        view_count = int(
            await db.scalar(select(func.count()).select_from(StoryView).where(StoryView.story_id == story.id))
            or 0
        )
        items.append(
            {
                "id": story.id,
                "kind": story.kind,
                "title": story.title,
                "summary": story.summary,
                "source_url": story.source_url or (repo.html_url if repo else None),
                "created_at": story.created_at,
                "expires_at": story.expires_at,
                "viewed": story.id in viewed_ids,
                "view_count": view_count,
                "author": {
                    "id": author.id,
                    "login": author.login,
                    "name": author.name,
                    "avatar_url": author.avatar_url,
                }
                if author
                else None,
                "repository": {
                    "id": repo.id,
                    "full_name": repo.full_name,
                    "html_url": repo.html_url,
                }
                if repo
                else None,
            }
        )
    return {"items": items}


@router.post("/stories", dependencies=[Depends(require_same_origin)])
async def create_story(payload: StoryCreateInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if payload.repository_id is not None:
        repo = await db.get(Repository, payload.repository_id)
        if not repo or not repo.is_public:
            raise HTTPException(404, "Repository not found")
    now = utcnow()
    story = Story(
        author_id=user.id,
        repository_id=payload.repository_id,
        kind=payload.kind,
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        source_url=payload.source_url,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return {
        "id": story.id,
        "title": story.title,
        "summary": story.summary,
        "kind": story.kind,
        "created_at": story.created_at,
        "expires_at": story.expires_at,
    }


@router.post("/stories/{story_id}/view", dependencies=[Depends(require_same_origin)])
async def mark_story_viewed(story_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    story = await db.get(Story, story_id)
    if not story or story.expires_at <= utcnow():
        raise HTTPException(404, "Active story not found")
    existing = await db.scalar(
        select(StoryView).where(StoryView.story_id == story_id, StoryView.viewer_id == user.id)
    )
    if not existing:
        db.add(StoryView(story_id=story_id, viewer_id=user.id))
        await db.commit()
    return {"status": "viewed"}


@router.get("/notifications")
async def list_notifications(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    rows = list(
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(desc(Notification.created_at))
            .limit(40)
        )
    )
    unread_count = sum(1 for row in rows if not row.is_read)
    return {
        "unread_count": unread_count,
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "message": row.message,
                "reference_id": row.reference_id,
                "is_read": row.is_read,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@router.post("/notifications/read-all", dependencies=[Depends(require_same_origin)])
async def mark_notifications_read(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    rows = list(
        await db.scalars(
            select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
    )
    for row in rows:
        row.is_read = True
    await db.commit()
    return {"status": "ok"}


@router.get("/settings")
async def get_settings(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    setting = await db.get(UserSetting, user.id)
    if not setting:
        setting = UserSetting(user_id=user.id)
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    return {
        "theme": setting.theme,
        "language": setting.language,
        "personalized_recommendations": setting.personalized_recommendations,
        "auto_story_enabled": setting.auto_story_enabled,
        "notifications_enabled": setting.notifications_enabled,
        "updated_at": setting.updated_at,
    }


@router.put("/settings", dependencies=[Depends(require_same_origin)])
async def update_settings(payload: SettingsInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    setting = await db.get(UserSetting, user.id)
    if not setting:
        setting = UserSetting(user_id=user.id)
        db.add(setting)
    setting.theme = payload.theme
    setting.language = payload.language
    setting.personalized_recommendations = payload.personalized_recommendations
    setting.auto_story_enabled = payload.auto_story_enabled
    setting.notifications_enabled = payload.notifications_enabled
    setting.updated_at = utcnow()
    await db.commit()
    return {
        "theme": setting.theme,
        "language": setting.language,
        "personalized_recommendations": setting.personalized_recommendations,
        "auto_story_enabled": setting.auto_story_enabled,
        "notifications_enabled": setting.notifications_enabled,
        "updated_at": setting.updated_at,
    }


@router.patch("/profile", dependencies=[Depends(require_same_origin)])
async def update_profile(payload: ProfileUpdateInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    user.name = payload.name.strip() if payload.name else None
    user.bio = payload.bio.strip() if payload.bio else None
    user.updated_at = utcnow()
    await db.commit()
    return {"id": user.id, "login": user.login, "name": user.name, "bio": user.bio}


@router.delete("/interactions", dependencies=[Depends(require_same_origin)])
async def clear_interaction_logs(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    await db.execute(delete(Interaction).where(Interaction.user_id == user.id))
    await db.execute(delete(RecommendationImpression).where(RecommendationImpression.user_id == user.id))
    await db.commit()
    return {"status": "cleared"}


@router.post("/reports", dependencies=[Depends(require_same_origin)])
async def create_report(payload: ReportInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    report = ContentReport(
        reporter_id=user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason.strip(),
    )
    db.add(report)
    await db.commit()
    return {"status": "reported"}
