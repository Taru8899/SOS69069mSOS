"""The messages you sent, as status entries kept on the phone until you dismiss them.
Pure Python. An entry is created when the wallet returns the transaction hash:
    id/hash  the transaction hash          kind  board / mind / chat      to    recipient address
    frm      sender address                lines the text lines           code  3-character reply code
    state    wait -> (slow) -> ok | fail   block block of the receipt     note  network hint while waiting
    err      {title, body, tail} when the transaction failed on the ledger
    t / t_ok seconds (submitted / finished)"""
import json
import os
import tempfile
import time

ACTIVE = ("wait", "slow")
FINAL = ("ok", "fail")
MAX_KEEP = 30


def new_entry(kind, to, frm, lines, code, tx_hash, wallet=""):
    return {"id": tx_hash, "hash": tx_hash, "kind": kind, "to": to.lower(), "frm": frm.lower(),
            "lines": list(lines), "code": code, "state": "wait", "block": 0, "note": "", "err": None,
            "wallet": wallet, "t": time.time(), "t_ok": 0}


class Outbox:
    def __init__(self, path):
        self.path = path
        self.items = []
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.items = [e for e in data if isinstance(e, dict) and e.get("hash") and e.get("state") in ACTIVE + FINAL]
        except Exception:  # noqa: BLE001
            self.items = []

    def save(self):
        try:
            folder = os.path.dirname(self.path)
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=folder)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.items, f)
            os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001
            pass

    def add(self, e):
        self.items = [x for x in self.items if x["id"] != e["id"]] + [e]
        finals = [x for x in self.items if x["state"] in FINAL]
        if len(finals) > MAX_KEEP:
            drop = {x["id"] for x in finals[:len(finals) - MAX_KEEP]}
            self.items = [x for x in self.items if x["id"] not in drop]
        self.save()
        return e

    def get(self, eid):
        return next((x for x in self.items if x["id"] == eid), None)

    def dismiss(self, eid):
        self.items = [x for x in self.items if x["id"] != eid]
        self.save()

    def active(self):
        return [x for x in self.items if x["state"] in ACTIVE]

    def for_page(self, kind, to=None):
        """Entries shown on a page: newest first. A Board shows the sends to that board address."""
        out = [x for x in self.items if x["kind"] == kind and (kind != "board" or to is None or x["to"] == to.lower())]
        return sorted(out, key=lambda x: x["t"], reverse=True)
