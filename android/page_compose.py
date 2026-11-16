"""New message: lines of at most 64 bytes, a destination (Board / Mind / Chat) and an optional reply
code. The wallet signs every line (EIP-712), the app dry-runs the finished transaction against the
ledger, then the wallet sends all lines in ONE transaction. The app holds no key."""
import os
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.utils import escape_markup

import core
import errors
import feed as F
import outbox
import strings as S
from design import FAB_CLEAR, H_TO_CARD, BLUE_HEX, D_STEP, FONT_LABEL, FONT_MEDIUM, FONT_MSG, FONT_NOTE, FONT_SMALL, FONT_TINY, FONT_TITLE, GAP, GAP_CARDS, GAP_SMALL, GAP_TINY, H_BUTTON_BIG, H_FIELD, H_HEADING, H_HINT, H_LINE, H_PAGE_BAR, H_REPLY_CARD, H_SENDTO, PAD_BOTTOM, PAD_CARD, PAD_PAGE, W_BACK, W_CANCEL, W_COUNTER
import tx
import util
from design import CHIP_BG, CODE_BG, CREAM, DARK_GREEN, LIGHT_BLUE, LIGHT_GREEN, MUTED
from theme import BLACK, BLUE, MAX_LINES, RED, WHITE, short
from ui import Chip, Wrap, chip_row, send_card
from widgets import Card, Choice, Dot, IconBtn, Overlay, Panel, PullScroll, label, make_input

REQUEST_TIMEOUT = 120    # seconds to wait for the wallet to answer one request
REJECT_CODES = (4001, 5000)
REJECT_WORDS = ("user rejected", "rejected by user", "user denied", "denied by user",
                "request rejected", "user cancel", "cancelled by user", "canceled by user")


UNSUPPORTED_WORDS = ("does not exist", "not available", "did not approve", "unauthorized method",
                     "unsupported method", "method not found")


def is_unsupported(text, code):
    """The wallet link cannot do typed-data signing (the request went to a public node instead)."""
    low = str(text).lower()
    return code in (4200, -32601) or any(w in low for w in UNSUPPORTED_WORDS)


def is_rejection(text, code):
    low = str(text).lower()
    return code in REJECT_CODES or any(w in low for w in REJECT_WORDS)


