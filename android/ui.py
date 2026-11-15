"""mSOS look (the mockup): chips, message cards, chat bubbles, block headings.
Colours and sizes come from design.py; wording from strings.py."""
import re

from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import escape_markup

import strings as S
from design import (AVATAR_D, BUBBLE_R, BUBBLE_TAIL_R, CHIP_H, CHIP_ROW_H, CODE_BG, CODE_H, CODE_W,
                    DARK_GREEN_HEX, ME_GREEN, TRACK_GRAY)
from theme import BLACK, BLUE, GREEN, RED, WHITE, short
from widgets import Choice, Dot, Divider, Tappable, rad, settle

CODE_AT_START = re.compile(r"^(\s*)(@[0-9a-zA-Z]{3})(?![0-9a-zA-Z])")


# ------------------------------------------------------------------ text
class Wrap(Label):
    """Label that wraps to its width and takes the height of its text."""

    def __init__(self, **kw):
        kw.setdefault("markup", True)
        kw.setdefault("color", BLACK)
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "top")
        kw["size_hint_y"] = None
        super().__init__(**kw)
        self.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        self.bind(texture_size=lambda i, ts: setattr(i, "height", ts[1]))


def fmt_line(text, bold=False):
    """Message line -> markup: the '@code' that starts a reply is blue."""
    t = escape_markup(text)
    t = CODE_AT_START.sub(lambda m: m.group(1) + "[color=0033ff][b]" + m.group(2) + "[/b][/color]", t)
    return "[b]%s[/b]" % t if bold else t


def eff_markup(eff):
    if eff is None:
        return S.M_EFF.format(eff="?")
    if eff > 0:
        return S.M_EFF.format(eff="[color=%s][b]+%d[/b][/color]" % (DARK_GREEN_HEX, eff))
    if eff < 0:
        return S.M_EFF.format(eff="[color=b00021][b]%d[/b][/color]" % eff)
    return S.M_EFF.format(eff="[b]0[/b]")


def who(addr, me):
    return S.M_YOU if addr == me else short(addr)


def block_head(m, ago_text):
    return Wrap(text="[b]%s[/b]" % S.M_BLOCK_HEAD.format(block=m["block"], ago=ago_text or "–"),
                font_size="12sp", halign="center", padding=(0, dp(2)))


# ------------------------------------------------------------------ chips
class Chip(Choice):
    """Round-ended chip, 44 dp high, as wide as its text."""

    def __init__(self, text, base=WHITE, sel=BLACK, fg=BLACK, sel_fg=WHITE, outline=False, **kw):
        kw.setdefault("font_size", "13sp")
        kw.setdefault("bold", True)
        kw["size_hint"] = (None, None)
        kw["height"] = dp(CHIP_H)
        kw["width"] = dp(70)
        kw["pos_hint"] = {"center_y": 0.5}
        super().__init__(base=base, sel=sel, fg=fg, sel_fg=sel_fg, text=text, **kw)
        self.bind(texture_size=lambda i, ts: setattr(i, "width", ts[0] + dp(30)))
        self._ol = None
        if outline:
            with self.canvas.after:
                Color(*BLACK)
                self._ol = Line(rounded_rectangle=(0, 0, 10, 10, 5), width=dp(1.5))
            settle(self, self._upd_outline)

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self._r.radius = [self.height / 2.0]

    def _upd_outline(self, *_):
        if self._ol is not None and self.width >= 4 and self.height >= 4:
            self._ol.rounded_rectangle = (self.x, self.y, self.width, self.height, self.height / 2.0)


def chip(text, on_tap=None, selected=False, kind="idle"):
    """kind: idle (white / black when selected), action (blue), outline, green (you), blue."""
    if kind == "action":
        c = Chip(text, base=BLUE, sel=BLUE, fg=WHITE)
    elif kind == "outline":
        c = Chip(text, base=GREEN, sel=GREEN, fg=BLACK, outline=True)
    elif kind == "green":
        c = Chip(text, base=ME_GREEN, sel=ME_GREEN, fg=WHITE)
    elif kind == "blue":
        c = Chip(text, base=BLUE, sel=BLUE, fg=WHITE)
    else:
        c = Chip(text)
        c.set_selected(selected)
    if on_tap:
        c.bind(on_release=lambda *_: on_tap())
    return c


def chip_row(chips):
    """One horizontally scrolling row of chips."""
    sv = ScrollView(size_hint_y=None, height=dp(CHIP_ROW_H), do_scroll_y=False, bar_width=0)
    row = BoxLayout(size_hint=(None, 1), spacing=dp(8))
    row.bind(minimum_width=row.setter("width"))
    for c in chips:
        row.add_widget(c)
    sv.add_widget(row)
    return sv


