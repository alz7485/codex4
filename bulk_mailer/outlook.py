from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .core import InputError, MailItem


class OutlookClient:
    """Instantiate in the worker thread and keep COM objects on that thread."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise InputError("Outlook連携はWindowsと従来版Outlookが必要です。")
        try:
            import pythoncom
            import win32com.client
        except ImportError as error:
            raise InputError("pywin32がありません。requirements.txtのパッケージをインストールしてください。") from error
        self.pythoncom = pythoncom
        pythoncom.CoInitialize()
        try:
            self.application = win32com.client.Dispatch("Outlook.Application")
            self.application.GetNamespace("MAPI").GetDefaultFolder(16)  # olFolderDrafts
        except Exception as error:
            pythoncom.CoUninitialize()
            raise InputError(f"従来版Outlookに接続できません。プロファイル設定と起動状態を確認してください。\n{error}") from error

    def close(self) -> None:
        self.application = None
        self.pythoncom.CoUninitialize()

    def create(self, item: MailItem, mode: str) -> str:
        mail = self.application.CreateItem(0)
        for address, kind in [(item.to, 1), *((address, 2) for address in item.cc)]:
            recipient = mail.Recipients.Add(address)
            recipient.Type = kind
        if not mail.Recipients.ResolveAll():
            raise InputError("Outlookで宛先を解決できません。")
        mail.Subject = item.subject
        mail.BodyFormat = 1  # olFormatPlain
        mail.Body = item.body
        if mode == "draft":
            mail.Save()
            return "下書き保存済み"
        if mode == "send":
            mail.Send()
            return "送信要求済み"
        raise InputError("実行方法が不正です。")


class Journal:
    """Flush an intent before Outlook is called; never retry uncertain operations."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a", encoding="utf-8")

    def write(self, item: MailItem, mode: str, status: str, detail: str = "") -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(),
                 "management_number": item.contract.values["管理番号"],
                 "to": item.to, "mode": mode, "status": status, "detail": detail}
        self.file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self) -> None:
        self.file.close()


class OperationLock:
    """One nonblocking OS lock shared by all runs in a logs directory."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.file = None

    def __enter__(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.file = (self.directory / ".execution.lock").open("a+b")
            self.file.seek(0, os.SEEK_END)
            if self.file.tell() == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if self.file is not None:
                self.file.close()
                self.file = None
            raise InputError("処理記録をロックできません。別の実行が処理中でないか、"
                             f"保存先の権限を確認してください。\n{error}") from error
        return self

    def __exit__(self, *_):
        # Closing the handle releases flock/byte-range locks, even on exceptions.
        if self.file is not None:
            self.file.close()
            self.file = None


def _read_history(directory: Path) -> dict[tuple[str, str], str]:
    """Read v2 JSONL logs under OperationLock; malformed history fails closed."""
    history: dict[tuple[str, str], str] = {}
    statuses = {"開始", "下書き保存済み", "送信要求済み", "要確認（再実行不可）"}
    try:
        # iterdir propagates access errors; glob can silently skip unreadable dirs.
        for path in sorted(path for path in Path(directory).iterdir() if path.suffix.lower() == ".jsonl"):
            current = {}
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("記録がオブジェクトではありません。")
                    number, mode, status = row.get("management_number"), row.get("mode"), row.get("status")
                    if (not isinstance(number, str) or not number.strip()
                            or mode not in ("draft", "send") or status not in statuses
                            or status == "下書き保存済み" and mode != "draft"
                            or status == "送信要求済み" and mode != "send"):
                        raise ValueError("管理番号・実行方法・処理状態が不正です。")
                    current[number, mode] = status if status in ("下書き保存済み", "送信要求済み") else "要確認"
                except (ValueError, TypeError) as error:
                    raise InputError(f"処理記録が壊れています: {path} ({line_number}行目)\n{error}\n"
                                     "Outlookと処理記録を確認してください。") from error
            for key, status in current.items():
                history[key] = "要確認" if "要確認" in (history.get(key), status) else status
    except (OSError, UnicodeError) as error:
        raise InputError(f"過去の処理記録を読み取れません。Outlookと処理記録を確認してください。\n{error}") from error
    return history


def apply_history(items: list[MailItem], mode: str, logs_directory: Path) -> None:
    """Reflect previous attempts into a newly prepared GUI list."""
    if mode not in ("draft", "send"):
        raise InputError("実行方法が不正です。")
    with OperationLock(logs_directory):
        history = _read_history(logs_directory)
        for item in items:
            status = history.get((item.contract.values["管理番号"], mode))
            if status:
                item.status = f"履歴あり（{status}）"
                item.included = False
                item.reviewed = False


def execute_batch(items: list[MailItem], mode: str, journal_path: Path,
                  callback: Callable[[int, str], None],
                  factory: Callable = OutlookClient) -> None:
    if mode not in ("draft", "send"):
        raise InputError("実行方法が不正です。")
    if not items:
        raise InputError("実行対象がありません。")
    keys = set()
    for item in items:
        item.validate()
        key = item.contract.values["管理番号"], mode
        if key in keys:
            raise InputError(f"管理番号 {key[0]} が実行対象内で重複しています。")
        keys.add(key)
    journal_path = Path(journal_path)
    with OperationLock(journal_path.parent):
        history = _read_history(journal_path.parent)
        for number, operation in keys:
            if (number, operation) in history:
                raise InputError(f"管理番号 {number} には過去の実行履歴（{history[number, operation]}）があります。\n"
                                 "再実行を停止しました。Outlookの下書き・送信トレイ・送信済みと処理記録を確認してください。")
        journal = Journal(journal_path)
        client = None
        try:
            client = factory()
            for index, item in enumerate(items):
                item.validate()
                journal.write(item, mode, "開始")
                item.status = "実行中"
                callback(index, item.status)
                try:
                    status = client.create(item, mode)
                except Exception as error:
                    item.status = "要確認（再実行不可）"
                    # A logging/UI failure must never hide the uncertain Outlook result.
                    secondary = []
                    try:
                        callback(index, item.status)
                    except Exception as callback_error:
                        secondary.append(f"画面更新失敗: {callback_error}")
                    try:
                        journal.write(item, mode, item.status, str(error))
                    except Exception as journal_error:
                        secondary.append(f"処理記録の保存失敗: {journal_error}")
                    detail = "\n" + "\n".join(secondary) if secondary else ""
                    raise InputError(f"管理番号 {item.contract.values['管理番号']} で処理を停止しました。\n"
                                     f"{error}{detail}\nOutlookの下書き・送信トレイ・送信済みを確認してください。"
                                     "未処理分はそのまま残ります。") from error
                item.status = status
                callback(index, status)
                journal.write(item, mode, status)
        finally:
            # Preserve any primary operation error while attempting every cleanup.
            primary_error = sys.exc_info()[1]
            cleanup_errors = []
            if client is not None:
                try:
                    client.close()
                except Exception as error:
                    cleanup_errors.append(error)
            try:
                journal.close()
            except Exception as error:
                cleanup_errors.append(error)
            if cleanup_errors and primary_error is None:
                raise cleanup_errors[0]
