"""他メンバーの閲覧・チーム一覧（F-08）。"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from . import aggregate as ag
from .models import STATUS_IN_PROGRESS, Task, Worklog
from .repository import DataFolder, UserRepository

LOAD_ERROR_MESSAGE = "読み込めませんでした"


@dataclass
class Member:
    username: str
    display_name: str
    repo: UserRepository | None = None
    error: str | None = None  # 読み込めなかった理由

    @property
    def ok(self) -> bool:
        return self.repo is not None


@dataclass
class MemberDay:
    member: Member
    worklogs: list[Worklog] = field(default_factory=list)
    working: int = 0
    in_progress: list[Task] = field(default_factory=list)


def member_names(folder: DataFolder) -> dict[str, str]:
    """ユーザー名 → 表示名（profile.json が読めなければユーザー名）。利用者切り替えリスト用。"""
    from . import storage
    from .models import Profile
    out = {}
    for u in folder.list_usernames():
        try:
            d = storage.read_json(folder.users_dir / u / "profile.json", default=None)
            name = Profile.from_dict(d).display_name if d else ""
        except (OSError, ValueError):
            name = ""
        out[u] = name or u
    return out


def load_members(folder: DataFolder, me: UserRepository) -> list[Member]:
    """全メンバーを読み取り専用で読み込む。自分は画面のデータ（未保存の変更を含む）を使う。

    読み込めないメンバーは error に理由を入れ、他のメンバーは表示を続けられるようにする。
    並びは 自分 → 他のメンバー（表示名順）。
    """
    names = member_names(folder)
    members = [Member(me.username, me.profile.display_name, me)]
    others = []
    for u, display in names.items():
        if u == me.username:
            continue
        try:
            repo = folder.user(u, readonly=True)
            others.append(Member(u, repo.profile.display_name or display, repo))
        except (OSError, ValueError, KeyError, TypeError) as e:
            others.append(Member(u, display, None, f"{type(e).__name__}: {e}"))
    others.sort(key=lambda m: (m.display_name, m.username))
    return members + others


def in_progress_tasks(tasks: list[Task]) -> list[Task]:
    """進行中のタスク（完了予定日の近い順、未設定は後ろ）。"""
    rows = [t for t in tasks if t.status == STATUS_IN_PROGRESS]
    rows.sort(key=lambda t: (t.planned_end or _dt.date.max, t.id))
    return rows


def team_day(members: list[Member], day: _dt.date) -> list[MemberDay]:
    out = []
    for m in members:
        if not m.ok:
            out.append(MemberDay(m))
            continue
        ws = m.repo.worklogs_on(day)
        out.append(MemberDay(m, ws, ag.working_minutes(ws), in_progress_tasks(m.repo.tasks)))
    return out