def pill_button(text, on_tap, base=BLACK, fg=WHITE, height=44):
    """Wide round button such as 'Load more (10)'."""
    b = Choice(base=base, fg=fg, text=text, bold=True, size_hint_y=None, height=dp(height))
    b.bind(on_release=lambda *_: on_tap())
    return b


# ------------------------------------------------------------------ message card (Board, Mind)
class CodeChip(ButtonBehavior, BoxLayout):
    """The light-blue reply code on the right of a message: tap = reply to this message."""

    def __init__(self, code, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(CODE_W), dp(CODE_H)))
        kw.setdefault("padding", [0, dp(4)])
        super().__init__(**kw)
        with self.canvas.before:
            Color(*CODE_BG)
            self._r = RoundedRectangle(radius=[dp(12)])
        settle(self, self._upd)
        self.add_widget(Label(text=code, bold=True, color=BLUE, font_size="16sp"))
        self.add_widget(Label(text=S.M_REPLY, color=BLUE, font_size="11sp"))

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self._r.radius = [rad(self.width, self.height, dp(12))]


class MsgCard(Tappable):
    """White card: avatar, the message as lines, a sub line, the reply code."""

    def __init__(self, m, me, sub, on_tap, on_reply, selected=False):
        super().__init__(padding=[dp(12), dp(10)], spacing=dp(12), size_hint_y=None, height=dp(72))
        self.set_selected(selected)
        self.bind(on_release=lambda *_: on_tap(m))
        mine = m["signer"] == me
        col = ME_GREEN if mine else (RED if (m["eff"] is not None and m["eff"] < 0) else BLUE)
        av = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(AVATAR_D))
        av.add_widget(Dot(bg=col, text=m["signer"][2:4], color=WHITE,
                          size=(dp(AVATAR_D), dp(AVATAR_D))))
        av.add_widget(Widget())
        self.add_widget(av)
        mid = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        mid.bind(minimum_height=mid.setter("height"))
        mid.bind(height=lambda i, h: setattr(self, "height", max(dp(72), h + dp(20))))
        for i, line in enumerate(m["lines"]):
            if i:
                mid.add_widget(Divider(color=TRACK_GRAY))
            mid.add_widget(Wrap(text=fmt_line(line, bold=(i == 0)), font_size="15sp"))
        mid.add_widget(Wrap(text=sub, font_size="12sp"))
        self.add_widget(mid)
        right = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(CODE_W))
        cc = CodeChip(m["code"])
        cc.bind(on_release=lambda *_: on_reply(m))
        right.add_widget(cc)
        right.add_widget(Widget())
        self.add_widget(right)


# ------------------------------------------------------------------ chat bubble
class Bubble(BoxLayout):
    """Rounded message balloon holding the lines of one message."""

    def __init__(self, lines, mine, pending=False, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, padding=[dp(12), dp(10)],
                         spacing=dp(4), **kw)
        self.mine, self.pending = mine, pending
        fg = WHITE if (mine and not pending) else BLACK
        bg = BLUE if (mine and not pending) else WHITE
        r, t = dp(BUBBLE_R), dp(BUBBLE_TAIL_R)
        self._radius = [r, r, t, r] if mine else [r, r, r, t]      # TL, TR, BR, BL
        with self.canvas.before:
            Color(*bg)
            self._bg = RoundedRectangle(radius=self._radius)
        self._ol = None
        if pending:
            with self.canvas.after:
                Color(*BLUE)
                self._ol = Line(rounded_rectangle=(0, 0, 10, 10, 8), width=dp(1.5),
                                dash_length=dp(4), dash_offset=dp(3))
        for i, line in enumerate(lines):
            if i:
                self.add_widget(Divider(color=(1, 1, 1, 0.4) if mine and not pending else TRACK_GRAY))
            self.add_widget(Wrap(text=fmt_line(line), color=fg, font_size="15sp"))
        self.bind(minimum_height=self.setter("height"))
        settle(self, self._upd)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        if self._ol is not None and self.width >= 4 and self.height >= 4:
            self._ol.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(BUBBLE_R))


class ChatItem(BoxLayout):
    """One chat message: balloon (left = other person, right = you) and a small caption."""

    def __init__(self, lines, mine, caption, pending=False):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(3))
        self.bind(minimum_height=self.setter("height"))
        row = BoxLayout(size_hint_y=None)
        row.bind(minimum_height=row.setter("height"))
        bubble = Bubble(lines, mine, pending, size_hint_x=0.78)
        if mine:
            row.add_widget(Widget(size_hint_x=0.22))
            row.add_widget(bubble)
        else:
            row.add_widget(bubble)
            row.add_widget(Widget(size_hint_x=0.22))
        self.add_widget(row)
        self.add_widget(Wrap(text=caption, font_size="12sp", halign="right" if mine else "left",
                             padding=(dp(6), 0)))
