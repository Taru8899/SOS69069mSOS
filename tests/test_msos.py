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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