class ComposeScreen(Overlay):
    def __init__(self, app, dest=None, reply=None, **kw):
        super().__init__(**kw)
        self.app = app
        self.alive = True
        self.busy = False
        self.reply = reply
        self.reply_code = reply["code"] if reply else ""
        self.ph0 = os.urandom(32)                       # payloadHash of line 1: its code is the reply code
        self.code = F.code_of(self.ph0)
        # destination: ("board", addr) / ("mind", me) / ("chat", peer)
        if dest is None:
            dest = ("board", app.boards[0]["addr"])
        self.kind, self.addr = dest[0], dest[1]
        if self.kind == "mind":
            self.addr = app.my
        # a chat destination may be a whole conversation ("0xB,0xC"): the recipient is one of them
        self.conv = app.conv_peers(self.addr) if self.kind == "chat" else app.conv_peers(app.ui.get("peer"))
        self.peer_text = self.conv[0] if self.conv else ""
        if self.kind == "chat" and self.addr and "," not in self.addr:
            self.peer_text = self.addr
        self.step = ""
        self.step_key = ""
        self.entry = None                 # the status entry of the message once it was sent
        self._i, self._n = 0, 0
        self.lines = [""]
        self.inputs = []
        self.counters = []
        self._req_no = 0
        self._open = set()
        self.col = BoxLayout(orientation="vertical")
        self.add_widget(self.col)
        self.rebuild()

    # ------------------------------------------------------------ layout
    def rebuild(self):
        app = self.app
        col = self.col
        col.clear_widgets()
        head = BoxLayout(size_hint_y=None, height=dp(H_PAGE_BAR), padding=[dp(PAD_PAGE), dp(GAP_SMALL)], spacing=dp(PAD_PAGE))
        back = IconBtn(icon="back", bg=WHITE, color=BLACK, size_hint=(None, 1), width=dp(W_BACK))
        back.bind(on_release=lambda *_: self.close())
        head.add_widget(back)
        head.add_widget(label(S.CMP_TITLE, font_size=FONT_TITLE))
        col.add_widget(head)

        sv = PullScroll(on_pull=self.app.check_now, do_scroll_x=False, bar_width=0)   # pull = check the transaction now
        box = BoxLayout(orientation="vertical", spacing=dp(GAP_CARDS), size_hint_y=None,
                        padding=[dp(PAD_PAGE), dp(GAP), dp(PAD_PAGE), dp(PAD_BOTTOM + FAB_CLEAR)])
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        col.add_widget(sv)

        # ---- send to
        p = Panel(orientation="vertical", size_hint_y=None, height=dp(H_SENDTO), spacing=dp(GAP_SMALL),
                  padding=[dp(PAD_CARD), dp(GAP_CARDS)])
        p.add_widget(label(S.CMP_SEND_TO, size_hint_y=None, height=dp(H_HINT), font_size=FONT_NOTE, color=MUTED))
        chips = []
        for b in app.boards:
            on = self.kind == "board" and self.addr.lower() == b["addr"].lower()
            chips.append(self.dest_chip(S.CMP_BOARD.format(name=b["name"]), on, ("board", b["addr"])))
        chips.append(self.dest_chip(S.CMP_MIND, self.kind == "mind", ("mind", app.my)))
        peer = (self.peer_text or "").strip()
        chips.append(self.dest_chip(S.CMP_CHAT.format(addr=short(peer)) if peer else S.CMP_CHAT_NEW,
                                    self.kind == "chat", ("chat", peer)))
        p.add_widget(chip_row(chips))
        box.add_widget(p)
        if self.kind == "chat":
            # who the record is sent to (its "intended to"): one of the chat's addresses, or any address
            tp = Panel(orientation="vertical", size_hint_y=None, height=dp(H_TO_CARD), spacing=dp(GAP_SMALL),
                       padding=[dp(PAD_CARD), dp(GAP_CARDS)])
            tp.add_widget(label(S.CHAT_PICK_TO, size_hint_y=None, height=dp(H_HINT), font_size=FONT_NOTE,
                                color=MUTED))
            who = []
            for a in self.conv:
                c = Chip(short(a), base=CHIP_BG)
                c.set_selected(a == self.peer_text.lower())
                c.bind(on_release=lambda _i, a=a: self.pick_peer(a))
                who.append(c)
            if who:
                tp.add_widget(chip_row(who))
            self.peer_in = make_input(S.CMP_PEER_HINT, self.peer_text)
            self.peer_in.bind(text=self.on_peer)
            tp.add_widget(self.peer_in)
            box.add_widget(tp)

        # ---- reply target
        if self.reply:
            r = self.reply
            rp = Panel(bg=LIGHT_BLUE, size_hint_y=None, height=dp(H_REPLY_CARD), spacing=dp(PAD_CARD),
                       padding=[dp(PAD_CARD), dp(GAP_CARDS)])
            code = Label(text=r["code"], bold=True, color=WHITE, font_size=FONT_MEDIUM,
                         size_hint=(None, None), size=(dp(H_BUTTON_BIG), dp(H_FIELD)))
            from kivy.graphics import Color, RoundedRectangle
            with code.canvas.before:
                Color(*BLUE)
                rr = RoundedRectangle(radius=[dp(PAD_CARD)])
            code.bind(pos=lambda i, v, rr=rr: setattr(rr, "pos", v), size=lambda i, v, rr=rr: setattr(rr, "size", v))
            rp.add_widget(code)
            mid = BoxLayout(orientation="vertical")
            mid.add_widget(label(S.CMP_REPLYING.format(who=short(r["signer"]), block=r["block"]),
                                 font_size=FONT_NOTE, color=MUTED))
            mid.add_widget(label("[b]%s[/b]" % escape_markup(r["lines"][0][:60]), font_size=FONT_MSG))
            rp.add_widget(mid)
            box.add_widget(rp)

        # ---- lines
        lp = Panel(orientation="vertical", size_hint_y=None, spacing=dp(GAP), padding=[dp(PAD_CARD), dp(PAD_CARD)])
        lp.bind(minimum_height=lp.setter("height"))
        top = BoxLayout(size_hint_y=None, height=dp(H_HEADING))
        top.add_widget(label("[b]%s[/b]" % S.CMP_LINES, font_size=FONT_LABEL))
        top.add_widget(label(S.CMP_LINES_HINT, font_size=FONT_TINY, halign="right", color=MUTED))
        lp.add_widget(top)
        self.inputs, self.counters = [], []
        for i, text in enumerate(self.lines):
            row = BoxLayout(size_hint_y=None, height=dp(H_FIELD), spacing=dp(GAP))
            row.add_widget(Dot(bg=BLACK, text=str(i + 1), color=WHITE, size=(dp(D_STEP), dp(D_STEP)),
                               pos_hint={"center_y": 0.5}, font_size=FONT_SMALL))
            ti = make_input(S.CMP_LINE_HINT.format(n=i + 1), text)
            ti.bind(text=lambda inst, v, i=i: self.on_line(i, v))
            self.inputs.append(ti)
            row.add_widget(ti)
            cnt = Label(text="", font_size=FONT_TINY, color=MUTED, size_hint=(None, 1), width=dp(W_COUNTER),
                        halign="right", valign="middle")
            cnt.bind(size=lambda inst, s: setattr(inst, "text_size", s))
            self.counters.append(cnt)
            row.add_widget(cnt)
            lp.add_widget(row)
        tools = [self.mk_chip(S.CMP_ADD_LINE, self.add_line, blue=True)]
        for t in app.tags:
            tools.append(self.mk_chip(t, lambda t=t: self.add_tag(t)))
        lp.add_widget(chip_row(tools))
        lp.add_widget(Wrap(text=S.CMP_LINES_NOTE, font_size=FONT_NOTE, color=MUTED))
        box.add_widget(lp)

        # ---- you will sign
        sp = Panel(orientation="vertical", size_hint_y=None, spacing=dp(GAP_TINY), padding=[dp(PAD_CARD), dp(PAD_CARD)])
        sp.bind(minimum_height=sp.setter("height"))
        sp.add_widget(label("[b]%s[/b]" % S.CMP_SIGN_HEAD, size_hint_y=None, height=dp(H_LINE), font_size=FONT_LABEL))
        self.sum = {}
        for key, name in (("from", S.CMP_FROM), ("to", S.CMP_TO), ("code", S.CMP_CODE),
                          ("records", S.CMP_RECORDS), ("asks", S.CMP_ASKS), ("gas", S.CMP_GAS)):
            r = BoxLayout(size_hint_y=None, height=dp(H_LINE))
            r.add_widget(label(name, font_size=FONT_SMALL, color=MUTED))
            v = label("", font_size=FONT_SMALL, halign="right")
            self.sum[key] = v
            r.add_widget(v)
            sp.add_widget(r)
        box.add_widget(sp)
        box.add_widget(Card(S.CMP_NOTE, bg=CREAM))

        self.status_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(GAP_SMALL))
        self.status_box.bind(minimum_height=self.status_box.setter("height"))
        box.add_widget(self.status_box)

        btns = BoxLayout(size_hint_y=None, height=dp(H_BUTTON_BIG), spacing=dp(GAP_CARDS))
        cancel = Choice(base=WHITE, fg=BLACK, text=S.CMP_CANCEL, bold=True, size_hint=(None, 1), width=dp(W_CANCEL))
        cancel.bind(on_release=lambda *_: self.close())
        self.go = Choice(base=BLUE, fg=WHITE, text="", bold=True, font_size=FONT_MEDIUM)
        self.go.bind(on_release=lambda *_: self.sign())
        btns.add_widget(cancel)
        btns.add_widget(self.go)
        box.add_widget(btns)
        for i in range(len(self.lines)):
            self.update_counter(i)
        self.update_summary()
        if self.entry is not None:
            self.show_entry()

    def dest_chip(self, text, on, dest):
        c = Chip(text, base=CHIP_BG)
        c.set_selected(on)
        c.bind(on_release=lambda *_: self.set_dest(dest))
        return c

    def mk_chip(self, text, fn, blue=False):
        c = Chip(text, base=BLUE if blue else CHIP_BG, fg=WHITE if blue else BLACK,
                 sel=BLUE if blue else BLACK)
        c.bind(on_release=lambda *_: fn())
        return c

    # ------------------------------------------------------------ editing
    def set_dest(self, dest):
        if self.busy:
            return
        self.kind = dest[0]
        self.addr = dest[1]
        if self.kind == "chat":
            self.peer_text = dest[1] or self.peer_text
        self.rebuild()

    def pick_peer(self, a):
        if self.busy:
            return
        self.peer_text = a
        self.rebuild()

    def on_peer(self, inst, v):
        self.peer_text = v.strip()
        self.update_summary()

    def on_line(self, i, v):
        if i < len(self.lines):
            self.lines[i] = v
            self.update_counter(i)
            self.update_summary()

    def update_counter(self, i):
        n = tx.byte_len(self.lines[i])
        c = self.counters[i]
        c.text = "%d/%d" % (n, tx.MAX_LINE_BYTES)
        c.color = RED if n > tx.MAX_LINE_BYTES else MUTED

    def add_line(self):
        if len(self.lines) >= MAX_LINES or self.busy or self.entry is not None:
            return
        self.lines.append("")
        self.rebuild()

    def add_tag(self, tag):
        for i, t in enumerate(self.lines):
            if tag.lower() in t.lower().split():
                return
        i = 0
        self.lines[i] = (self.lines[i] + " " + tag).strip()
        self.inputs[i].text = self.lines[i]

    def destination(self):
        """(kind, address) of the message."""
        if self.kind == "mind":
            return "mind", self.app.my.strip()
        if self.kind == "chat":
            return "chat", (self.peer_text or "").strip()
        return "board", self.addr.strip()

    def final_lines(self):
        try:
            return tx.prepare_lines(self.lines, self.reply_code), ""
        except ValueError as e:
            return [], str(e)

    def update_summary(self):
        if not hasattr(self, "sum"):
            return
        kind, addr = self.destination()
        if kind == "board":
            name = next((b["name"] for b in self.app.boards if b["addr"].lower() == addr.lower()), S.M_BOARD_FALLBACK)
            to = S.CMP_TO_BOARD.format(name=name, addr=short(addr))
        elif kind == "mind":
            to = S.CMP_TO_MIND.format(addr=short(addr) or "?")
        else:
            to = S.CMP_TO_CHAT.format(addr=short(addr) or "?")
        lines, err = self.final_lines()
        n = len(lines)
        self.sum["from"].text = "[b]%s[/b]" % (short(self.app.my) or "?")
        self.sum["to"].text = "[b]%s[/b]" % to
        self.sum["code"].text = "[color=%s][b]%s[/b][/color]" % (BLUE_HEX, self.code)
        self.sum["records"].text = "[b]%s[/b]" % (S.CMP_RECORDS_V.format(n=n) if n != 1 else S.CMP_ONE_RECORD_V)
        self.sum["asks"].text = "[b]%s[/b]" % (S.CMP_ASKS_V.format(n=n) if n != 1 else S.CMP_ASKS_ONE)
        self.sum["gas"].text = "[b]%s[/b]" % S.CMP_GAS_V
        self.go.text = S.CMP_SIGN_N.format(n=n) if n != 1 else S.CMP_SIGN_ONE
        if n == 0:
            self.go.text = S.CMP_SIGN_N.format(n=0)
        if not self.busy:
            self.go.set_enabled(n > 0)             # nothing to sign: the button waits for a first line

    # ------------------------------------------------------------ status
    def show(self, text, bg=CREAM, fg=BLACK):
        if not self.alive:
            return
        self.status_box.clear_widgets()
        if text:
            self.status_box.add_widget(Card(text, bg=bg, fg=fg))

    def stop_sending(self):
        self.busy = False
        self.app.sending = False              # reload is allowed again

    def fail(self, text, code=None, reason=""):
        self.stop_sending()
        self.go.set_enabled(True)
        self.update_summary()                 # the button says "Sign N lines" again
        app = self.app
        wallet = app.wallet.label()
        e = errors.explain(self.step_key or "send", text, code, reason, wallet=wallet,
                           me=app.my.strip(), i=self._i, n=self._n)
        if e["kind"] == "typed":
            try:
                app.wallet.disconnect()       # drop the old link: the next Sign connects again
            except Exception:  # noqa: BLE001
                pass
        self.show(S.OUT_FAIL.format(title=e["title"], body=e["body"], tail=e["tail"]), bg=RED, fg=WHITE)
        plain = errors.plain(e, wallet)
        cp = Choice(base=WHITE, fg=BLACK, text=S.CMP_COPY_ERR, bold=True, size_hint_y=None, height=dp(H_FIELD))
        cp.bind(on_release=lambda *_: self.show_copy(plain))
        self.status_box.add_widget(cp)

    def show_copy(self, plain):
        self.show(S.CMP_ERR_COPIED if util.copy_text(plain) else S.TX_COPY_FAILED, bg=CREAM, fg=BLACK)

    def close(self):
        self.alive = False
        if self.entry is None:
            self.app.sending = False
        try:
            self.app.wallet.set_listener(None)
        except Exception:  # noqa: BLE001
            pass
        self.app.close_all()

    # ------------------------------------------------------------ the flow
    def sign(self):
        if self.entry is not None:                      # sent: the button now says Done
            return self.close()
        if self.busy:
            return
        app = self.app
        me = app.my.strip()
        kind, to = self.destination()
        lines, err = self.final_lines()
        if not tx.valid_address(me):
            return self.show(S.CMP_E_ME, bg=RED, fg=WHITE)
        if not tx.valid_address(to):
            return self.show(S.CMP_E_TO, bg=RED, fg=WHITE)
        if err or not lines:
            return self.show(err or S.CMP_E_EMPTY, bg=RED, fg=WHITE)
        self.frm, self.to, self.send_kind = me.lower(), to.lower(), kind
        self.items = tx.new_items(lines)
        self.items[0]["ph"] = self.ph0                  # so the code shown above is the real one
        self.busy = True
        app.sending = True                              # no reload until the transaction is submitted
        self.go.set_enabled(False)
        self.go.text = S.CMP_BUSY
        w = app.wallet
        w.set_listener(lambda text: self.alive and self.show(text))
        if w.connected:
            self.after_connect()
        else:
            self.show(S.CMP_CONNECTING)
            w.connect(self.after_connect, self.fail)

    def after_connect(self):
        if not self.alive:
            return
        w = self.app.wallet
        got = (w.accounts[0] if w.accounts else "").lower()
        if got != self.frm:
            self.fail(S.TX_WRONG_ACCOUNT.format(got=short(got) or "?", want=short(self.frm)))
            return
        self.sign_next(0)

    def request(self, method, params, on_ok, on_err):
        """Ask the wallet; a reply that never comes is reported after REQUEST_TIMEOUT seconds."""
        self._req_no += 1
        rid = self._req_no
        self._open.add(rid)

        def ok(result):
            self._open.discard(rid)
            on_ok(result)

        def err(text, code=None):
            self._open.discard(rid)
            on_err(text, code)
        self.app.wallet.request(method, params, ok, err)

        def timeout(dt):
            if rid in self._open and self.alive:
                self._open.discard(rid)
                self.fail("timed out: the wallet did not answer %s" % method)
        Clock.schedule_once(timeout, REQUEST_TIMEOUT)

    def sign_next(self, i):
        if not self.alive:
            return
        n = len(self.items)
        if i >= n:
            self.check()
            return
        it = self.items[i]
        typed = tx.ledger_typed_data(self.frm, self.to, it["ph"], it["meta"])
        self.step_key, self._i, self._n = "sign", i + 1, n
        self.step = S.CMP_STEP_SIGN.format(i=i + 1, n=n)
        self.show(S.CMP_SIGNING.format(i=i + 1, n=n, wallet=self.app.wallet.label()))
        self.request("eth_signTypedData_v4", [self.frm, typed],
                     lambda res: self.got_sig(i, res), self.fail)

    def got_sig(self, i, result):
        try:
            sig = bytes.fromhex(str(result)[2:])
            if len(sig) != 65:
                raise ValueError("signature length")
        except Exception:  # noqa: BLE001
            self.fail(S.CMP_SIGN_BAD)
            return
        self.items[i]["sig"] = sig
        self.sign_next(i + 1)

    def check(self):
        """Dry run of the whole transaction: a bad signature is caught before anything is sent."""
        self.step_key, self.step = "check", S.CMP_STEP_CHECK
        self.show(S.CMP_CHECKING)
        to, data = tx.record_call(self.frm, self.to, self.items)
        self.call = (to, data)

        def work():
            try:
                ok, reason = core.Chain("").simulate(self.frm, to, data, 0)
            except Exception:  # noqa: BLE001
                ok, reason = True, ""          # no node reachable: the chain decides
            Clock.schedule_once(lambda dt: self.checked(ok, reason))
        threading.Thread(target=work, daemon=True).start()

    def checked(self, ok, reason):
        if not self.alive:
            return
        if not ok:
            self.fail("", None, reason=str(reason) or "refused")
            return
        to, data = self.call
        self.step_key, self.step = "send", S.CMP_STEP_SEND
        self.show(S.CMP_SENDING.format(wallet=self.app.wallet.label()))
        self.request("eth_sendTransaction",
                     [{"from": self.frm, "to": to, "value": "0x0", "data": data}],
                     self.sent, self.fail)

    def sent(self, result):
        """The wallet returned the transaction hash: keep a status entry, stay open, track the receipt."""
        h = str(result)
        app = self.app
        lines = [i["meta"] for i in self.items]
        e = outbox.new_entry(self.send_kind, self.to, self.frm, lines, self.code, h, app.wallet.label())
        app.outbox.add(e)
        app.submitted()                                  # reload is held for a minute from now
        if self.send_kind == "chat":
            app.add_chat(self.to)
            app.ui["peer"] = app.conv_with(self.to)
        self.busy = False
        self.entry = e
        app.track(e)
        if self.alive:
            self.go.text = S.CMP_DONE
            self.go.set_enabled(True)
            self.show_entry()

    def show_entry(self):
        """The status card (waiting / recorded / failed) with the transaction link."""
        if not self.alive or self.entry is None:
            return
        app = self.app
        self.status_box.clear_widgets()
        self.status_box.add_widget(send_card(self.entry, app.open_tx, app.copy_hash, self.dismiss_entry))
        self.go.text = S.CMP_DONE

    def dismiss_entry(self, eid):
        self.app.outbox.dismiss(eid)
        self.close()

    def on_entry(self, e):
        if self.entry is not None and e["id"] == self.entry["id"]:
            self.entry = e
            self.show_entry()
