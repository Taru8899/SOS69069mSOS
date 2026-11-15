"""Settings: the ledger, your address and Etherscan key, boards, watched addresses, saved tags."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.utils import escape_markup

import strings as S
import tx
import util
from design import CHIP_BG, CREAM, MUTED
from theme import BLACK, BLUE, BUILD, ETHERSCAN_ADDR, LEDGER_ADDR, WHITE, short
from ui import Chip, Wrap
from widgets import Card, Choice, IconBtn, Overlay, Panel, label, make_input


class SettingsScreen(Overlay):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.col = BoxLayout(orientation="vertical")
        self.add_widget(self.col)
        self.status_text = ""
        self.rebuild()

    # ------------------------------------------------------------ helpers
    def card(self, title, note=""):
        p = Panel(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=[dp(12), dp(12)])
        p.bind(minimum_height=p.setter("height"))
        p.add_widget(label("[b]%s[/b]" % title, size_hint_y=None, height=dp(22), font_size="15sp"))
        if note:
            p.add_widget(Wrap(text=note, font_size="13sp", color=MUTED))
        return p

    def btn(self, text, fn, base=BLUE, fg=WHITE, width=None):
        kw = dict(size_hint=(None, 1), width=dp(width)) if width else {}
        b = Choice(base=base, fg=fg, text=text, bold=True, **kw)
        b.bind(on_release=lambda *_: fn())
        return b

    def input_row(self, field, button):
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        row.add_widget(field)
        row.add_widget(button)
        return row

    def say(self, text):
        self.status_text = text
        self.rebuild()

    # ------------------------------------------------------------ layout
    def rebuild(self):
        app = self.app
        col = self.col
        col.clear_widgets()
        head = BoxLayout(size_hint_y=None, height=dp(64), padding=[dp(14), dp(6)], spacing=dp(14))
        back = IconBtn(icon="back", bg=WHITE, color=BLACK, size_hint=(None, 1), width=dp(56))
        back.bind(on_release=lambda *_: app.close_top())
        head.add_widget(back)
        head.add_widget(label(S.SET_TITLE, font_size="24sp"))
        col.add_widget(head)
        if self.status_text:
            col.add_widget(label(escape_markup(self.status_text), size_hint_y=None, height=dp(22),
                                 font_size="13sp", padding=(dp(14), 0)))
        sv = ScrollView(do_scroll_x=False, bar_width=0)
        box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None,
                        padding=[dp(14), dp(8), dp(14), dp(20)])
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        col.add_widget(sv)

        # ---- ledger
        p = self.card(S.SET_LEDGER)
        p.add_widget(label(S.SET_LEDGER_SUB.format(addr=short(LEDGER_ADDR)), size_hint_y=None,
                           height=dp(20), font_size="13sp"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        row.add_widget(self.btn(S.BTN_COPY, lambda: self.copy(LEDGER_ADDR)))
        row.add_widget(self.btn(S.BTN_OPEN, lambda: self.open(ETHERSCAN_ADDR + LEDGER_ADDR)))
        p.add_widget(row)
        box.add_widget(p)

        # ---- my address and keys
        p = self.card(S.SET_ADDR_HEAD, S.SET_ADDR_NOTE)
        self.addr_in = make_input(S.SET_ADDR_HINT, app.my)
        w = app.wallet
        if w.connected:
            b = self.btn(S.SET_DISCONNECT, self.disconnect, base=BLACK, width=104)
        else:
            b = self.btn(S.SET_CONNECT, self.connect, width=104)
        p.add_widget(self.input_row(self.addr_in, b))
        p.add_widget(self.btn_full(S.SET_WATCH_SAVE, self.save_addr))
        p.add_widget(label(S.SET_KEY_LABEL, size_hint_y=None, height=dp(18), font_size="12sp", color=MUTED))
        self.key_in = make_input(S.SET_KEY_HINT, app.es_key, password=True)
        p.add_widget(self.input_row(self.key_in, self.btn(S.SET_WATCH_SAVE, self.save_key, width=84)))
        box.add_widget(p)

        # ---- boards
        p = self.card(S.SET_BOARDS)
        for i, b in enumerate(app.boards):
            r = BoxLayout(size_hint_y=None, height=dp(44))
            r.add_widget(label("[b]%s[/b] %s" % (escape_markup(b["name"]), short(b["addr"])), font_size="14sp"))
            if i == 0:
                r.add_widget(label(S.SET_BOARD_DEFAULT, font_size="12sp", halign="right", color=MUTED,
                                   size_hint_x=None, width=dp(70)))
            else:
                x = Choice(base=WHITE, fg=BLACK, text="×", bold=True, font_size="18sp",
                           size_hint=(None, 1), width=dp(44))
                x.bind(on_release=lambda *_, a=b["addr"]: self.do(lambda: app.remove_board(a)))
                r.add_widget(x)
            p.add_widget(r)
        self.board_in = make_input(S.SET_BOARD_HINT, "")
        p.add_widget(self.input_row(self.board_in, self.btn(S.SET_ADD, self.add_board, width=72)))
        box.add_widget(p)

        # ---- mind watch
        p = self.card(S.SET_WATCH_HEAD)
        for a in app.watch:
            r = BoxLayout(size_hint_y=None, height=dp(44))
            r.add_widget(label(short(a), font_size="14sp"))
            x = Choice(base=WHITE, fg=BLACK, text="×", bold=True, font_size="18sp",
                       size_hint=(None, 1), width=dp(44))
            x.bind(on_release=lambda *_, a=a: self.do(lambda: app.remove_watch(a)))
            r.add_widget(x)
            p.add_widget(r)
        self.watch_in = make_input(S.SET_WATCH_HINT, "")
        p.add_widget(self.input_row(self.watch_in, self.btn(S.SET_WATCH_SAVE, self.add_watch, width=72)))
        p.add_widget(Wrap(text=S.SET_WATCH_NOTE, font_size="12sp", color=MUTED))
        box.add_widget(p)

        # ---- tags
        p = self.card(S.SET_TAGS)
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        from ui import chip_row
        chips = []
        for t in app.tags:
            c = Chip("%s ×" % t, base=CHIP_BG)
            c.bind(on_release=lambda *_, t=t: self.do(lambda: app.remove_tag(t)))
            chips.append(c)
        if chips:
            p.add_widget(chip_row(chips))
        self.tag_in = make_input(S.SET_TAG_HINT, "")
        p.add_widget(self.input_row(self.tag_in, self.btn(S.SET_TAG_ADD, self.add_tag, width=84)))
        p.add_widget(Wrap(text=S.SET_TAGS_NOTE, font_size="12sp", color=MUTED))
        box.add_widget(p)

        box.add_widget(Card(S.SET_VERSION.format(build=escape_markup(BUILD)), bg=CREAM))

    def btn_full(self, text, fn):
        b = Choice(base=BLUE, fg=WHITE, text=text, bold=True, size_hint_y=None, height=dp(44))
        b.bind(on_release=lambda *_: fn())
        return b

    # ------------------------------------------------------------ actions
    def do(self, fn):
        fn()
        self.rebuild()

    def copy(self, text):
        self.say(S.M_COPIED if util.copy_text(text) else S.TX_COPY_FAILED)

    def open(self, url):
        if not util.open_url(url):
            self.say(S.SETTINGS_OPEN_FAILED)

    def save_addr(self):
        a = self.addr_in.text.strip()
        if a and not tx.valid_address(a):
            return self.say(S.SET_BAD_ADDR)
        self.app.set_my(a)
        self.say("")

    def save_key(self):
        self.app.set_key(self.key_in.text.strip())
        self.say("")

    def add_board(self):
        t = self.board_in.text.strip().split()
        if not t or not tx.valid_address(t[-1]):
            return self.say(S.SET_BAD_ADDR)
        name = " ".join(t[:-1]) or short(t[-1])
        self.app.add_board(name, t[-1])
        self.say("")

    def add_watch(self):
        a = self.watch_in.text.strip()
        if not tx.valid_address(a):
            return self.say(S.SET_BAD_ADDR)
        self.app.add_watch(a)
        self.say("")

    def add_tag(self):
        t = self.tag_in.text.strip().lstrip("#").lower().replace(" ", "-")
        if t:
            self.app.add_tag("#" + t)
        self.say("")

    def connect(self):
        w = self.app.wallet
        w.set_listener(lambda text: self.say(text))
        self.say(S.CMP_CONNECTING)

        def ok():
            if w.accounts:
                self.app.set_my(w.accounts[0])
            self.say(S.SET_CONNECTED.format(wallet=w.label(), addr=short(w.accounts[0] if w.accounts else "")))

        def err(text, code=None):
            self.say(S.SET_WALLET_FAIL.format(error=text))
        w.connect(ok, err)

    def disconnect(self):
        self.app.exit_wallet()
        self.say(S.MSG_WALLET_DISCONNECTED)
