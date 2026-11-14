# ShopDesk agent roadmap

The support assistant learns one capability at a time. Each step adds **one new idea**: build it, try it with the test questions, write down what you learned, then move on.

**Status key:** ⬜ not started · 🟨 in progress · ✅ done

| # | Step | Tools | New idea | Status |
|---|---|---|---|---|
| 0 | Chat foundation | none | Streaming chat, stored conversations, system prompt | ✅ |
| 1 | The agent loop | `get_store_overview` | Tool definitions and the tool-calling loop | ⬜ |
| 2 | Look up by ID | `get_order` | Arguments, errors as data, output size | ⬜ |
| 3 | Search, then chain | `find_customer`, `list_customer_orders` | Multi-step reasoning, ambiguity, limits | ⬜ |
| 4 | Tickets | `get_ticket`, `list_tickets` | Summarizing real data, page context | ⬜ |
| 5 | Products and stock | `search_products` | Grounding: never invent facts | ⬜ |
| 6 | Analytics and charts | `sales_by_day`, `top_products` | Structured output rendered as charts | ⬜ |
| 7 | Actions with approval | `draft_ticket_reply`, `create_refund`, `cancel_order` | Human in the loop, backend-enforced rules | ⬜ |
| 8 | Evals | none | Measuring whether a change made the agent better | ⬜ |

---

## Principles (apply to every step)

- **Tools call the service layer directly** (`app/services/...`), not ShopDesk's own HTTP API. They share the same validation and business rules.
- **Read-only before write.** No tool changes data until Step 7, and then only with human approval.
- **One step at a time.** Add the tool, try the test questions, note what happened, then move on.
- **Rules live in the backend.** The model's judgement is never the safety net; the code enforces limits (e.g. refund amounts).
- **Log every tool call and its result.** When the agent does something odd, the log tells you why.
- **Keep tool outputs small.** Return only the fields that matter; everything returned costs tokens.

---

## Step 0: Chat foundation ✅

Already in place before the agent work starts.

- [x] Groq connection: `app/services/ai.py` (`complete()` and `stream()`, model `openai/gpt-oss-120b`)
- [x] Stored conversations: `chat_conversations` and `chat_messages` tables, kept across reseeds
- [x] Streaming replies over Server-Sent Events (`delta` / `done` / `error`), with a Stop button
- [x] System prompt that keeps the assistant to support work and forbids inventing data: `app/services/chat.py`
- [x] Assistant page at `/assistant`: conversation list, Markdown with tables, links per conversation

**Current limitation:** the assistant cannot see store data. Asked about an order, it says it can't look it up yet.

---

## Step 1: The agent loop ⬜

**Tool:** `get_store_overview()`: revenue, order counts, open tickets. No arguments. The numbers match the dashboard, so answers are easy to check by eye.

**What you learn**
- **The loop:** send the question with the tool list → the model answers *or* asks for a tool → run the tool, send the result back → repeat until it answers.
- **Tool definitions:** a name, a description and a JSON schema for the arguments. The description is effectively part of the prompt.
- **Streaming with tools:** the model can stream a request to call a tool instead of text.
- **Visible tool use:** a "Looked up store overview" chip in the chat, so you can watch the agent work.
- **Design decision:** are tool calls saved with the conversation, so follow-up questions can use them?

**Tasks**
- [ ] Tool registry: tool definitions plus the Python functions they call
- [ ] Agent loop in `app/services/chat.py`, with a maximum number of steps
- [ ] Stream tool activity to the UI (a new SSE event)
- [ ] Show a tool-use chip in the chat
- [ ] Decide how tool calls are stored, and update the system prompt
- [ ] Tests with a fake model that asks for the tool

**Test questions**
- "How are we doing this month?"
- "How many open tickets are there?"
- "Hi!" (should answer without calling a tool)

**Notes / what I learned**
-

---

## Step 2: Look up by ID ⬜

**Tool:** `get_order(order_number)`

**What you learn**
- **Arguments:** the model has to pull `ORD-00000002` out of the question and pass it correctly.
- **Errors as data:** an unknown order goes back to the model as a result ("not found") so it can tell the user. It does not crash the request.
- **Output size:** return only the fields that matter.

**Tasks**
- [ ] `get_order` tool with a clear description and schema
- [ ] Not-found and bad-input results returned to the model
- [ ] Tests: found, not found, badly formatted number

