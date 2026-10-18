#!/usr/bin/env python3
"""Value snapshot: the stored order of the cards under Model servers (board_layout.py).

Under Model servers the board drew its machines first and its cloud providers after
them, always. Since 2026-10-04 the cards stand in one list in the operator's order,
kept on the controller in the admin document's `topology.layout`, so every browser
and account sees the same board (the board-side rule: static/js/server-order.js).

What is pinned, by value: what a save stores and answers (the keys as sent, a
revision that grows by one); what a save refuses, whole — not a list, a key that is
not `node:<id>` or `cloud:<id>`, a key listed twice, a list too long — and that a
refused save stores nothing and keeps the revision; what a document edited by hand
reads as (no order, never a guess at one); and the route that saves it.

The store and its save are stand-ins: nothing here touches admin.json.

Run: python3 scripts/test_server_order.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.board_layout import ServerOrder  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Doc:
    """The topology section of a stand-in admin document, and how often it was saved."""

    def __init__(self, layout=None):
        self.topo = {} if layout is None else {"layout": layout}
        self.saves = 0

    def order(self):
        return ServerOrder(section=lambda: self.topo, save=self.save)

    def save(self):
        self.saves += 1


def refused(order, doc):
    """The status and message a save of `order` is refused with, or None when it is not."""
    try:
        doc.order().save(order)
    except AppError as err:
        return err.status, str(err)
    return None


print("a fresh document holds no order:")
doc = Doc()
check(doc.order().keys() == [] and doc.order().revision() == 0, "no keys, revision 0")
check(doc.order().layout() == {"serverOrder": [], "serverOrderRev": 0},
      f"what the board is handed: an empty order, revision 0 (got {doc.order().layout()})")
check(doc.saves == 0 and doc.topo == {}, "negative: reading writes nothing")

print("a save stores the keys as sent and answers them:")
first = ["cloud:openai-pool", "node:box-a", "cloud:router-or", "node:box-b"]
answer = doc.order().save(list(first))
check(answer == {"ok": True, "order": first, "rev": 1}, f"the answer: the stored keys and revision 1 (got {answer})")
check(doc.topo["layout"] == {"serverOrder": first, "serverOrderRev": 1} and doc.saves == 1,
      f"the document holds them, saved once (got {doc.topo}, {doc.saves} saves)")
second = ["node:box-b", "cloud:openai-pool"]
answer = doc.order().save(list(second))
check(answer == {"ok": True, "order": second, "rev": 2} and doc.saves == 2,
      "the next save replaces the list whole — a key it leaves out is gone — and the revision grows by one")
answer = doc.order().save([])
check(answer == {"ok": True, "order": [], "rev": 3} and doc.order().layout() == {"serverOrder": [], "serverOrderRev": 3},
      "an empty list is an order too: the board's own; the revision still grows")

print("what a key may be (as-is):")
odd = ["cloud:acct:2", "node:My Box", "node:машина", "node:" + "x" * 195]
answer = Doc().order().save(list(odd))
check(answer["order"] == odd,
      "a colon inside the id (the kind ends at the first one), a space, a non-Latin name, 200 characters — all keys")

print("what a save refuses, whole:")
for value, why in ((None, "nothing"), ("node:box-a", "a string"), ({"order": []}, "an object"), (5, "a number")):
    doc = Doc({"serverOrder": ["node:kept"], "serverOrderRev": 7})
    check(refused(value, doc) == (400, "order must be a list of card keys") and doc.saves == 0,
          f"negative: {why} is no list — 400, nothing saved")
bad_keys = [("", "an empty key"), ("node:", "a kind with no id"), ("box-a", "an id with no kind"),
            ("machine:box-a", "an unknown kind"), ("node:   ", "a blank id"), (5, "a number"),
            ("node:box\na", "a line break"), ("node:" + "x" * 196, "201 characters")]
for key, why in bad_keys:
    doc = Doc({"serverOrder": ["node:kept"], "serverOrderRev": 7})
    got = refused(["node:fine", key], doc)
    check(got is not None and got[0] == 400 and got[1].startswith("order[1] is not a card key"),
          f"negative: {why} — 400 naming its place in the list (got {got})")
    check(doc.topo["layout"] == {"serverOrder": ["node:kept"], "serverOrderRev": 7} and doc.saves == 0,
          f"  and {why} stores nothing: the stored order and its revision stay")
doc = Doc()
check(refused(["node:a", "cloud:b", "node:a"], doc) == (400, "order lists node:a twice") and doc.saves == 0,
      "negative: a key listed twice — 400; the board never sends that, and a guess at which place it meant is no answer")
doc = Doc()
check(refused([f"node:m{i}" for i in range(501)], doc) == (400, "order holds 501 keys; at most 500"),
      "negative: 501 keys — 400; a fleet has a few dozen cards")
check(Doc().order().save([f"node:m{i}" for i in range(500)])["rev"] == 1, "500 keys are an order")

print("what a document edited by hand reads as:")
check(Doc({"serverOrder": "node:a"}).order().keys() == [], "negative: a string where the list was — no order, not a one-card order")
check(Doc({"serverOrder": ["node:a", 5, "bad", "node:a", "cloud:b", "machine:c"]}).order().keys() == ["node:a", "cloud:b"],
      "as-is: the keys that are keys, the first of a repeated one, in their order; the rest is not read")
for rev, want in (("7", 0), (-1, 0), (True, 0), (2.5, 0), (3, 3)):
    check(Doc({"serverOrderRev": rev}).order().revision() == want, f"revision {rev!r} reads as {want}")
doc = Doc()
doc.topo["layout"] = None
check(doc.order().keys() == [] and doc.order().save(["node:a"])["rev"] == 1 and doc.topo["layout"]["serverOrder"] == ["node:a"],
      "a layout that is no section (null) reads as none and is made one by the first save")

print("the route:")
from caravan.admin import routes  # noqa: E402
handler = routes.POST_ROUTES.get("/api/topology/server-order")
check(handler is not None, "POST /api/topology/server-order is a route")


class Reply:
    def __init__(self):
        self.sent = []

    def send_json(self, data, status=200):
        self.sent.append((status, data))


doc = Doc()
saved_order = routes.SERVER_ORDER
routes.SERVER_ORDER = doc.order()
try:
    reply = Reply()
    handler(reply, None, {"order": ["node:box-b", "cloud:p"]})
    check(reply.sent == [(200, {"ok": True, "order": ["node:box-b", "cloud:p"], "rev": 1})],
          f"the route answers what the order answers (got {reply.sent})")
    reply = Reply()
    try:
        handler(reply, None, {})
        outcome = "answered"
    except AppError as err:
        outcome = (err.status, str(err))
    check(outcome == (400, "order must be a list of card keys") and reply.sent == [],
          "negative: a body without `order` is refused with 400, which the dispatcher sends")
finally:
    routes.SERVER_ORDER = saved_order
check(routes.ROUTE_ACCESS.security("POST", "/api/topology/server-order").get("x-caravan-roles") == ["admin"],
      "only an admin account saves an order: a viewer reads the board and cannot rearrange it")

print("the clients' order (1.3.503: a client card carried in Routing):")
from caravan.admin.board_layout import ClientOrder  # noqa: E402


class ClientDoc(Doc):
    def order(self):
        return ClientOrder(section=lambda: self.topo, save=self.save)


fresh = ClientDoc()
check((fresh.order().ports(), fresh.order().revision(), fresh.order().layout()) == ([], 0, {"clientOrder": [], "clientOrderRev": 0}),
      "a fresh document holds no clients' order and no revision")
check(fresh.order().save([23002, 23001]) == {"ok": True, "order": [23002, 23001], "rev": 1} and fresh.saves == 1
      and fresh.topo["layout"] == {"clientOrder": [23002, 23001], "clientOrderRev": 1},
      f"a save stores the ports as sent, its revision 1, in the layout section (got {fresh.topo})")
fresh.order().save([])
check((fresh.order().ports(), fresh.order().revision()) == ([], 2), "an empty list returns the clients to their order by name; the revision still grows")
for bad, why in (("23001", "not a list"), ([23001, "23002"], "a port as text"), ([23001, True], "a truth value"),
                 ([0], "port 0"), ([65536], "a port past 65535"), ([23001, 23001], "a port twice"),
                 (list(range(1, ClientOrder.LIMIT + 2)), "a list longer than the limit")):
    doc = ClientDoc({"clientOrder": [23003], "clientOrderRev": 5})
    try:
        doc.order().save(bad)
        status = None
    except AppError as err:
        status = err.status
    check(status == 400 and doc.saves == 0 and doc.order().ports() == [23003] and doc.order().revision() == 5,
          f"negative: {why} — refused 400 whole; nothing stored, the revision kept (got {status})")
hand = ClientDoc({"clientOrder": [23002, "x", 23002, None, 70000, 23001], "clientOrderRev": "7"})
check((hand.order().ports(), hand.order().revision()) == ([23002, 23001], 0),
      "a hand-edited document: what is no port and a port twice are not read; a revision that is no number is none")
check(ClientDoc({"clientOrder": "23001"}).order().ports() == [] and ClientDoc().order().layout()["clientOrder"] == [],
      "negative: a value that is no list reads as no order")
both = Doc({"serverOrder": ["node:a"], "serverOrderRev": 3})
ClientOrder(section=lambda: both.topo, save=both.save).save([23001])
check(both.topo["layout"] == {"serverOrder": ["node:a"], "serverOrderRev": 3, "clientOrder": [23001], "clientOrderRev": 1},
      "the clients' order is kept beside the server cards' order, which it leaves as it was")

handler = routes.POST_ROUTES.get("/api/consumers/order")
check(handler is not None, "POST /api/consumers/order is a route")
doc = ClientDoc()
saved_state = routes.topology_state
import caravan.admin.board_layout as board_layout  # noqa: E402
saved_module_order = board_layout.CLIENT_ORDER
board_layout.CLIENT_ORDER = doc.order()
routes.topology_state = lambda **kw: {"drawn": True}
try:
    reply = Reply()
    handler(reply, None, {"order": [23002, 23001]})
    check(reply.sent == [(200, {"ok": True, "order": [23002, 23001], "rev": 1, "topology": {"drawn": True}})],
          f"the route answers what the order answers, and the board drawn again (got {reply.sent})")
    try:
        handler(Reply(), None, {"order": ["23001"]})
        outcome = "answered"
    except AppError as err:
        outcome = err.status
    check(outcome == 400 and doc.saves == 1, "negative: a port as text is refused with 400; nothing more is stored")
finally:
    board_layout.CLIENT_ORDER = saved_module_order
    routes.topology_state = saved_state
check(routes.ROUTE_ACCESS.security("POST", "/api/consumers/order").get("x-caravan-roles") == ["admin"],
      "only an admin account saves the clients' order")

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for message in _fail:
        print("  -", message)
    sys.exit(1)
print("\nserver order OK: a save stores the list whole and refuses it whole, a hand-edited document reads as no order; the clients' order beside it")
