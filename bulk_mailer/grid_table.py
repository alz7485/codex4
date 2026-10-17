"""A virtualized, ruled table with two lines per record and no clipped text."""
from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import font as tkfont


@dataclass
class GridRow:
    iid: str
    values: tuple[str, ...]
    problem: str = ""
    status: str = ""


class ContractTable(tk.Canvas):
    columns = ("included", "id", "worker", "period", "receiver")
    headings = ("対象", "管理番号／承認状態", "氏名・派遣元／メールアドレス", "受入開始・終了", "受入先情報")

    def __init__(self, parent, *, family: str):
        super().__init__(parent, background="white", highlightthickness=1,
                         highlightbackground="#c6cfdb", highlightcolor="#2867e8",
                         borderwidth=0, takefocus=True, height=350)
        self.cell_font = tkfont.Font(self, family=family, size=9)
        self.header_font = tkfont.Font(self, family=family, size=9, weight="bold")
        self.row_height = self.cell_font.metrics("linespace") * 2 + 24
        self.header_height = self.header_font.metrics("linespace") + 24
        self.rows: list[GridRow] = []
        self._by_id: dict[str, GridRow] = {}
        self._selected: tuple[str, ...] = ()
        self._pressed_target: tuple[str, int, int] | None = None
        self.widths = [68, 128, 310, 160, 330]
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<Button-1>", self.select_at)
        self.bind("<B1-Motion>", self.track_drag)
        self.bind("<Up>", lambda _: self.move_selection(-1))
        self.bind("<Down>", lambda _: self.move_selection(1))
        self.bind("<Home>", lambda _: self.select_position(0))
        self.bind("<End>", lambda _: self.select_position(len(self.rows) - 1))
        self.bind("<Prior>", lambda _: self.move_selection(-self.page_size()))
        self.bind("<Next>", lambda _: self.move_selection(self.page_size()))
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<Button-4>", lambda _: self.yview_scroll(-1, "units"))
        self.bind("<Button-5>", lambda _: self.yview_scroll(1, "units"))
        self.configure(yscrollincrement=self.row_height)

    def set_rows(self, rows: list[GridRow]) -> None:
        self._pressed_target = None
        self.rows = rows
        self._by_id = {row.iid: row for row in rows}
        self._selected = tuple(iid for iid in self._selected if iid in self._by_id)
        widths = [68, 128, 310, 160, 330]
        for index, heading in enumerate(self.headings):
            widths[index] = max(widths[index], self.header_font.measure(heading) + 28)
        for row in rows:
            for index, value in enumerate(row.values):
                widths[index] = max(widths[index], *(self.cell_font.measure(line.expandtabs(4)) + 28 for line in value.split("\n")))
        self.widths = widths
        self.redraw()

    def get_children(self) -> tuple[str, ...]:
        return tuple(row.iid for row in self.rows)

    def item(self, iid: str, option: str):
        row = self._by_id[iid]
        return {"values": row.values, "tags": ("error",) if row.problem else ()}[option]

    def set(self, iid: str, column: str) -> str:
        return self._by_id[iid].values[self.columns.index(column)]

    def selection(self) -> tuple[str, ...]:
        return self._selected

    def selection_set(self, iid: str) -> None:
        selected = (str(iid),) if str(iid) in self._by_id else ()
        if selected != self._selected:
            self._selected = selected
            self.redraw()
            self.event_generate("<<TreeviewSelect>>")

    def page_size(self) -> int:
        return max(1, (self.winfo_height() - self.header_height) // self.row_height)

    def select_position(self, position: int):
        if self.rows:
            position = min(max(position, 0), len(self.rows) - 1)
            self.selection_set(self.rows[position].iid)
            top = self.canvasy(0)
            row_top = self.header_height + position * self.row_height
            if row_top < top + self.header_height:
                self.yview_moveto(position * self.row_height / self.total_height())
            elif row_top + self.row_height > top + self.winfo_height():
                self.yview_moveto((row_top + self.row_height - self.winfo_height() + 2) / self.total_height())
        return "break"

    def move_selection(self, step: int):
        position = next((i for i, row in enumerate(self.rows) if row.iid in self._selected), -1)
        return self.select_position(max(0, position + step))

    def select_at(self, event) -> None:
        self._pressed_target = None
        self.focus_set()
        iid = self.identify_row(event.y)
        if iid:
            if self.identify_column(event.x) == "#1":
                self._pressed_target = (iid, event.x, event.y)
            self.selection_set(iid)

    def track_drag(self, event) -> None:
        if self._pressed_target is not None:
            _, x, y = self._pressed_target
            if abs(event.x - x) > 6 or abs(event.y - y) > 6:
                self._pressed_target = None

    def released_target(self, event) -> str:
        pressed, self._pressed_target = self._pressed_target, None
        if (pressed is not None and self.identify_column(event.x) == "#1"
                and self.identify_row(event.y) == pressed[0]
                and abs(event.x - pressed[1]) <= 6 and abs(event.y - pressed[2]) <= 6):
            return pressed[0]
        return ""

    def identify_row(self, y: int) -> str:
        if y < self.header_height:
            return ""
        position = int((self.canvasy(y) - self.header_height) // self.row_height)
        return self.rows[position].iid if 0 <= position < len(self.rows) else ""

    def identify_column(self, x: int) -> str:
        position = self.canvasx(x)
        edge = 0
        for index, width in enumerate(self.display_widths()):
            edge += width
            if 0 <= position < edge:
                return f"#{index + 1}"
        return ""

    def identify_region(self, x: int, y: int) -> str:
        return "cell" if self.identify_row(y) and self.identify_column(x) else ""

    def total_height(self) -> int:
        return self.header_height + len(self.rows) * self.row_height

    def display_widths(self) -> list[int]:
        widths = self.widths.copy()
        extra = max(0, self.winfo_width() - 2 - sum(widths))
        widths[2] += extra // 3
        widths[4] += extra - extra // 3
        return widths

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self.redraw()
        return result

    def yview_moveto(self, fraction):
        super().yview_moveto(fraction)
        self.redraw()

    def yview_scroll(self, number, what):
        super().yview_scroll(number, what)
        self.redraw()

    def wheel(self, event):
        amount = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.yview_scroll(amount, "units")
        return "break"

    def redraw(self) -> None:
        self.delete("all")
        widths = self.display_widths()
        width = sum(widths)
        height = max(self.total_height(), self.winfo_height() - 2)
        self.configure(scrollregion=(0, 0, width, height))
        top = self.canvasy(0)
        first = max(0, int((top - self.header_height) // self.row_height))
        last = min(len(self.rows), int(math.ceil((top + self.winfo_height()) / self.row_height)))
        for index in range(first, last):
            row = self.rows[index]
            y = self.header_height + index * self.row_height
            background, foreground = ("#fff8ee", "#a45d12") if row.problem else ("white", "#18263b")
            x = 0
            for column, cell_width in enumerate(widths):
                self.create_rectangle(x, y, x + cell_width, y + self.row_height,
                                      fill=background, outline="#c6cfdb", tags=("cell", row.iid))
                self.create_text(x + 14, y + 12, text=row.values[column].expandtabs(4), font=self.cell_font,
                                 fill=foreground, anchor="nw", tags=("cell_text", row.iid))
                x += cell_width
            if row.iid in self._selected:
                self.create_rectangle(1, y + 1, width - 1, y + self.row_height - 1,
                                      outline="#2867e8", width=2, tags="selection")
        x = 0
        for heading, cell_width in zip(self.headings, widths):
            self.create_rectangle(x, top, x + cell_width, top + self.header_height,
                                  fill="#f7f9fc", outline="#c6cfdb", tags="header")
            self.create_text(x + 14, top + 12, text=heading, font=self.header_font,
                             fill="#53627b", anchor="nw", tags="header")
            x += cell_width
