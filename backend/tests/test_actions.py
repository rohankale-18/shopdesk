"""Step 9: the assistant proposes changes; only a person's approval carries them out, exactly once."""

import json

from sqlalchemy import func, select

from app.core.errors import UpstreamError
from app.db import SessionLocal
from app.models import ChatAction
from app.services import ai, tools
from tests.test_chat import new_chat, scripted_model, send  # noqa: F401  (scripted_model is a fixture)

# Seeded scenarios (see seed.py): ORD-00000001 delivered (headphones $199.99 + serum), ORD-00000003
# has only $199.99 left to refund, ORD-00000004 is paid and not shipped.
DAMAGED, PARTLY_REFUNDED, NOT_SHIPPED = "ORD-00000001", "ORD-00000003", "ORD-00000004"


def propose(cid: int, name: str, **arguments) -> dict:
    return tools.run(name, json.dumps(arguments), cid)


def order(number: str) -> dict:
    return tools.run("get_order", json.dumps({"order_number": number}))


def refund(cid: int, number: str = DAMAGED, amount: float = 199.99) -> dict:
    return propose(cid, "create_refund", order_number=number, amount_usd=amount, reason="damaged")


def test_a_proposal_changes_nothing_until_approved(client):
    cid = new_chat(client)
    before = order(DAMAGED)
    result = refund(cid)

    assert result["status"] == "waiting_for_approval"
    assert "Nothing has happened yet" in result["next_step"]
    assert order(DAMAGED) == before
    action = client.get(f"/api/chat/actions/{result['action_id']}").json()
    assert action["status"] == "pending"
    assert action["summary"] == f"Refund $199.99 on {DAMAGED} (damaged)"
    assert action["arguments"]["amount_cents"] == 19999


