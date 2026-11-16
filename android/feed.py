"""Messages on the SOS69069 ledger: read, decode, group, sort. Nothing here touches the UI; all
functions that use the network block, so call them from a worker thread.

A message is what the ledger calls records: every `SignatureRecorded` event has
    signer (topic 1), intendedTo (topic 2), submitter (topic 3),
    data = payloadHash, signature, timestamp, metadata   (metadata = the text, at most 64 bytes)

mSOS reads the events like this
    Board  = records sent TO a board address            topics [T, any, board]
    Mind   = records a person signed TO THEMSELVES      topics [T, a, a]  (one query per address)
    Chat   = A to B and B to A                           topics [T, A, B] and [T, B, A]

Records of ONE transaction with the same signer and recipient are the LINES of one message
(ordered by log index). The reply code of a message is derived from the payloadHash of its first
line (3 characters, a-z 0-9), so it costs no bytes. A reply writes "@code" at the start of its first
line. Tags are words that start with "#".

Time is block time: the event carries block.timestamp of the block that included the record.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

import core
import store
import strings as S
from activity import RPC_WINDOW, T_RECORDED, WINDOW_BLOCKS, ago, pad_topic
from core import LEDGER

B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
REPLY_RE = re.compile(r"^\s*@([0-9a-z]{3})(?![0-9a-z])", re.I)
TAG_RE = re.compile(r"(?<![\w#])#([\w-]{1,30})")
MIN_FIRST = 4            # a first load keeps looking further back until it has this many messages
SEARCH_SECONDS = 40      # ... but never longer than this (public nodes are slow; then Load more)
MAX_SPAN = 2_000_000     # largest Etherscan window (blocks) after several empty ones
FORWARD_BOARD_ES = 4 * WINDOW_BLOCKS   # newer blocks fetched in one go for a saved Board (28 days)
FORWARD_RPC = 3 * RPC_WINDOW           # ... without a key

__all__ = ["normalize_tag", "decode_record", "group", "code_of", "reply_code", "tags_of", "Feed", "queries",
           "sort_newest", "sort_eff", "sort_replies", "with_tag", "eff_at_least", "ago"]


# ------------------------------------------------------------------ small pure helpers
def code_of(payload_hash):
    """3-character reply code from the first record's payloadHash (uniform: low bits)."""
    n = int.from_bytes(bytes(payload_hash), "big") % (36 ** 3)
    return B36[n // 1296] + B36[(n // 36) % 36] + B36[n % 36]


def reply_code(text):
    """The code a message answers ('' when it is not a reply). Looks at the start of line 1."""
    m = REPLY_RE.match(text or "")
    return m.group(1).lower() if m else ""


def tags_of(text):
    seen, out = set(), []
    for t in TAG_RE.findall((text or "").lower()):
        if t not in seen:
            seen.add(t)
            out.append("#" + t)
    return out


def decode_record(log):
    """Normalised log (activity.norm_log) of SignatureRecorded -> record dict, or None."""
    t = log.get("topics") or []
    if len(t) < 4 or t[0] != T_RECORDED:
        return None
    try:
        raw = bytes.fromhex((log.get("data") or "0x")[2:])
        if len(raw) < 128:
            return None
        ph = raw[0:32]
        ts = int.from_bytes(raw[64:96], "big")
        off = int.from_bytes(raw[96:128], "big")
        n = int.from_bytes(raw[off:off + 32], "big")
        text = raw[off + 32:off + 32 + n].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    return {"tx": log["tx"], "block": log["block"], "idx": log["idx"], "ts": ts or log.get("ts", 0),
            "signer": "0x" + t[1][-40:], "to": "0x" + t[2][-40:], "submitter": "0x" + t[3][-40:],
            "ph": ph, "text": text}


def group(records):
    """Records -> messages (dicts), newest first. Same tx + signer + recipient = one message."""
    groups = {}
    for r in records:
        groups.setdefault((r["tx"], r["signer"], r["to"]), []).append(r)
    msgs = []
    for (tx, signer, to), rs in groups.items():
        rs.sort(key=lambda r: r["idx"])
        first = rs[0]
        lines = [r["text"].strip() for r in rs if r["text"].strip()] or ["\u2013"]
        text = "\n".join(lines)
        msgs.append({
            "id": "%s:%s:%s" % (tx, signer, to), "tx": tx, "block": first["block"],
            "idx": first["idx"], "ts": max(r["ts"] for r in rs), "signer": signer, "to": to,
            "lines": lines, "text": text, "code": code_of(first["ph"]),
            "reply_to": reply_code(lines[0]), "tags": tags_of(text), "eff": None,
            "n_replies": 0,
        })
    count_replies(msgs)
    msgs.sort(key=lambda m: (m["block"], m["idx"]), reverse=True)
    return msgs


def count_replies(msgs):
    """Fill n_replies: how many of these messages answer each code."""
    n = {}
    for m in msgs:
        if m["reply_to"]:
            n[m["reply_to"]] = n.get(m["reply_to"], 0) + 1
    for m in msgs:
        m["n_replies"] = n.get(m["code"], 0)


def find_target(msgs, code, before=None):
    """The message a reply code points to: newest with that code (older than `before`)."""
    best = None
    for m in msgs:
        if m["code"] != code:
            continue
        if before is not None and (m["block"], m["idx"]) >= before:
            continue
        if best is None or (m["block"], m["idx"]) > (best["block"], best["idx"]):
            best = m
    return best


# ------------------------------------------------------------------ sort / filter
def _key(m):
    return (m["block"], m["idx"])


def sort_newest(msgs):
    return sorted(msgs, key=_key, reverse=True)


def sort_eff(msgs):
    return sorted(msgs, key=lambda m: ((m["eff"] if m["eff"] is not None else -10 ** 18),) + _key(m),
                  reverse=True)


def sort_replies(msgs):
    return sorted(msgs, key=lambda m: (m["n_replies"],) + _key(m), reverse=True)


CODE_RE = re.compile(r"^[0-9a-z]{3}$")


def normalize_tag(text):
    """What a person typed or pasted -> a saved tag, or ''.
        kg6 or @kg6   -> '@kg6'  a reply code: the replies to that message
        #sale or sale -> '#sale' a hash tag (a word of any other length; write # to force a hash tag)"""
    t = (text or "").strip().lower().replace(" ", "-")
    if t.startswith("@"):
        c = t[1:]
        return "@" + c if CODE_RE.match(c) else ""
    if not t.startswith("#") and CODE_RE.match(t):
        return "@" + t
    t = re.sub(r"[^\w-]", "", t.lstrip("#"))[:30]
    return "#" + t if t else ""


def with_tag(msgs, tag):
    """Messages that carry a #tag, or - for an @code tag - the message with that code and every
    reply to it (replies start with @code), so a whole thread is one filter."""
    if not tag:
        return list(msgs)
    if tag.startswith("@"):
        c = tag[1:].lower()
        return [m for m in msgs if m["reply_to"] == c or m["code"] == c]
    t = tag.lower() if tag.startswith("#") else "#" + tag.lower()
    return [m for m in msgs if t in m["tags"]]


def eff_at_least(msgs, n):
    return [m for m in msgs if m["eff"] is not None and m["eff"] >= n]


# ------------------------------------------------------------------ queries
def chat_members(params):
    """Lower-case addresses of a conversation: me first, then the others (no duplicates)."""
    others = params.get("peers") or ([params["peer"]] if params.get("peer") else [])
    out = []
    for a in [params["me"]] + list(others):
        a = (a or "").lower()
        if a and a not in out:
            out.append(a)
    return out


def queries(kind, params):
    """List of topic lists (all for the ledger address) that make up a view."""
    if kind == "board":
        return [[T_RECORDED, None, pad_topic(params["board"])]]
    if kind == "mind":
        return [[T_RECORDED, pad_topic(a), pad_topic(a)] for a in params["addrs"]]
    if kind == "chat":
        # every ordered pair of the conversation: me and each other address, and the others among themselves
        members = chat_members(params)
        return [[T_RECORDED, pad_topic(a), pad_topic(b)] for a in members for b in members if a != b]
    raise ValueError(kind)


# ------------------------------------------------------------------ the feed
class Feed:
    """Logs of one view (a board, a mind, a chat), extended step by step into the past."""

    def __init__(self, chain, kind, params, path=None):
        self.chain, self.kind, self.params = chain, kind, params
        self.path = path              # file of saved messages (None = nothing is saved)
        self.hi = 0                   # newest block searched
        self.seeded = False           # records came from the saved file (or an earlier refresh)
        self.records = {}
        self.latest = 0
        self.lo = None
        self.complete = False
        self.truncated = False
        self.use_es = bool(chain.api_key)
        self.exact = self.use_es
        self.note = ""
        self.eff = {}                 # address -> effective score (int) or None when unknown
        self.span = WINDOW_BLOCKS     # Etherscan Board window; doubles after an empty one
        self.counter = None           # optional: records -> number of messages that count for MIN_FIRST

    # -- fetching
    def _add(self, logs):
        for lg in logs:
            r = decode_record(lg)
            if r:
                self.records[(r["tx"], r["idx"])] = r

    def _fetch_es(self, lo, hi):
        for topics in queries(self.kind, self.params):
            logs, trunc = self.chain.es_logs(LEDGER, topics, lo, hi)
            self._add(logs)
            self.truncated = self.truncated or trunc

    def _fetch_rpc(self, lo, hi):
        for topics in queries(self.kind, self.params):
            self._add(self.chain.rpc_logs(LEDGER, topics, lo, hi))

    def _load(self, hi):
        """Fetch the next piece of history ending at block `hi`; returns its first block.
        Etherscan (key): Board = 7 days per step, Mind and Chat = the whole history at once.
        Public nodes: about 2 days per step."""
        if self.use_es:
            lo = max(0, hi - self.span + 1) if self.kind == "board" else 0
            try:
                before = len(self.records)
                self._fetch_es(lo, hi)
                if self.kind == "board":
                    # nothing in this window: look twice as far next time; found something: back to 7 days
                    self.span = min(self.span * 2, MAX_SPAN) if len(self.records) == before else WINDOW_BLOCKS
                return lo
            except Exception as e:  # noqa: BLE001
                self.note = S.M_ES_FAILED.format(error=str(e) or type(e).__name__)
                self.use_es = False
                self.exact = False
        lo = max(0, hi - RPC_WINDOW + 1)
        self._fetch_rpc(lo, hi)
        return lo

    # -- saved messages
    def seed(self):
        """Fill the feed from the saved file, without any network call. True when something was loaded."""
        d = store.load(self.path) if self.path else None
        if not d:
            return False
        self.records = {(r["tx"], r["idx"]): r for r in d["records"]}
        self.lo, self.hi, self.latest = d["lo"], d["hi"], d["hi"]
        self.complete = self.lo == 0
        self.seeded = True
        return True

    def save(self):
        if not self.path or self.lo is None or not self.hi:
            return
        kept, new_lo = store.prune(self.records.values())
        if new_lo is not None:
            self.records = {(r["tx"], r["idx"]): r for r in kept}
            self.lo = max(self.lo, new_lo)
            self.complete = self.lo == 0
        try:
            store.save(self.path, self.lo, self.hi, kept)
        except Exception:  # noqa: BLE001   a full disk must never break reading
            pass

    def _fetch(self, lo, hi):
        """Fetch lo..hi (Etherscan when there is a key, else the public node)."""
        if self.use_es:
            try:
                self._fetch_es(lo, hi)
                return
            except Exception as e:  # noqa: BLE001
                self.note = S.M_ES_FAILED.format(error=str(e) or type(e).__name__)
                self.use_es = False
                self.exact = False
        self._fetch_rpc(lo, hi)

    def _forward(self):
        """Saved messages: read only the blocks after the saved range (and the last REORG blocks again)."""
        start = max(self.lo, self.hi - store.REORG + 1)
        limit = None if (self.use_es and self.kind != "board") else (FORWARD_BOARD_ES if self.use_es else FORWARD_RPC)
        new_lo = self.lo
        if limit and self.latest - start + 1 > limit:
            # too long since the last visit: search the newest part only; older() fills the gap later
            start = self.latest - (WINDOW_BLOCKS if self.use_es else RPC_WINDOW) + 1
            new_lo = start
        self.records = {k: r for k, r in self.records.items() if r["block"] < start}
        self._fetch(start, self.latest)
        self.lo, self.hi = new_lo, self.latest

    def refresh(self):
        self.truncated = False
        self.note = ""
        self.latest = self.chain.block()
        self.use_es = bool(self.chain.api_key)
        self.exact = self.use_es
        self.span = WINDOW_BLOCKS
        if self.seeded and self.lo is not None:
            self._forward()
        else:
            self.records.clear()
            self.lo = self._load(self.latest)
            self.hi = self.latest
        self.seeded = True
        self.complete = self.lo == 0
        t0 = time.time()
        # always try to have MIN_FIRST messages: go further back until found, the start of the
        # ledger is reached, or the time budget is used up
        while not self.complete and self.count() < MIN_FIRST and time.time() - t0 < SEARCH_SECONDS:
            self.older()
        self.save()

    def count(self):
        msgs = self.messages()
        return self.counter(msgs) if self.counter else len(msgs)

    def older(self):
        if self.complete or self.lo is None:
            return
        self.lo = self._load(self.lo - 1)
        self.complete = self.lo == 0
        self.save()

    # -- result
    def messages(self):
        msgs = group(self.records.values())
        for m in msgs:
            m["eff"] = self.eff.get(m["signer"])
        return msgs

    def fill_eff(self, msgs=None):
        """effectiveOf(sender) for every sender not known yet (trust - push, read live)."""
        need = sorted({m["signer"] for m in (msgs if msgs is not None else self.messages())
                       if m["signer"] not in self.eff})
        if not need:
            return

        def one(a):
            try:
                return core.s(self.chain.call(LEDGER, "effectiveOf(address)", [a])[0])
            except Exception:  # noqa: BLE001
                return None
        with ThreadPoolExecutor(max_workers=6) as ex:
            for a, v in zip(need, ex.map(one, need)):
                self.eff[a] = v


def when(ts, now=None):
    """'2m ago' style text of a block timestamp."""
    return ago(ts, now) if ts else ""
