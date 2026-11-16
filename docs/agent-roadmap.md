# ShopDesk agent roadmap

The support assistant learns one capability at a time. Each step adds **one new idea**: build it, try it with the test questions, write down what you learned, then move on.

**Status key:** ⬜ not started · 🟨 in progress · ✅ done

| # | Step | Tools | New idea | Status |
|---|---|---|---|---|
| 0 | Chat foundation | none | Streaming chat, stored conversations, system prompt | ✅ |
| 1 | The agent loop | `get_store_overview` | Tool definitions and the tool-calling loop | ✅ |
| 2 | Sales for any period | `get_sales` | Arguments the model works out (dates), combining tool results | ✅ |
| 3 | Tracing | none | See every model call, tool run, token and millisecond behind a reply | ✅ |
| 4 | Look up by ID | `get_order` | Arguments, errors as data, output size | ⬜ |
| 5 | Search, then chain | `find_customer`, `list_customer_orders` | Multi-step reasoning, ambiguity, limits | ⬜ |
| 6 | Tickets | `get_ticket`, `list_tickets` | Summarizing real data, page context | ⬜ |
| 7 | Products and stock | `search_products` | Grounding: never invent facts | ⬜ |
| 8 | Analytics and charts | `sales_by_day`, `top_products` | Structured output rendered as charts | ⬜ |
| 9 | Actions with approval | `draft_ticket_reply`, `create_refund`, `cancel_order` | Human in the loop, backend-enforced rules | ⬜ |
| 10 | Evals | none | Measuring whether a change made the agent better | ⬜ |

---

## Principles (apply to every step)

- **Tools call the service layer directly** (`app/services/...`), not ShopDesk's own HTTP API. They share the same validation and business rules.
- **Read-only before write.** No tool changes data until Step 9, and then only with human approval.
- **One step at a time.** Add the tool, try the test questions, note what happened, then move on.
- **Rules live in the backend.** The model's judgement is never the safety net; the code enforces limits (e.g. refund amounts).
- **Log every tool call and its result.** When the agent does something odd, the log tells you why.
- **Keep tool outputs small.** Return only the fields that matter; everything returned costs tokens.
- **Tools do the deterministic work.** Date ranges, totals, averages and filtering happen in code. The model picks the tool and its arguments, then puts the result into words. It never does the arithmetic.
- **Arguments as each tool needs them.** Each tool gets the arguments its questions need when it's built, not in a big pass at the end.
- **Check overlap with existing tools.** When a new tool can answer some of the same questions as an old one, update both descriptions to say which to use, or trim the old tool.
- **Comparisons share one pattern.** A tool that measures something over a period takes optional `compare_start_date` / `compare_end_date`, and builds `period` / `comparison` / `change` with the shared `compare()` helper in `tools.py`.
- **Mistakes the model can fix are results, not crashes.** Raise `ToolError("...")` with a message written for the model; `tools.run()` returns it as `{"error": ...}`.

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
- (observed) "Open tickets": the app's badge counts open + pending (2,551), but the model reported status `open` only (1,781). Fixed in the tool, not the system prompt: the field is now `tickets_now.open_tickets`, and the description defines it as "open or pending, the same number as the Tickets badge". What a field means belongs with the tool. If several tools share the term later (Step 6), move it into a glossary in the system prompt.
- (observed) A fixed tool tempts the model to do arithmetic. Asked "How did we do last week?", it took the 30-day numbers, divided by 3 and subtracted all-time refunds from 30-day revenue. Two fixes:
  - Today's date in the system prompt (`system_prompt()`, added last so the fixed text stays identical between requests).
  - A rule to report figures exactly as returned, never derive new ones, and say so when no tool has the exact period.
  
  Now it says it has no weekly figure and offers the labelled 30-day one. The real fix is a tool with date arguments (`get_sales(start_date, end_date)`, Step 2).
-

---

## Step 2: Sales for any period ✅

**Tool:** `get_sales(start_date, end_date, compare_start_date?, compare_end_date?)`: orders placed and revenue (before refunds, cancelled orders excluded) for exactly that period, computed in code.

**Why now:** Step 1 showed the gap. "Revenue in the last 10 days?" or "How did we do last week?" can't be answered from a fixed 30-day snapshot, and the model was tempted to divide and subtract.

**What you learn**
- **Arguments:** a JSON schema with dates, and a description that says the format and what "inclusive" means.
- **Arguments the model works out:** "last week" or "since Monday" become real dates.
- **Validation in code:** bad dates, end before start or a future range go back to the model as an error result it can explain or fix. They don't crash the request.
- **Combining tool results:** several calls in one turn, or two different tools (sales plus open tickets).
- **Who does the maths when combining:** the tool returns the comparison (`change`, with differences and %); the model only reports it.

**Tasks**
- [x] `get_sales` in `app/services/tools.py`, computed by `sales_totals()` in `app/services/stats.py`
- [x] Argument validation (`parse_period()`), with errors returned as data (`ToolError`)
- [x] Comparisons: optional `compare_start_date` / `compare_end_date` plus the shared `compare()` helper, instead of a rigid `compare_to_previous` flag. Prompt rule: report the `change` the tool returns.
- [x] Chip labels show the arguments ("Looked up sales, 2026-11-02 to 2026-11-08")
- [x] Overlap: the overview's description points to `get_sales` for specific periods, and vice versa
- [x] Tests: `tests/test_tools.py` (totals, comparison, every bad-argument case, labels) and two tools in one turn in `tests/test_chat.py`

