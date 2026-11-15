# ShopDesk agent roadmap

The support assistant learns one capability at a time. Each step adds **one new idea**: build it, try it with the test questions, write down what you learned, then move on.

**Status key:** ⬜ not started · 🟨 in progress · ✅ done

| # | Step | Tools | New idea | Status |
|---|---|---|---|---|
| 0 | Chat foundation | none | Streaming chat, stored conversations, system prompt | ✅ |
| 1 | The agent loop | `get_store_overview` | Tool definitions and the tool-calling loop | ✅ |
| 2 | Sales for any period | `get_sales` | Arguments the model works out (dates), combining tool results | ⬜ |
| 3 | Look up by ID | `get_order` | Arguments, errors as data, output size | ⬜ |
| 4 | Search, then chain | `find_customer`, `list_customer_orders` | Multi-step reasoning, ambiguity, limits | ⬜ |
| 5 | Tickets | `get_ticket`, `list_tickets` | Summarizing real data, page context | ⬜ |
| 6 | Products and stock | `search_products` | Grounding: never invent facts | ⬜ |
| 7 | Analytics and charts | `sales_by_day`, `top_products` | Structured output rendered as charts | ⬜ |
| 8 | Actions with approval | `draft_ticket_reply`, `create_refund`, `cancel_order` | Human in the loop, backend-enforced rules | ⬜ |
| 9 | Evals | none | Measuring whether a change made the agent better | ⬜ |

---

## Principles (apply to every step)

- **Tools call the service layer directly** (`app/services/...`), not ShopDesk's own HTTP API. They share the same validation and business rules.
- **Read-only before write.** No tool changes data until Step 8, and then only with human approval.
- **One step at a time.** Add the tool, try the test questions, note what happened, then move on.
- **Rules live in the backend.** The model's judgement is never the safety net; the code enforces limits (e.g. refund amounts).
- **Log every tool call and its result.** When the agent does something odd, the log tells you why.
- **Keep tool outputs small.** Return only the fields that matter; everything returned costs tokens.
- **Tools do the deterministic work.** Date ranges, totals, averages and filtering happen in code. The model picks the tool and its arguments, then puts the result into words. It never does the arithmetic.
- **Arguments as each tool needs them.** Each tool gets the arguments its questions need when it's built, not in a big pass at the end.

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

## Step 1: The agent loop ✅

**Tool:** `get_store_overview()`: revenue, order counts, open tickets. No arguments. The numbers match the dashboard, so answers are easy to check by eye.

**What you learn**
- **The loop:** send the question with the tool list → the model answers *or* asks for a tool → run the tool, send the result back → repeat until it answers.
- **Tool definitions:** a name, a description and a JSON schema for the arguments. The description is effectively part of the prompt.
- **Streaming with tools:** the model can stream a request to call a tool instead of text.
- **Visible tool use:** a "Looked up store overview" chip in the chat, so you can watch the agent work.
- **Design decision:** are tool calls saved with the conversation, so follow-up questions can use them?

**Tasks**
- [x] Tool registry: tool definitions plus the Python functions they call (`app/services/tools.py`)
- [x] Agent loop in `app/services/chat.py`, with a maximum number of steps (`MAX_STEPS = 5`)
- [x] Stream tool activity to the UI (a new SSE event: `tool`)
- [x] Show a tool-use chip in the chat
- [x] Decide how tool calls are stored, and update the system prompt
- [x] Tests with a fake model that asks for the tool (`tests/test_chat.py`, "the agent loop" section)

**How it fits together**
1. `services/ai.py` `stream()` now takes `tools`. It yields text as it arrives, and a `ToolCall` for each tool the model asks for (assembled from pieces, at the end of the stream).
2. `services/chat.py` `_agent_loop()`: if the model asked for tools, it adds the request and each result to the messages, then calls the model again. The last allowed call uses `tool_choice="none"`, so the model has to answer.
3. `services/tools.py`: each `Tool` has a name, a label for the UI, a description and a JSON schema (what the model sees), plus `run` (what we execute). `run()` never raises: errors go back to the model as `{"error": ...}`.
4. `routers/chat.py` sends a `tool` event for each run and saves the runs with the reply.
5. The dashboard numbers moved to `services/stats.py`, so the dashboard and the tool share the same code.

