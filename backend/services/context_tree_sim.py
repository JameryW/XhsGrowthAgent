"""MCP-Persona-style Context-Tree state simulator for ``--dry-run``.

The simulator keeps an in-memory entity tree ``User → Account → Post/Draft →
Comment/DM`` and applies the same deterministic hard boundaries the real
gateway enforces: title length, body length, banned terms, session validity,
signature availability, daily posting quota and DM quota.  It is intentionally
side-effect free and clock-injectable so CI can replay exact failures.

The tree is not a mock of the transport layer; it is a *state* mock.  A dry
run therefore catches "title 21 chars", "session expired" and "DM quota
exhausted" before the browser path is ever exercised.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

DEFAULT_TITLE_MAX = 20
DEFAULT_BODY_MAX = 1000
DEFAULT_DAILY_POST_LIMIT = 5
DEFAULT_DM_QUOTA = 20
DEFAULT_BANNED_TERMS = (
    "最便宜",
    "第一",
    "绝对",
    "百分百",
    "国家级",
    "顶级",
    "最好",
    "永久",
)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


@dataclass
class User:
    user_id: str
    name: str = ""


@dataclass
class Account:
    account_id: str
    user_id: str
    logged_in: bool = True
    session_valid_until: datetime | None = None
    posts_today: int = 0
    dms_sent_today: int = 0

    def session_valid(self, now: datetime) -> bool:
        if not self.logged_in:
            return False
        if self.session_valid_until is None:
            return True
        return now <= self.session_valid_until


@dataclass
class Draft:
    draft_id: str
    account_id: str
    title: str
    body: str
    hashtags: tuple[str, ...] = ()
    image_count: int = 0
    status: str = "draft"


@dataclass
class Post:
    post_id: str
    account_id: str
    title: str
    body: str
    status: str = "published"
    comments: list[str] = field(default_factory=list)
    analytics: list[AnalyticsSnapshot] = field(default_factory=list)


@dataclass
class AnalyticsSnapshot:
    snapshot_id: str
    post_id: str
    views: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0
    fetched_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "post_id": self.post_id,
            "views": self.views,
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
            "shares": self.shares,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


@dataclass
class Comment:
    comment_id: str
    post_id: str
    account_id: str
    content: str


@dataclass
class DirectMessage:
    dm_id: str
    account_id: str
    user_id: str
    content: str


@dataclass
class SimulationConfig:
    title_max: int = DEFAULT_TITLE_MAX
    body_max: int = DEFAULT_BODY_MAX
    daily_post_limit: int = DEFAULT_DAILY_POST_LIMIT
    dm_quota: int = DEFAULT_DM_QUOTA
    banned_terms: tuple[str, ...] = DEFAULT_BANNED_TERMS
    signature_available: bool = True
    injected_faults: tuple[str, ...] = ()


@dataclass
class ContextTree:
    """In-memory entity tree with deterministic operations."""

    config: SimulationConfig = field(default_factory=SimulationConfig)
    users: dict[str, User] = field(default_factory=dict)
    accounts: dict[str, Account] = field(default_factory=dict)
    posts: dict[str, Post] = field(default_factory=dict)
    drafts: dict[str, Draft] = field(default_factory=dict)
    comments: list[Comment] = field(default_factory=list)
    dms: list[DirectMessage] = field(default_factory=list)

    def add_user(self, user_id: str, name: str = "") -> User:
        user = User(user_id=user_id, name=name or user_id)
        self.users[user_id] = user
        return user

    def add_account(self, account_id: str, user_id: str, **kwargs: Any) -> Account:
        if user_id not in self.users:
            self.add_user(user_id)
        account = Account(account_id=account_id, user_id=user_id, **kwargs)
        self.accounts[account_id] = account
        return account

    def create_draft(
        self,
        account_id: str,
        title: str,
        body: str,
        *,
        hashtags: Iterable[str] = (),
        image_count: int = 0,
    ) -> Draft:
        draft = Draft(
            draft_id=_stable_id("draft", account_id, title, body),
            account_id=account_id,
            title=title,
            body=body,
            hashtags=tuple(str(tag).lstrip("#") for tag in hashtags),
            image_count=int(image_count),
        )
        self.drafts[draft.draft_id] = draft
        return draft

    def check_draft(
        self,
        draft: Draft,
        *,
        now: datetime | None = None,
        faults: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return structured boundary errors; empty list means publishable."""
        now = now or datetime.now()
        fault_set = set(self.config.injected_faults) | set(faults or ())
        errors: list[dict[str, Any]] = []

        account = self.accounts.get(draft.account_id)
        if account is None:
            errors.append({"code": "ACCOUNT_NOT_FOUND", "message": "账号不存在"})
            return errors
        if not account.session_valid(now):
            errors.append({"code": "SESSION_EXPIRED", "message": "登录会话已过期"})

        if len(draft.title) > self.config.title_max:
            errors.append(
                {
                    "code": "TITLE_TOO_LONG",
                    "message": f"标题 {len(draft.title)} 字超过上限 {self.config.title_max}",
                    "actual": len(draft.title),
                    "limit": self.config.title_max,
                }
            )
        if len(draft.body) > self.config.body_max:
            errors.append(
                {
                    "code": "BODY_TOO_LONG",
                    "message": f"正文 {len(draft.body)} 字超过上限 {self.config.body_max}",
                    "actual": len(draft.body),
                    "limit": self.config.body_max,
                }
            )
        if draft.image_count <= 0:
            errors.append({"code": "NO_IMAGES", "message": "图文笔记至少需要 1 张图片"})
        for term in self.config.banned_terms:
            if term and term in f"{draft.title}{draft.body}":
                errors.append(
                    {"code": "BANNED_TERM", "message": f"命中违禁词：{term}", "term": term}
                )
        if account.posts_today >= self.config.daily_post_limit:
            errors.append(
                {
                    "code": "RATE_LIMITED",
                    "message": f"今日发布已达上限 {self.config.daily_post_limit}",
                }
            )
        if "signature_unavailable" in fault_set or not self.config.signature_available:
            errors.append({"code": "SIGNATURE_UNAVAILABLE", "message": "平台签名不可用"})
        if "session_expired" in fault_set and not any(
            error["code"] == "SESSION_EXPIRED" for error in errors
        ):
            errors.append({"code": "SESSION_EXPIRED", "message": "注入故障：会话过期"})
        return errors

    def publish(
        self,
        draft_id: str,
        *,
        now: datetime | None = None,
        faults: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return {
                "status": "rejected",
                "errors": [{"code": "DRAFT_NOT_FOUND", "message": "草稿不存在"}],
            }
        errors = self.check_draft(draft, now=now, faults=faults)
        if errors:
            return {"status": "rejected", "draft_id": draft_id, "errors": errors}
        account = self.accounts[draft.account_id]
        post_id = _stable_id("post", draft.account_id, draft.title, draft.body)
        self.posts[post_id] = Post(
            post_id=post_id,
            account_id=draft.account_id,
            title=draft.title,
            body=draft.body,
        )
        account.posts_today += 1
        draft.status = "published"
        return {"status": "published", "post_id": post_id, "errors": []}

    def record_analytics(
        self,
        post_id: str,
        *,
        views: int = 0,
        likes: int = 0,
        collects: int = 0,
        comments: int = 0,
        shares: int = 0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Append one analytics snapshot to a published note."""
        post = self.posts.get(post_id)
        if post is None:
            return {
                "status": "rejected",
                "errors": [{"code": "POST_NOT_FOUND", "message": "笔记不存在"}],
            }
        fetched_at = now or datetime.now()
        snapshot = AnalyticsSnapshot(
            snapshot_id=_stable_id(
                "analytics",
                post_id,
                fetched_at.isoformat(),
                str(views),
                str(likes),
                str(collects),
                str(comments),
                str(shares),
            ),
            post_id=post_id,
            views=max(0, int(views)),
            likes=max(0, int(likes)),
            collects=max(0, int(collects)),
            comments=max(0, int(comments)),
            shares=max(0, int(shares)),
            fetched_at=fetched_at,
        )
        post.analytics.append(snapshot)
        return {"status": "recorded", "snapshot": snapshot.as_dict()}

    def comment(self, post_id: str, account_id: str, content: str) -> dict[str, Any]:
        if post_id not in self.posts:
            return {
                "status": "rejected",
                "errors": [{"code": "POST_NOT_FOUND", "message": "笔记不存在"}],
            }
        if not content.strip():
            return {
                "status": "rejected",
                "errors": [{"code": "EMPTY_COMMENT", "message": "评论为空"}],
            }
        comment = Comment(
            comment_id=_stable_id("comment", post_id, account_id, content),
            post_id=post_id,
            account_id=account_id,
            content=content,
        )
        self.comments.append(comment)
        self.posts[post_id].comments.append(comment.comment_id)
        return {"status": "sent", "comment_id": comment.comment_id}

    def send_dm(self, account_id: str, user_id: str, content: str) -> dict[str, Any]:
        account = self.accounts.get(account_id)
        if account is None:
            return {
                "status": "rejected",
                "errors": [{"code": "ACCOUNT_NOT_FOUND", "message": "账号不存在"}],
            }
        if account.dms_sent_today >= self.config.dm_quota:
            return {
                "status": "rejected",
                "errors": [{"code": "DM_QUOTA_EXHAUSTED", "message": "今日私信配额已耗尽"}],
            }
        dm = DirectMessage(
            dm_id=_stable_id("dm", account_id, user_id, content),
            account_id=account_id,
            user_id=user_id,
            content=content,
        )
        self.dms.append(dm)
        account.dms_sent_today += 1
        return {"status": "sent", "dm_id": dm.dm_id}


def simulate_publish(
    payload: Mapping[str, Any],
    *,
    config: SimulationConfig | None = None,
    tree: ContextTree | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one deterministic dry-run publish through a fresh/existing tree.

    ``payload`` accepts the workflow fields: ``account_id``, ``title``,
    ``body``, ``hashtags``, ``image_count``/``images`` and optional
    ``injected_faults``.  The returned dict always carries ``status`` and
    ``trace`` so callers can persist a machine-readable simulation result.
    """
    cfg = config or SimulationConfig()
    tree = tree or ContextTree(config=cfg)
    account_id = str(payload.get("account_id") or "dry_run_account")
    if account_id not in tree.accounts:
        tree.add_account(
            account_id,
            f"user_{account_id}",
            session_valid_until=(now or datetime.now()) + timedelta(days=1),
        )
    hashtags = payload.get("hashtags") or payload.get("tags") or ()
    if isinstance(hashtags, str):
        hashtags = [part.strip() for part in hashtags.replace("，", ",").split(",") if part.strip()]
    image_count = int(
        payload.get("image_count") or len(payload.get("images") or payload.get("image_paths") or [])
    )
    draft = tree.create_draft(
        account_id,
        str(payload.get("title") or ""),
        str(payload.get("body") or payload.get("body_text") or ""),
        hashtags=hashtags,
        image_count=image_count,
    )
    faults = payload.get("injected_faults") or cfg.injected_faults
    result = tree.publish(draft.draft_id, now=now, faults=faults)
    trace = {
        "simulator": "context-tree",
        "draft_id": draft.draft_id,
        "checks": [
            {"name": "title_length", "limit": cfg.title_max},
            {"name": "body_length", "limit": cfg.body_max},
            {"name": "banned_terms", "count": len(cfg.banned_terms)},
            {"name": "daily_post_limit", "limit": cfg.daily_post_limit},
            {
                "name": "session",
                "valid": tree.accounts[account_id].session_valid(now or datetime.now()),
            },
        ],
        "faults": list(faults or ()),
    }
    return {
        **result,
        "trace": trace,
        "post_url": f"https://www.xiaohongshu.com/explore/{result.get('post_id', '')}"
        if result.get("post_id")
        else "",
    }


__all__ = [
    "Account",
    "AnalyticsSnapshot",
    "Comment",
    "ContextTree",
    "DirectMessage",
    "Draft",
    "Post",
    "SimulationConfig",
    "User",
    "simulate_publish",
]
