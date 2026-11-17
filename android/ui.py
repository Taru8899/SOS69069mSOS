"""mSOS look (the mockup): chips, message cards, chat bubbles, block headings.
Colours and sizes come from design.py; wording from strings.py."""
import re

from kivy.graphics import Color, Line, RoundedRectangle, Triangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import escape_markup

import strings as S
from design import W_BTN_LINK, BLUE_HEX, FONT_MEDIUM, FONT_MSG, FONT_NOTE, FONT_SMALL, FONT_TINY, GAP, GAP_CARDS, GAP_HAIR, GAP_PIXEL, GAP_SMALL, GAP_TINY, H_LABEL_ROW, H_NOTE, LINE_W, PAD_CARD, RED_HEX, W_BTN_SMALL, W_TAG_COL
from design import (AVATAR_D, BUBBLE_R, BUBBLE_TAIL_R, CHIP_H, CHIP_ROW_H, CODE_BG, CODE_H, CODE_W,
                    DARK_GREEN_HEX, ME_GREEN, TRACK_GRAY, FOLD_ARROW_D, FOLD_ARROW_W, FOLD_SUMMARY_SP, H_BUTTON)
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
    t = CODE_AT_START.sub(lambda m: m.group(1) + "[color=" + BLUE_HEX + "][b]" + m.group(2) + "[/b][/color]", t)
    return "[b]%s[/b]" % t if bold else t


def eff_markup(eff):
    if eff is None:
        return S.M_EFF.format(eff="?")
    if eff > 0:
        return S.M_EFF.format(eff="[color=%s][b]+%d[/b][/color]" % (DARK_GREEN_HEX, eff))
    if eff < 0:
        return S.M_EFF.format(eff="[color=%s][b]%d[/b][/color]" % (RED_HEX, eff))
    return S.M_EFF.format(eff="[b]0[/b]")


def who(addr, me):
    return S.M_YOU if addr == me else short(addr)


def block_head(m, ago_text):
    return Wrap(text="[b]%s[/b]" % S.M_BLOCK_HEAD.format(block=m["block"], ago=ago_text or "–"),
                font_size=FONT_NOTE, halign="center", padding=(0, dp(GAP_HAIR)))


# ------------------------------------------------------------------ chips
class Chip(Choice):
    """Round-ended chip, 44 dp high, as wide as its text."""

    def __init__(self, text, base=WHITE, sel=BLACK, fg=BLACK, sel_fg=WHITE, outline=False, **kw):
        kw.setdefault("font_size", FONT_SMALL)
        kw.setdefault("bold", True)
        kw["size_hint"] = (None, None)
        kw["height"] = dp(CHIP_H)
        kw["width"] = dp(W_TAG_COL)
        kw["pos_hint"] = {"center_y": 0.5}
        super().__init__(base=base, sel=sel, fg=fg, sel_fg=sel_fg, text=text, **kw)
        self.bind(texture_size=lambda i, ts: setattr(i, "width", ts[0] + dp(H_LABEL_ROW)))
        self._ol = None
        if outline:
            with self.canvas.after:
                Color(*BLACK)
                self._ol = Line(rounded_rectangle=(0, 0, 10, 10, 5), width=dp(LINE_W))
            settle(self, self._upd_outline)

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self._r.radius = [self.height / 2.0]

    def _upd_outline(self, *_):
        if self._ol is not None and self.width >= 4 and self.height >= 4:
            self._ol.rounded_rectangle = (self.x, self.y, self.width, self.height, self.height / 2.0)


def chip(text, on_tap=None, selected=False, kind="idle", color=None):
    """kind: idle (white / black when selected), action (blue), outline, green (you), blue.
    color: a fixed colour chip with white text (the senders of a chat)."""
    if color is not None:
        c = Chip(text, base=color, sel=color, fg=WHITE)
    elif kind == "action":
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
    row = BoxLayout(size_hint=(None, 1), spacing=dp(GAP))
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
        kw.setdefault("padding", [0, dp(GAP_TINY)])
        super().__init__(**kw)
        with self.canvas.before:
            Color(*CODE_BG)
            self._r = RoundedRectangle(radius=[dp(PAD_CARD)])
        settle(self, self._upd)
        self.add_widget(Label(text=code, bold=True, color=BLUE, font_size=FONT_MEDIUM))
        self.add_widget(Label(text=S.M_REPLY, color=BLUE, font_size=FONT_TINY))

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self._r.radius = [rad(self.width, self.height, dp(PAD_CARD))]