**Test questions** (tried against the real model)
- "What was our revenue in the last 10 days?": correct dates (Nov 6–15)
- "How did we do last week compared to the week before?": Nov 2–8 vs Oct 26–Nov 1, with `change`
- "Revenue since the 1st of this month, and how many open tickets do we have?": both tools in one turn
- "Sales on 30 February": declines, since the date doesn't exist
- "How did October compare to September?": correct months, with `change`

**Notes / what I learned**
- (observed) The model is bad at calendar maths. For "last week" it picked Wed Nov 4 – Tue Nov 10, even though the tool description says weeks run Monday to Sunday. It also wrote "2024" in a table when the tool had returned 2026 dates.
  - **Fix:** the system prompt now ends with a calendar computed in code (`calendar()` in `chat.py`), listing this week, last week, the week before last, this month and last month as exact dates.
  - **Rule:** "Report figures **and dates** exactly as a tool returns them."
  
  After the fix, "last week" came out right in repeated runs. Same principle as before: the code does the deterministic work, including dates.
- (observed) "This week so far" returned 0 orders. That's correct: the dev data was seeded up to Nov 7. Reseed to get recent orders. Sometimes the data is the explanation, not the agent.
-

---

## Step 3: Tracing ✅

**No new tool.** Record everything behind each reply, and show it on a page.

**Why now:** from Step 5 on, the loop goes round several times (search, then look up, then answer). Twice already (the "last week" dates and the closed tickets question) we had to dig through terminal logs or the database to see what the model was given. Step 10 (evals) builds on the same data.

**What gets recorded (one trace per reply)**
- **The reply:** question, status (ok / error / stopped), total time, time until the first word, loop passes, tokens.
- **Each model call:** the exact messages sent, the tools offered and `tool_choice`, the model's reasoning text, its reply or tool requests, `finish_reason`, tokens (prompt / output / reasoning), time.
- **Each tool run:** name, arguments, result, whether it was an error, time.

**What you learn**
- What the model actually receives on each pass: the prompt grows by the tool results every time round the loop.
- Why it chose a tool (its reasoning), and where the time and tokens go (reasoning tokens vs answer tokens).
- How tracing tools like Langfuse, LangSmith and Phoenix work, by building a small one.

**Tasks**
- [x] `ai.stream()` ends every stream with a `StreamEnd`: `finish_reason`, token usage (prompt / output / reasoning), and the reasoning text gpt-oss streams in `delta.reasoning`
- [x] Trace tables (`chat_traces`, `chat_model_calls`, `chat_tool_runs`), recorded in `_agent_loop` via a `TraceRecorder` (`app/services/tracing.py`). These replace `chat_tool_calls`; chips now come from the trace.
- [x] Traces are saved for failed (`error`) and stopped (`stopped`) replies too
- [x] API: `GET /api/traces` and `GET /api/traces/{id}` (`app/routers/traces.py`)
- [x] UI: a "Details" link on each reply, a **Traces** page (list), and a trace page with stats, a time bar, and a step-by-step timeline: the prompt sent (new messages highlighted), reasoning, tool requests, tool arguments and results
- [x] Tests: `tests/test_traces.py`

**How to use it**
- After any odd answer: **Details** under the reply, then read the reasoning of each model call. It says *why* a tool was or wasn't chosen.
- "Prompt sent": the messages marked **new this call** show how the prompt grows round the loop.
- The Traces list: sort by eye for slow replies (Time) or expensive ones (Tokens).

**Notes / what I learned**
- (observed) **Reasoning tokens are most of the output.** A 3-word "hi" cost 89 output tokens, 76 of them hidden reasoning. You pay for (and wait for) thinking the user never sees.
- (observed) **The model calls tools one at a time.** For "revenue since the 1st, and open tickets?" its reasoning planned both tools in call 1, but it asked for `get_sales`, then `get_store_overview` in call 2, then answered in call 3. Each pass re-sends the whole prompt (1,375 → 1,470 → ~1,900 tokens in), so the reply cost ~5,000 tokens. Asking for both at once would save a pass. Something to try in the prompt or tool descriptions, then measure here.
- (observed) **The system prompt is the bulk of every call.** About 1,300 of the ~1,400 input tokens on a first call, re-sent every pass. Keep it tight; prompt caching would help if the provider supports it.
- (observed) **Stop isn't instant through the dev proxy.** A reply stopped in the browser via Vite's proxy kept generating for ~30 s on the server (its trace says 32 s) before the server noticed. Disconnecting directly was noticed in ~2 s. The server can't stop what it doesn't know about. A real "cancel" call would fix it if it matters.
- (observed) The old `chat_tool_calls` table may still exist in an existing database. It's no longer used and is safe to drop.
-

---

## Step 4: Look up by ID ⬜

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

## Step 5: Search, then chain ⬜

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

## Step 6: Tickets ⬜

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

## Step 7: Products and stock ⬜

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

## Step 8: Analytics and charts ⬜

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

## Step 9: Actions with approval ⬜

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

## Step 10: Evals ⬜

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
