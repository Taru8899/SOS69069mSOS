"""Board: a feed of the messages sent to a board address (default: the ledger address). Filter by
tag, sort by block time / sender effective score / replies, reply to an exact message by its code."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

import feed as F
import strings as S
from design import FONT_SMALL, H_LINE
from page_feed import FeedPage
from theme import EFF_MIN, short
from ui import MsgCard, chip, chip_row
from widgets import label


class BoardPage(FeedPage):
    kind = "board"

    def board(self):
        a = self.ui.get("board")
        if not any(b["addr"].lower() == (a or "").lower() for b in self.app.boards):
            a = self.app.boards[0]["addr"]
            self.ui["board"] = a
        return a

    def params(self):
        return {"board": self.board()}

    def card_to(self):
        return self.ui.get("board") or self.app.boards[0]["addr"]

    def cache_key(self):
        return self.ui.get("board") or self.app.boards[0]["addr"]

    def counter(self, msgs):
        return len(F.with_tag(msgs, self.ui.get("tag")))     # what the person will actually see

    def reply_dest(self):
        return ("board", self.board())

    def fold_title(self):
        cur = self.board().lower()
        for b in self.app.boards:
            if b["addr"].lower() == cur:
                return b["name"]
        return S.FOLD_BOARD

    def fold_summary(self):
        sort = dict(S.BOARD_SORTS).get(self.ui.get("board_sort", "newest"), "").format(n=EFF_MIN)
        return S.SEP.join([x for x in (self.ui.get("tag"), sort) if x])

    def chips(self):
        app, ui = self.app, self.ui
        cur = self.board().lower()
        boards = []
        for b in app.boards:
            on = b["addr"].lower() == cur
            text = "%s %s" % (b["name"], short(b["addr"])) if on else b["name"]
            boards.append(chip(text, lambda a=b["addr"]: app.set_board(a), selected=on))
        boards.append(chip(S.BOARD_ADD, app.open_settings, kind="action"))
        sorts = []
        for key, text in S.BOARD_SORTS:
            sorts.append(chip(text.format(n=EFF_MIN), lambda k=key: app.set_sort("board_sort", k),
                              selected=ui.get("board_sort", "newest") == key))
        return [chip_row(boards), self.tag_row("tag"), chip_row(sorts)]

    def arrange(self, msgs):
        msgs = F.with_tag(msgs, self.ui.get("tag"))
        sort = self.ui.get("board_sort", "newest")
        if sort == "effmin":
            return F.sort_newest(F.eff_at_least(msgs, EFF_MIN))
        if sort == "eff":
            return F.sort_eff(msgs)
        if sort == "replies":
            return F.sort_replies(msgs)
        return F.sort_newest(msgs)

    def show(self, feed, slot):
        b = self.box
        msgs = self.arrange(feed.messages())
        visible = msgs[:self.shown()]
        if not visible:
            from widgets import Card
            b.add_widget(Card(S.M_EMPTY))
        now = None
        for m in visible:
            extras = [S.M_BLOCK.format(block=m["block"])]
            ago = F.when(m["ts"], now)
            if ago:
                extras.append(ago)
            b.add_widget(MsgCard(m, self.app.my, self.sub(m, extras), self.select, self.reply,
                                 selected=self.ui.get("sel") == m["id"]))
            if self.ui.get("sel") == m["id"]:
                b.add_widget(self.detail(m))
        b.add_widget(label(S.M_SHOWN.format(n=len(visible)), size_hint_y=None, height=dp(H_LINE),
                           font_size=FONT_SMALL, halign="center"))
        more = self.more_button(len(msgs), feed, slot)
        if more is not None:
            b.add_widget(more)
        b.add_widget(self.footer_note(feed))


def build(app, box):
    BoardPage(app, box).build()
