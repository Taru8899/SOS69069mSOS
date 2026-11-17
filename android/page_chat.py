"""Chat: a conversation between your address (A) and one or more other addresses (B, C ...). Every
message is an SOS record signed by one of them to another one ("intended to"); the page reads every
pair of the conversation and shows them by block time, newest at the bottom."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

import feed as F
import strings as S
import tx
import util
from design import CHAT_COLORS, FONT_NOTE, FONT_SMALL, H_LINE, GAP, GAP_CARDS, GAP_SMALL, H_FIELD, H_HINT, ME_GREEN, MUTED, PAD_CARD, W_BTN_PASTE
from page_feed import FeedPage
from theme import BLACK, BLUE, WHITE, short
from ui import MsgCard, block_head, chip, chip_row
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
        p = Panel(orientation="vertical", size_hint_y=None, spacing=dp(GAP_SMALL),
                  padding=[dp(PAD_CARD), dp(GAP_CARDS)])
        p.bind(minimum_height=p.setter("height"))        # as tall as its content: no empty band
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
        if self.peer():                                     # who is who: one coloured chip per sender
            out.append(chip_row([chip(S.CHAT_LEGEND_YOU, color=ME_GREEN)] +
                                [chip(short(a), color=c) for a, c in self.colors().items() if a != self.app.my.lower()]))
        out.append(self.tag_row("chat_tag"))
        out.append(chip_row(row2))
        return out

    def colors(self):
        """address -> colour of its messages: you dark green, the others blue, purple, orange in chat order."""
        out = {self.app.my.lower(): ME_GREEN}
        for i, a in enumerate(self.peers()):
            out[a] = CHAT_COLORS[i % len(CHAT_COLORS)]
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
        out = F.with_tag(out, self.ui.get("chat_tag"))      # All tags / a saved #tag / an @code thread
        return F.sort_newest(out)            # newest first; shown oldest first

    def show(self, feed, slot):
        """The same cards as Board and Mind (newest first, block headings, Load more at the bottom);
        the avatar circle carries the colour of the sender."""
        b = self.box
        me = self.app.my.lower()
        msgs = self.arrange(feed.messages())
        visible = msgs[:self.shown()]
        colors = self.colors()
        for p in self.app.pending:                          # sent, not in a block yet: on top, waiting
            if p["kind"] == "chat" and p["to"].lower() in self.peers():
                pm = {"signer": me, "to": p["to"].lower(), "lines": p["lines"], "eff": None, "code": "",
                      "id": "pending", "block": 0, "n_replies": 0}
                b.add_widget(MsgCard(pm, me, S.M_PENDING, lambda m: None, lambda m: None,
                                     color=ME_GREEN, pending=True))
        if not visible:
            b.add_widget(Card(S.M_NO_TAG_MATCH if self.ui.get("chat_tag") else S.M_EMPTY))
        last_block = None
        for m in visible:
            if m["block"] != last_block:
                b.add_widget(block_head(m, F.when(m["ts"])))
                last_block = m["block"]
            b.add_widget(MsgCard(m, me, self.chat_sub(m, me), self.select, self.reply,
                                 selected=self.ui.get("sel") == m["id"], color=colors.get(m["signer"])))
            if self.ui.get("sel") == m["id"]:
                b.add_widget(self.detail(m))
        b.add_widget(label(S.M_SHOWN.format(n=len(visible)), size_hint_y=None, height=dp(H_LINE),
                           font_size=FONT_SMALL, halign="center"))
        more = self.more_button(len(msgs), feed, slot)
        if more is not None:
            b.add_widget(more)
        b.add_widget(self.footer_note(feed))

    def chat_sub(self, m, me):
        """'You to 0x08e5...5fee · 2 lines · 18h ago · 2 replies' (the grey line of a card)."""
        a = S.M_YOU if m["signer"] == me else short(m["signer"])
        c = S.M_YOU if m["to"] == me else short(m["to"])
        parts = [S.CHAT_ARROW.format(a=a, b=c)]
        if len(m["lines"]) > 1:
            parts.append(S.M_LINES.format(n=len(m["lines"])))
        parts.append(S.M_BLOCK.format(block=m["block"]))
        ago = F.when(m["ts"])
        if ago:
            parts.append(ago)
        if m["n_replies"]:
            parts.append(S.M_REPLIES.format(n=m["n_replies"]))
        return S.SEP.join(parts)


def build(app, box):
    ChatPage(app, box).build()
