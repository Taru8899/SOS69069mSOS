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
import strings as S
from activity import RPC_WINDOW, T_RECORDED, WINDOW_BLOCKS, ago, pad_topic
from core import LEDGER

B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
REPLY_RE = re.compile(r"^\s*@([0-9a-z]{3})(?![0-9a-z])", re.I)
TAG_RE = re.compile(r"(?<![\w#])#([\w-]{1,30})")
FIRST_PAGE = 10          # try to have at least this many messages after the first load
MAX_EXTRA_STEPS = 3      # extra older windows fetched at start while the first page is not full

__all__ = ["decode_record", "group", "code_of", "reply_code", "tags_of", "Feed", "queries",
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
        lines = [r["text"] for r in rs]
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


def with_tag(msgs, tag):
    if not tag:
        return list(msgs)
    t = tag.lower() if tag.startswith("#") else "#" + tag.lower()
    return [m for m in msgs if t in m["tags"]]


def eff_at_least(msgs, n):
    return [m for m in msgs if m["eff"] is not None and m["eff"] >= n]


# ------------------------------------------------------------------ queries
def queries(kind, params):
    """List of topic lists (all for the ledger address) that make up a view."""
    if kind == "board":
        return [[T_RECORDED, None, pad_topic(params["board"])]]
    if kind == "mind":
        return [[T_RECORDED, pad_topic(a), pad_topic(a)] for a in params["addrs"]]
    if kind == "chat":
        a, b = pad_topic(params["me"]), pad_topic(params["peer"])
        return [[T_RECORDED, a, b], [T_RECORDED, b, a]]
    raise ValueError(kind)


# ------------------------------------------------------------------ the feed
class Feed:
    """Logs of one view (a board, a mind, a chat), extended step by step into the past."""

    def __init__(self, chain, kind, params):
        self.chain, self.kind, self.params = chain, kind, params
        self.records = {}
        self.latest = 0
        self.lo = None
        self.complete = False
        self.truncated = False
        self.use_es = bool(chain.api_key)
        self.exact = self.use_es
        self.note = ""
        self.eff = {}                 # address -> effective score (int) or None when unknown

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
            lo = max(0, hi - WINDOW_BLOCKS + 1) if self.kind == "board" else 0
            try:
                self._fetch_es(lo, hi)
                return lo
            except Exception as e:  # noqa: BLE001
                self.note = S.M_ES_FAILED.format(error=str(e) or type(e).__name__)
                self.use_es = False
                self.exact = False
        lo = max(0, hi - RPC_WINDOW + 1)
        self._fetch_rpc(lo, hi)
        return lo

    def refresh(self):
        self.records.clear()
        self.truncated = False
        self.note = ""
        self.latest = self.chain.block()
        self.use_es = bool(self.chain.api_key)
        self.exact = self.use_es
        self.lo = self._load(self.latest)
        self.complete = self.lo == 0
        steps = 0
        while not self.complete and steps < MAX_EXTRA_STEPS and len(self.messages()) < FIRST_PAGE:
            self.older()
            steps += 1

    def older(self):
        if self.complete or self.lo is None:
            return
        self.lo = self._load(self.lo - 1)
        self.complete = self.lo == 0

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
