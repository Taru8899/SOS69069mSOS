import json
import os
import time
import traceback

from kivy.animation import Animation
from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.utils import escape_markup

import page_board
import page_chat
import page_mind
import strings as S
import tx
import util
from design import FAB_D, FAB_SINK, FONT_BODY, HEADER_H, HEADER_LINE_H, LIGHT, LOGO_W, NAV_H
from page_compose import ComposeScreen
from page_settings import SettingsScreen
from theme import (BLACK, BLUE, BUILD, DEFAULT_BOARDS, GREEN, HAS_LOGO, LOGO, WELCOME_MIN, WHITE,
                   short)
from wallet import Wallet
from widgets import (Card, Chevron, Choice, ErrorBanner, IconBtn, LogoBtn, NavTab, Panel, PillBtn,
                     PullScroll, Tap, Welcome, label, make_input)

Window.clearcolor = GREEN
Window.softinput_mode = "below_target"   # keep the focused field visible above the keyboard

# tab name -> function that fills that tab:  build(app, box)
PAGES = {"board": page_board.build, "mind": page_mind.build, "chat": page_chat.build}
TITLES = {"board": S.TAB_BOARD, "mind": S.TAB_MIND, "chat": S.TAB_CHAT}
ICONS = {"board": "grid", "mind": "mind", "chat": "chat"}


class Catcher(ExceptionHandler):
    """Any exception inside a button/timer callback ends up here instead of closing the app."""

    def handle_exception(self, inst):
        app = App.get_running_app()
        try:
            if app is not None:
                app.report_error(inst)
        except Exception:  # noqa: BLE001
            pass
        return ExceptionManager.PASS


ExceptionManager.add_handler(Catcher())


