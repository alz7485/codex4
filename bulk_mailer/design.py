"""Visual layout shared by the Windows application and the screenshot preview."""
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, ttk
from tkinter.scrolledtext import ScrolledText

from .core import FIELDS

BG = "#f3f5f9"
WHITE = "#ffffff"
INK = "#18263b"
MUTED = "#758197"
LINE = "#e4e9f1"
BLUE = "#2867e8"
NAV = "#17263e"


class PageStack(ttk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, style="Page.TFrame")
        self.on_select = on_select
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def add(self, page, **_):
        page.grid(row=0, column=0, sticky="nsew")

    def select(self, page):
        page.tkraise()
        self.on_select(page)


def card(parent, padding=18):
    return ttk.Frame(parent, style="Card.TFrame", padding=padding)


def scroll_card(parent, padding=22):
    outer = card(parent, 0)
    canvas = tk.Canvas(outer, background=WHITE, highlightthickness=0, width=100, height=100)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = ttk.Frame(canvas, style="Surface.TFrame", padding=padding)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

    def wheel(event):
        widget = event.widget
        while widget is not None:
            if widget == outer:
                canvas.yview_scroll(-int(event.delta / 120), "units")
                break
            widget = getattr(widget, "master", None)

    outer.winfo_toplevel().bind("<MouseWheel>", wheel, add="+")
    return outer, inner


