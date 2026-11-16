"""Chat: a conversation between your address (A) and one or more other addresses (B, C ...). Every
message is an SOS record signed by one of them to another one ("intended to"); the page reads every
pair of the conversation and shows them by block time, newest at the bottom."""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

import feed as F
import strings as S
import tx
import util
from design import FONT_NOTE, GAP, GAP_CARDS, GAP_SMALL, H_CONV_CARD, H_FIELD, H_HINT, MUTED, PAD_CARD, W_BTN_PASTE
from page_feed import FeedPage
from theme import BLACK, BLUE, WHITE, short
from ui import ChatItem, block_head, chip, chip_row
from widgets import Card, Choice, Panel, label, make_input


class ChatPage(FeedPage):
    kind = "chat"

    def peer(self):
        """The selected conversation: its key (the other addresses joined by a comma) or ''."""
        p = (self.ui.get("peer") or "").lower()
        if p not in self.app.chats:
            p = self.app.chats[0] if self.app.chats else ""
            self.ui["peer"] = p
        return p

    def peers(self):
        return self.app.conv_peers(self.peer())

    def params(self):
        return {"me": self.app.my.lower(), "peers": self.peers()}

    def not_ready(self):
        if not self.app.my:
            return S.CHAT_NO_ME
        if not self.peer():
            return S.CHAT_NO_PEER
        return ""

    def cache_key(self):
        return ",".join(sorted([self.app.my.lower()] + self.peers()))

    def reply_dest(self):
        p = self.peers()
        return ("chat", p[0] if p else "")

    def reply(self, m):
        me = self.app.my.lower()
        to = m["to"] if m["signer"] == me else m["signer"]
        self.app.open_compose(dest=("chat", to), reply=m)

    # ---- the "Chat with" card: type or paste an address, start a chat or add it to this one
    def conv_card(self):
        app, ui = self.app, self.ui
        p = Panel(orientation="vertical", size_hint_y=None, height=dp(H_CONV_CARD), spacing=dp(GAP_SMALL),
                  padding=[dp(PAD_CARD), dp(GAP_CARDS)])
        p.add_widget(label(S.CHAT_CONV_HEAD, size_hint_y=None, height=dp(H_HINT), font_size=FONT_NOTE,
                           color=MUTED))
        row = BoxLayout(size_hint_y=None, height=dp(H_FIELD), spacing=dp(GAP))
        self.addr_in = make_input(S.CHAT_ADDR_HINT, ui.get("chat_addr", ""))
        self.addr_in.bind(text=lambda i, v: ui.__setitem__("chat_addr", v.strip()))
        row.add_widget(self.addr_in)
        paste = Choice(base=BLUE, fg=WHITE, text=S.BTN_PASTE, bold=True, size_hint=(None, 1), width=dp(W_BTN_PASTE))
        paste.bind(on_release=lambda *_: self.paste())
        row.add_widget(paste)
        p.add_widget(row)
        btns = BoxLayout(size_hint_y=None, height=dp(H_FIELD), spacing=dp(GAP))
        new = Choice(base=BLUE, fg=WHITE, text=S.CHAT_BTN_NEW, bold=True)
        new.bind(on_release=lambda *_: self.new_chat())
        btns.add_widget(new)
        if self.peer():
            add = Choice(base=BLACK, fg=WHITE, text=S.CHAT_BTN_ADD, bold=True)
            add.bind(on_release=lambda *_: self.add_here())
            btns.add_widget(add)
        p.add_widget(btns)
        return p

    def paste(self):
        t = util.paste_text()
        if t:
            self.ui["chat_addr"] = t.strip()
            self.addr_in.text = t.strip()
        else:
            self.app.say(S.MSG_CLIPBOARD_EMPTY)

    def typed(self):
        a = (self.ui.get("chat_addr") or "").strip().lower()
        if not tx.valid_address(a):
            self.app.say(S.CHAT_BAD_ADDR)
            return ""
        if a == self.app.my.lower():
            self.app.say(S.CHAT_SELF)
            return ""
        return a

    def new_chat(self):
        a = self.typed()
        if not a:
            return
        key = self.app.conv_with(a) or a
        self.app.add_chat(a)
        self.ui["peer"], self.ui["chat_addr"], self.ui["sel"] = key, "", None
        self.app.render()

    def add_here(self):
        a = self.typed()
        if not a:
            return
        err = self.app.add_to_chat(self.peer(), a)
        if err:
            self.app.say(err)
            return
        self.ui["chat_addr"] = ""
        self.app.render()

    def chips(self):
        app, ui = self.app, self.ui
        cur = self.peer()
        convs = [chip(S.CHAT_PLUS.join(short(a) for a in app.conv_peers(c)),
                      lambda c=c: app.set_peer(c), selected=c == cur) for c in app.chats]
        if cur:
            convs.append(chip(S.CHAT_REMOVE, lambda: app.remove_chat(cur), kind="outline"))
        row2 = [chip(text, lambda k=key: app.set_sort("chat_filter", k),
                     selected=ui.get("chat_filter", "all") == key) for key, text in S.CHAT_FILTERS]
        out = [self.conv_card()]
        if convs:
            out.append(chip_row(convs))
        out.append(chip_row(row2))
        return out

    def arrange(self, msgs):
        me = self.app.my.lower()
        members = set([me] + self.peers())
        flt = self.ui.get("chat_filter", "all")
        out = []
        for m in msgs:
            if m["signer"] not in members or m["to"] not in members or m["signer"] == m["to"]:
                continue
            if flt == "sent" and m["signer"] != me:
                continue
            if flt == "recv" and m["to"] != me:
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
            who = S.M_YOU if mine else short(m["signer"])
            if len(self.peers()) > 1 or (m["to"] != me and not mine):
                who = S.CHAT_ARROW.format(a=who, b=S.M_YOU if m["to"] == me else short(m["to"]))
            elif not mine:
                who = short(m["signer"])
            parts = [who]
            if len(m["lines"]) > 1:
                parts.append(S.M_LINES.format(n=len(m["lines"])))
            parts.append(S.M_CODE_CAPTION.format(code=m["code"]))
            parts.append(S.M_BLOCK.format(block=m["block"]))
            item = ChatItem(m["lines"], mine, S.SEP.join(parts))
            b.add_widget(self.tappable(item, m))
            if self.ui.get("sel") == m["id"]:
                b.add_widget(self.detail(m))
        for p in self.app.pending:                          # sent, not in a block yet
            if p["kind"] == "chat" and p["to"].lower() in self.peers():
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