**Test questions**
- "What's the status of ORD-00000002?" (late-delivery scenario: shipped 12 days ago, never delivered)
- "What's in order ORD-00000001?"
- "Check order ORD-99999999" (doesn't exist)

**Notes / what I learned**
-

---

## Step 3: Search, then chain ⬜

**Tools:** `find_customer(query)`, `list_customer_orders(customer_id)`

**What you learn**
- **Multi-step reasoning:** "What did Priya order?" means finding the customer first, then their orders.
- **Ambiguity:** when the search returns several matches, the model should ask which one.
- **Limits:** cap results, and cap loop steps so a confused model can't run forever.

**Tasks**
- [ ] `find_customer` (name or email, limited results)
- [ ] `list_customer_orders` (newest first, limited results)
- [ ] Tests for chaining and for several matches

**Test questions**
- "What did priya.sharma@example.com order recently?"
- "Find customer James" (could match more than one)
- "Has Marcus Lee had any problems with his orders?"

**Notes / what I learned**
-

---

## Step 4: Tickets ⬜

**Tools:** `get_ticket(id)`, `list_tickets(status, priority)`

**What you learn**
- **Summarizing real data:** "What's urgent in the queue?"
- **Page context:** an "Ask about this ticket" button on the ticket page that opens the assistant with the ticket attached, so the agent knows what you're looking at without a tool call.

**Tasks**
- [ ] `get_ticket` with its message thread
- [ ] `list_tickets` with filters and a limit
- [ ] "Ask about this ticket" button, which passes context into the conversation

**Test questions**
- "What's urgent in the queue right now?"
- "Summarize ticket #12 and suggest a reply."
- From a ticket page: "What does this customer want?"

**Notes / what I learned**
-

---

## Step 5: Products and stock ⬜

**Tool:** `search_products(query)`

**What you learn**
- **Grounding:** the out-of-stock scenario. Stock is 0, and the agent must say so without inventing a restock date. This tests whether the prompt and tools together stop the model from making things up.

**Tasks**
- [ ] `search_products` (name, category, stock, price)
- [ ] System prompt rule about unknown facts (restock dates, delivery promises)

**Test questions**
- "Is product SCN-0003 in stock? When will it be back?" (the agent must not promise a date)
- "Which products are running low?"

**Notes / what I learned**
-

---

## Step 6: Analytics and charts ⬜

**Tools:** `sales_by_day`, `top_products` (or similar), returning rows of data

**What you learn**
- **Structured output for the UI:** the model returns a chart spec (for example a fenced ` ```chart ` block with JSON), and the frontend renders a real chart instead of text.

**Tasks**
- [ ] Analytics tools that return compact data
- [ ] Chart block format, documented in the system prompt
- [ ] Render chart blocks in `frontend/src/components/chat/ChatMarkdown.tsx`

**Test questions**
- "Show revenue for the last 30 days as a chart."
- "What were our top 5 products this month?"

**Notes / what I learned**
-

---

## Step 7: Actions with approval ⬜

**Tools, in this order:** `draft_ticket_reply` (low risk, only fills a draft), then `create_refund`, `cancel_order`

**What you learn**
- **Human in the loop:** the agent *proposes* an action, and an Approve / Reject card asks you before anything changes.
- **Backend-enforced rules:** the backend already rejects refunds above the refundable amount. The model is never the safety net.
- **Idempotency:** the same approval must never refund twice.

**Tasks**
- [ ] Proposed-action flow: the model proposes, the UI shows a card, the user approves, then the backend executes
- [ ] `draft_ticket_reply`
- [ ] `create_refund` and `cancel_order` behind approval
- [ ] Tests: rejected actions do nothing; approved ones run exactly once

**Test questions**
- Damaged item scenario: priya.sharma@example.com, `ORD-00000001`. Refund the headphones only ($199.99), not the serum.
- Partial refund limit: elena.garcia@example.com, `ORD-00000003`. Customer asks for $249.98; only $199.99 is refundable.
- Cancel request: james.okafor@example.com, `ORD-00000004`. Paid but not shipped, so cancelling is allowed.

**Notes / what I learned**
-

---

## Step 8: Evals ⬜

**What you learn:** how to know whether a prompt or tool change made the agent better or worse.

**Tasks**
- [ ] Reseed with a fixed date: `uv run shopdesk seed --anchor-date 2026-01-01`
- [ ] Script that runs the agent on the 5 built-in scenarios (see the README)
- [ ] Check the resulting database state, e.g. "refund = $199.99, not more"
- [ ] Re-run after every prompt or tool change, and record the results below

**Results log**

| Date | Change | Scenarios passed | Notes |
|---|---|---|---|
| | | | |

---

## Later ideas (not scheduled)

- Approval rules per role, once the app has logins
- Hide empty conversations, and rename conversations
- Auto-titling conversations with the model instead of using the first message
