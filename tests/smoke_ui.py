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


if __name__ == "__main__":
    test_everything()
