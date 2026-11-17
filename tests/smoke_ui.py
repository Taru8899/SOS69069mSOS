"""Smoke test of the UI code WITHOUT Kivy: every kivy class is replaced by a permissive stub, then
the app is built and every page, the composer and the settings are created with sample data. It
finds typos, wrong names and wrong calls (not layout problems: those need a phone).
Run:  python tests/smoke_ui.py"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "android"))
import test_msos as T  # noqa: E402,F401  (installs the keccak stand-in when needed)


class Any:
    """Permissive stand-in: any attribute, call, arithmetic or comparison works."""
    def __init__(self, *a, **k):
        self.__dict__["children"] = []
        self.__dict__["parent"] = None
        self.__dict__.update(k)

    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return Any()

    def __call__(self, *a, **k):
        return Any()

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(())
    def __bool__(self): return True
    def __lt__(self, o): return False
    __le__ = __gt__ = __ge__ = __lt__
    def __add__(self, o): return 0
    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __add__
    __floordiv__ = __neg__ = __add__
    def __float__(self): return 0.0
    def __int__(self): return 0
    def __getitem__(self, i): return 0
    def __index__(self): return 0


class Widget(Any):
    def bind(self, **k): pass
    def unbind(self, **k): pass
    def add_widget(self, w, *a, **k):
        self.children.append(w)
        try:
            w.__dict__["parent"] = self
        except Exception:  # noqa: BLE001
            pass
    def remove_widget(self, w):
        if w in self.children:
            self.children.remove(w)
    def clear_widgets(self): self.children.clear()
    def setter(self, name): return lambda *a: None
    def collide_point(self, *a): return False
    def dispatch(self, *a): pass
    def on_touch_down(self, t): return False
    def on_touch_up(self, t): return False
    def __getattr__(self, n):
        if n in ("pos", "size", "center"):
            return (100, 100)
        if n in ("center_x", "center_y", "x", "y", "width", "height", "top", "right",
                 "texture_size", "scroll_y", "opacity", "minimum_height", "minimum_width"):
            return 100
        return Any.__getattr__(self, n)


class Prop:
    def __init__(self, *a, **k): pass


class AppBase(Widget):
    user_data_dir = tempfile.mkdtemp()
    _inst = None
    def __init__(self, *a, **k):
        Widget.__init__(self)
        AppBase._inst = self
    @staticmethod
    def get_running_app(): return AppBase._inst


class Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        if n in ("Property", "NumericProperty", "StringProperty", "ListProperty", "BooleanProperty",
                 "ObjectProperty", "ColorProperty"):
            return Prop
        if n == "App":
            return AppBase
        if n == "dp":
            return lambda v: v
        if n == "escape_markup":
            return lambda s: str(s).replace("[", "&bl;").replace("]", "&br;")
        if n in ("Window",):
            return Any()
        if n in ("Clock",):
            c = Any()
            c.schedule_once = lambda fn, t=0: None
            c.schedule_interval = lambda fn, t=0: Any()
            c.create_trigger = lambda fn, t=0: Any()
            return c
        if n in ("ExceptionHandler",):
            return Widget
        if n == "ExceptionManager":
            return Any()
        if n == "Metrics":
            return Any()
        cls = type(n, (Widget,), {})
        setattr(self, n, cls)
        return cls


for name in ["kivy", "kivy.animation", "kivy.app", "kivy.base", "kivy.clock", "kivy.core", "kivy.core.window",
             "kivy.core.clipboard", "kivy.graphics", "kivy.metrics", "kivy.uix", "kivy.uix.behaviors",
             "kivy.uix.boxlayout", "kivy.uix.button", "kivy.uix.floatlayout", "kivy.uix.image",
             "kivy.uix.label", "kivy.uix.scrollview", "kivy.uix.textinput", "kivy.properties",
             "kivy.uix.widget", "kivy.utils"]:
    sys.modules[name] = Mod(name)

import feed as F  # noqa: E402
import main  # noqa: E402
import page_board  # noqa: E402,F401
from page_feed import Slot  # noqa: E402

ME, PEER, WATCH = "0x" + "91" * 20, "0x" + "2c" * 20, "0x" + "e7" * 20


def sample_feed(kind, params):
    f = F.Feed(types.SimpleNamespace(api_key="", source="test"), kind, params)
    f.latest, f.lo, f.complete, f.exact = 21904298, 21900000, False, False
    n = 0

    def rec(tx, idx, block, signer, to, meta, ph):
        f.records[(tx, idx)] = {"tx": tx, "block": block, "idx": idx, "ts": 1700000000 + block,
                                "signer": signer, "to": to, "submitter": signer, "ph": ph, "text": meta}
    board = params.get("board", T.BOARD)
    rec("0xa", 1, 100, PEER, board, "#market lamp oil for sale", bytes([1]) * 32)
    rec("0xa", 2, 100, PEER, board, "3 left at the east gate", bytes([2]) * 32)
    rec("0xa", 3, 100, PEER, board, "0.02 ETH each, bring a jar", bytes([3]) * 32)
    rec("0xb", 1, 103, ME, board, "@%s how much? #market" % F.code_of(bytes([1]) * 32), bytes([4]) * 32)
    rec("0xc", 1, 104, ME, ME, "buy lamp oil before 6", bytes([5]) * 32)
    rec("0xd", 1, 105, WATCH, WATCH, "call the printer after lunch", bytes([6]) * 32)
    rec("0xe", 1, 106, ME, PEER, "is the blue awning stall free?", bytes([7]) * 32)
    rec("0xf", 1, 107, PEER, ME, "@%s yes" % F.code_of(bytes([7]) * 32), bytes([8]) * 32)
    f.eff = {ME: 12, PEER: 31, WATCH: -3}
    return f


def test_everything():
    app = main.MsosApp()
    app.build()
    app.my = ME
    app.watch = [WATCH]
    app.chats = [PEER]
    app.ui["peer"] = PEER
    for page, kind in (("board", "board"), ("mind", "mind"), ("chat", "chat")):
        app.page = page
        mod = {"board": main.page_board, "mind": main.page_mind, "chat": main.page_chat}[page]
        pg = getattr(mod, {"board": "BoardPage", "mind": "MindPage", "chat": "ChatPage"}[page])(app, app.box)
        slot = Slot()
        slot.feed = sample_feed(kind, pg.params())
        app.slots[pg.skey()] = slot
        for sort in ("newest", "eff", "effmin", "replies"):
            app.ui["board_sort"] = sort
            app.ui["mind_sort"] = sort if sort in ("newest", "eff") else "newest"
            app.ui["tag"] = "#market" if sort == "effmin" else None
            app.box.clear_widgets()
            pg.build()
        app.ui["sel"] = pg.arrange(slot.feed.messages())[0]["id"] if pg.arrange(slot.feed.messages()) else None
        app.box.clear_widgets()
        pg.build()
        print("ok page", page, len(app.box.children), "widgets")
    app.render()
    app.addr_in.text, app.key_in.text = ME, "KEY"
    app.load()
    assert app.my == ME and app.es_key == "KEY" and not app.drawer_open
    app.addr_in.text = "bad"
    app.load()
    assert app.my == ME                       # a bad address is refused, the old one stays
    app.toggle_drawer()
    assert app.drawer_open
    app.toggle_drawer()
    app.exit_wallet()
    app.open_settings()
    app.close_all()
    app.open_compose()
    app.close_all()
    msg = F.group(sample_feed("board", {"board": T.BOARD}).records.values())[0]
    app.open_compose(dest=("board", T.BOARD), reply=msg)
    cs = app.overlays[-1]
    cs.lines[0] = "I need 4 and can pick up today, please keep them until six"
    cs.update_summary()
    print("ok compose; lines ->", cs.final_lines()[0])
    cs.set_dest(("mind", ME))
    cs.set_dest(("chat", PEER))
    app.close_all()
    app.add_board("Night Market", "0x" + "b0" * 20)
    app.add_watch(WATCH)
    app.add_tag("#help")
    app.remove_tag("#help")
    app.remove_board("0x" + "b0" * 20)
    app.set_sort("board_sort", "eff")
    app.tx_done({}, "0xhash", True, 5, "", "abc")
    print("ok app actions")


def test_rules():
    """The rules of this version: + on every screen, chats with 2+ addresses kept, Mind clean-up."""
    src = open(os.path.join(HERE, "..", "android", "main.py")).read()
    assert "fab.opacity = 0" not in src and "fab.disabled = True" not in src      # the + is never hidden
    OTHER = "0x" + "5d" * 20
    app = main.MsosApp()
    app.build()
    app.my, app.es_key = ME, "KEYKEEP"
    app.open_settings()                                   # a screen over the page: the + still works
    opened = []
    app.open_compose = lambda *a, **k: opened.append(1)
    app.fab_tap()
    assert opened == [1]
    del app.open_compose
    app.close_all()
    app.open_compose()
    cs = app.overlays[-1]
    n = len(cs.lines)
    app.fab_tap()                                         # on New message the + adds a line
    assert len(cs.lines) == n + 1
    app.close_all()
    # a chat of 2+ addresses
    app.add_chat(PEER)
    assert app.add_to_chat(PEER, OTHER) == "" and app.chats == [PEER + "," + OTHER]
    assert app.ui["peer"] == PEER + "," + OTHER
    assert app.add_to_chat(app.ui["peer"], ME)            # your own address is refused
    assert app.add_to_chat(app.ui["peer"], "0x12")        # not an address
    assert app.add_to_chat(app.ui["peer"], "0x" + "11" * 20) == "" and len(app.conv_peers(app.ui["peer"])) == 3
    assert app.add_to_chat(app.ui["peer"], "0x" + "22" * 20)      # a 4th other address: full
    assert app.conv_with(OTHER) == app.ui["peer"]
    app.page = "chat"
    pg = main.page_chat.ChatPage(app, app.box)
    f = sample_feed("chat", pg.params())
    f.records[("0xz", 1)] = {"tx": "0xz", "block": 120, "idx": 1, "ts": 1700000120, "signer": PEER, "to": OTHER,
                             "submitter": PEER, "ph": bytes([9]) * 32, "text": "between the two of them"}
    got = pg.arrange(f.messages())
    assert any(m["signer"] == PEER and m["to"] == OTHER for m in got)       # B to C is part of the chat
    assert not any(m["signer"] == WATCH for m in got)
    slot = Slot()
    slot.feed = f
    app.slots[pg.skey()] = slot
    app.box.clear_widgets()
    pg.build()
    app.open_compose(dest=("chat", app.ui["peer"]))
    cs = app.overlays[-1]
    assert cs.kind == "chat" and cs.conv[0] == PEER and cs.peer_text == PEER
    cs.pick_peer(OTHER)
    assert cs.destination() == ("chat", OTHER)
    cs.lines[0] = ""
    cs.update_summary()
    app.close_all()
    # Mind: exit keeps your own messages, forgets the watched addresses; Chat and the key stay
    app.page = "mind"
    app.watch = [WATCH]
    mp = main.page_mind.MindPage(app, app.box)
    mslot = Slot()
    mslot.feed = sample_feed("mind", mp.params())
    app.slots[mp.skey()] = mslot
    chats_before = list(app.chats)
    app.exit_wallet()
    assert app.watch == [] and app.es_key == "KEYKEEP" and app.chats == chats_before
    kept = [k for k in app.slots if k[0] == "mind"]
    assert len(kept) == 1
    recs = app.slots[kept[0]].feed.records.values()
    assert recs and all(r["signer"] == ME and r["to"] == ME for r in recs)
    assert set(app.slots[kept[0]].feed.eff) <= {ME}
    assert main.slot_key("mind", {"addrs": [ME]}) == kept[0]               # the next Mind load finds it
    app.add_watch(WATCH)
    app.on_stop()                                         # closing the app does the same
    assert app.watch == []
    import json
    with open(app.cfg_path) as fh:
        saved = json.load(fh)
    assert saved["watch"] == [] and saved["key"] == "KEYKEEP" and saved["chats"] == chats_before
    print("ok rules")


def test_send_flow_cards_hold_and_paste():
    """Result cards with the transaction link, the reload hold, Paste in Settings, pull to reload."""
    import time
    import tx
    import strings as S
    import util
    app = main.MsosApp()
    app.build()
    app.my, app.es_key = ME, ""
    app.add_chat(PEER)
    app.open_compose(dest=("mind", ME))
    cs = app.overlays[-1]
    cs.lines = ["a note to myself"]
    cs.items = tx.new_items(cs.lines)
    cs.items[0]["ph"] = cs.ph0
    cs.frm, cs.to, cs.send_kind = ME.lower(), ME.lower(), "mind"
    app.sending = True                                    # the wallet is signing
    app.slots[("x", "y")] = Slot()
    app.reload()                                          # a reload now would interrupt the signing: held
    assert ("x", "y") in app.slots
    tracked = []
    app.track = lambda e: tracked.append(e)
    h = "0x" + "ab" * 32
    cs.sent(h)
    assert app.sending is False and app.hold_until > time.time() + 55          # a minute of calm
    assert tracked and tracked[0]["hash"] == h and tracked[0]["state"] == "wait"
    assert cs.entry is not None and cs.go.text == S.CMP_DONE and app.pending
    opened = []
    util_open = util.open_url
    util.open_url = lambda u: opened.append(u) or True
    app.open_tx(h)
    assert opened == ["https://etherscan.io/tx/" + h]
    util.open_url = util_open
    app.reload(auto=True)                                 # an automatic reload waits for the hold
    assert ("x", "y") in app.slots
    app.hold_until = 0
    app.reload()                                          # a manual pull after the hold works
    assert ("x", "y") not in app.slots

    class Chain:                                          # the receipt: recorded in block 123
        def receipt(self, tx_hash):
            return {"status": "0x1", "blockNumber": hex(123)}
    e = cs.entry
    assert app._check_once(Chain(), e) and e["state"] == "ok" and e["block"] == 123
    app.on_entry(e)
    assert cs.entry["state"] == "ok"
    app.close_all()
    app.page = "mind"
    app.render()                                          # the card of the sent message is on the Mind page
    assert any(w.__class__.__name__ == "Panel" for w in app.box.children)

    class Bad:                                            # reverted on the ledger
        def receipt(self, tx_hash):
            return {"status": "0x0", "blockNumber": hex(5)}

        def failure_reason(self, tx_hash, rc):
            return "InvalidSignature"
    e2 = main.outbox.new_entry("mind", ME, ME, ["x"], "abc", "0x" + "cd" * 32)
    app.outbox.add(e2)
    assert app._check_once(Bad(), e2) and e2["state"] == "fail" and "signature" in e2["err"]["body"]
    app.outbox.dismiss(e2["id"])
    # pulling down on every screen: Settings and New message have the same pull as the pages
    app.open_settings()
    st = app.overlays[-1]
    assert st.status_text == ""
    # Paste in Settings: the clipboard text is added at once, no Add / Save button
    util.paste_text = lambda: "kg6"
    st.paste_and(st.tag_in, st.add_tag)
    assert "@kg6" in app.tags
    util.paste_text = lambda: "My shop " + "0x" + "ab" * 20
    st.paste_and(st.board_in, st.add_board)
    assert app.boards[-1]["name"] == "My shop"
    util.paste_text = lambda: ""
    st.paste_and(st.watch_in, st.add_watch)
    assert st.status_text == S.MSG_CLIPBOARD_EMPTY_DOT
    app.close_all()
    # welcome screen texts as on the dSOS start screen
    assert S.WELCOME_SLOGAN == "Decentralised\nTrustless. Yours"
    assert S.WELCOME_RATE == "Everything is public. Nothing is private."
    import os
    assert os.path.exists(os.path.join(HERE, "..", "android", "wordmark.png"))
    # follow a reply code from a message: saved as a tag and selected
    app.follow_code("KG6")
    assert app.ui["tag"] == "@kg6"
    print("ok send flow, hold, paste, welcome")


def test_tags_on_mind_and_chat_and_colours():
    import json
    import strings as S
    from design import CHAT_COLORS, ME_GREEN
    OTHER = "0x" + "5d" * 20
    app = main.MsosApp()
    app.build()
    app.my, app.es_key = ME, ""
    app.tags = ["#market", "@abc"]
    app.ui["tag"] = app.ui["mind_tag"] = app.ui["chat_tag"] = None      # (the stub keeps one cfg file)
    # Mind: All tags / a saved tag
    app.page = "mind"
    mp = main.page_mind.MindPage(app, app.box)
    f = sample_feed("mind", mp.params())
    f.records[("0xm1", 1)] = {"tx": "0xm1", "block": 90, "idx": 1, "ts": 1700000090, "signer": ME, "to": ME,
                              "submitter": ME, "ph": bytes([40]) * 32, "text": "plan #market stall"}
    msgs = f.messages()
    assert len(mp.arrange(msgs)) > 1                      # no tag selected: everything
    app.set_tag("#market", "mind_tag")
    got = mp.arrange(msgs)
    assert [m["tx"] for m in got] == ["0xm1"]
    assert app.ui["tag"] is None and app.ui["mind_tag"] == "#market"          # Board keeps its own selection
    chips = mp.chips()
    assert len(chips) == 3                                # who, tags, scope/sort
    app.remove_tag("#market")
    assert app.ui["mind_tag"] is None
    with open(app.cfg_path) as fh:
        saved = json.load(fh)
    assert "mind_tag" in saved and "chat_tag" in saved
    # Chat: one colour per sender, code box, no arrow glyph, tag filter
    app.add_chat(PEER)
    assert app.add_to_chat(PEER, OTHER) == ""
    app.page = "chat"
    cp = main.page_chat.ChatPage(app, app.box)
    cols = cp.colors()
    assert cols[ME.lower()] == ME_GREEN and cols[PEER] == CHAT_COLORS[0] and cols[OTHER] == CHAT_COLORS[1]
    assert "\u2192" not in S.CHAT_ARROW and S.CHAT_ARROW.format(a="A", b="B") == "A to B"
    ch = f2 = sample_feed("chat", cp.params())
    msgs = ch.messages()
    code = F.code_of(bytes([7]) * 32)
    app.tags = ["@" + code]
    app.set_tag("@" + code, "chat_tag")
    got = cp.arrange(msgs)
    assert got and all(m["code"] == code or m["reply_to"] == code for m in got)
    assert len(cp.chips()) == 5                           # card, chats, legend, tags, filters
    # Chat list = the Board/Mind card (MsgCard), avatar coloured by sender, newest first
    app.tags = []
    app.set_tag(None, "chat_tag")
    app.box.clear_widgets()
    slot = type("S", (), {"busy": False})()
    cp.show(ch, slot)
    cards = [w for w in app.box.children if type(w).__name__ == "MsgCard"]
    assert cards and not any(type(w).__name__ in ("ChatItem", "Bubble") for w in app.box.children)
    # "Replies to" thread button on every page, into that page's own tag slot
    for k, slot_key in (("board", "tag"), ("mind", "mind_tag"), ("chat", "chat_tag")):
        app.ui[slot_key] = None
        app.follow_code("abc", slot_key)
        assert app.ui[slot_key] == "@abc", k
    cc = cp.conv_card()
    def walk(w):
        yield w
        for c in w.children:
            yield from walk(c)
    order = [w.text for w in walk(cc) if getattr(w, "text", "") in (S.CHAT_BTN_ADD, S.CHAT_BTN_NEW)]
    texts = order if order[0] == S.CHAT_BTN_ADD else order[::-1]      # (stub may list children either way)
    assert texts == [S.CHAT_BTN_ADD, S.CHAT_BTN_NEW], texts
    # fold header: open = chips shown, closed = only the header; remembered per page
    def count_after(pg, fold):
        app.ui["fold_" + pg.kind] = fold
        app.box.clear_widgets()
        pg.box = app.box
        import ui as U
        app.box.add_widget(U.FoldHeader(pg.fold_title(), pg.fold_summary(), not pg.folded(), pg.toggle_fold))
        if not pg.folded():
            for w in pg.chips():
                app.box.add_widget(w)
        return len(app.box.children)
    for pg in (cp, main.page_mind.MindPage(app, app.box), main.page_board.BoardPage(app, app.box)):
        assert count_after(pg, False) > 1 and count_after(pg, True) == 1, pg.kind
        assert pg.fold_title()
    pg.toggle_fold()
    assert app.ui["fold_board"] is False
    print("ok tags on mind/chat, colours, chat cards", len(cards))


if __name__ == "__main__":
    test_everything()
    test_rules()
    test_send_flow_cards_hold_and_paste()
    test_tags_on_mind_and_chat_and_colours()
