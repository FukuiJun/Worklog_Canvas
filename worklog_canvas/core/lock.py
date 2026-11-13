"""同じ利用者が2台のPCで同時に起動したことの検出（仕様9章）。

自分のフォルダに .lock を置き、起動中は1分ごとに更新する。
他のPC（または同じPCの別の起動）が使用中で、更新が新しい（2分以内）なら、後から起動した方は閲覧モードで開く。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from . import storage

LOCK_FILE = ".lock"
STALE_AFTER = _dt.timedelta(minutes=2)
HEARTBEAT_SECONDS = 60


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class LockInfo:
    host: str
    pid: int
    started: str
    heartbeat: _dt.datetime


@dataclass
class LockResult:
    acquired: bool
    other: LockInfo | None = None  # 使用中の相手（acquired=False のとき）


class UserLock:
    def __init__(self, user_dir: Path, host: str | None = None, pid: int | None = None):
        self.path = Path(user_dir) / LOCK_FILE
        self.host = host or socket.gethostname()
        self.pid = pid or os.getpid()
        self.started = _dt.datetime.now().isoformat(timespec="seconds")
        self.held = False

    def read(self) -> LockInfo | None:
        try:
            d = json.loads(self.path.read_text("utf-8"))
            return LockInfo(d["host"], int(d["pid"]), d.get("started", ""),
                            _dt.datetime.fromisoformat(d["heartbeat"]))
        except (OSError, ValueError, KeyError):
            return None

    def _is_me(self, info: LockInfo) -> bool:
        return info.host == self.host and info.pid == self.pid

    def acquire(self, now: _dt.datetime | None = None) -> LockResult:
        now = now or _dt.datetime.now()
        info = self.read()
        if info and not self._is_me(info):
            fresh = now - info.heartbeat < STALE_AFTER
            same_host_dead = info.host == self.host and not _pid_alive(info.pid)
            if fresh and not same_host_dead:
                return LockResult(False, info)
        self.heartbeat(now)
        self.held = True
        return LockResult(True)

    def heartbeat(self, now: _dt.datetime | None = None) -> None:
        now = now or _dt.datetime.now()
        storage.atomic_write_json(self.path, {"host": self.host, "pid": self.pid, "started": self.started,
                                              "heartbeat": now.isoformat(timespec="seconds")})

    def release(self) -> None:
        if not self.held:
            return
        info = self.read()
        if info is None or self._is_me(info):
            try:
                self.path.unlink()
            except OSError:
                pass
        self.held = False
