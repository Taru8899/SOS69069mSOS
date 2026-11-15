"""Chat: the classic A to B / B to A conversation between your address (A) and one other address
(B). Newest messages at the bottom; Load older (10) at the top."""
from kivy.clock import Clock
from kivy.metrics import dp

import feed as F
import strings as S
from page_feed import FeedPage
from theme import short
from ui import ChatItem, block_head, chip, chip_row
from widgets import Card, label


class ChatPage(FeedPage):
    kind = "chat"

    def peer(self):
        p = (self.ui.get("peer") or "").lower()
        if p not in [c.lower() for c in self.app.chats]:
            p = self.app.chats[0].lower() if self.app.chats else ""
            self.ui["peer"] = p
        return p

    def params(self):
        return {"me": self.app.my.lower(), "peer": self.peer()}

    def not_ready(self):
        if not self.app.my:
            return S.CHAT_NO_ME
        if not self.peer():
            return S.CHAT_NO_PEER
        return ""

    def reply_dest(self):
        return ("chat", self.peer())

    def chips(self):
        app, ui = self.app, self.ui
        cur = self.peer()
        peers = [chip(short(a), lambda a=a: app.set_peer(a), selected=a.lower() == cur)
                 for a in app.chats]
        peers.append(chip(S.CHAT_NEW, lambda: app.open_compose(dest=("chat", ""), reply=None), kind="action"))
        row2 = [chip(text, lambda k=key: app.set_sort("chat_filter", k),
                     selected=ui.get("chat_filter", "all") == key) for key, text in S.CHAT_FILTERS]
        return [chip_row(peers), chip_row(row2)]

    def arrange(self, msgs):
        me, peer = self.app.my.lower(), self.peer()
        flt = self.ui.get("chat_filter", "all")
        out = []
        for m in msgs:
            sent = m["signer"] == me and m["to"] == peer
            recv = m["signer"] == peer and m["to"] == me
            if not (sent or recv):
                continue
            if flt == "sent" and not sent:
                continue
            if flt == "recv" and not recv:
                continue
            if flt == "replies" and not m["reply_to"]:
                continue
            out.append(m)
        return F.sort_newest(out)            # newest first; shown oldest first

    def show(self, feed, slot):
        b = self.box
        me = self.app.my.lower()
        msgs = self.arrange(feed.messages())
        visible = msgs[:self.shown()]
        more = self.more_button(len(msgs), feed, slot, older_label=True)
        if more is not None:
            b.add_widget(more)
        if not visible:
            b.add_widget(Card(S.M_EMPTY))
        last_block = None
        for m in reversed(visible):                       # oldest at the top
            if m["block"] != last_block:
                b.add_widget(block_head(m, F.when(m["ts"])))
                last_block = m["block"]
            mine = m["signer"] == me
            parts = [S.M_YOU if mine else short(m["signer"])]
            if len(m["lines"]) > 1:
                parts.append(S.M_LINES.format(n=len(m["lines"])))
            parts.append("code [b]%s[/b]" % m["code"])
            parts.append(S.M_BLOCK.format(block=m["block"]))
            item = ChatItem(m["lines"], mine, " · ".join(parts))
            b.add_widget(self.tappable(item, m))
            if self.ui.get("sel") == m["id"]:
                b.add_widget(self.detail(m))
        for p in self.app.pending:                          # sent, not in a block yet
            if p["kind"] == "chat" and p["to"].lower() == self.peer():
                b.add_widget(ChatItem(p["lines"], True, S.M_PENDING, pending=True))
        b.add_widget(self.footer_note(feed))
        Clock.schedule_once(lambda dt: setattr(self.app.sv, "scroll_y", 0), 0.1)

    def tappable(self, item, m):
        """Make a chat item tappable (tap = details and reply)."""
        from kivy.uix.behaviors import ButtonBehavior
        from kivy.uix.boxlayout import BoxLayout

        class Hit(ButtonBehavior, BoxLayout):
            pass
        h = Hit(orientation="vertical", size_hint_y=None)
        h.bind(minimum_height=h.setter("height"))
        h.add_widget(item)
        h.bind(on_release=lambda *_: self.select(m))
        return h


def build(app, box):
    ChatPage(app, box).build()