class MsosApp(App):
    def build(self):
        self.title = S.APP_TITLE
        if HAS_LOGO:
            self.icon = LOGO
        self.cfg_path = os.path.join(self.user_data_dir, "cfg.json")
        self.crash_path = os.path.join(self.user_data_dir, "crash.txt")
        self.crumb_path = os.path.join(self.user_data_dir, "breadcrumb.txt")
        cfg = {}
        try:
            with open(self.cfg_path) as f:
                cfg = json.load(f)
        except Exception:  # noqa: BLE001
            pass

        # ---- saved settings (the app stores no private key: only addresses, tags, the Etherscan key)
        self.my = (cfg.get("addr") or "").strip()
        self.es_key = (cfg.get("key") or "").strip()
        self.boards = [dict(b) for b in (cfg.get("boards") or DEFAULT_BOARDS)]
        if not self.boards or self.boards[0]["addr"].lower() != DEFAULT_BOARDS[0]["addr"].lower():
            self.boards.insert(0, dict(DEFAULT_BOARDS[0]))      # the ledger board is always first
        self.watch = list(cfg.get("watch") or [])
        self.tags = list(cfg.get("tags") or [])
        self.chats = list(cfg.get("chats") or [])
        # page state
        self.ui = {"board": cfg.get("board") or self.boards[0]["addr"], "tag": cfg.get("tag"),
                   "board_sort": cfg.get("board_sort", "newest"),
                   "mind_scope": cfg.get("mind_scope", "all"), "mind_sort": cfg.get("mind_sort", "newest"),
                   "peer": cfg.get("peer") or (self.chats[0] if self.chats else ""),
                   "chat_filter": "all", "sel": None, "shown": {}}

        self.wallet = Wallet(self)
        self.slots = {}           # (page, params) -> page_feed.Slot (cleared by reload)
        self.pending = []         # messages sent, not yet in a block
        self.page = "board"
        self.overlays = []
        self.banner = None
        self.block = None
        self.block_src = ""

        root = FloatLayout()
        self.root_box = root
        main = BoxLayout(orientation="vertical", spacing=0)
        self.main = main

        # ---- header: logo, page title + line, Ethereum pill
        head = BoxLayout(size_hint_y=None, height=dp(HEADER_H), spacing=dp(10),
                         padding=[dp(14), dp(4), dp(14), dp(2)])
        self.head = head
        logo_col = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(LOGO_W))
        if HAS_LOGO:
            self.logo = LogoBtn(source=LOGO, size_hint=(1, 1))
            self.logo.bind(on_release=lambda *_: self.set_page("board"))
            logo_col.add_widget(self.logo)
        head.add_widget(logo_col)
        # page title, and under it the wallet address (underlined, with a triangle): tap = the wallet
        # panel with the Etherscan key and the address, exactly as in dSOS
        title = Tap(orientation="vertical")
        title.bind(on_release=lambda *_: self.toggle_drawer())
        title.add_widget(BoxLayout())                      # equal spacers keep the two lines together
        self.title_lbl = label("", size_hint_y=None, height=dp(HEADER_LINE_H), font_size="22sp")
        title.add_widget(self.title_lbl)
        addr_row = BoxLayout(size_hint_y=None, height=dp(HEADER_LINE_H), spacing=dp(6))
        self.sub = Label(text=self._head_text(), markup=True, color=BLACK, font_size=FONT_BODY,
                         halign="left", valign="middle", size_hint=(None, 1))
        self.sub.bind(texture_size=lambda i, ts: setattr(i, "width", ts[0]))
        self.chev = Chevron(pos_hint={"center_y": 0.5})
        addr_row.add_widget(self.sub)
        addr_row.add_widget(self.chev)
        addr_row.add_widget(BoxLayout())
        title.add_widget(addr_row)
        title.add_widget(BoxLayout())
        head.add_widget(title)
        pill = PillBtn(text=S.CHAIN_PILL, color=WHITE, bold=True, size_hint=(None, None),
                       size=(dp(124), dp(38)), pos_hint={"center_y": 0.5})
        pill.bind(on_release=lambda *_: self.open_settings())
        head.add_widget(pill)
        main.add_widget(head)

        self.msg = Label(text="", size_hint_y=None, height=dp(18), color=BLACK, font_size="13sp")
        main.add_widget(self.msg)

        # ---- wallet panel (Etherscan key + address + Load / Exit): floats over the top of the body
        # and is added to it only while open, so folded it takes no space
        self.addr_in = make_input(S.HINT_ADDRESS, self.my)
        self.key_in = make_input(S.HINT_API_KEY, self.es_key, password=True)
        self.drawer_open = False
        self.drawer = Panel(orientation="vertical", size_hint=(None, None), spacing=dp(8),
                            padding=dp(12), bg=LIGHT)
        self.drawer.size = (dp(300), dp(12 * 2 + 3 * 50 + 2 * 8))
        self.drawer.add_widget(self._with_paste(self.key_in))
        self.drawer.add_widget(self._with_paste(self.addr_in))
        btn_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        load_btn = Choice(base=BLUE, fg=WHITE, text=S.BTN_LOAD, bold=True, size_hint_x=0.7)
        load_btn.bind(on_release=self.load)
        exit_btn = Choice(base=BLACK, fg=WHITE, text=S.BTN_EXIT, bold=True, size_hint_x=0.3)
        exit_btn.bind(on_release=self.exit_wallet)
        btn_row.add_widget(load_btn)
        btn_row.add_widget(exit_btn)
        self.drawer.add_widget(btn_row)

        # ---- body: the page (scrolls, pull to reload) and overlay pages on top of it
        self.body = FloatLayout()
        self.body.bind(width=self._fit_drawer)
        self.sv = PullScroll(size_hint=(1, 1), pos_hint={"x": 0, "y": 0}, on_pull=self.reload)
        self.box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None,
                             padding=[dp(14), dp(4), dp(14), dp(16)])
        self.box.bind(minimum_height=self.box.setter("height"))
        self.sv.add_widget(self.box)
        self.body.add_widget(self.sv)
        main.add_widget(self.body)

        # ---- bottom bar: Board, Mind, Chat (the "+" is NOT in it: it floats above)
        nav = BoxLayout(size_hint_y=None, height=dp(NAV_H))
        self.nav = nav
        with nav.canvas.before:
            Color(*BLACK)
            nav_bg = Rectangle()
        nav.bind(pos=lambda i, p: setattr(nav_bg, "pos", p),
                 size=lambda i, s: setattr(nav_bg, "size", s))
        self.nav_btns = {}
        for name in ("board", "mind", "chat"):
            nav.add_widget(self._tab(name, TITLES[name], ICONS[name]))
        main.add_widget(nav)
        root.add_widget(main)

        # ---- the cross: centred over the Mind tab, just above the bar, outside it
        d = dp(FAB_D + 6)                                  # IconBtn draws its circle 6 dp smaller
        self.fab = IconBtn(icon="plus", bg=BLUE, color=WHITE, icon_size=30, size_hint=(None, None),
                           size=(d, d), pos_hint={"center_x": 0.5})
        self.fab.y = dp(NAV_H - FAB_SINK * FAB_D - 3)     # circle bottom = 10 % of its height inside the bar
        self.fab.bind(on_release=lambda *_: self.open_compose())
        root.add_widget(self.fab)

        # ---- welcome screen on top of everything at start
        self.splash = Welcome()
        root.add_widget(self.splash)
        self.splash.start()

        self.set_drawer(not self.my, animate=False)         # first start: ask for the address
        self.render()
        self._mark_tabs()
        return root

    # ---------------------------------------------------------- saved settings
    def save_cfg(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            u = self.ui
            with open(self.cfg_path, "w") as f:
                json.dump({"addr": self.my, "key": self.es_key, "boards": self.boards,
                           "watch": self.watch, "tags": self.tags, "chats": self.chats,
                           "board": u.get("board"), "tag": u.get("tag"),
                           "board_sort": u.get("board_sort"), "mind_scope": u.get("mind_scope"),
                           "mind_sort": u.get("mind_sort"), "peer": u.get("peer")}, f)
        except Exception:  # noqa: BLE001
            pass

    def _changed(self, reload=False):
        self.save_cfg()
        if reload:
            self.slots.clear()
        self.ui["shown"] = {} if reload else self.ui["shown"]
        self.render()

    def set_my(self, addr):
        self.my = (addr or "").strip()
        self.addr_in.text = self.my
        self._changed(reload=True)

    def set_key(self, key):
        self.es_key = key
        self.key_in.text = key
        self._changed(reload=True)

    # ---------------------------------------------------------- wallet panel (as in dSOS)
    def _head_text(self):
        return "[u]%s[/u]" % (short(self.my) or S.HEADER_NO_ADDR)

    def refresh_head(self):
        self.sub.text = self._head_text()

    def _with_paste(self, field):
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        row.add_widget(field)
        pb = Choice(base=BLUE, fg=WHITE, text=S.BTN_PASTE, bold=True, size_hint=(None, 1), width=dp(72))
        pb.bind(on_release=lambda *_: self.paste_into(field))
        row.add_widget(pb)
        return row

    def paste_into(self, field):
        t = util.paste_text()
        if t:
            field.text = t.strip()
            self.say(S.MSG_PASTED)
        else:
            self.say(S.MSG_CLIPBOARD_EMPTY)

    def _fit_drawer(self, *_):
        self.drawer.width = max(dp(240), self.body.width - dp(28))
        self.drawer.pos_hint = {"x": dp(14) / max(self.body.width, 1), "top": 1}

    def set_drawer(self, show, animate=True):
        self.drawer_open = bool(show)
        self.chev.set_open(self.drawer_open, animate=animate)
        if self.drawer_open:
            self.close_all()                  # the panel and a page are never open together
        if self.drawer_open and self.drawer.parent is None:
            self._fit_drawer()
            self.body.add_widget(self.drawer)
        elif not self.drawer_open and self.drawer.parent is not None:
            self.drawer.parent.remove_widget(self.drawer)

    def toggle_drawer(self):
        self.set_drawer(not self.drawer_open)

    def load(self, *_):
        """Load: take the address and the Etherscan key, save them, read everything again."""
        a = self.addr_in.text.strip()
        if a and not tx.valid_address(a):
            self.say(S.SET_BAD_ADDR)
            return
        self.my, self.es_key = a, self.key_in.text.strip()
        self.save_cfg()
        self.slots.clear()
        self.ui["shown"] = {}
        self.set_drawer(False)                # the key and address fold back into the header
        self.msg.text = S.MSG_RELOADING
        self._say_until = 0
        self.render()

    def add_board(self, name, addr):
        if not any(b["addr"].lower() == addr.lower() for b in self.boards):
            self.boards.append({"name": name, "addr": addr})
        self.ui["board"] = addr
        self._changed()

    def remove_board(self, addr):
        self.boards = [b for i, b in enumerate(self.boards) if i == 0 or b["addr"].lower() != addr.lower()]
        if self.ui["board"].lower() == addr.lower():
            self.ui["board"] = self.boards[0]["addr"]
        self._changed()

    def add_watch(self, addr):
        if addr.lower() not in [a.lower() for a in self.watch]:
            self.watch.append(addr)
        self._changed(reload=True)

    def remove_watch(self, addr):
        self.watch = [a for a in self.watch if a.lower() != addr.lower()]
        self._changed(reload=True)

    def add_tag(self, tag):
        if tag not in self.tags:
            self.tags.append(tag)
        self._changed()

    def remove_tag(self, tag):
        self.tags = [t for t in self.tags if t != tag]
        if self.ui.get("tag") == tag:
            self.ui["tag"] = None
        self._changed()

    def add_chat(self, addr):
        if addr.lower() not in [a.lower() for a in self.chats]:
            self.chats.append(addr.lower())
        self.save_cfg()

    # ---------------------------------------------------------- page state set by chips
    def set_board(self, addr):
        self.ui["board"] = addr
        self.ui["sel"] = None
        self._changed()

    def set_tag(self, tag):
        self.ui["tag"] = tag
        self._changed()

    def set_sort(self, key, value):
        self.ui[key] = value
        self.ui["sel"] = None
        self._changed()

    def set_peer(self, addr):
        self.ui["peer"] = addr.lower()
        self.ui["sel"] = None
        self._changed()

    # ---------------------------------------------------------- header / block line
    def set_block(self, block, source):
        """Block number and where it came from ("Block 26,423,806 via ethereum-rpc.publicnode.com");
        a short message from say() is left alone until it has run out."""
        self.block, self.block_src = block, source
        if time.time() >= getattr(self, "_say_until", 0):
            self.restore_msg()

    def restore_msg(self):
        self.msg.text = S.MSG_BLOCK_VIA.format(block=self.block, source=self.block_src) if self.block else ""

    def say(self, text, secs=6):
        """Short message under the header; it goes away after `secs` seconds."""
        self.msg.text = text
        self._say_until = time.time() + secs
        if getattr(self, "_say_ev", None) is not None:
            self._say_ev.cancel()
        self._say_ev = Clock.schedule_once(lambda dt: self.restore_msg(), secs)

    # ---------------------------------------------------------- tabs
    def _tab(self, name, text, icon):
        b = NavTab(icon, text)
        b.bind(on_release=lambda *_: self.tab_tap(name))
        self.nav_btns[name] = b
        return b

    def _mark_tabs(self):
        for name, b in self.nav_btns.items():
            b.set_active(name == self.page)

    def tab_tap(self, name):
        self.close_all()
        self.set_page(name)

    def set_page(self, name):
        self.close_all()
        if self.drawer_open:
            self.set_drawer(False)
        self.page = name
        self.ui["sel"] = None
        self._mark_tabs()
        self.render()
        self.sv.scroll_y = 1

    # ---------------------------------------------------------- overlays (inside the body)
    def open_overlay(self, w):
        if self.drawer_open:
            self.set_drawer(False)
        self.overlays.append(w)
        self.body.add_widget(w)
        self.fab.opacity = 0
        self.fab.disabled = True

    def close_top(self):
        if self.overlays:
            self.body.remove_widget(self.overlays.pop())
        if not self.overlays:
            self.fab.opacity = 1
            self.fab.disabled = False
            self.render()

    def close_all(self):
        while self.overlays:
            self.body.remove_widget(self.overlays.pop())
        self.fab.opacity = 1
        self.fab.disabled = False

    def open_settings(self):
        if self.overlays and isinstance(self.overlays[-1], SettingsScreen):
            self.close_all()
            return
        self.close_all()
        self.open_overlay(SettingsScreen(self))

    def open_compose(self, dest=None, reply=None):
        """The cross: a new message for the page you are on (or a reply to a message)."""
        self.close_all()
        if dest is None:
            if self.page == "mind":
                dest = ("mind", self.my)
            elif self.page == "chat":
                dest = ("chat", self.ui.get("peer") or "")
            else:
                dest = ("board", self.ui.get("board") or self.boards[0]["addr"])
        self.open_overlay(ComposeScreen(self, dest=dest, reply=reply))

    def on_back(self, window, key, *args):
        if key == 27 and self.overlays:   # Android back button
            self.close_top()
            return True
        return False

    def on_pause(self):
        return True                      # the wallet app comes to the front while it approves

    def on_resume(self):
        self.wallet.on_resume()

    def exit_wallet(self, *_):
        """Exit: disconnect the wallet link (the next signing asks the wallet again)."""
        try:
            self.wallet.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.say(S.MSG_WALLET_DISCONNECTED)

    # ---------------------------------------------------------- sending finished
    def tx_done(self, pend, h, ok, block, reason, code):
        """A message transaction was mined (ok), reverted (not ok) or is still pending (None)."""
        if ok is None:
            self.say(S.CMP_PENDING.format(hash=short(h)), 12)
            return
        if pend in self.pending:
            self.pending.remove(pend)
        if ok:
            self.say(S.CMP_OK.format(block=block, code=code), 10)
            self.reload()
        else:
            why = reason or S.TX_FAILED_UNKNOWN
            self.show_banner(S.CMP_FAILED.format(reason=why), "%s\n%s" % (why, h))
            self.render()

    # ---------------------------------------------------------- reload / render
    def reload(self, *_):
        """Pull-to-reload: every view is read again."""
        self.slots.clear()
        self.ui["shown"] = {}
        self.msg.text = S.MSG_RELOADING
        self._say_until = 0
        self.render()

    def render(self):
        b = self.box
        b.clear_widgets()
        self.title_lbl.text = "[b]%s[/b]" % TITLES[self.page]
        self.refresh_head()
        self.crumb("render " + self.page)
        try:
            PAGES[self.page](self, b)
        except Exception as e:  # noqa: BLE001
            b.clear_widgets()
            b.add_widget(Card(S.ERR_PAGE.format(error=escape_markup(f"{type(e).__name__}: {e}"))))
            self.report_error(e)
        self.crumb("ok")

    def layout_report(self):
        out = ["window=%s build=%s" % (tuple(Window.size), BUILD)]
        for n in ("head", "msg", "body", "sv", "box", "nav", "drawer"):
            w = getattr(self, n, None)
            if w is not None:
                out.append("%s pos=%s size=%s" % (n, tuple(round(v) for v in w.pos),
                                                  tuple(round(v) for v in w.size)))
        return "\n".join(out)

    # ---------------------------------------------------------- errors
    def crumb(self, step):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.crumb_path, "w") as f:
                f.write(step)
        except Exception:  # noqa: BLE001
            pass

    def report_error(self, exc):
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.crash_path, "w") as f:
                f.write(text)
        except Exception:  # noqa: BLE001
            pass
        self.show_banner(f"{type(exc).__name__}: {exc}", text)

    def show_banner(self, short_text, full_text):
        if getattr(self, "banner", None) is not None:
            self.root_box.remove_widget(self.banner)
            self.banner = None
        b = ErrorBanner(S.ERR_BANNER.format(text=short_text), full_text, self.close_banner,
                        pos_hint={"top": 1})
        self.banner = b
        self.root_box.add_widget(b)

    def close_banner(self, b=None):
        if self.banner is not None:
            self.root_box.remove_widget(self.banner)
            self.banner = None
        try:
            os.remove(self.crash_path)
        except OSError:
            pass

    def check_last_run(self):
        try:
            with open(self.crash_path) as f:
                txt = f.read()
            if txt.strip():
                self.show_banner(txt.strip().splitlines()[-1], txt)
                return
        except OSError:
            pass
        try:
            with open(self.crumb_path) as f:
                step = f.read().strip()
            if step and step != "ok":
                self.show_banner(S.ERR_LAST_RUN.format(step=step), step)
        except OSError:
            pass

    # ---------------------------------------------------------- start / welcome
    def on_start(self):
        Window.bind(on_keyboard=self.on_back)
        self.check_last_run()
        self.t0 = time.time()
        Clock.schedule_interval(self.welcome_tick, 0.2)

    def welcome_tick(self, dt):
        if time.time() - self.t0 >= WELCOME_MIN:
            self.hide_splash()
            return False
        return True

    def hide_splash(self, *_):
        sp = self.splash
        if sp is None:
            return
        self.splash = None
        anim = Animation(opacity=0, duration=0.4)

        def gone(*a):
            sp.stop()
            if sp.parent is not None:
                sp.parent.remove_widget(sp)
        anim.bind(on_complete=gone)
        anim.start(sp)


if __name__ == "__main__":
    MsosApp().run()
