"""Actions the assistant proposes and a person approves.

The model never changes store data itself. Its action tools (see tools.py) check the request and
save it here as a *pending* action; the chat shows it as a card. Only an Approve click runs it.

Exactly once: approving first flips the action from pending to done with a conditional UPDATE
("... WHERE status = 'pending'"), in the same transaction as the change itself. A second click,
a retry or another tab finds nothing pending and changes nothing. If the change fails, the
transaction rolls back, so the action can't be marked done without the change, or the reverse.
"""

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import ActionStatus, ChatAction, Order, RefundReason, Ticket, TicketStatus, utcnow
from app.services import orders


def propose(
    db: Session, conversation_id: int, kind: str, arguments: dict[str, Any], summary: str
) -> ChatAction:
    """Save a checked proposal. Asking twice for the same thing returns the pending one."""
    args = json.dumps(arguments, sort_keys=True)
    action = db.scalar(
        select(ChatAction).where(
            ChatAction.conversation_id == conversation_id,
            ChatAction.kind == kind,
            ChatAction.arguments == args,
            ChatAction.status == ActionStatus.pending,
        )
    )
    if action is None:
        action = ChatAction(conversation_id=conversation_id, kind=kind, arguments=args, summary=summary)
        db.add(action)
        db.commit()
    return action


def get(db: Session, action_id: int) -> ChatAction:
    action = db.get(ChatAction, action_id)
    if action is None:
        raise NotFoundError(f"Action {action_id} not found.")
    return action


def _claim(db: Session, action_id: int, status: ActionStatus, outcome: str | None = None) -> bool:
    """Move a pending action to `status`. False if it isn't pending (any more)."""
    result = db.execute(
        update(ChatAction)
        .where(ChatAction.id == action_id, ChatAction.status == ActionStatus.pending)
        .values(status=status, decided_at=utcnow(), outcome=outcome)
    )
    return result.rowcount == 1


def decide(db: Session, action_id: int, approve: bool) -> ChatAction:
    """Approve (run it) or reject a pending action."""
    if not _claim(db, action_id, ActionStatus.done if approve else ActionStatus.rejected):
        db.rollback()
        action = get(db, action_id)
        raise ConflictError(f"This action is already {action.status}.", details={"status": action.status})
    if not approve:
        db.commit()
        return get(db, action_id)

    action = get(db, action_id)
    try:
        # Commits the change together with the claim above.
        outcome = _run(db, action.kind, json.loads(action.arguments))
    except BusinessRuleError as e:  # the store's rules said no (e.g. already refunded since)
        db.rollback()  # undoes the claim too
        _claim(db, action_id, ActionStatus.failed, e.message)
        db.commit()
        return get(db, action_id)
    action.outcome = outcome
    db.commit()
    return action


def drop(db: Session, action_ids: list[int]) -> None:
    """Reject proposals from a reply that failed or was stopped: it isn't saved, so no card shows them."""
    for action_id in action_ids:
        _claim(db, action_id, ActionStatus.rejected, "The reply failed, so this proposal was dropped.")
    db.commit()


def _order(db: Session, number: str) -> Order:
    order = db.scalar(select(Order).where(Order.number == number))
    if order is None:
        raise BusinessRuleError(f"Order {number} no longer exists.")
    return order


def _run(db: Session, kind: str, args: dict[str, Any]) -> str:
    """Carry out an approved action through the normal business rules. Returns what happened."""
    if kind == "create_refund":
        order = _order(db, args["order_number"])
        orders.refund_order(
            db,
            order,
            amount_cents=args["amount_cents"],
            reason=RefundReason(args["reason"]),
            note=args["note"],
        )
        left = order.refundable_cents / 100
        amount = args["amount_cents"] / 100
        return f"Refunded ${amount:.2f} on {order.number}. ${left:.2f} can still be refunded."
    if kind == "cancel_order":
        order = orders.cancel_order(db, _order(db, args["order_number"]))
        return f"Cancelled {order.number}. Its items are back in stock."
    if kind == "draft_ticket_reply":
        ticket = db.get(Ticket, args["ticket_id"])
        if ticket is None:
            raise BusinessRuleError(f"Ticket {args['ticket_id']} no longer exists.")
        if ticket.status == TicketStatus.closed:
            raise BusinessRuleError(f"Ticket #{ticket.id} is closed.")
        ticket.draft_reply = args["body"]
        db.commit()
        return f"The draft is in ticket #{ticket.id}'s reply box. Nothing has been sent."
    raise BusinessRuleError(f"Unknown action {kind!r}.")


def notes(actions: list[ChatAction]) -> str | None:
    """What happened to this conversation's proposals, for the model (it can't see the cards)."""
    if not actions:
        return None
    lines = [f"- #{a.id} {a.summary}: {a.status}" + (f" ({a.outcome})" if a.outcome else "") for a in actions]
    return (
        "Actions you proposed in this conversation and what the user decided. Only those marked "
        "done have happened; pending ones are still waiting on the card.\n" + "\n".join(lines)
    )