def test_approving_runs_it_exactly_once(client):
    cid = new_chat(client)
    action_id = refund(cid)["action_id"]
    refunded = order(DAMAGED)["refunded_usd"]

    r = client.post(f"/api/chat/actions/{action_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["outcome"].startswith(f"Refunded $199.99 on {DAMAGED}.")
    assert order(DAMAGED)["refunded_usd"] == round(refunded + 199.99, 2)

    # A double click, a retry or a second tab: refused, and nothing is refunded twice.
    again = client.post(f"/api/chat/actions/{action_id}/approve")
    assert again.status_code == 409
    assert again.json()["error"]["details"]["status"] == "done"
    assert order(DAMAGED)["refunded_usd"] == round(refunded + 199.99, 2)


def test_rejecting_changes_nothing_and_cant_be_approved_later(client):
    cid = new_chat(client)
    action_id = refund(cid)["action_id"]
    before = order(DAMAGED)

    assert client.post(f"/api/chat/actions/{action_id}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/chat/actions/{action_id}/approve").status_code == 409
    assert order(DAMAGED) == before


def test_a_refund_above_the_refundable_amount_is_refused_up_front(client):
    cid = new_chat(client)
    result = refund(cid, PARTLY_REFUNDED, 249.98)
    assert result == {
        "error": f"Only $199.99 can still be refunded on {PARTLY_REFUNDED}. "
        "Tell the user; propose that amount or less only if they ask."
    }
    # Nothing was saved for the refused one, so the next proposal is the conversation's first action.
    allowed = refund(cid, PARTLY_REFUNDED, 199.99)
    assert allowed["status"] == "waiting_for_approval"
    with SessionLocal() as db:
        assert (
            db.scalar(select(func.count()).select_from(ChatAction).where(ChatAction.conversation_id == cid))
            == 1
        )


def test_rules_are_checked_again_on_approval(client):
    """Two proposals that each fit, but not together: the second fails, and refunds nothing."""
    cid = new_chat(client)
    first = refund(cid, PARTLY_REFUNDED, 150)["action_id"]
    second = refund(cid, PARTLY_REFUNDED, 100)["action_id"]

    assert client.post(f"/api/chat/actions/{first}/approve").json()["status"] == "done"
    failed = client.post(f"/api/chat/actions/{second}/approve").json()
    assert failed["status"] == "failed"
    assert "exceeds what's refundable" in failed["outcome"]
    assert order(PARTLY_REFUNDED)["still_refundable_usd"] == 49.99
    assert client.post(f"/api/chat/actions/{second}/approve").status_code == 409


def test_asking_twice_gives_the_same_pending_action(client):
    cid = new_chat(client)
    assert refund(cid)["action_id"] == refund(cid)["action_id"]


def test_cancel_only_before_shipping(client):
    cid = new_chat(client)
    shipped = propose(cid, "cancel_order", order_number=DAMAGED)
    assert "can't be cancelled" in shipped["error"]

    action_id = propose(cid, "cancel_order", order_number=NOT_SHIPPED)["action_id"]
    assert order(NOT_SHIPPED)["status"] == "paid"
    done = client.post(f"/api/chat/actions/{action_id}/approve").json()
    assert done["status"] == "done"
    assert order(NOT_SHIPPED)["status"] == "cancelled"


def test_an_approved_draft_lands_in_the_reply_box_and_is_cleared_by_a_reply(client):
    cid = new_chat(client)
    ticket = client.get("/api/tickets", params={"status": "open"}).json()["items"][0]["id"]
    action_id = propose(cid, "draft_ticket_reply", ticket_id=ticket, body="Hi! [refund decision]")[
        "action_id"
    ]
    before = client.get(f"/api/tickets/{ticket}").json()
    assert before["draft_reply"] is None

    client.post(f"/api/chat/actions/{action_id}/approve")
    t = client.get(f"/api/tickets/{ticket}").json()
    assert t["draft_reply"] == "Hi! [refund decision]"
    assert t["messages"] == before["messages"]  # nothing was sent

    client.post(f"/api/tickets/{ticket}/messages", json={"body": "Hi! We refunded you."})
    assert client.get(f"/api/tickets/{ticket}").json()["draft_reply"] is None


def test_no_draft_for_a_closed_ticket(client):
    cid = new_chat(client)
    ticket = client.get("/api/tickets", params={"status": "closed"}).json()["items"][0]["id"]
    assert "closed" in propose(cid, "draft_ticket_reply", ticket_id=ticket, body="Hi")["error"]


def test_action_tools_need_a_conversation():
    assert "only works in a saved conversation" in tools.run("cancel_order", '{"order_number": "4"}')["error"]


def test_the_chat_shows_the_card_and_tells_the_model_what_happened(client, scripted_model):  # noqa: F811
    script, calls = scripted_model
    args = json.dumps({"order_number": DAMAGED, "amount_usd": 199.99, "reason": "damaged"})
    script += [
        [ai.ToolCall(id="c1", name="create_refund", arguments=args)],
        ["I've proposed it."],
        ["Done."],
    ]
    cid = new_chat(client)
    events = send(client, cid, "Refund the headphones")

    tool_event = events[0][1]
    assert tool_event["label"] == f"Proposed a refund on {DAMAGED}"
    action_id = tool_event["action_id"]
    saved = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["tool_calls"]
    assert saved[0]["action_id"] == action_id  # the card survives a reload

    # The approval happens outside the chat; the next turn tells the model about it.
    client.post(f"/api/chat/actions/{action_id}/approve")
    send(client, cid, "Is it done?")
    note = calls[-1][0][-2]
    assert note["role"] == "system"
    assert f"#{action_id} Refund $199.99 on {DAMAGED} (damaged): done (Refunded $199.99" in note["content"]


def test_deleting_the_conversation_deletes_its_actions(client):
    cid = new_chat(client)
    action_id = refund(cid)["action_id"]
    client.delete(f"/api/chat/conversations/{cid}")
    assert client.get(f"/api/chat/actions/{action_id}").status_code == 404


def test_a_failed_reply_drops_its_proposals(client, monkeypatch):
    """The reply isn't saved, so its card would never show: the proposal mustn't stay pending."""
    calls = []

    def stream(messages, **_):
        calls.append(1)
        if len(calls) == 1:
            args = json.dumps({"order_number": DAMAGED, "amount_usd": 10, "reason": "damaged"})
            yield ai.ToolCall(id="c1", name="create_refund", arguments=args)
        else:
            raise UpstreamError("Groq rate limit reached. Wait a moment and try again.")

    monkeypatch.setattr(ai, "stream", stream)
    cid = new_chat(client)
    events = send(client, cid, "Refund $10")

    assert events[-1][0] == "error"
    action = client.get(f"/api/chat/actions/{events[0][1]['action_id']}").json()
    assert action["status"] == "rejected"
    assert action["outcome"] == "The reply failed, so this proposal was dropped."
