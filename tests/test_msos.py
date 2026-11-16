"""Tests of the data layer (no Kivy, no network). Run:  python -m pytest tests  (or python tests/test_msos.py)
Needs pycryptodome (as the app). Without it, a tiny pure-Python keccak stands in."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "android"))

try:
    import Crypto  # noqa: F401
except ImportError:                       # stand-in keccak so that the tests run anywhere
    import types
    RC = [0x1, 0x8082, 0x800000000000808A, 0x8000000080008000, 0x808B, 0x80000001, 0x8000000080008081,
          0x8000000000008009, 0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B, 0x800000000000008B,
          0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x800A,
          0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x80000001, 0x8000000080008008]
    ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
    M = (1 << 64) - 1
    rol = lambda x, n: ((x << n) | (x >> (64 - n))) & M if n else x  # noqa: E731

    def f(A):
        for rc in RC:
            C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
            D = [C[(x - 1) % 5] ^ rol(C[(x + 1) % 5], 1) for x in range(5)]
            A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
            B = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    B[y][(2 * x + 3 * y) % 5] = rol(A[x][y], ROT[x][y])
            A = [[B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            A[0][0] ^= rc
        return A

    class _K:
        def __init__(self, digest_bits=256):
            self.buf = b""

        def update(self, d):
            self.buf += d

        def digest(self):
            rate = 136
            d = bytearray(self.buf)
            d.append(0x01)
            while len(d) % rate:
                d.append(0)
            d[-1] |= 0x80
            A = [[0] * 5 for _ in range(5)]
            for off in range(0, len(d), rate):
                for i in range(rate // 8):
                    A[i % 5][i // 5] ^= int.from_bytes(d[off + 8 * i: off + 8 * i + 8], "little")
                A = f(A)
            out = b"".join(A[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
            return out[:32]
    kk = types.ModuleType("Crypto.Hash.keccak")
    kk.new = lambda digest_bits=256: _K()
    hh = types.ModuleType("Crypto.Hash")
    hh.keccak = kk
    cc = types.ModuleType("Crypto")
    cc.Hash = hh
    sys.modules.update({"Crypto": cc, "Crypto.Hash": hh, "Crypto.Hash.keccak": kk})
    if "requests" not in sys.modules:
        try:
            import requests  # noqa: F401
        except ImportError:
            sys.modules["requests"] = types.ModuleType("requests")

import core  # noqa: E402
import feed  # noqa: E402
import tx  # noqa: E402
from activity import T_RECORDED, norm_log  # noqa: E402

ME = "0x" + "91" * 20
PEER = "0x" + "2c" * 20
BOARD = core.LEDGER


def test_keccak_known_vector():
    assert core.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert core.selector("transfer(address,uint256)").hex() == "a9059cbb"


def enc_event_data(ph, ts, meta):
    m = meta.encode()
    sig = bytes(65)
    sg = tx.enc_bytes(sig)
    # head: ph, offset(sig)=4*32, ts, offset(meta)=4*32+len(sg)
    head = ph + core.enc(128) + core.enc(ts) + core.enc(128 + len(sg))
    return "0x" + (head + sg + tx.enc_str(meta)).hex()


def make_log(txh, idx, block, signer, to, ph, ts, meta):
    return norm_log({"transactionHash": txh, "blockNumber": hex(block), "timeStamp": hex(ts),
                     "logIndex": hex(idx), "address": core.LEDGER,
                     "topics": [T_RECORDED, "0x" + signer[2:].rjust(64, "0"), "0x" + to[2:].rjust(64, "0"),
                                "0x" + ME[2:].rjust(64, "0")],
                     "data": enc_event_data(ph, ts, meta)})


def test_decode_group_code_reply_tags():
    ph1, ph2, ph3 = (bytes([i]) * 32 for i in (1, 2, 3))
    logs = [make_log("0xaa", 5, 100, PEER, BOARD, ph1, 1000, "#market lamp oil for sale"),
            make_log("0xaa", 6, 100, PEER, BOARD, ph2, 1000, "3 left at the east gate"),
            make_log("0xbb", 2, 105, ME, BOARD, ph3, 1060, "@%s how much? #Market" % feed.code_of(ph1))]
    recs = [feed.decode_record(l) for l in logs]
    assert all(recs) and recs[0]["text"] == "#market lamp oil for sale" and recs[0]["ts"] == 1000
    msgs = feed.group(recs)
    assert [m["block"] for m in msgs] == [105, 100]               # newest first
    first = msgs[1]
    assert first["lines"] == ["#market lamp oil for sale", "3 left at the east gate"]
    assert first["code"] == feed.code_of(ph1) and first["n_replies"] == 1
    reply = msgs[0]
    assert reply["reply_to"] == first["code"] and reply["tags"] == ["#market"]
    assert feed.find_target(msgs, reply["reply_to"], before=(105, 2))["id"] == first["id"]
    assert feed.with_tag(msgs, "market") == [first, reply] or len(feed.with_tag(msgs, "#market")) == 2
    first["eff"], reply["eff"] = 31, 12
    assert [m["eff"] for m in feed.sort_eff(msgs)] == [31, 12]
    assert feed.eff_at_least(msgs, 20) == [first]
    assert [m["n_replies"] for m in feed.sort_replies(msgs)][0] == 1


def test_code_format():
    for i in range(50):
        c = feed.code_of(os.urandom(32))
        assert len(c) == 3 and c == c.lower() and c.isalnum()


def test_queries():
    assert feed.queries("board", {"board": BOARD})[0][2].endswith(BOARD[2:].lower())
    q = feed.queries("chat", {"me": ME, "peer": PEER})
    assert len(feed.queries("chat", {"me": ME, "peers": [PEER, "0x" + "ab" * 20]})) == 6
    assert q[0][1:] == [ "0x" + "0" * 24 + ME[2:], "0x" + "0" * 24 + PEER[2:]] and q[1][1] == q[0][2]
    assert len(feed.queries("mind", {"addrs": [ME, PEER]})) == 2


def test_split_text():
    assert tx.split_text("hello world") == ["hello world"]
    long = "word " * 40
    lines = tx.split_text(long)
    assert all(tx.byte_len(l) <= 64 for l in lines) and " ".join(lines) == long.strip()
    cyr = "привет " * 20                                           # 2 bytes per letter
    assert all(tx.byte_len(l) <= 64 for l in tx.split_text(cyr))
    assert all(tx.byte_len(l) <= 64 for l in tx.split_text("x" * 200))
    assert tx.split_text("a\n\n b ") == ["a", "b"]
    assert tx.prepare_lines(["how much?", "", "4 please"], "7k2") == ["@7k2 how much?", "4 please"]
    assert tx.prepare_lines(["@7K2 hi"], "7k2") == ["@7K2 hi"]
    try:
        tx.prepare_lines(["x"] * 201)
        assert False
    except ValueError:
        pass


def abi_words(data):
    b = bytes.fromhex(data[2:])
    return b[:4], b[4:]


def read_array_of_bytes(body, offset):
    n = int.from_bytes(body[offset:offset + 32], "big")
    base = offset + 32
    out = []
    for i in range(n):
        o = int.from_bytes(body[base + 32 * i: base + 32 * i + 32], "big")
        ln = int.from_bytes(body[base + o: base + o + 32], "big")
        out.append(body[base + o + 32: base + o + 32 + ln])
    return out


def test_batch_encoding_roundtrip():
    items = tx.new_items(["@7k2 how much per lamp? #market", "I need 4 and can pick up today", "привет"])
    for i, it in enumerate(items):
        it["sig"] = bytes([i + 1]) * 65
    to, data = tx.record_call(ME, PEER, items)
    assert to == core.LEDGER
    sel, body = abi_words(data)
    assert sel == core.selector(tx.BATCH_SIG)
    assert body[12:32].hex() == ME[2:] and body[44:64].hex() == PEER[2:]
    off_ph, off_sig, off_meta = (int.from_bytes(body[64 + 32 * i: 96 + 32 * i], "big") for i in range(3))
    n = int.from_bytes(body[off_ph:off_ph + 32], "big")
    assert n == 3
    assert [body[off_ph + 32 + 32 * i: off_ph + 64 + 32 * i] for i in range(3)] == [i["ph"] for i in items]
    assert read_array_of_bytes(body, off_sig) == [i["sig"] for i in items]
    assert [m.decode() for m in read_array_of_bytes(body, off_meta)] == [i["meta"] for i in items]
    assert len(body) % 32 == 0


def test_single_uses_record_signature():
    items = tx.new_items(["hello"])
    items[0]["sig"] = bytes(65)
    to, data = tx.record_call(ME, PEER, items)
    assert bytes.fromhex(data[2:10]) == core.selector(tx.LEDGER_RECORD_SIG)


def test_typed_data_matches_struct_hash():
    import json
    ph = os.urandom(32)
    d = json.loads(tx.ledger_typed_data(ME, PEER, ph, "hello"))
    assert d["message"]["metadataHash"] == "0x" + core.keccak256(b"hello").hex()
    assert d["domain"]["verifyingContract"] == core.LEDGER


def test_board_looks_back_until_four_messages():
    """A first Board load keeps going back (windows double while empty) until it has 4 messages."""
    import types
    from activity import T_RECORDED, WINDOW_BLOCKS, norm_log  # noqa: F401
    latest = 30_000_000
    old_block = latest - 400_000                     # about 55 days back: far outside the first 4 windows
    calls = []

    class FakeChain:
        api_key, source = "key", "fake"

        def es_logs(self, addr, topics, lo, hi):
            calls.append((lo, hi))
            out = []
            for i in range(4):
                if lo <= old_block <= hi:
                    data = "0x" + (bytes([i + 1]) * 32).hex() + (96).to_bytes(32, "big").hex() + \
                        (1700000000).to_bytes(32, "big").hex() + (128).to_bytes(32, "big").hex() + \
                        (3).to_bytes(32, "big").hex() + (b"hi" + bytes([48 + i])).ljust(32, b"\0").hex()
                    out.append({"tx": "0x%d" % i, "block": old_block, "idx": i, "ts": 1700000000,
                                "topics": [T_RECORDED, "0x" + "00" * 12 + ME[2:], "0x" + "00" * 12 + BOARD[2:],
                                           "0x" + "00" * 12 + ME[2:]], "data": data})
            return out, False

        def block(self):
            return latest

    f = feed.Feed(FakeChain(), "board", {"board": BOARD})
    f.refresh()
    assert len(f.messages()) >= 4, len(f.messages())
    spans = [hi - lo + 1 for lo, hi in calls]
    assert spans[0] == WINDOW_BLOCKS and spans[1] == 2 * WINDOW_BLOCKS and len(calls) <= 8, spans


def _rec(tx, idx, block, signer, to, text, ph=None):
    return {"tx": tx, "block": block, "idx": idx, "ts": 1700000000 + block, "signer": signer, "to": to,
            "submitter": signer, "ph": ph or bytes([idx + 1]) * 32, "text": text}


def test_store_round_trip_damage_and_prune():
    import tempfile
    import store
    d = tempfile.mkdtemp()
    path = store.file_for(d, "board", BOARD)
    recs = [_rec("0x%d" % i, 1, 1000 + i, ME, BOARD, "m%d" % i) for i in range(10)]
    store.save(path, 900, 1100, recs)
    got = store.load(path)
    assert got["lo"] == 900 and got["hi"] == 1100 and len(got["records"]) == 10
    assert got["records"][0]["ph"] == recs[0]["ph"] and isinstance(got["records"][0]["ph"], bytes)
    open(path, "w").write("{broken")                      # a damaged file is ignored
    assert store.load(path) is None
    open(path, "w").write('{"v": 99, "lo": 1, "hi": 2, "records": []}')     # another version
    assert store.load(path) is None
    kept, new_lo = store.prune(recs, 4)                  # the newest 4 are kept, and the cut block is dropped
    assert new_lo == 1007 and [r["block"] for r in kept] == [1009, 1008, 1007]
    assert store.clear(d) == 1 and store.load(path) is None


def _fake_chain(latest, events, calls):
    class C:
        api_key, source = "key", "fake"

        def block(self):
            return latest

        def es_logs(self, addr, topics, lo, hi):
            calls.append((lo, hi))
            from activity import T_RECORDED
            out = []
            for r in events:
                if lo <= r["block"] <= hi:
                    off = (128).to_bytes(32, "big")
                    txt = r["text"].encode()
                    data = "0x" + r["ph"].hex() + (96).to_bytes(32, "big").hex() + r["ts"].to_bytes(32, "big").hex() + \
                        off.hex() + len(txt).to_bytes(32, "big").hex() + txt.ljust(32, b"\0").hex()
                    out.append({"tx": r["tx"], "block": r["block"], "idx": r["idx"], "ts": r["ts"],
                                "topics": [T_RECORDED, "0x" + "00" * 12 + r["signer"][2:], "0x" + "00" * 12 + r["to"][2:],
                                           "0x" + "00" * 12 + r["signer"][2:]], "data": data})
            return out, False
    return C()


def test_saved_board_fetches_only_new_blocks():
    import tempfile
    import store
    from activity import WINDOW_BLOCKS
    d = tempfile.mkdtemp()
    path = store.file_for(d, "board", BOARD)
    latest1 = 5_000_000
    ev = [_rec("0x%d" % i, 1, latest1 - 100 * i, ME, BOARD, "old%d" % i) for i in range(1, 6)]
    calls = []
    f = feed.Feed(_fake_chain(latest1, ev, calls), "board", {"board": BOARD}, path=path)
    assert not f.seed()                                   # nothing saved yet
    f.refresh()
    assert len(f.messages()) == 5 and os.path.exists(path)
    # next visit: 3 blocks later, one new message, one message in the last 64 blocks is read again
    ev.append(_rec("0xnew", 1, latest1 + 2, ME, BOARD, "fresh"))
    calls2 = []
    g = feed.Feed(_fake_chain(latest1 + 3, ev, calls2), "board", {"board": BOARD}, path=path)
    assert g.seed() and len(g.messages()) == 5            # the saved messages are there without any network call
    g.refresh()
    assert len(g.messages()) == 6
    assert calls2 == [(latest1 - store.REORG + 1, latest1 + 3)], calls2     # only the newest blocks were fetched
    # a very long absence: only the newest window is fetched, older ones are filled in later
    calls3 = []
    h = feed.Feed(_fake_chain(latest1 + 10 * WINDOW_BLOCKS, ev, calls3), "board", {"board": BOARD}, path=path)
    h.seed()
    h.refresh()
    assert calls3[0][0] == latest1 + 10 * WINDOW_BLOCKS - WINDOW_BLOCKS + 1 and h.lo == calls3[0][0]
    assert len(h.records) >= 6                           # the saved ones are still shown


def test_offline_keeps_saved_messages():
    import tempfile
    import store
    d = tempfile.mkdtemp()
    path = store.file_for(d, "board", BOARD)
    store.save(path, 100, 200, [_rec("0x1", 1, 150, ME, BOARD, "kept")])

    class Down:
        api_key = ""

        def block(self):
            raise RuntimeError("no network")
    f = feed.Feed(Down(), "board", {"board": BOARD}, path=path)
    assert f.seed()
    try:
        f.refresh()
        raise AssertionError("should fail")
    except RuntimeError:
        pass
    assert len(f.messages()) == 1 and f.hi == 200


def test_reply_code_tag_groups_a_thread():
    root = _rec("0xr", 1, 10, ME, BOARD, "888 for sale", bytes([7]) * 32)
    code = feed.code_of(bytes([7]) * 32)
    rep1 = _rec("0xa", 1, 11, PEER, BOARD, "@%s how much" % code)
    rep2 = _rec("0xb", 1, 12, ME, BOARD, "@%s.. 20 eth" % code.upper(), bytes([9]) * 32)
    other = _rec("0xc", 1, 13, PEER, BOARD, "something else #sale", bytes([8]) * 32)
    msgs = feed.group([root, rep1, rep2, other])
    got = feed.with_tag(msgs, "@" + code)
    assert sorted(m["tx"] for m in got) == ["0xa", "0xb", "0xr"]           # the message and its replies
    assert [m["tx"] for m in feed.with_tag(msgs, "#sale")] == ["0xc"]
    assert feed.normalize_tag("kg6") == "@kg6" and feed.normalize_tag("@KG6") == "@kg6"
    assert feed.normalize_tag("#kg6") == "#kg6" and feed.normalize_tag("sale") == "#sale"
    assert feed.normalize_tag("@toolong") == "" and feed.normalize_tag("  ") == "" and feed.normalize_tag("#") == ""


def test_outbox_and_errors():
    import tempfile
    import errors
    import outbox
    path = os.path.join(tempfile.mkdtemp(), "outbox.json")
    ob = outbox.Outbox(path)
    e = ob.add(outbox.new_entry("board", BOARD, ME, ["hi"], "abc", "0x" + "11" * 32, "TP"))
    ob.add(outbox.new_entry("mind", ME, ME, ["note"], "def", "0x" + "22" * 32))
    again = outbox.Outbox(path)                           # survives a restart
    assert len(again.items) == 2 and len(again.active()) == 2
    assert [x["kind"] for x in again.for_page("board", BOARD)] == ["board"] and again.for_page("chat") == []
    again.items[0]["state"] = "ok"
    assert len(again.active()) == 1
    again.dismiss(e["id"])
    assert len(outbox.Outbox(path).items) == 1
    table = [("sign", "User rejected the request", 4001, "", "cancel", False),
             ("sign", "the method eth_signTypedData_v4 does not exist", None, "", "typed", False),
             ("send", "insufficient funds for gas * price + value", None, "", "gas", False),
             ("send", "replacement transaction underpriced", None, "", "fee", None),
             ("check", "", None, "InvalidSignature", "check", False),
             ("wait", "", None, "DuplicatePayloadHash", "revert", True),
             ("send", "request timed out", None, "", "timeout", None),
             ("wait", "connection reset", None, "", "network", True),
             ("send", "weird [b] text", 7, "", "other", None)]
    for step, text, code, reason, kind, sent in table:
        x = errors.explain(step, text, code, reason, wallet="TokenPocket", me="0x08E5...5fEE", has_hash=(step == "wait"))
        assert x["kind"] == kind and x["sent"] is sent, (step, x["kind"], x["sent"])
        assert "[b] text" not in x["body"]                # user text is escaped for markup
    assert "already on the ledger" in errors.explain("wait", "", None, "DuplicatePayloadHash")["body"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
