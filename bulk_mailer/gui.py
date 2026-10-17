from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD
from uuid import uuid4

from .core import (
    AddressBook, DEFAULT_TEMPLATE, FIELDS, InputError, MailItem, Settings,
    data_directory, load_contacts, load_settings, parse_cc, parse_contracts, prepare_mails,
    read_address_book, read_text_file, save_contacts, save_settings, validate_address, validate_body,
)
from .outlook import apply_history, execute_batch
from .design import Layout
from .grid_table import GridRow


def readonly_text(widget: tk.Text, value: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


class Application(Layout, TkinterDnD.Tk):
    def __init__(self, data_dir: Path | None = None, *, preview_mode: bool = False) -> None:
        super().__init__()
        self.title("Mail Desk — 契約通知メール作成")
        self.geometry(f"{min(1500, max(1120, self.winfo_screenwidth() - 60))}x{min(940, max(700, self.winfo_screenheight() - 100))}")
        self.minsize(1120, 700)
        self.preview_mode = preview_mode
        self.install_theme()
        self.directory = data_dir if data_dir is not None else data_directory()
        self.settings_path = self.directory / "settings.json"
        self.contacts_path = self.directory / "contacts.json"
        initial_error = ""
        try:
            self.settings = load_settings(self.settings_path)
        except InputError as error:
            self.settings = Settings()
            initial_error = str(error)
        self.book = AddressBook()
        self.contacts_dirty = False
        self.items: list[MailItem] = []
        self.source_snapshot: str | None = None
        self.busy = False
        self.saved_states: list[tuple[tk.Widget, str]] = []
        self.events: queue.Queue = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.build_shell()
        self.register_file_drops(self)
        self.update_mode_label()
        if self.contacts_path.exists() or self.settings.address_book_path:
            try:
                if self.contacts_path.exists():
                    self.book, source_excel = load_contacts(self.contacts_path)
                    self.settings.address_book_path = source_excel
                    self.path_var.set(source_excel)
                else:
                    # Migrate the old Excel-path-only setting once.
                    imported = read_address_book(self.settings.address_book_path)
                    save_contacts(imported, self.contacts_path, self.settings.address_book_path)
                    self.book = imported
                self.contact_info.set(f"{len(self.book.contacts)}件の宛先をJSONから復元済み")
            except (InputError, OSError) as error:
                initial_error += "\n" + str(error)
        if initial_error:
            self.after(100, lambda: messagebox.showwarning("設定・宛先表の確認", initial_error.strip(), parent=self))
        self.poll_job = self.after(150, self.poll_events)

    def update_mode_label(self) -> None:
        sending = self.settings.mode == "send"
        self.mode_label.configure(text="●  " + ("送信する" if sending else "下書きに保存"),
                                  foreground="#a33b30" if sending else "#245ca6",
                                  background="#fff0ed" if sending else "#edf3ff")
        self.execute_button.configure(text="対象メールを送信  →" if sending else "下書きを保存  →",
                                      style="Danger.TButton" if sending else "Primary.TButton")

    def refresh_contacts(self) -> None:
        names = ["".join(contact.name.split()) for contact in self.book.contacts]
        self.contact_info.set(f"{len(names)}件をJSON保存済み（設定を保存して一覧に反映）")

    def register_file_drops(self, widget: tk.Misc) -> None:
        """Accept files even when the pointer is over a child control."""
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<DropEnter>>", self.allow_file_drop)
        widget.dnd_bind("<<DropPosition>>", self.allow_file_drop)
        widget.dnd_bind("<<Drop>>", self.on_file_drop)
        for child in widget.winfo_children():
            self.register_file_drops(child)

    def allow_file_drop(self, event) -> str:
        # File names are supplied only at Drop, not at DropEnter/DropPosition.
        return REFUSE_DROP if self.busy else COPY

    def on_file_drop(self, event) -> str:
        if self.busy:
            return REFUSE_DROP
        try:
            paths = self.tk.splitlist(event.data)
        except (tk.TclError, TypeError):
            paths = ()
        if len(paths) != 1:
            messagebox.showwarning("ファイルの取り込み", "txtまたはExcel（.xlsx）を1ファイルずつドロップしてください。", parent=self)
            return REFUSE_DROP
        path = Path(paths[0])
        if path.suffix.lower() not in {".txt", ".xlsx"} or not path.is_file():
            messagebox.showwarning("ファイルの取り込み", "読み込めるファイルはtxtとExcel（.xlsx）です。フォルダーは読み込めません。", parent=self)
            return REFUSE_DROP
        success = self.load_text(path) if path.suffix.lower() == ".txt" else self.import_contacts(path)
        return COPY if success else REFUSE_DROP

    def import_contacts(self, path: str | Path | None = None) -> bool:
        if self.busy:
            return False
        if path is None:
            path = filedialog.askopenfilename(parent=self, title="氏名・メールアドレスの対応表", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return False
        path = str(path)
        try:
            book = read_address_book(path)
            save_contacts(book, self.contacts_path, path)
        except (InputError, OSError) as error:
            messagebox.showerror("宛先の読み込み・保存エラー", str(error), parent=self)
            return False
        self.book = book
        self.contacts_dirty = True
        self.path_var.set(path)
        self.refresh_contacts()
        self.status.set("宛先JSONを全件置換しました。設定を保存して一覧へ反映してください。")
        self.notebook.select(self.settings_page)
        return True

    def show_contacts(self) -> None:
        if self.busy:
            return
        window = tk.Toplevel(self)
        window.title("宛先対応表")
        window.geometry("700x450")
        window.transient(self)
        from .core import normalize_name
        counts: dict[str, int] = {}
        for contact in self.book.contacts:
            key = normalize_name(contact.name)
            counts[key] = counts.get(key, 0) + 1
        text = ScrolledText(window, wrap="none")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        rows = [f"{contact.name}\t{contact.email}" + ("\t【氏名重複】" if counts[normalize_name(contact.name)] > 1 else "")
                for contact in self.book.contacts]
        readonly_text(text, "氏名\tメールアドレス\n\n" + "\n".join(rows))
        window.grab_set()

    def reset_template(self) -> None:
        if not self.busy:
            self.template_input.delete("1.0", "end")
            self.template_input.insert("1.0", DEFAULT_TEMPLATE)

    def form_settings(self) -> Settings:
        return Settings(subject=self.subject_var.get().strip(),
                        cc=self.cc_input.get("1.0", "end-1c"),
                        template=self.template_input.get("1.0", "end-1c"),
                        mode=self.mode_var.get(), address_book_path=self.path_var.get())

    def has_unsaved_settings(self) -> bool:
        return self.contacts_dirty or asdict(self.form_settings()) != asdict(self.settings)

    def save_config(self) -> None:
        if self.busy:
            return
        try:
            candidate = self.form_settings()
            candidate.validate()
            book = self.book
            replacements = prepare_mails([item.contract for item in self.items], candidate, book)
            apply_history(replacements, candidate.mode, self.directory / "logs")
            save_settings(candidate, self.settings_path)
        except (InputError, OSError) as error:
            messagebox.showerror("設定エラー", str(error), parent=self)
            return
        self.settings, self.book = candidate, book
        self.contacts_dirty = False
        if self.items:
            for index, replacement in enumerate(replacements):
                old = self.items[index]
                if old.status == "未実行" or old.status.startswith("履歴あり"):
                    if replacement.status == "未実行":
                        replacement.included = old.included if old.status == "未実行" else True
                    self.items[index] = replacement
            self.refresh_table()
        self.refresh_contacts()
        self.contact_info.set(f"{len(self.book.contacts)}件の宛先をJSON保存済み")
        self.update_mode_label()
        self.status.set("設定を保存しました。" + ("未実行メールの内容を更新しました。" if self.items else ""))

    def load_text(self, path: str | Path | None = None) -> bool:
        if self.busy:
            return False
        if path is None:
            path = filedialog.askopenfilename(parent=self, title="入力テキスト", filetypes=[("テキスト", "*.txt"), ("すべて", "*.*")])
        if not path:
            return False
        try:
            text = read_text_file(path)
        except (InputError, OSError) as error:
            messagebox.showerror("txt読込エラー", str(error), parent=self)
            return False
        if self.source.get("1.0", "end-1c").strip() and not messagebox.askyesno("入力を置き換え", "現在の入力テキストを置き換えますか？", parent=self):
            return False
        self.source.delete("1.0", "end")
        self.source.insert("1.0", text)
        self.source_info.set(f"{Path(path).name}  ·  {len(text.splitlines())}行")
        self.status.set(f"読み込み済み: {Path(path).name}。リスト作成後に内容を確認してください。")
        self.notebook.select(self.input_page)
        return True

    def create_list(self) -> None:
        if self.busy:
            return
        if self.has_unsaved_settings():
            messagebox.showinfo("設定の保存", "設定画面の変更を保存してからリストを作成してください。", parent=self)
            self.notebook.select(self.settings_page)
            return
        try:
            source = self.source.get("1.0", "end-1c")
            contracts = parse_contracts(source)
            items = prepare_mails(contracts, self.settings, self.book)
            apply_history(items, self.settings.mode, self.directory / "logs")
        except InputError as error:
            messagebox.showerror("入力・実行履歴の確認", str(error), parent=self)
            return
        if self.items and not messagebox.askyesno("リストを作り直す", "現在のリストと個別編集を置き換えます。\n実行済みのメールはOutlookに残ります。同じデータを再実行しないよう確認してください。\n\nリストを作り直しますか？", parent=self):
            return
        self.items = items
        self.source_snapshot = source
        self.refresh_table()
        self.notebook.select(self.review_page)
        self.table.xview_moveto(0)
        self.table.select_position(0)
        self.status.set(f"{len(items)}件を取り込みました。宛先と本文を確認してください。")

    def selected_item(self) -> MailItem | None:
        selection = self.table.selection()
        if not selection:
            return None
        index = int(selection[0])
        return self.items[index] if index < len(self.items) else None

    @staticmethod
    def mail_problem(item: MailItem) -> str:
        try:
            item.validate_content()
        except InputError as error:
            return str(error)
        if "要確認" in item.status:
            return "実行結果が不確定です。Outlookと処理記録を確認してください。"
        return ""

    def refresh_table(self) -> None:
        selected = self.table.selection()
        scroll_y, scroll_x = self.table.yview(), self.table.xview()
        common_cc = parse_cc(self.settings.cc)
        rows = []
        for index, item in enumerate(self.items):
            values = item.contract.values
            problem = self.mail_problem(item)
            state = "要修正" if problem else {
                "未実行": "作成待ち", "下書き保存済み": "下書き済", "送信要求済み": "送信要求済",
            }.get(item.status, "処理済み")
            if item.status.startswith("履歴あり"):
                state = "要確認" if problem else "履歴あり"
            elif item.status == "実行中":
                state = "実行中"
            address_line = item.to or "宛先未登録"
            if item.cc != common_cc:
                address_line += "  CC：" + ("; ".join(item.cc) or "なし")
            rows.append(GridRow(str(index), (
                ("✓ 対象" if item.included else "— 除外") + "\n" + state,
                values["管理番号"] + "\n" + values["契約承認状態"],
                values["氏名"] + "（" + values["派遣元"] + "）\n" + address_line,
                "開始：" + values["受入開始日"] + "\n終了：" + values["受入終了日"],
                values["会社名"] + " / " + values["事業所名"] + "\n" +
                " / ".join(values[key] for key in ("部署名", "業務名", "チーム名")),
            ), problem, item.status))
        self.table.set_rows(rows)
        if selected and int(selected[0]) < len(self.items):
            self.table.selection_set(selected[0])
        if scroll_y:
            self.table.yview_moveto(scroll_y[0])
        if scroll_x:
            self.table.xview_moveto(scroll_x[0])
        pending = [item for item in self.items if item.included and item.status == "未実行"]
        issues = sum(bool(self.mail_problem(item)) for item in pending)
        self.summary.set(f"全 {len(self.items)}件  ·  作成対象 {len(pending)}件" + (f"  ·  要修正 {issues}件" if issues else ""))
        self.list_subject.set("件名：" + (self.settings.subject or "未設定") + "    CC：" + ("; ".join(common_cc) or "なし"))
        self.show_preview()

    def show_preview(self) -> None:
        item = self.selected_item()
        if item is None:
            self.preview_person.set("一覧からメールを選択")
            self.preview_to.set("—")
            self.preview_cc.set("—")
            self.preview_subject.set("件名は設定で登録できます")
            self.preview_issue.set("")
            readonly_text(self.preview, "一覧からメールを選択してください。")
            readonly_text(self.record_preview, "取り込んだ契約の情報を表示します。")
            return
        values = item.contract.values
        self.preview_person.set(f"{values['氏名']}  /  {values['管理番号']}")
        self.preview_to.set(item.to or "未確定：宛先を指定してください")
        self.preview_cc.set("; ".join(item.cc) or "なし")
        self.preview_subject.set(item.subject or "件名未設定：設定で登録してください")
        problem = self.mail_problem(item)
        self.preview_issue.set("要修正：" + problem if problem else "")
        readonly_text(self.preview, item.body)
        readonly_text(self.record_preview, "\n\n".join(f"{key}  {values[key]}" for key in FIELDS))

    def toggle_included(self) -> None:
        if self.busy:
            return
        item = self.selected_item()
        if item is not None and item.status == "未実行":
            item.included = not item.included
            self.refresh_table()

    def edit_mail(self) -> None:
        if self.busy:
            return
        item = self.selected_item()
        if item is None or item.status != "未実行":
            return
        window = tk.Toplevel(self)
        window.title(f"メールを編集 — {item.contract.values['氏名']}")
        window.geometry("850x650")
        window.minsize(650, 450)
        window.configure(background="#f3f5f9")
        window.transient(self)
        window.columnconfigure(1, weight=1)
        to_var, cc_var = tk.StringVar(value=item.to), tk.StringVar(value="; ".join(item.cc))
        for row, label, variable in ((0, "To", to_var), (1, "CC", cc_var)):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=12, pady=8)
            ttk.Entry(window, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=8)
        ttk.Label(window, text="件名").grid(row=2, column=0, padx=12, pady=8)
        ttk.Label(window, text=item.subject or "未設定（設定画面で共通件名を入力してください）", wraplength=700)\
            .grid(row=2, column=1, sticky="w")
        body = self.text_box(window, wrap="word", undo=True)
        body.insert("1.0", item.body)
        body.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=12, pady=8)
        window.rowconfigure(3, weight=1)

        def save() -> None:
            try:
                address = validate_address(to_var.get())
                cc = parse_cc(cc_var.get())
                content = body.get("1.0", "end-1c")
                validate_body(content)
            except InputError as error:
                messagebox.showerror("入力内容の確認", str(error), parent=window)
                return
            item.to, item.cc, item.body = address, cc, content
            if not item.issue.startswith("管理番号が重複"):
                item.issue = ""
            window.destroy()
            self.refresh_table()

        ttk.Button(window, text="変更を反映", style="Primary.TButton", command=save).grid(row=4, column=1, sticky="e", padx=12, pady=12)
        window.grab_set()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.saved_states = []

            def disable(widget: tk.Widget) -> None:
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Radiobutton, tk.Text)):
                    state = str(widget.cget("state"))
                    self.saved_states.append((widget, state))
                    widget.configure(state="disabled")
                for child in widget.winfo_children():
                    disable(child)

            disable(self.notebook)
            self.progress.pack(side="right", padx=(14, 0))
            self.progress.start(12)
        else:
            for widget, state in self.saved_states:
                widget.configure(state=state)
            self.saved_states = []
            self.progress.stop()
            self.progress.pack_forget()

    def execute(self) -> None:
        if self.busy:
            return
        if self.preview_mode:
            messagebox.showinfo("画面プレビュー", "プレビューではOutlookの操作を実行しません。", parent=self)
            return
        if self.has_unsaved_settings():
            messagebox.showinfo("設定の保存", "設定画面の変更を保存し、内容を再確認してから実行してください。", parent=self)
            self.notebook.select(self.settings_page)
            return
        if self.items and self.source_snapshot != self.source.get("1.0", "end-1c"):
            messagebox.showinfo("リストの再作成", "入力テキストが変更されています。作成対象リストを作り直し、内容を確認してから実行してください。", parent=self)
            self.notebook.select(self.input_page)
            return
        items = [item for item in self.items if item.included and item.status == "未実行"]
        try:
            self.settings.validate(execution=True)
            if not items:
                raise InputError("実行対象がありません。")
            for item in items:
                item.validate()
        except InputError as error:
            messagebox.showerror("実行できません", str(error), parent=self)
            return
        mode = self.settings.mode
        action = "送信します" if mode == "send" else "Outlookの下書きに保存します"
        detail = "\n送信にはOutlookの既定アカウントを使用します。" if mode == "send" else ""
        if not messagebox.askyesno("送信確認" if mode == "send" else "下書き保存の確認",
                                  f"一覧で全件の宛先・本文を確認しましたか？\n\n{len(items)}件のメールを{action}。\n件名: {self.settings.subject}{detail}\n\n実行しますか？", parent=self):
            return
        self.set_busy(True)
        self.status.set(f"{len(items)}件を処理しています。")
        journal_path = self.directory / "logs" / (datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8] + ".jsonl")

        def worker() -> None:
            error = ""
            try:
                execute_batch(items, mode, journal_path, lambda index, status: self.events.put(("progress", index + 1, len(items), status)))
            except Exception as exception:
                error = str(exception)
            self.events.put(("finished", error, str(journal_path)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self) -> None:
        latest_progress = None
        finished = None
        try:
            for _ in range(5000):
                event = self.events.get_nowait()
                if event[0] == "progress":
                    latest_progress = event
                elif event[0] == "finished":
                    finished = event
        except queue.Empty:
            pass
        if finished is not None:
            self.set_busy(False)
            for item in self.items:
                if item.status != "未実行":
                    item.included = False
            self.refresh_table()
            if finished[1]:
                self.status.set("処理を停止しました。実行結果とOutlookを確認してください。")
                messagebox.showerror("処理停止", finished[1] + "\n\n処理記録: " + finished[2], parent=self)
            else:
                self.status.set("処理が完了しました。記録: " + finished[2])
                messagebox.showinfo("完了", "対象メールの処理が完了しました。\n送信要求済みのメールはOutlookで送信状況を確認できます。" if self.settings.mode == "send"
                                    else "Outlookの下書きフォルダーに保存しました。", parent=self)
        elif latest_progress is not None:
            self.status.set(f"{latest_progress[1]} / {latest_progress[2]}件: {latest_progress[3]}")
            self.refresh_table()
        self.poll_job = self.after(150, self.poll_events)

    def destroy(self) -> None:
        if hasattr(self, "poll_job"):
            self.after_cancel(self.poll_job)
        super().destroy()

    def close_app(self) -> None:
        if self.busy:
            messagebox.showinfo("処理中", "Outlookの処理が完了してから終了してください。", parent=self)
            return
        if self.has_unsaved_settings():
            message = "保存していない設定があります。保存せずに終了しますか？"
            if self.contacts_dirty:
                message += "\n\nExcelから読み込んだ宛先JSONは保存済みです。"
            if not messagebox.askyesno("未保存の設定", message, parent=self):
                return
        self.destroy()


def main() -> None:
    if os.name != "nt":
        raise SystemExit("このアプリはWindows専用です。Windowsで python main.py を実行してください。")
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MailDesk.ContractNotification.1")
    except (OSError, AttributeError):
        pass
    Application().mainloop()