class MsgCard(Tappable):
    """White card: avatar, the message as lines, a sub line, the reply code."""

    def __init__(self, m, me, sub, on_tap, on_reply, selected=False, color=None, pending=False):
        super().__init__(padding=[dp(PAD_CARD), dp(GAP_CARDS)], spacing=dp(PAD_CARD), size_hint_y=None, height=dp(W_BTN_SMALL))
        self.set_selected(selected)
        self.bind(on_release=lambda *_: on_tap(m))
        mine = m["signer"] == me
        col = ME_GREEN if mine else (RED if (m["eff"] is not None and m["eff"] < 0) else BLUE)
        if color is not None:                                  # Chat: the colour of the sender
            col = color
        av = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(AVATAR_D))
        av.add_widget(Dot(bg=col, text=m["signer"][2:4], color=WHITE,
                          size=(dp(AVATAR_D), dp(AVATAR_D))))
        av.add_widget(Widget())
        self.add_widget(av)
        mid = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(GAP_TINY))
        mid.bind(minimum_height=mid.setter("height"))
        mid.bind(height=lambda i, h: setattr(self, "height", max(dp(W_BTN_SMALL), h + dp(H_NOTE))))
        for i, line in enumerate(m["lines"]):
            if i:
                mid.add_widget(Divider(color=TRACK_GRAY))
            mid.add_widget(Wrap(text=fmt_line(line, bold=(i == 0)), font_size=FONT_MSG))
        mid.add_widget(Wrap(text=sub, font_size=FONT_NOTE))
        self.add_widget(mid)
        right = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(CODE_W))
        if not pending:
            cc = CodeChip(m["code"])
            cc.bind(on_release=lambda *_: on_reply(m))
            right.add_widget(cc)
        right.add_widget(Widget())
        self.add_widget(right)


# ------------------------------------------------------------------ fold header (Board, Mind, Chat)
class Arrow(Widget):
    """A small filled triangle: pointing right when closed, down when open."""

    def __init__(self, open_, **kw):
        kw.setdefault("size_hint", (None, 1))
        kw.setdefault("width", dp(FOLD_ARROW_W))
        super().__init__(**kw)
        self.open_ = open_
        with self.canvas:
            Color(*BLACK)
            self._t = Triangle(points=[0, 0, 0, 0, 0, 0])
        settle(self, self._upd)

    def _upd(self, *_):
        s = dp(FOLD_ARROW_D)
        cx, cy = self.center_x, self.center_y
        if self.open_:                                   # down
            pts = [cx - s, cy + s / 2, cx + s, cy + s / 2, cx, cy - s / 2]
        else:                                            # right
            pts = [cx - s / 2, cy + s, cx - s / 2, cy - s, cx + s / 2, cy]
        self._t.points = pts


class FoldHeader(Tappable):
    """One line above the messages: the page's name, what is selected, and a triangle. Tap = show
    or hide the address chips, tags and filters below it."""

    def __init__(self, title, summary, open_, on_tap, **kw):
        super().__init__(size_hint_y=None, height=dp(H_BUTTON), padding=[dp(PAD_CARD), 0], spacing=dp(GAP), **kw)
        text = "[b]%s[/b]" % escape_markup(title)
        if summary and not open_:
            text += "  [size=%s]%s[/size]" % (FOLD_SUMMARY_SP, escape_markup(summary))
        lb = Label(text=text, markup=True, color=BLACK, halign="left", valign="middle", shorten=True,
                   shorten_from="right", font_size=FONT_MSG)
        lb.bind(size=lambda i, s: setattr(i, "text_size", s))
        self.add_widget(lb)
        self.add_widget(Arrow(open_))
        self.bind(on_release=lambda *_: on_tap())


# ------------------------------------------------------------------ status card of a sent message
def send_card(e, on_open, on_copy, on_dismiss):
    """Card for one sent message: waiting (cream), recorded (green), failed (red), with the
    Etherscan link, Copy hash and - once finished - Dismiss."""
    from design import CREAM, LIGHT_GREEN, H_BUTTON
    from widgets import Panel
    st = e["state"]
    bg, fg = {"ok": (LIGHT_GREEN, BLACK), "fail": (RED, WHITE)}.get(st, (CREAM, BLACK))
    h = e["hash"]
    if st == "ok":
        text = S.OUT_OK.format(block=e["block"], code=e["code"], tx=short(h))
    elif st == "fail":
        err = e.get("err") or {}
        text = S.OUT_FAIL.format(title=err.get("title", ""), body=err.get("body", ""), tail=err.get("tail", ""))
    elif st == "slow":
        text = S.OUT_SLOW.format(code=e["code"], tx=short(h))
    else:
        text = S.OUT_WAIT.format(code=e["code"], tx=short(h))
    p = Panel(bg=bg, orientation="vertical", size_hint_y=None, spacing=dp(GAP_SMALL),
              padding=[dp(PAD_CARD), dp(PAD_CARD)])
    p.bind(minimum_height=p.setter("height"))
    p.add_widget(Wrap(text=text, color=fg, font_size=FONT_MSG))
    if e.get("note") and st in ("wait", "slow"):
        p.add_widget(Wrap(text=S.OUT_NOTE.format(note=e["note"]), color=fg, font_size=FONT_NOTE))
    row = BoxLayout(size_hint_y=None, height=dp(H_BUTTON), spacing=dp(GAP))
    b = Choice(base=BLUE if st != "fail" else WHITE, fg=WHITE if st != "fail" else BLACK, text=S.OUT_VIEW, bold=True,
               size_hint_x=W_BTN_LINK)
    b.bind(on_release=lambda *_: on_open(h))
    row.add_widget(b)
    c = Choice(base=WHITE, fg=BLACK, text=S.OUT_COPY, bold=True)
    c.bind(on_release=lambda *_: on_copy(h))
    row.add_widget(c)
    if st in ("ok", "fail"):
        d = Choice(base=BLACK, fg=WHITE, text=S.OUT_DISMISS, bold=True)
        d.bind(on_release=lambda *_: on_dismiss(e["id"]))
        row.add_widget(d)
    p.add_widget(row)
    return p
