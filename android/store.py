"""Messages saved on the phone (Board and Chat; Mind is never saved).

One small JSON file per view. Besides the decoded ledger records it stores the block range that has
been searched completely (lo..hi), so the next start shows the saved messages at once and asks the
network only for newer blocks. Nothing secret is stored: it is public ledger data."""
import hashlib
import json
import os
import tempfile

VERSION = 1
MAX_RECORDS = 2000          # newest records kept per view
REORG = 64                  # blocks at the head that are always read again
FIELDS = ("tx", "block", "idx", "ts", "signer", "to", "submitter", "ph", "text")
PREFIX = "msgs_"


def file_for(folder, kind, key):
    h = hashlib.sha1(("%s|%s" % (kind, key)).encode()).hexdigest()[:16]
    return os.path.join(folder, "%s%s_%s.json" % (PREFIX, kind, h))


def _pack(r):
    d = {k: r[k] for k in FIELDS if k != "ph"}
    d["ph"] = bytes(r["ph"]).hex()
    return d


def _unpack(d):
    if not all(k in d for k in FIELDS):
        raise ValueError("record")
    if not (isinstance(d["tx"], str) and isinstance(d["text"], str) and isinstance(d["signer"], str)
            and isinstance(d["to"], str) and isinstance(d["submitter"], str)):
        raise ValueError("record types")
    if not all(isinstance(d[k], int) for k in ("block", "idx", "ts")):
        raise ValueError("record numbers")
    r = dict(d)
    r["ph"] = bytes.fromhex(d["ph"])
    if len(r["ph"]) != 32:
        raise ValueError("payload hash")
    return r


def prune(records, max_n=MAX_RECORDS):
    """Keep the newest records. When some are dropped, the whole oldest block that was cut is dropped
    too and the new first searched block is returned (so coverage never claims more than is stored).
    Returns (kept, new_lo or None)."""
    recs = sorted(records, key=lambda r: (r["block"], r["idx"]), reverse=True)
    if len(recs) <= max_n:
        return recs, None
    cut_block = recs[max_n - 1]["block"]
    kept = [r for r in recs[:max_n] if r["block"] > cut_block]
    return kept, cut_block + 1


def load(path):
    """{'lo', 'hi', 'records'} or None (missing, damaged or from another version)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != VERSION:
            return None
        lo, hi = d["lo"], d["hi"]
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi + 1):
            return None
        return {"lo": lo, "hi": hi, "records": [_unpack(x) for x in d["records"]]}
    except Exception:  # noqa: BLE001  any damage = start again
        return None


def save(path, lo, hi, records):
    """Write atomically: a temporary file in the same folder, then rename."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    data = {"v": VERSION, "lo": int(lo), "hi": int(hi), "records": [_pack(r) for r in records]}
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def clear(folder):
    """Delete every saved message file. Returns how many were removed."""
    n = 0
    try:
        for name in os.listdir(folder):
            if name.startswith(PREFIX) or name.startswith(".tmp_"):
                os.remove(os.path.join(folder, name))
                n += 1
    except OSError:
        pass
    return n
