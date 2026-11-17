"""Base of the Board, Mind and Chat pages: one feed per view, loaded in a worker thread, shown
10 messages at a time with a Load more button (same pattern as dSOS' Activity page)."""
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import escape_markup

import core
import feed as F
import store
import strings as S
from design import FONT_LABEL, FONT_NOTE, FONT_SMALL, GAP, GAP_SMALL, H_BUTTON, H_DETAIL, H_FIELD, H_LINE, H_NOTE
import util
from theme import BLACK, BLUE, ETHERSCAN_TX, PAGE_SIZE, WHITE, short
from ui import Wrap, chip, chip_row, pill_button, send_card
from widgets import Card, Choice, Panel, label


def slot_key(kind, params):
    return (kind, repr(sorted(params.items())))


class Slot:
    """State of one view: its feed, a busy flag and the last error."""

    def __init__(self):
        self.feed = None
        self.busy = False
        self.error = ""
        self.synced = False       # the network has been asked for news since this slot was made


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

    def tag_row(self, key):
        """All tags + the saved tags + Save tag: the same row on Board, Mind and Chat. `key` is the
        place where this page keeps its selected tag (tag, mind_tag, chat_tag)."""
        app, ui = self.app, self.ui
        row = [chip(S.BOARD_ALL_TAGS, lambda: app.set_tag(None, key), selected=not ui.get(key))]
        for t in app.tags:
            row.append(chip(t, lambda t=t: app.set_tag(t, key), selected=ui.get(key) == t))
        row.append(chip(S.BOARD_SAVE_TAG, app.open_settings, kind="outline"))
        return chip_row(row)

    def card_to(self):
        """Address whose sent-message cards this page shows (None = all of its kind)."""
        return None

    def cache_key(self):
        """What the saved-messages file of this view is named after, or None (nothing is saved)."""
        return None

    def make_feed(self):
        key = self.cache_key()
        path = store.file_for(self.app.store_dir, self.kind, key) if key else None
        f = F.Feed(core.Chain(self.app.es_key), self.kind, self.params(), path=path)
        f.counter = self.counter
        return f

    def counter(self, msgs):
        """How many of the loaded messages count towards the 4 a first load must find."""
        return len(msgs)

    # ---- state
    def skey(self):
        return slot_key(self.kind, self.params())

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
        skey = self.skey()

        def work():
            try:
                if slot.feed is None:
                    f = self.make_feed()
                    f.seed()                  # the saved messages first, then only what is new
                    slot.feed = f
                if older:
                    slot.feed.older()
                else:
                    slot.feed.refresh()
                    slot.synced = True
                slot.feed.fill_eff()
            except Exception as e:  # noqa: BLE001
                slot.error = str(e) or type(e).__name__
            slot.busy = False
            Clock.schedule_once(lambda dt: self.done(slot, skey))
        threading.Thread(target=work, daemon=True).start()

    def done(self, slot, skey):
        app = self.app
        if slot.feed is not None and slot.feed.latest and slot.synced:
            app.set_block(slot.feed.latest, slot.feed.chain.source)
        if app.slots.get(skey) is slot and app.page == self.kind:
            app.render()

    # ---- layout
    def build(self):
        b = self.box
        why = self.not_ready()
        for w in self.chips():
            b.add_widget(w)
        for e in self.app.outbox.for_page(self.kind, self.card_to()):      # sent messages: link, result, errors
            b.add_widget(send_card(e, self.app.open_tx, self.app.copy_hash, self.app.dismiss_entry))
        if why:
            b.add_widget(Card(why))
            return
        slot = self.slot()
        if slot.feed is None and not slot.error:
            f = self.make_feed()              # saved messages show at once, no network needed
            if f.seed():
                slot.feed = f
        if not slot.synced and not slot.busy and not slot.error:
            self.start()
        if slot.busy and slot.feed is None:
            b.add_widget(Card(S.M_LOADING))
            return
        if slot.error and slot.feed is None:
            b.add_widget(Card(S.M_ERROR.format(error=escape_markup(slot.error))))
            retry = Choice(base=BLUE, fg=WHITE, text=S.BTN_RETRY, bold=True, size_hint_y=None,
                           height=dp(H_FIELD))
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
            b.add_widget(Card((S.M_OFFLINE if feed.hi else S.M_ERROR).format(
                block=feed.hi, error=escape_markup(slot.error))))
        elif slot.busy and not slot.synced:
            b.add_widget(Card(S.M_CHECKING))
        if feed.note:
            b.add_widget(Card(escape_markup(feed.note)))
        if feed.truncated:
            b.add_widget(Card(S.M_TRUNCATED))

    def footer_note(self, feed):
        return label(S.M_COMPLETE if feed.complete else S.M_WINDOW.format(lo=feed.lo or 0, hi=feed.latest),
                     size_hint_y=None, height=dp(H_NOTE), font_size=FONT_NOTE, halign="center")

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
        p = Panel(orientation="vertical", size_hint_y=None, height=dp(H_DETAIL), spacing=dp(GAP_SMALL))
        p.add_widget(Wrap(text="[size=12sp]%s[/size]\n[b]%s[/b]" % (S.M_DETAIL_TX, short(m["tx"])),
                          font_size=FONT_LABEL))
        p.add_widget(label("[size=12sp]%s[/size] %s   [size=12sp]%s[/size] %s" % (
            S.M_DETAIL_FROM, short(m["signer"]), S.M_DETAIL_TO, short(m["to"])),
            size_hint_y=None, height=dp(H_LINE), font_size=FONT_SMALL))
        self.msg = label("", size_hint_y=None, height=dp(H_NOTE), font_size=FONT_NOTE)
        p.add_widget(self.msg)
        btns = BoxLayout(size_hint_y=None, height=dp(H_BUTTON), spacing=dp(GAP))
        cp = Choice(base=BLUE, fg=WHITE, text=S.BTN_COPY, bold=True)
        cp.bind(on_release=lambda *_: self.copy(m["tx"]))
        op = Choice(base=BLUE, fg=WHITE, text=S.M_BTN_ETHERSCAN, bold=True)
        op.bind(on_release=lambda *_: self.open(ETHERSCAN_TX + m["tx"]))
        btns.add_widget(cp)
        btns.add_widget(op)
        p.add_widget(btns)
        row = BoxLayout(size_hint_y=None, height=dp(H_BUTTON), spacing=dp(GAP))
        rp = Choice(base=BLACK, fg=WHITE, text="%s %s" % (S.M_BTN_REPLY, m["code"]), bold=True)
        rp.bind(on_release=lambda *_: self.reply(m))
        row.add_widget(rp)
        key = {"board": "tag", "mind": "mind_tag", "chat": "chat_tag"}.get(self.kind, "tag")
        th = Choice(base=BLUE, fg=WHITE, text=S.M_BTN_THREAD.format(code=m["code"]), bold=True)   # every reply as one tag
        th.bind(on_release=lambda *_: self.app.follow_code(m["code"], key))
        row.add_widget(th)
        p.add_widget(row)
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
        return S.SEP.join(parts)
