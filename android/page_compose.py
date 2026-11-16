"""New message: lines of at most 64 bytes, a destination (Board / Mind / Chat) and an optional reply
code. The wallet signs every line (EIP-712), the app dry-runs the finished transaction against the
ledger, then the wallet sends all lines in ONE transaction. The app holds no key."""
import os
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.utils import escape_markup

import core
import feed as F
import strings as S
import tx
from design import CHIP_BG, CODE_BG, CREAM, DARK_GREEN, LIGHT_BLUE, LIGHT_GREEN, MUTED
from theme import BLACK, BLUE, MAX_LINES, RED, WHITE, short
from ui import Chip, Wrap, chip_row
from widgets import Card, Choice, Dot, IconBtn, Overlay, Panel, label, make_input

POLL_SECONDS = 4
POLL_TRIES = 45          # 45 x 4 s = 3 minutes
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
        self.peer_text = self.addr if self.kind == "chat" else (app.ui.get("peer") or "")
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
        head = BoxLayout(size_hint_y=None, height=dp(64), padding=[dp(14), dp(6)], spacing=dp(14))
        back = IconBtn(icon="back", bg=WHITE, color=BLACK, size_hint=(None, 1), width=dp(56))
        back.bind(on_release=lambda *_: self.close())
        head.add_widget(back)
        head.add_widget(label(S.CMP_TITLE, font_size="24sp"))
        col.add_widget(head)

        sv = ScrollView(do_scroll_x=False, bar_width=0)
        box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None,
                        padding=[dp(14), dp(8), dp(14), dp(16)])
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        col.add_widget(sv)

        # ---- send to
        p = Panel(orientation="vertical", size_hint_y=None, height=dp(98), spacing=dp(6),
                  padding=[dp(12), dp(10)])
        p.add_widget(label(S.CMP_SEND_TO, size_hint_y=None, height=dp(18), font_size="12sp", color=MUTED))
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
            self.peer_in = make_input(S.CMP_PEER_HINT, self.peer_text)
            self.peer_in.bind(text=self.on_peer)
            box.add_widget(self.peer_in)

        # ---- reply target
        if self.reply:
            r = self.reply
            rp = Panel(bg=LIGHT_BLUE, size_hint_y=None, height=dp(74), spacing=dp(12),
                       padding=[dp(12), dp(10)])
            code = Label(text=r["code"], bold=True, color=WHITE, font_size="16sp",
                         size_hint=(None, None), size=(dp(52), dp(48)))
            from kivy.graphics import Color, RoundedRectangle
            with code.canvas.before:
                Color(*BLUE)
                rr = RoundedRectangle(radius=[dp(12)])
            code.bind(pos=lambda i, v, rr=rr: setattr(rr, "pos", v), size=lambda i, v, rr=rr: setattr(rr, "size", v))
            rp.add_widget(code)
            mid = BoxLayout(orientation="vertical")
            mid.add_widget(label(S.CMP_REPLYING.format(who=short(r["signer"]), block=r["block"]),
                                 font_size="12sp", color=MUTED))
            mid.add_widget(label("[b]%s[/b]" % escape_markup(r["lines"][0][:60]), font_size="15sp"))
            rp.add_widget(mid)
            box.add_widget(rp)

        # ---- lines
        lp = Panel(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=[dp(12), dp(12)])
        lp.bind(minimum_height=lp.setter("height"))
        top = BoxLayout(size_hint_y=None, height=dp(22))
        top.add_widget(label("[b]%s[/b]" % S.CMP_LINES, font_size="14sp"))
        top.add_widget(label(S.CMP_LINES_HINT, font_size="11sp", halign="right", color=MUTED))
        lp.add_widget(top)
        self.inputs, self.counters = [], []
        for i, text in enumerate(self.lines):
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            row.add_widget(Dot(bg=BLACK, text=str(i + 1), color=WHITE, size=(dp(28), dp(28)),
                               pos_hint={"center_y": 0.5}, font_size="13sp"))
            ti = make_input(S.CMP_LINE_HINT.format(n=i + 1), text)
            ti.bind(text=lambda inst, v, i=i: self.on_line(i, v))
            self.inputs.append(ti)
            row.add_widget(ti)
            cnt = Label(text="", font_size="11sp", color=MUTED, size_hint=(None, 1), width=dp(46),
                        halign="right", valign="middle")
            cnt.bind(size=lambda inst, s: setattr(inst, "text_size", s))
            self.counters.append(cnt)
            row.add_widget(cnt)
            lp.add_widget(row)
        tools = [self.mk_chip(S.CMP_ADD_LINE, self.add_line, blue=True)]
        for t in app.tags:
            tools.append(self.mk_chip(t, lambda t=t: self.add_tag(t)))
        lp.add_widget(chip_row(tools))
        lp.add_widget(Wrap(text=S.CMP_LINES_NOTE, font_size="12sp", color=MUTED))
        box.add_widget(lp)

        # ---- you will sign
        sp = Panel(orientation="vertical", size_hint_y=None, spacing=dp(4), padding=[dp(12), dp(12)])
        sp.bind(minimum_height=sp.setter("height"))
        sp.add_widget(label("[b]%s[/b]" % S.CMP_SIGN_HEAD, size_hint_y=None, height=dp(24), font_size="14sp"))
        self.sum = {}
        for key, name in (("from", S.CMP_FROM), ("to", S.CMP_TO), ("code", S.CMP_CODE),
                          ("records", S.CMP_RECORDS), ("asks", S.CMP_ASKS), ("gas", S.CMP_GAS)):
            r = BoxLayout(size_hint_y=None, height=dp(24))
            r.add_widget(label(name, font_size="13sp", color=MUTED))
            v = label("", font_size="13sp", halign="right")
            self.sum[key] = v
            r.add_widget(v)
            sp.add_widget(r)
        box.add_widget(sp)
        box.add_widget(Card(S.CMP_NOTE, bg=CREAM))

        self.status_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.status_box.bind(minimum_height=self.status_box.setter("height"))
        box.add_widget(self.status_box)

        btns = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        cancel = Choice(base=WHITE, fg=BLACK, text=S.CMP_CANCEL, bold=True, size_hint=(None, 1), width=dp(96))
        cancel.bind(on_release=lambda *_: self.close())
        self.go = Choice(base=BLUE, fg=WHITE, text="", bold=True, font_size="16sp")
        self.go.bind(on_release=lambda *_: self.sign())
        btns.add_widget(cancel)
        btns.add_widget(self.go)
        box.add_widget(btns)
        for i in range(len(self.lines)):
            self.update_counter(i)
        self.update_summary()

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
        if len(self.lines) >= MAX_LINES or self.busy:
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
            name = next((b["name"] for b in self.app.boards if b["addr"].lower() == addr.lower()), "Board")
            to = S.CMP_TO_BOARD.format(name=name, addr=short(addr))
        elif kind == "mind":
            to = S.CMP_TO_MIND.format(addr=short(addr) or "?")
        else:
            to = S.CMP_TO_CHAT.format(addr=short(addr) or "?")
        lines, err = self.final_lines()
        n = len(lines)
        self.sum["from"].text = "[b]%s[/b]" % (short(self.app.my) or "?")
        self.sum["to"].text = "[b]%s[/b]" % to
        self.sum["code"].text = "[color=0033ff][b]%s[/b][/color]" % self.code
        self.sum["records"].text = "[b]%s[/b]" % (S.CMP_RECORDS_V.format(n=n) if n != 1 else S.CMP_ONE_RECORD_V)
        self.sum["asks"].text = "[b]%s[/b]" % (S.CMP_ASKS_V.format(n=n) if n != 1 else S.CMP_ASKS_ONE)
        self.sum["gas"].text = "[b]%s[/b]" % S.CMP_GAS_V
        self.go.text = S.CMP_SIGN_N.format(n=n) if n != 1 else S.CMP_SIGN_ONE
        if n == 0:
            self.go.text = S.CMP_SIGN_N.format(n=0)

    # ------------------------------------------------------------ status
    def show(self, text, bg=CREAM, fg=BLACK):
        if not self.alive:
            return
        self.status_box.clear_widgets()
        if text:
            self.status_box.add_widget(Card(text, bg=bg, fg=fg))

    def fail(self, text, code=None):
        self.busy = False
        self.go.set_enabled(True)
        self.update_summary()                 # the button says "Sign N lines" again
        if is_rejection(text, code):
            self.show(S.CMP_REJECTED, bg=RED, fg=WHITE)
        elif is_unsupported(text, code):
            try:
                self.app.wallet.disconnect()          # drop the old link: the next Sign connects again
            except Exception:  # noqa: BLE001
                pass
            self.show(S.CMP_NO_TYPED, bg=RED, fg=WHITE)
        else:
            self.show(S.TX_ERROR.format(error=escape_markup(str(text))), bg=RED, fg=WHITE)

    def close(self):
        self.alive = False
        try:
            self.app.wallet.set_listener(None)
        except Exception:  # noqa: BLE001
            pass
        self.app.close_all()

    # ------------------------------------------------------------ the flow
    def sign(self):
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
                self.fail(S.TX_TIMEOUT.format(step=method, wallet=self.app.wallet.label()))
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
            self.busy = False
            self.go.set_enabled(True)
            self.update_summary()
            self.show(S.CMP_DRY_FAILED.format(reason=escape_markup(str(reason))), bg=RED, fg=WHITE)
            return
        to, data = self.call
        self.show(S.CMP_SENDING.format(wallet=self.app.wallet.label()))
        self.request("eth_sendTransaction",
                     [{"from": self.frm, "to": to, "value": "0x0", "data": data}],
                     self.sent, self.fail)

    def sent(self, result):
        h = str(result)
        app = self.app
        lines = [i["meta"] for i in self.items]
        pend = {"kind": self.send_kind, "to": self.to, "lines": lines, "hash": h}
        app.pending.append(pend)
        if self.send_kind == "chat":
            app.add_chat(self.to)
            app.ui["peer"] = self.to
        code, kind = self.code, self.send_kind
        app.say(S.CMP_WAITING.format(hash=short(h)).split("\n")[0], 12)
        if self.alive:
            self.show(S.CMP_WAITING.format(hash=short(h)))
        threading.Thread(target=self._poll, args=(h, pend, code), daemon=True).start()
        # the message is on its way: leave the form; the chat shows it as "waiting"
        if self.alive:
            Clock.schedule_once(lambda dt: self.close(), 1.2)

    def _poll(self, h, pend, code):
        chain = core.Chain(self.app.es_key)
        err = None
        for _ in range(POLL_TRIES):
            try:
                rc = chain.receipt(h)
            except Exception as e:  # noqa: BLE001
                rc, err = None, str(e)
            if rc:
                ok = str(rc.get("status", "0x1")) == "0x1"
                block = int(rc.get("blockNumber") or "0x0", 16)
                reason = "" if ok else chain.failure_reason(h, rc)
                Clock.schedule_once(lambda dt: self.app.tx_done(pend, h, ok, block, reason, code))
                return
            time.sleep(POLL_SECONDS)
        Clock.schedule_once(lambda dt: self.app.tx_done(pend, h, None, 0, err or "", code))
