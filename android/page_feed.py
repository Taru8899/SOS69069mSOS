"""Base of the Board, Mind and Chat pages: one feed per view, loaded in a worker thread, shown
10 messages at a time with a Load more button (same pattern as dSOS' Activity page)."""
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import escape_markup

import core
import feed as F
import strings as S
import util
from theme import BLACK, BLUE, ETHERSCAN_TX, PAGE_SIZE, WHITE, short
from ui import Wrap, pill_button
from widgets import Card, Choice, Panel, label


class Slot:
    """State of one view: its feed, a busy flag and the last error."""

    def __init__(self):
        self.feed = None
        self.busy = False
        self.error = ""


class FeedPage:
    kind = ""                     # board / mind / chat

    def __init__(self, app, box):
        self.app, self.box, self.ui = app, box, app.ui
        self.msg = None

    # ---- to be provided by the page
    def params(self):
        """Parameters of the feed, or None when the view cannot be loaded yet."""
        raise NotImplementedError

    def not_ready(self):
        return ""

    def chips(self):
        """List of widgets (chip rows) above the messages."""
        return []

    def show(self, feed, slot):
        """Add the messages (and the Load more button) for a loaded feed."""
        raise NotImplementedError

    def reply_dest(self):
        """(kind, address) a reply from this page is sent to."""
        raise NotImplementedError

    # ---- state
    def skey(self):
        return (self.kind, repr(sorted(self.params().items())))

    def slot(self):
        k = self.skey()
        s = self.app.slots.get(k)
        if s is None:
            s = self.app.slots[k] = Slot()
        return s

    def start(self, older=False):
        slot = self.slot()
        if slot.busy:
            return
        slot.busy = True
        slot.error = ""
        key, kind, params = self.app.es_key, self.kind, self.params()
        skey = self.skey()
        app = self.app

        def work():
            try:
                if slot.feed is None or not older:
                    f = F.Feed(core.Chain(key), kind, params)
                    f.refresh()
                    slot.feed = f
                else:
                    slot.feed.older()
                slot.feed.fill_eff()
            except Exception as e:  # noqa: BLE001
                slot.error = str(e) or type(e).__name__
            slot.busy = False
            Clock.schedule_once(lambda dt: self.done(slot, skey))
        threading.Thread(target=work, daemon=True).start()

    def done(self, slot, skey):
        app = self.app
        if slot.feed is not None:
            app.set_block(slot.feed.latest, slot.feed.chain.source)
        if app.slots.get(skey) is slot and app.page == self.kind:
            app.render()

    # ---- layout
    def build(self):
        b = self.box
        why = self.not_ready()
        for w in self.chips():
            b.add_widget(w)
        if why:
            b.add_widget(Card(why))
            return
        slot = self.slot()
        if slot.feed is None and not slot.busy and not slot.error:
            self.start()
        if slot.busy and slot.feed is None:
            b.add_widget(Card(S.M_LOADING))
            return
        if slot.error and slot.feed is None:
            b.add_widget(Card(S.M_ERROR.format(error=escape_markup(slot.error))))
            retry = Choice(base=BLUE, fg=WHITE, text=S.BTN_RETRY, bold=True, size_hint_y=None,
                           height=dp(48))
            retry.bind(on_release=lambda *_: self.retry())
            b.add_widget(retry)
            return
        self.notes(slot.feed, slot)
        self.show(slot.feed, slot)

    def notes(self, feed, slot):
        b = self.box
        if not feed.exact:
            b.add_widget(Card(S.M_NO_KEY))
        if slot.error:
            b.add_widget(Card(S.M_ERROR.format(error=escape_markup(slot.error))))
        if feed.note:
            b.add_widget(Card(escape_markup(feed.note)))
        if feed.truncated:
            b.add_widget(Card(S.M_TRUNCATED))

    def footer_note(self, feed):
        return label(S.M_COMPLETE if feed.complete else S.M_WINDOW.format(lo=feed.lo or 0, hi=feed.latest),
                     size_hint_y=None, height=dp(20), font_size="12sp", halign="center")

    # ---- paging
    def shown(self):
        return self.ui["shown"].get(self.skey(), PAGE_SIZE)

    def more(self, total):
        """Show 10 more; when everything loaded is already shown, load an older window first."""
        k = self.skey()
        self.ui["shown"][k] = self.shown() + PAGE_SIZE
        slot = self.slot()
        if total < self.ui["shown"][k] and slot.feed is not None and not slot.feed.complete:
            self.start(older=True)
        else:
            self.app.render()

    def more_button(self, total, feed, slot, older_label=False):
        """The Load more / Load older pill, or None when there is nothing more."""
        if total <= self.shown() and feed.complete:
            return None
        text = S.M_BUSY if slot.busy else (S.M_LOAD_OLDER if older_label else S.M_LOAD_MORE).format(n=PAGE_SIZE)
        b = pill_button(text, lambda: self.more(total), base=BLACK, fg=WHITE)
        b.disabled = slot.busy
        return b

    # ---- rows
    def select(self, m):
        self.ui["sel"] = None if self.ui.get("sel") == m["id"] else m["id"]
        self.app.render()

    def reply(self, m):
        kind, addr = self.reply_dest()
        self.app.open_compose(dest=(kind, addr), reply=m)

    def detail(self, m):
        p = Panel(orientation="vertical", size_hint_y=None, height=dp(228), spacing=dp(6))
        p.add_widget(Wrap(text="[size=12sp]%s[/size]\n[b]%s[/b]" % (S.M_DETAIL_TX, short(m["tx"])),
                          font_size="14sp"))
        p.add_widget(label("[size=12sp]%s[/size] %s   [size=12sp]%s[/size] %s" % (
            S.M_DETAIL_FROM, short(m["signer"]), S.M_DETAIL_TO, short(m["to"])),
            size_hint_y=None, height=dp(24), font_size="13sp"))
        self.msg = label("", size_hint_y=None, height=dp(20), font_size="12sp")
        p.add_widget(self.msg)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cp = Choice(base=BLUE, fg=WHITE, text=S.BTN_COPY, bold=True)
        cp.bind(on_release=lambda *_: self.copy(m["tx"]))
        op = Choice(base=BLUE, fg=WHITE, text=S.M_BTN_ETHERSCAN, bold=True)
        op.bind(on_release=lambda *_: self.open(ETHERSCAN_TX + m["tx"]))
        btns.add_widget(cp)
        btns.add_widget(op)
        p.add_widget(btns)
        rp = Choice(base=BLACK, fg=WHITE, text="%s %s" % (S.M_BTN_REPLY, m["code"]), bold=True,
                    size_hint_y=None, height=dp(44))
        rp.bind(on_release=lambda *_: self.reply(m))
        p.add_widget(rp)
        return p

    def copy(self, text):
        self.msg.text = S.M_COPIED if util.copy_text(text) else S.TX_COPY_FAILED

    def open(self, url):
        if not util.open_url(url):
            self.msg.text = S.SETTINGS_OPEN_FAILED

    def retry(self):
        self.slot().error = ""
        self.app.render()

    # ---- helpers for pages
    def sub(self, m, extras=()):
        """The small grey line under a message."""
        from ui import eff_markup, who
        parts = [who(m["signer"], self.app.my), eff_markup(m["eff"])]
        if len(m["lines"]) > 1:
            parts.append(S.M_LINES.format(n=len(m["lines"])))
        parts.extend(extras)
        if m["n_replies"]:
            parts.append(S.M_REPLIES.format(n=m["n_replies"]))
        return " · ".join(parts)
