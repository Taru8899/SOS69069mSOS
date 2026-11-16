"""Settings: the ledger, your address and Etherscan key, boards, watched addresses, saved tags."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.utils import escape_markup

import strings as S
from design import FONT_BIG, FONT_LABEL, FONT_MSG, FONT_NOTE, FONT_SMALL, FONT_TITLE, GAP, GAP_CARDS, GAP_SMALL, H_BUTTON, H_FIELD, H_HEADING, H_NOTE, H_PAGE_BAR, PAD_CARD, PAD_PAGE, W_BACK, W_TAG_COL
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
        p = Panel(orientation="vertical", size_hint_y=None, spacing=dp(GAP), padding=[dp(PAD_CARD), dp(PAD_CARD)])
        p.bind(minimum_height=p.setter("height"))
        p.add_widget(label("[b]%s[/b]" % title, size_hint_y=None, height=dp(H_HEADING), font_size=FONT_MSG))
        if note:
            p.add_widget(Wrap(text=note, font_size=FONT_SMALL, color=MUTED))
        return p

    def btn(self, text, fn, base=BLUE, fg=WHITE, width=None):
        kw = dict(size_hint=(None, 1), width=dp(width)) if width else {}
        b = Choice(base=base, fg=fg, text=text, bold=True, **kw)
        b.bind(on_release=lambda *_: fn())
        return b

    def input_row(self, field, button):
        row = BoxLayout(size_hint_y=None, height=dp(H_FIELD), spacing=dp(GAP))
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
        head = BoxLayout(size_hint_y=None, height=dp(H_PAGE_BAR), padding=[dp(PAD_PAGE), dp(GAP_SMALL)], spacing=dp(PAD_PAGE))
        back = IconBtn(icon="back", bg=WHITE, color=BLACK, size_hint=(None, 1), width=dp(W_BACK))
        back.bind(on_release=lambda *_: app.close_top())
        head.add_widget(back)
        head.add_widget(label(S.SET_TITLE, font_size=FONT_TITLE))
        col.add_widget(head)
        if self.status_text:
            col.add_widget(label(escape_markup(self.status_text), size_hint_y=None, height=dp(H_HEADING),
                                 font_size=FONT_SMALL, padding=(dp(PAD_PAGE), 0)))
        sv = ScrollView(do_scroll_x=False, bar_width=0)
        box = BoxLayout(orientation="vertical", spacing=dp(GAP_CARDS), size_hint_y=None,
                        padding=[dp(PAD_PAGE), dp(GAP), dp(PAD_PAGE), dp(H_NOTE)])
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        col.add_widget(sv)

        # ---- ledger
        p = self.card(S.SET_LEDGER)
        p.add_widget(label(S.SET_LEDGER_SUB.format(addr=short(LEDGER_ADDR)), size_hint_y=None,
                           height=dp(H_NOTE), font_size=FONT_SMALL))
        row = BoxLayout(size_hint_y=None, height=dp(H_BUTTON), spacing=dp(GAP))
        row.add_widget(self.btn(S.BTN_COPY, lambda: self.copy(LEDGER_ADDR)))
        row.add_widget(self.btn(S.BTN_OPEN, lambda: self.open(ETHERSCAN_ADDR + LEDGER_ADDR)))
        p.add_widget(row)
        box.add_widget(p)

        # ---- boards
        p = self.card(S.SET_BOARDS)
        for i, b in enumerate(app.boards):
            r = BoxLayout(size_hint_y=None, height=dp(H_BUTTON))
            r.add_widget(label("[b]%s[/b] %s" % (escape_markup(b["name"]), short(b["addr"])), font_size=FONT_LABEL))
            if i == 0:
                r.add_widget(label(S.SET_BOARD_DEFAULT, font_size=FONT_NOTE, halign="right", color=MUTED,
                                   size_hint_x=None, width=dp(W_TAG_COL)))
            else:
                x = Choice(base=WHITE, fg=BLACK, text=S.CLOSE_X, bold=True, font_size=FONT_BIG,
                           size_hint=(None, 1), width=dp(H_BUTTON))
                x.bind(on_release=lambda *_, a=b["addr"]: self.do(lambda: app.remove_board(a)))
                r.add_widget(x)
            p.add_widget(r)
        self.board_in = make_input(S.SET_BOARD_HINT, "")
        p.add_widget(self.input_row(self.board_in, self.btn(S.SET_ADD, self.add_board, width=72)))
        box.add_widget(p)

        # ---- mind watch
        p = self.card(S.SET_WATCH_HEAD)
        for a in app.watch:
            r = BoxLayout(size_hint_y=None, height=dp(H_BUTTON))
            r.add_widget(label(short(a), font_size=FONT_LABEL))
            x = Choice(base=WHITE, fg=BLACK, text=S.CLOSE_X, bold=True, font_size=FONT_BIG,
                       size_hint=(None, 1), width=dp(H_BUTTON))
            x.bind(on_release=lambda *_, a=a: self.do(lambda: app.remove_watch(a)))
            r.add_widget(x)
            p.add_widget(r)
        self.watch_in = make_input(S.SET_WATCH_HINT, "")
        p.add_widget(self.input_row(self.watch_in, self.btn(S.SET_WATCH_SAVE, self.add_watch, width=72)))
        p.add_widget(Wrap(text=S.SET_WATCH_NOTE, font_size=FONT_NOTE, color=MUTED))
        box.add_widget(p)

        # ---- tags
        p = self.card(S.SET_TAGS)
        row = BoxLayout(size_hint_y=None, height=dp(H_FIELD), spacing=dp(GAP))
        from ui import chip_row
        chips = []
        for t in app.tags:
            c = Chip(S.CLOSE_X_FMT % t, base=CHIP_BG)
            c.bind(on_release=lambda *_, t=t: self.do(lambda: app.remove_tag(t)))
            chips.append(c)
        if chips:
            p.add_widget(chip_row(chips))
        self.tag_in = make_input(S.SET_TAG_HINT, "")
        p.add_widget(self.input_row(self.tag_in, self.btn(S.SET_TAG_ADD, self.add_tag, width=84)))
        p.add_widget(Wrap(text=S.SET_TAGS_NOTE, font_size=FONT_NOTE, color=MUTED))
        box.add_widget(p)

        box.add_widget(Card(S.SET_VERSION.format(build=escape_markup(BUILD)), bg=CREAM))

    def btn_full(self, text, fn):
        b = Choice(base=BLUE, fg=WHITE, text=text, bold=True, size_hint_y=None, height=dp(H_BUTTON))
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