**Decisions made**
- **Storage:** each tool run is saved in a new `chat_tool_calls` table (name, arguments, result), linked to the assistant message. It drives the chips after a reload and works as a log.
- **History:** tool results are *not* replayed in later turns, only the text of past answers. Store data changes, so the model should look it up again rather than trust an old result.
- **System prompt:** the "no data access" rule became "use tools for real data; only state numbers that came from a tool; say so if no tool can answer".

**Test questions** (tried against the real model)
- "How are we doing this month?": calls the tool, answers with a table
- "How many open tickets are there?": calls the tool
- "Hi!": answers without a tool
- "What's the status of ORD-00000002?": no tool for this yet, so it says it can't look it up

**Notes / what I learned**
- (observed) The first version returned flat keys like `revenue_usd` and `open_tickets`. The model reported 30-day revenue as "after refunds", put all-time order counts under "this month", and misread the ticket numbers. Grouping the output by period with explicit names (`all_time`, `last_30_days.revenue_before_refunds_usd`, `tickets_now.open_or_pending`) fixed all three. Tool output is part of the prompt.
- (observed) "Open tickets": the app's badge counts open + pending (2,551), but the model reported status `open` only (1,781). Fixed in the tool, not the system prompt: the field is now `tickets_now.open_tickets`, and the description defines it as "open or pending, the same number as the Tickets badge". What a field means belongs with the tool. If several tools share the term later (Step 5), move it into a glossary in the system prompt.
- (observed) A fixed tool tempts the model to do arithmetic. Asked "How did we do last week?", it took the 30-day numbers, divided by 3 and subtracted all-time refunds from 30-day revenue. Two fixes:
  - Today's date in the system prompt (`system_prompt()`, added last so the fixed text stays identical between requests).
  - A rule to report figures exactly as returned, never derive new ones, and say so when no tool has the exact period.
  
  Now it says it has no weekly figure and offers the labelled 30-day one. The real fix is a tool with date arguments (`get_sales(start_date, end_date)`, Step 2).
-

---

## Step 2: Sales for any period ⬜

**Tool:** `get_sales(start_date, end_date)`: orders placed and revenue for exactly that period, computed in code.

**Why now:** Step 1 showed the gap. "Revenue in the last 10 days?" or "How did we do last week?" can't be answered from a fixed 30-day snapshot, and the model was tempted to divide and subtract.

**What you learn**
- **Arguments:** a JSON schema with two dates, and a description that says the format and what "inclusive" means.
- **Arguments the model works out:** "last week" or "since Monday" become real dates, using today's date from the system prompt.
- **Validation in code:** bad dates, end before start or a future range go back to the model as an error result it can explain or fix. They don't crash the request.
- **Combining tool results:** several calls in one turn (e.g. this week *and* last week to compare), or two different tools (sales plus open tickets).
- **Who does the maths when combining:** the "no arithmetic" rule meets comparisons. The tool returns the derived figures (e.g. a previous-period comparison); the model only puts them side by side.

**Tasks**
- [ ] `get_sales` in `app/services/tools.py`, computed in `app/services/stats.py`
- [ ] Argument validation, with errors returned as data
- [ ] Decide how comparisons work (a `compare_to_previous` option, or two calls), and adjust the system prompt rule
- [ ] Tests: a valid range, a bad range, two calls in one turn

**Test questions**
- "What was our revenue in the last 10 days?"
- "How did we do last week compared to the week before?"
- "Revenue since the 1st of this month, and how many open tickets do we have?" (two tools)
- "Sales on 30 February" (invalid date)

**Notes / what I learned**
-

---

## Step 3: Look up by ID ⬜

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

## Step 4: Search, then chain ⬜

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

## Step 5: Tickets ⬜

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

## Step 6: Products and stock ⬜

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

## Step 7: Analytics and charts ⬜

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

## Step 8: Actions with approval ⬜

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

## Step 9: Evals ⬜

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
