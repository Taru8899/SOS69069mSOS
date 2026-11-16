"""Plain-language explanation of everything that can go wrong while sending a message.
Pure Python (no Kivy), so it is tested on its own. `explain` returns a dict:
    kind   short class name (cancel, typed, account, gas, fee, check, revert, timeout, network, other)
    title  one line
    body   what happened and what to do
    sent   True = a transaction was sent (maybe gas spent), False = nothing was sent, None = unknown"""
import strings as S

STEPS = ("sign", "check", "send", "wait")
REJECT_CODES = (4001, 5000)
REJECT_WORDS = ("user rejected", "rejected by user", "user denied", "denied by user", "request rejected",
                "user cancel", "cancelled by user", "canceled by user", "rejected the request")
UNSUPPORTED_CODES = (4200, -32601)
UNSUPPORTED_WORDS = ("does not exist", "not available", "did not approve", "unauthorized method",
                     "unsupported method", "method not found", "not supported")
GAS_WORDS = ("insufficient funds", "insufficient balance", "exceeds balance", "not enough eth",
             "gas required exceeds")
FEE_WORDS = ("underpriced", "replacement transaction", "fee too low", "nonce too low", "nonce too high",
             "already known", "max fee per gas less than")
TIMEOUT_WORDS = ("timeout", "timed out", "no answer", "did not answer")
NETWORK_WORDS = ("network", "connection", "unreachable", "http", "socket", "resolve", "ssl", "econn", "offline")
ACCOUNT_WORDS = ("account", "from address", "unknown address", "not authorized", "no such account", "signer")


def esc(text):
    """Make text safe inside Kivy markup."""
    return str(text).replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def step_name(step, i=0, n=0):
    if step == "sign":
        return S.CMP_STEP_SIGN.format(i=i, n=n) if n else S.CMP_STEP_SIGN_ANY
    return {"check": S.CMP_STEP_CHECK, "send": S.CMP_STEP_SEND, "wait": S.CMP_STEP_WAIT}.get(step, step or "?")


def reason_text(reason):
    """Contract error name (or node text) -> a sentence."""
    r = (reason or "").strip()
    return S.ERR_CONTRACT.get(r, r)


def kind_of(step, text, code=None, reason=""):
    low = str(text or "").lower()
    if code in REJECT_CODES or any(w in low for w in REJECT_WORDS):
        return "cancel"
    if code in UNSUPPORTED_CODES or any(w in low for w in UNSUPPORTED_WORDS):
        return "typed" if step in ("sign", "send") else "other"
    if any(w in low for w in GAS_WORDS):
        return "gas"
    if any(w in low for w in FEE_WORDS):
        return "fee"
    if any(w in low for w in TIMEOUT_WORDS):
        return "timeout"
    if step == "check" and (reason or low):
        return "check"
    if step == "wait" and reason:
        return "revert"
    if any(w in low for w in ACCOUNT_WORDS):
        return "account"
    if any(w in low for w in NETWORK_WORDS):
        return "network"
    return "other"


def explain(step, text="", code=None, reason="", wallet="", me="", has_hash=False, i=0, n=0):
    k = kind_of(step, text, code, reason)
    what = step_name(step, i, n)
    raw = str(text or "").strip()
    title = S.ERR_TITLE[k]
    body = S.ERR_BODY[k].format(step=what, wallet=esc(wallet or S.ERR_WALLET), me=me, raw=esc(raw or "-"),
                                reason=esc(reason_text(reason) or raw or "-"), code=code if code is not None else "-")
    if has_hash or step == "wait":
        sent = True                      # the wallet gave a transaction hash: it is on its way / on the chain
    elif step in ("sign", "check") or k in ("cancel", "gas"):
        sent = False                     # nothing could have left the phone yet
    else:
        sent = None                      # the send request itself failed: unclear
    if sent is True:
        tail = S.ERR_SENT_YES
    elif sent is False:
        tail = S.ERR_SENT_NO
    else:
        tail = S.ERR_SENT_UNKNOWN
    return {"kind": k, "title": title, "body": body, "sent": sent, "tail": tail, "step": what,
            "raw": raw, "code": code}


def plain(e, wallet="", has_hash=False):
    """One line for 'Copy error'."""
    return "%s | %s | %s | code %s | %s" % (e["title"], e["step"], e["raw"] or "-",
                                          e["code"] if e["code"] is not None else "-", wallet)
