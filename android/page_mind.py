"""Mind: your own notes (signed to yourself) and the notes of any addresses you watch, in one
list aligned by block time."""
from kivy.metrics import dp

import feed as F
import strings as S
from design import FONT_SMALL, H_LINE
from page_feed import FeedPage
from theme import short
from ui import MsgCard, block_head, chip, chip_row
from widgets import Card, label


class MindPage(FeedPage):
    kind = "mind"

    def addrs(self):
        me = self.app.my.lower()
        out = [me] if me else []
        for a in self.app.watch:
            if a.lower() not in out:
                out.append(a.lower())
        return out

    def params(self):
        return {"addrs": self.addrs()}

    def not_ready(self):
        return "" if self.addrs() else S.MIND_NO_ME

    def reply_dest(self):
        return ("mind", self.app.my)

    def chips(self):
        app, ui = self.app, self.ui
        who = []
        if app.my:
            who.append(chip(S.MIND_ME.format(addr=short(app.my)), kind="green"))
        for a in app.watch:
            who.append(chip(S.CLOSE_X_FMT % short(a), lambda a=a: app.remove_watch(a), kind="blue"))
        who.append(chip(S.MIND_WATCH, app.open_settings))
        row2 = []
        for key, text in S.MIND_SCOPES:
            row2.append(chip(text, lambda k=key: app.set_sort("mind_scope", k),
                             selected=ui.get("mind_scope", "all") == key))
        for key, text in S.MIND_SORTS:
            row2.append(chip(text, lambda k=key: app.set_sort("mind_sort", k),
                             selected=ui.get("mind_sort", "newest") == key))
        return [chip_row(who), self.tag_row("mind_tag"), chip_row(row2)]

    def arrange(self, msgs):
        me = self.app.my.lower()
        scope = self.ui.get("mind_scope", "all")
        if scope == "mine":
            msgs = [m for m in msgs if m["signer"] == me]
        elif scope == "watched":
            msgs = [m for m in msgs if m["signer"] != me]
        # a message is "mind" only when it was signed to its own signer
        msgs = [m for m in msgs if m["signer"] == m["to"]]
        msgs = F.with_tag(msgs, self.ui.get("mind_tag"))          # All tags / a saved #tag / an @code thread
        return F.sort_eff(msgs) if self.ui.get("mind_sort", "newest") == "eff" else F.sort_newest(msgs)

    def show(self, feed, slot):
        b = self.box
        msgs = self.arrange(feed.messages())
        visible = msgs[:self.shown()]
        if not visible:
            b.add_widget(Card(S.M_NO_TAG_MATCH if self.ui.get("mind_tag") else S.M_EMPTY))
        by_block = self.ui.get("mind_sort", "newest") == "newest"
        last_block = None
        me = self.app.my.lower()
        for m in visible:
            if by_block and m["block"] != last_block:
                b.add_widget(block_head(m, F.when(m["ts"])))
                last_block = m["block"]
            extras = [S.MIND_MINE_TAG if m["signer"] == me else S.MIND_WATCHED_TAG]
            b.add_widget(MsgCard(m, me, self.sub(m, extras), self.select, self.reply,
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
    MindPage(app, box).build()