class Layout:
    def install_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        available = set(tkfont.families(self))
        self.ui_font = next((name for name in ("Yu Gothic UI", "Noto Sans CJK JP", "Meiryo") if name in available), "TkDefaultFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=self.ui_font, size=10)
        style.configure(".", font=(self.ui_font, 10), background=BG, foreground=INK)
        style.configure("Page.TFrame", background=BG)
        style.configure("Surface.TFrame", background=WHITE, borderwidth=0)
        style.configure("Card.TFrame", background=WHITE, borderwidth=1, relief="solid", bordercolor=LINE)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=WHITE)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("CardMuted.TLabel", background=WHITE, foreground=MUTED, font=(self.ui_font, 9))
        style.configure("Heading.TLabel", font=(self.ui_font, 23, "bold"))
        style.configure("CardTitle.TLabel", background=WHITE, font=(self.ui_font, 11, "bold"))
        style.configure("Subject.TLabel", background=WHITE, font=(self.ui_font, 12, "bold"))
        style.configure("Metric.TLabel", background=WHITE, font=(self.ui_font, 25, "bold"))
        style.configure("MetricBlue.TLabel", background=WHITE, foreground=BLUE, font=(self.ui_font, 25, "bold"))
        style.configure("MetricGreen.TLabel", background=WHITE, foreground="#168069", font=(self.ui_font, 25, "bold"))
        style.configure("MetricOrange.TLabel", background=WHITE, foreground="#c47a21", font=(self.ui_font, 25, "bold"))
        style.configure("TButton", background=WHITE, foreground=INK, bordercolor=LINE, borderwidth=1,
                        padding=(13, 8), focusthickness=0, font=(self.ui_font, 9))
        style.map("TButton", background=[("active", "#edf2fa"), ("disabled", "#f2f4f8")],
                  foreground=[("disabled", "#a7b0be")], bordercolor=[("active", "#b8c8e3")])
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE, bordercolor=BLUE,
                        font=(self.ui_font, 10, "bold"), padding=(22, 10))
        style.map("Primary.TButton", background=[("disabled", "#bacbef"), ("active", "#1e54c9")],
                  foreground=[("disabled", "#edf2fc"), ("active", WHITE)], bordercolor=[("active", "#1e54c9")])
        style.configure("Danger.TButton", background="#c34739", foreground=WHITE, bordercolor="#c34739", padding=(22, 10))
        style.map("Danger.TButton", background=[("active", "#a63529"), ("disabled", "#dcc2bf")], foreground=[("active", WHITE)])
        style.configure("Nav.TButton", background=NAV, foreground="#a9bad1", borderwidth=0, bordercolor=NAV,
                        anchor="w", padding=(18, 14), font=(self.ui_font, 10))
        style.map("Nav.TButton", background=[("active", "#213651")], foreground=[("active", WHITE)])
        style.configure("NavSelected.TButton", background="#294362", foreground=WHITE, borderwidth=0,
                        bordercolor="#294362", anchor="w", padding=(18, 14), font=(self.ui_font, 10, "bold"))
        style.map("NavSelected.TButton", background=[("active", "#304d70")], foreground=[("active", WHITE)])
        style.configure("TEntry", fieldbackground=WHITE, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=9)
        style.map("TEntry", bordercolor=[("focus", BLUE)], fieldbackground=[("readonly", "#f5f7fb")])
        style.configure("TRadiobutton", background=WHITE, padding=(4, 6))
        style.map("TRadiobutton", background=[("active", WHITE)])
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, borderwidth=0,
                        rowheight=44, font=(self.ui_font, 9))
        style.configure("Treeview.Heading", background="#f7f9fc", foreground=MUTED, borderwidth=0,
                        padding=(8, 12), font=(self.ui_font, 9))
        style.map("Treeview", background=[("selected", "#eaf1ff")], foreground=[("selected", "#194aa7")])
        style.map("Treeview.Heading", background=[("active", "#edf2f9")])
        style.configure("TScrollbar", background="#d6dfe9", troughcolor=WHITE, borderwidth=0,
                        arrowcolor=MUTED, arrowsize=12)
        style.configure("TNotebook", background=WHITE, borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab", background=WHITE, foreground=MUTED, padding=(16, 10), borderwidth=0)
        # Clam's inherited selected padding overrides configure(), changing tab size.
        style.map("TNotebook.Tab", background=[("selected", "#edf3ff")], foreground=[("selected", BLUE)],
                  padding=[("selected", (16, 10)), ("!selected", (16, 10))])
        style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor="#e8edf5", borderwidth=0)
        self.configure(background=BG)
        image_path = Path(__file__).parent / "assets" / "maildesk.png"
        if image_path.exists():
            self.app_icon = tk.PhotoImage(file=str(image_path))
            self.iconphoto(True, self.app_icon)

    def text_box(self, parent, **options):
        box = ScrolledText(parent, relief="flat", borderwidth=0, highlightthickness=0,
                           background=WHITE, foreground=INK, insertbackground=BLUE,
                           selectbackground="#d8e6ff", selectforeground=INK,
                           font=(self.ui_font, 10), padx=8, pady=8, spacing1=2, spacing3=4, **options)
        box.vbar.configure(background=WHITE, troughcolor=WHITE, relief="flat", borderwidth=0, width=10)
        return box

    def heading(self, page, title, description):
        frame = ttk.Frame(page, style="Page.TFrame")
        frame.pack(fill="x", pady=(0, 22))
        ttk.Label(frame, text=title, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(frame, text=description, style="Muted.TLabel").pack(anchor="w", pady=(7, 0))

    def build_shell(self):
        sidebar = tk.Frame(self, background=NAV, width=202)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=NAV)
        brand.pack(fill="x", padx=24, pady=(30, 30))
        if hasattr(self, "app_icon"):
            self.brand_icon = self.app_icon.subsample(2, 2)
            tk.Label(brand, image=self.brand_icon, bg=NAV).pack(anchor="w", pady=(0, 12))
        tk.Label(brand, text="MAIL DESK", bg=NAV, fg=WHITE, font=(self.ui_font, 17, "bold")).pack(anchor="w")
        tk.Label(brand, text="契約通知メール作成", bg=NAV, fg="#9fb0c9", font=(self.ui_font, 9)).pack(anchor="w", pady=(5, 0))
        tk.Label(sidebar, text="ワークスペース", bg=NAV, fg="#7287a6", font=(self.ui_font, 8)).pack(anchor="w", padx=24, pady=(4, 10))
        self.nav_buttons = []
        for index, label in enumerate(("01    テキスト入力", "02    一覧・内容確認", "       設定")):
            button = ttk.Button(sidebar, text=label, style="Nav.TButton", command=lambda i=index: self.navigate(i))
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons.append(button)
        bottom = tk.Frame(sidebar, bg=NAV)
        bottom.pack(side="bottom", fill="x", padx=24, pady=28)
        tk.Frame(bottom, bg="#30415c", height=1).pack(fill="x", pady=(0, 20))
        tk.Label(bottom, text="OUTLOOK CLASSIC", bg=NAV, fg="#a9bad1", font=(self.ui_font, 8, "bold")).pack(anchor="w")
        tk.Label(bottom, text="Windows デスクトップ版", bg=NAV, fg="#7287a6", font=(self.ui_font, 8)).pack(anchor="w", pady=(5, 0))

        workspace = ttk.Frame(self, style="Page.TFrame")
        workspace.pack(side="left", fill="both", expand=True)
        top = card(workspace, padding=(26, 15))
        top.pack(fill="x")
        self.breadcrumb = tk.StringVar(value="ワークスペース  /  テキスト入力")
        ttk.Label(top, textvariable=self.breadcrumb, style="CardMuted.TLabel").pack(side="left")
        self.mode_label = tk.Label(top, text="", font=(self.ui_font, 9, "bold"), padx=13, pady=6)
        self.mode_label.pack(side="right")
        ttk.Label(top, text="実行モード", style="CardMuted.TLabel").pack(side="right", padx=(0, 12))
        self.notebook = PageStack(workspace, self.on_page_selected)
        self.notebook.pack(fill="both", expand=True, padx=26, pady=(24, 14))
        self.input_page = ttk.Frame(self.notebook, style="Page.TFrame")
        self.review_page = ttk.Frame(self.notebook, style="Page.TFrame")
        self.settings_page = ttk.Frame(self.notebook, style="Page.TFrame")
        self.pages = [self.input_page, self.review_page, self.settings_page]
        for page in self.pages:
            self.notebook.add(page)
        self.build_input()
        self.build_review()
        self.build_settings()
        footer = ttk.Frame(workspace, style="Page.TFrame", padding=(26, 0, 26, 14))
        footer.pack(fill="x")
        self.status = tk.StringVar(value="設定で宛先Excelと共通の件名を登録すると、準備が整います。")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=900).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=110)
        self.notebook.pack_forget()
        footer.pack_forget()
        footer.pack(side="bottom", fill="x")
        self.notebook.pack(fill="both", expand=True, padx=26, pady=(24, 14))
        self.notebook.select(self.input_page)

    def navigate(self, index):
        if not self.busy:
            self.notebook.select(self.pages[index])

    def on_page_selected(self, page):
        labels = ("テキスト入力", "一覧・内容確認", "設定")
        index = self.pages.index(page)
        for number, button in enumerate(self.nav_buttons):
            button.configure(style="NavSelected.TButton" if number == index else "Nav.TButton")
        self.breadcrumb.set("ワークスペース  /  " + labels[index])

    def build_input(self):
        page = self.input_page
        self.heading(page, "テキストを取り込む", "契約データを貼り付けるか、テキストファイルを読み込んで、作成対象リストを用意します。")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        editor = card(body)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        bar = ttk.Frame(editor, style="Surface.TFrame")
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="入力テキスト", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(bar, text="txtファイルを開く", command=self.load_text).pack(side="right")
        self.source = self.text_box(editor, wrap="none", undo=True, width=20, height=15)
        self.source.pack(fill="both", expand=True)
        self.source_info = tk.StringVar(value="テキストを貼り付けるか、txtをここにドラッグ＆ドロップしてください。")
        ttk.Label(editor, textvariable=self.source_info, style="CardMuted.TLabel").pack(anchor="w", pady=(12, 0))
        guide = card(body, 22)
        guide.grid(row=0, column=1, sticky="ns")
        ttk.Label(guide, text="入力のガイド", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 16))
        for number, title, detail in (("01", "データを入力", "テキストを貼り付けるか、\ntxtファイルを開きます。"),
                                      ("02", "内容を編集", "必要に応じて、この画面で\n元データを修正できます。"),
                                      ("03", "リストを作成", "宛先を照合し、メールの\n確認画面へ進みます。")):
            ttk.Label(guide, text=number + "   " + title, style="CardTitle.TLabel").pack(anchor="w", pady=(10, 7))
            ttk.Label(guide, text=detail, style="CardMuted.TLabel").pack(anchor="w", pady=(0, 14))
        ttk.Separator(guide).pack(fill="x", pady=14)
        ttk.Label(guide, text="受入期間の記載例", style="CardMuted.TLabel").pack(anchor="w")
        ttk.Label(guide, text="2026/11/01 - 2027/03/31", style="Card.TLabel").pack(anchor="w", pady=8)
        ttk.Label(guide, text="必須項目間の空白行は1行です。\n先頭の空白行は読み飛ばします。", style="CardMuted.TLabel").pack(anchor="w")
        controls = ttk.Frame(page, style="Page.TFrame")
        controls.pack(side="bottom", before=body, fill="x", pady=(18, 0))
        ttk.Label(controls, text="リスト作成後に、宛先とメール内容を確認できます。", style="Muted.TLabel").pack(side="left")
        ttk.Button(controls, text="作成対象リストを作る  →", style="Primary.TButton", command=self.create_list).pack(side="right")

    def build_review(self):
        page = self.review_page
        self.heading(page, "作成対象を確認", "宛先と本文を確認し、必要なメールだけを下書き保存・送信します。")
        metrics = ttk.Frame(page, style="Page.TFrame")
        metrics.pack(fill="x", pady=(0, 18))
        self.metric_vars = [tk.StringVar(value="0") for _ in range(4)]
        for index, (title, caption, style_name) in enumerate((("取り込み件数", "契約ごとに1通を作成", "Metric.TLabel"),
                ("作成対象", "除外したメールを除く", "MetricBlue.TLabel"), ("確認済み", "対象の内容確認が完了", "MetricGreen.TLabel"),
                ("要修正", "宛先・入力内容を確認", "MetricOrange.TLabel"))):
            metrics.columnconfigure(index, weight=1, uniform="metric")
            tile = card(metrics, padding=(18, 12))
            tile.grid(row=0, column=index, sticky="ew", padx=(0, 12 if index < 3 else 0))
            ttk.Label(tile, text=title, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Label(tile, textvariable=self.metric_vars[index], style=style_name).pack(anchor="w", pady=(2, 0))
            ttk.Label(tile, text=caption, style="CardMuted.TLabel").pack(anchor="w")

        panes = ttk.Panedwindow(page, orient="horizontal")
        panes.pack(fill="both", expand=True)
        panes.bind("<Map>", lambda _: self.after_idle(lambda: panes.sashpos(0, int(panes.winfo_width() * .54))))
        list_card = card(panes, 14)
        panes.add(list_card, weight=6)
        bar = ttk.Frame(list_card, style="Surface.TFrame")
        bar.pack(fill="x", pady=(0, 14))
        ttk.Label(bar, text="対象一覧", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(bar, text="全対象を確認済みにする", command=self.review_all).pack(side="right")
        table_frame = ttk.Frame(list_card, style="Surface.TFrame")
        table_frame.pack(fill="both", expand=True)
        columns = ("included", "reviewed", "id", "name", "to", "status")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=8)
        for column, heading, width in zip(columns, ("対象", "確認", "管理番号", "氏名", "To", "状態"), (44, 56, 83, 100, 175, 96)):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=40, stretch=column == "to", anchor="center" if column in ("included", "reviewed") else "w")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.tag_configure("alternate", background="#fafbfd")
        self.table.tag_configure("error", foreground="#b66a16", background="#fff8ee")
        self.table.tag_configure("reviewed", foreground="#168069")
        self.table.tag_configure("done", foreground=MUTED)
        self.table.bind("<<TreeviewSelect>>", lambda _: self.show_preview())
        self.table.bind("<Double-1>", lambda _: self.edit_mail())
        self.table.bind("<space>", lambda _: self.toggle_included())
        self.table.bind("<ButtonRelease-1>", self.on_table_click)
        tools = ttk.Frame(list_card, style="Surface.TFrame")
        tools.pack(side="bottom", before=table_frame, fill="x", pady=(14, 0))
        for title, command in (("対象／除外", self.toggle_included), ("宛先・本文を編集", self.edit_mail), ("確認済みにする", self.review_selected)):
            ttk.Button(tools, text=title, command=command).pack(side="left", padx=(0, 7))

        preview_card = card(panes, 18)
        panes.add(preview_card, weight=5)
        ttk.Label(preview_card, text="メールプレビュー", style="CardTitle.TLabel").pack(anchor="w")
        self.preview_person = tk.StringVar(value="一覧からメールを選択")
        ttk.Label(preview_card, textvariable=self.preview_person, style="CardMuted.TLabel").pack(anchor="w", pady=(5, 18))
        metadata = ttk.Frame(preview_card, style="Surface.TFrame")
        metadata.pack(fill="x")
        metadata.columnconfigure(1, weight=1)
        self.preview_to = tk.StringVar(value="—")
        self.preview_cc = tk.StringVar(value="—")
        meta_labels = []
        for row, label, variable in ((0, "To", self.preview_to), (1, "CC", self.preview_cc)):
            ttk.Label(metadata, text=label, style="CardMuted.TLabel", width=5).grid(row=row, column=0, sticky="nw", pady=4)
            value_label = ttk.Label(metadata, textvariable=variable, style="Card.TLabel", wraplength=400)
            value_label.grid(row=row, column=1, sticky="nw", pady=4)
            meta_labels.append(value_label)
        ttk.Separator(preview_card).pack(fill="x", pady=(16, 12))
        self.preview_subject = tk.StringVar(value="件名は設定で登録できます")
        subject_label = ttk.Label(preview_card, textvariable=self.preview_subject, style="Subject.TLabel", wraplength=470)
        subject_label.pack(anchor="w", pady=(0, 12))
        self.preview_tabs = preview_tabs = ttk.Notebook(preview_card)
        preview_tabs.pack(fill="both", expand=True)
        body_frame, data_frame = ttk.Frame(preview_tabs, style="Surface.TFrame"), ttk.Frame(preview_tabs, style="Surface.TFrame")
        preview_tabs.add(body_frame, text="メール本文")
        preview_tabs.add(data_frame, text="取り込み情報")
        self.preview = self.text_box(body_frame, wrap="word", width=20, height=10, state="disabled")
        self.preview.pack(fill="both", expand=True, pady=(12, 0))
        self.record_preview = self.text_box(data_frame, wrap="word", width=20, height=10, state="disabled")
        self.record_preview.pack(fill="both", expand=True, pady=(12, 0))
        self.preview_issue = tk.StringVar(value="")
        issue_label = ttk.Label(preview_card, textvariable=self.preview_issue, style="CardMuted.TLabel", wraplength=470)
        issue_label.pack(side="bottom", before=preview_tabs, anchor="w", pady=(12, 0))

        def resize_preview(event):
            subject_label.configure(wraplength=max(180, event.width - 40))
            issue_label.configure(wraplength=max(180, event.width - 40))
            for label in meta_labels:
                label.configure(wraplength=max(150, event.width - 95))

        preview_card.bind("<Configure>", resize_preview)

        actionbar = ttk.Frame(page, style="Page.TFrame")
        actionbar.pack(side="bottom", before=panes, fill="x", pady=(18, 0))
        self.summary = tk.StringVar(value="作成対象リストはまだありません。")
        ttk.Label(actionbar, textvariable=self.summary, style="Muted.TLabel").pack(side="left")
        self.execute_button = ttk.Button(actionbar, text="下書きを保存  →", style="Primary.TButton", command=self.execute)
        self.execute_button.pack(side="right")

    def build_settings(self):
        page = self.settings_page
        self.heading(page, "メールの設定", "宛先の対応表と、全メールで共通の件名・CC・本文テンプレートを管理します。")
        self.subject_var = tk.StringVar(value=self.settings.subject)
        self.path_var = tk.StringVar(value=self.settings.address_book_path)
        self.mode_var = tk.StringVar(value=self.settings.mode)
        panels = ttk.Frame(page, style="Page.TFrame")
        panels.pack(fill="both", expand=True)
        panels.columnconfigure(0, weight=5, uniform="settings")
        panels.columnconfigure(1, weight=6, uniform="settings")
        panels.rowconfigure(0, weight=1)
        left_outer, left = scroll_card(panels, 22)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        ttk.Label(left, text="基本設定", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 16))
        ttk.Label(left, text="共通の件名", style="Card.TLabel").pack(anchor="w", pady=(0, 7))
        ttk.Entry(left, textvariable=self.subject_var).pack(fill="x")
        ttk.Label(left, text="未定の間は空欄で保存できます。作成前に入力してください。", style="CardMuted.TLabel", wraplength=430).pack(anchor="w", pady=(7, 10))
        ttk.Label(left, text="共通のCC", style="Card.TLabel").pack(anchor="w", pady=(0, 7))
        self.cc_input = self.text_box(left, height=2, width=20, wrap="word")
        self.cc_input.insert("1.0", self.settings.cc)
        self.cc_input.pack(fill="x")
        ttk.Label(left, text="改行・カンマ・セミコロンで区切って入力。空欄も可能です。", style="CardMuted.TLabel", wraplength=430).pack(anchor="w", pady=(6, 8))
        ttk.Label(left, text="実行方法", style="Card.TLabel").pack(anchor="w", pady=(0, 5))
        methods = ttk.Frame(left, style="Surface.TFrame")
        methods.pack(fill="x")
        ttk.Radiobutton(methods, text="下書きに保存", variable=self.mode_var, value="draft").pack(side="left")
        ttk.Radiobutton(methods, text="送信する", variable=self.mode_var, value="send").pack(side="left", padx=20)
        ttk.Separator(left).pack(fill="x", pady=14)
        ttk.Label(left, text="宛先の対応表", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 9))
        ttk.Entry(left, textvariable=self.path_var, state="readonly").pack(fill="x", pady=(0, 8))
        ttk.Label(left, text="A列「氏名」・B列「メールアドレス」、1行目は見出し。\n.xlsxはドロップでも読込可。JSON保存・再読込で全件置換。", style="CardMuted.TLabel", wraplength=430).pack(anchor="w", pady=(0, 10))
        self.contact_info = tk.StringVar(value="未登録：宛先Excelを読み込んでください。")
        ttk.Label(left, textvariable=self.contact_info, style="CardMuted.TLabel", wraplength=430).pack(anchor="w")
        controls = ttk.Frame(left, style="Surface.TFrame")
        controls.pack(fill="x", pady=(14, 0))
        ttk.Button(controls, text="Excelを読み込む", command=self.import_contacts).pack(side="left")
        ttk.Button(controls, text="登録した宛先を確認", command=self.show_contacts).pack(side="left", padx=8)
        right = card(panels, 22)
        right.grid(row=0, column=1, sticky="nsew")
        head = ttk.Frame(right, style="Surface.TFrame")
        head.pack(fill="x", pady=(0, 14))
        ttk.Label(head, text="本文テンプレート", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(head, text="初期値に戻す", command=self.reset_template).pack(side="right")
        self.template_input = self.text_box(right, height=8, width=20, wrap="word", undo=True)
        self.template_input.insert("1.0", self.settings.template)
        self.template_input.pack(fill="both", expand=True)
        ttk.Separator(right).pack(fill="x", pady=(14, 12))
        ttk.Label(right, text="差し込み項目を挿入", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 10))
        chips = ttk.Frame(right, style="Surface.TFrame")
        chips.pack(fill="x")
        for index, name in enumerate(FIELDS):
            ttk.Button(chips, text=name, command=lambda n=name: self.insert_field(n), padding=(9, 6)).grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 5), pady=(0, 6))
        bottom = ttk.Frame(page, style="Page.TFrame")
        bottom.pack(side="bottom", before=panels, fill="x", pady=(18, 0))
        ttk.Label(bottom, text="保存すると未実行メールを更新し、確認済みを解除します。", style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text="設定を保存して反映", style="Primary.TButton", command=self.save_config).pack(side="right")

    def insert_field(self, name):
        if not self.busy:
            self.template_input.insert("insert", "{" + name + "}")
            self.template_input.focus_set()

    def on_table_click(self, event):
        if self.busy:
            return
        if self.table.identify_region(event.x, event.y) == "cell" and self.table.identify_column(event.x) == "#1":
            row = self.table.identify_row(event.y)
            if row:
                self.table.selection_set(row)
                self.toggle_included()
