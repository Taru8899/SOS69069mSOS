import json
import os
import threading
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

import core
import errors
import outbox
import page_board
import page_chat
import page_mind
from page_feed import slot_key
import strings as S
import tx
import util
from design import FAB_CLEAR, FAB_D, FAB_SINK, FONT_BODY, HEADER_H, HEADER_LINE_H, LIGHT, LOGO_W, NAV_H
from page_compose import ComposeScreen
from page_settings import SettingsScreen
from theme import (ETHERSCAN_TX, BLACK, BLUE, BUILD, DEFAULT_BOARDS, GREEN, HAS_LOGO, LOGO, WELCOME_MIN, WHITE,
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


POLL_SECONDS = 4
POLL_TRIES = 45          # 45 x 4 s = 3 minutes, then "still waiting" and a slower look
SLOW_SECONDS = 20
SLOW_TRIES = 180         # about one more hour
HOLD_SECONDS = 60        # no automatic reload for a minute after a message was sent


class MsosApp(App):
    def build(self):
        self.title = S.APP_TITLE
        if HAS_LOGO:
            self.icon = LOGO
        self.cfg_path = os.path.join(self.user_data_dir, "cfg.json")
        self.store_dir = os.path.join(self.user_data_dir, "msgs")
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
        self.watch = []           # watched addresses live for one session only (see wipe_mind)
        self.tags = list(cfg.get("tags") or [])
        # chats: every entry is one conversation = the other addresses joined by "," (1 to 3 of them);
        # they are kept between sessions, together with the selected one
        self.chats = [c.lower() for c in (cfg.get("chats") or []) if c]
        # page state
        self.ui = {"board": cfg.get("board") or self.boards[0]["addr"], "tag": cfg.get("tag"),
                   "board_sort": cfg.get("board_sort", "newest"),
                   "mind_scope": cfg.get("mind_scope", "all"), "mind_sort": cfg.get("mind_sort", "newest"),
                   "peer": cfg.get("peer") or (self.chats[0] if self.chats else ""),
                   "mind_tag": cfg.get("mind_tag"), "chat_tag": cfg.get("chat_tag"),
                   "chat_filter": "all", "sel": None, "shown": {}}

        self.wallet = Wallet(self)
        self.slots = {}           # (page, params) -> page_feed.Slot (cleared by reload)
        self.outbox = outbox.Outbox(os.path.join(self.user_data_dir, "outbox.json"))
        self.sending = False      # a message is being signed: no reload until the wallet has sent it
        self.hold_until = 0.0     # no automatic reload before this time (a minute after sending)
        self._tracking = set()
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
                             padding=[dp(14), dp(4), dp(14), dp(16 + FAB_CLEAR)])
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
        self.fab.bind(on_release=lambda *_: self.fab_tap())
        root.add_widget(self.fab)

        # ---- welcome screen on top of everything at start
        self.splash = Welcome()
        root.add_widget(self.splash)
        self.splash.start()

        self.set_drawer(not self.my, animate=False)         # first start: ask for the address
        self.render()
        self._mark_tabs()
        # messages sent before the app was closed and not final yet: keep following them
        Clock.schedule_once(lambda dt: [self.track(e) for e in self.outbox.active()], 1)
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
                           "mind_sort": u.get("mind_sort"), "peer": u.get("peer"),
                           "mind_tag": u.get("mind_tag"), "chat_tag": u.get("chat_tag")}, f)
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

    def follow_code(self, code):
        """Save @code as a tag and show only that thread (the message and its replies)."""
        self.add_tag("@" + code.lower())
        self.set_tag("@" + code.lower())

    def remove_tag(self, tag):
        self.tags = [t for t in self.tags if t != tag]
        for k in ("tag", "mind_tag", "chat_tag"):
            if self.ui.get(k) == tag:
                self.ui[k] = None
        self._changed()

    # ---- chats: a conversation is "0xB" or "0xB,0xC": me plus those addresses
    MAX_PEERS = 3

    @staticmethod
    def conv_peers(key):
        return [a for a in (key or "").lower().split(",") if a]

    def conv_with(self, addr):
        """The saved conversation that contains this address, or ''."""
        a = (addr or "").lower()
        return next((c for c in self.chats if a in self.conv_peers(c)), "")

    def add_chat(self, addr):
        """A conversation with one more address (nothing happens when one with it already exists)."""
        a = (addr or "").lower()
        if a and not self.conv_with(a):
            self.chats.append(a)
        self.save_cfg()

    def add_to_chat(self, key, addr):
        """Add an address to the conversation `key` (2 or more addresses in one chat). Returns an error text or ''."""
        a = (addr or "").lower()
        if not tx.valid_address(a) or a == self.my.lower():
            return S.CHAT_BAD_ADDR if not tx.valid_address(a) else S.CHAT_SELF
        peers = self.conv_peers(key)
        if a in peers:
            return ""
        if len(peers) >= self.MAX_PEERS:
            return S.CHAT_FULL.format(n=self.MAX_PEERS)
        new = ",".join(peers + [a])
        self.chats = [new if c == key else c for c in self.chats] if key in self.chats else self.chats + [new]
        self.ui["peer"] = new
        self.slots = {k: v for k, v in self.slots.items() if k[0] != "chat"}
        self.save_cfg()
        return ""

    def remove_chat(self, key):
        self.chats = [c for c in self.chats if c != key]
        if self.ui.get("peer") == key:
            self.ui["peer"] = self.chats[0] if self.chats else ""
        self.save_cfg()
        self.render()

    # ---------------------------------------------------------- page state set by chips
    def set_board(self, addr):
        self.ui["board"] = addr
        self.ui["sel"] = None
        self._changed()

    def set_tag(self, tag, key="tag"):
        """Select a saved tag for a page: key is tag (Board), mind_tag or chat_tag."""
        self.ui[key] = tag
        self.ui["sel"] = None
        self.ui["shown"] = {}
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
        self.body.add_widget(w)               # the blue "+" stays visible on every screen

    def close_top(self):
        if self.overlays:
            self.body.remove_widget(self.overlays.pop())
        if not self.overlays:
            self.render()

    def close_all(self):
        while self.overlays:
            self.body.remove_widget(self.overlays.pop())

    def fab_tap(self):
        """The blue +: a new message, or one more line when a message is being written."""
        top = self.overlays[-1] if self.overlays else None
        if isinstance(top, ComposeScreen):
            top.add_line()
        else:
            self.open_compose()

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
        self.wipe_mind()
        self.say(S.MSG_MIND_CLEARED)

    def wipe_mind(self):
        """Mind keeps only the messages you signed to yourself. Watched addresses are forgotten: the
        list, their messages and their scores. Chat, boards, tags and the Etherscan key are not touched."""
        me = self.my.lower()
        self.watch = []
        keep = None
        for k in [k for k in self.slots if k[0] == "mind"]:
            slot = self.slots.pop(k)
            f = slot.feed
            if f is None or not me:
                continue
            f.records = {i: r for i, r in f.records.items() if r["signer"] == me and r["to"] == me}
            f.eff = {a: v for a, v in f.eff.items() if a == me}
            f.params = {"addrs": [me]}
            keep = slot
        if keep is not None:
            self.slots[slot_key("mind", {"addrs": [me]})] = keep
        for k in [k for k in self.ui["shown"] if k[0] == "mind"]:
            del self.ui["shown"][k]
        self.ui["mind_scope"] = "all"
        self.ui["sel"] = None
        self.save_cfg()
        self.render()

    def on_stop(self):
        """App closed: the same clean-up for Mind (the file is saved without watched addresses)."""
        try:
            self.wipe_mind()
            self.wallet.disconnect()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- sending finished
    # ---------------------------------------------------------- sent messages
    @property
    def pending(self):
        """Sent messages that are not in a block yet (the chat shows them as waiting)."""
        return self.outbox.active()

    def submitted(self):
        """The wallet returned the transaction hash: reload is allowed again, but not for a minute."""
        self.sending = False
        self.hold_until = time.time() + HOLD_SECONDS

    def open_tx(self, h):
        if not util.open_url(ETHERSCAN_TX + h):
            self.say(S.SETTINGS_OPEN_FAILED)

    def copy_hash(self, h):
        self.say(S.M_COPIED if util.copy_text(h) else S.TX_COPY_FAILED)

    def dismiss_entry(self, eid):
        self.outbox.dismiss(eid)
        self.render()

    def track(self, e):
        """Follow a sent transaction in a worker thread until it is in a block (or forever, slowly)."""
        if e["id"] in self._tracking:
            return
        self._tracking.add(e["id"])
        threading.Thread(target=self._track_work, args=(e,), daemon=True).start()

    def _track_work(self, e):
        chain = core.Chain(self.es_key)
        n = 0
        try:
            while e["state"] in outbox.ACTIVE and self.outbox.get(e["id"]) is e:
                if self._check_once(chain, e):
                    return
                n += 1
                if n == POLL_TRIES and e["state"] == "wait":
                    e["state"] = "slow"
                    Clock.schedule_once(lambda dt: self.on_entry(e))
                if n > POLL_TRIES + SLOW_TRIES:
                    return
                time.sleep(POLL_SECONDS if n < POLL_TRIES else SLOW_SECONDS)
        finally:
            self._tracking.discard(e["id"])

    def _check_once(self, chain, e):
        """One look at the receipt. True when the transaction is final (recorded or failed)."""
        try:
            rc = chain.receipt(e["hash"])
        except Exception as ex:  # noqa: BLE001
            note = errors.explain("wait", str(ex) or type(ex).__name__, has_hash=True)
            if e.get("note") != note["title"]:
                e["note"] = note["title"]
                Clock.schedule_once(lambda dt: self.on_entry(e))
            return False
        if not rc:
            if e.get("note"):
                e["note"] = ""
                Clock.schedule_once(lambda dt: self.on_entry(e))
            return False
        ok = str(rc.get("status", "0x1")) == "0x1"
        e["block"] = int(rc.get("blockNumber") or "0x0", 16)
        e["t_ok"] = time.time()
        e["note"] = ""
        if ok:
            e["state"] = "ok"
        else:
            reason = chain.failure_reason(e["hash"], rc)
            x = errors.explain("wait", "", None, reason, wallet=e.get("wallet", ""), me=short(e["frm"]), has_hash=True)
            e["state"], e["err"] = "fail", {"title": x["title"], "body": x["body"], "tail": x["tail"]}
        Clock.schedule_once(lambda dt: self.on_entry(e))
        return True

    def on_entry(self, e):
        """A sent message changed state: save, update the open screens, reload after a successful one."""
        self.outbox.save()
        top = self.overlays[-1] if self.overlays else None
        if isinstance(top, ComposeScreen):
            top.on_entry(e)
        elif not self.overlays:
            self.render()
        if e["state"] == "ok":
            self.say(S.CMP_OK.format(block=e["block"], code=e["code"]), 10)
            self.reload_later()

    def check_now(self, *_):
        """Pull down on New message: look at the waiting transactions right now."""
        act = self.outbox.active()
        if not act:
            return
        self.say(S.CMP_CHECKING, 4)

        def work():
            chain = core.Chain(self.es_key)
            for e in act:
                self._check_once(chain, e)
        threading.Thread(target=work, daemon=True).start()

    def reload_later(self):
        """Reload after a message was recorded, but not earlier than a minute after it was sent."""
        Clock.schedule_once(lambda dt: self.reload(auto=True), max(0.2, self.hold_until - time.time()))

    # ---------------------------------------------------------- reload / render
    def reload(self, *_, auto=False):
        """Pull-to-reload: every view is read again (saved messages show at once, then the news).
        Nothing reloads while a message is being signed; after it was sent an automatic reload
        waits for the end of the hold."""
        if self.sending:
            self.say(S.MSG_RELOAD_HELD)
            return
        left = self.hold_until - time.time()
        if auto and left > 0.5:
            Clock.schedule_once(lambda dt: self.reload(auto=True), left)
            return
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
