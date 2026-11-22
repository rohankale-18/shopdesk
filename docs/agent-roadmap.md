# ShopDesk agent roadmap

The support assistant learns one capability at a time. Each step adds **one new idea**: build it, try it with the test questions, write down what you learned, then move on.

**Status key:** ⬜ not started · 🟨 in progress · ✅ done

| # | Step | Tools | New idea | Status |
|---|---|---|---|---|
| 0 | Chat foundation | none | Streaming chat, stored conversations, system prompt | ✅ |
| 1 | The agent loop | `get_store_overview` | Tool definitions and the tool-calling loop | ✅ |
| 2 | Sales for any period | `get_sales` | Arguments the model works out (dates), combining tool results | ✅ |
| 3 | Tracing | none | See every model call, tool run, token and millisecond behind a reply | ✅ |
| 4 | Look up by ID | `get_order` | Arguments, errors as data, output size | ✅ |
| 5 | Search, then chain | `find_customer`, `list_customer_orders` | Multi-step reasoning, ambiguity, limits | ✅ |
| 6 | Tickets | `get_ticket`, `list_tickets` | Summarizing real data, page context | ✅ |
| 7 | Products and stock | `search_products` | Grounding: never invent facts | ✅ |
| 8 | Analytics and charts | `sales_by_day`, `top_products` | Structured output rendered as charts | ⬜ |
| 9 | Actions with approval | `draft_ticket_reply`, `create_refund`, `cancel_order` | Human in the loop, backend-enforced rules | ⬜ |
| 10 | Evals | none | Measuring whether a change made the agent better | ⬜ |
| 11 | Flexible queries | `query_orders` (and maybe `run_sql`) | One tool for many questions: a structured query the code turns into SQL | ⬜ |

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
- (observed) "Open tickets": the app's badge counts open + pending (2,551), but the model reported status `open` only (1,781). Fixed in the tool, not the system prompt: the field is now `tickets_now.open_tickets`, and the description defines it as "open or pending, the same number as the Tickets badge". What a field means belongs with the tool. If several tools share the term later (Step 6), move it into a glossary in the system prompt. Done in Step 6 ("## ShopDesk terms").
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
- (observed) **Asked to "compare all the values", the model made up a table.** For September vs October, `get_sales` only returned orders and revenue. The model added rows for open tickets, tickets resolved, low-stock products and refunds, all invented, plus an average order value it worked out itself. Its reasoning had even said *"we can say we only have those metrics available"*. The final call then filled the table anyway. A prompt rule ("only state numbers from tools") doesn't hold when the user asks for more than the tools have.
  - **Fix 1, give the tool the figures:** `get_sales` now also returns average order value, cancelled orders and refunds issued in the period, all computed in code. "All the values" now has a real answer. Tickets stay out: they aren't sales, and they come in Step 6.
  - **Fix 2, prompt:** when asked for "everything", report what the tools returned and list what isn't available. Never put a number in a cell that isn't in a tool result.
  - **Fix 3, catch it:** the trace page flags numbers in the answer that don't appear in any tool result (see Step 3).
  
  After the fixes, the same question got a full table with every number from the tool.
- (observed) **Real numbers, wrong direction.** The model passed September as the main period and October as the comparison. It then reported September minus October as "October vs September", so revenue appeared to fall 15% when it rose 18%. The grounding check can't catch this, because every number was real. **Fix:** the description says to put the later period first, and the result includes `change_means`, which states which way round the change is (for example "2026-10-01 to 2026-10-31 compared with 2026-09-01 to 2026-09-30"). After that, the direction came out right.
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
- [x] Token breakdown on the trace page ("Where the tokens went"), using only what Groq reports:
  - output split into reasoning and the visible answer or tool requests;
  - per call: input, output, and Groq's own timings (queue, reading the input, writing the output), plus output speed in tokens/s;
  - the trace list shows tokens in and tokens out separately.
- [x] `init_db()` adds new nullable columns to existing tables (`_add_new_columns` in `app/db.py`), so an older database picks up new trace fields without a reset. It's a minimal migration, not a migration tool.
- [x] **Grounding check:** the trace page lists the numbers in the answer that appear in no tool result and no message the model was sent, and highlights them in the answer (`app/services/grounding.py`). It runs when a trace is read, so older traces get it too. Dates, list numbering and rounding (17.9 → "18%") don't count as unsupported.
  - Catches invented figures and figures the model worked out itself (like an average it calculated).
  - Misses small numbers that happen to appear elsewhere. In the made-up table, "5 open tickets" passed because a 5 appeared in an earlier message. It also can't tell a real number used wrongly, like a change reported in the wrong direction.
  - Treat a flag as worth a look, not as proof of a mistake.
- Tried and removed: splitting the input by part (system prompt, tool definitions, history, tool results). Groq gives the input as one total, so the split could only be estimated. I dropped it to keep the page to exact numbers. "Prompt sent" already shows what's in each call.

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
- (observed, from the estimate before it was removed) **The fixed parts dominate the input.** For a two-call follow-up question, the input was 3,133 tokens:
  - system prompt about 47%
  - tool definitions about 32%
  - earlier messages and tool results under 10% each
  - the question itself about 1%

  Each tool adds roughly 170 tokens to every call, so the fixed parts are worth keeping lean as the tool count grows.
- (observed) **Groq's own time is small; the rest is waiting.**
  - Reading 1,400 input tokens takes about 10–80 ms.
  - Writing runs at about 120–460 tokens/s.
  - Queue time varies from 50 to 280 ms.
  - On top of that is the network: a call Groq timed at about 1.2 s took 1.3 s end to end.

  Fewer passes round the loop saves more time than anything else.
-

---

## Step 4: Look up by ID ✅

**Tool:** `get_order(order_number)`: one order with its status, customer, timeline, items, money, refunds and linked tickets.

**What you learn**
- **Arguments:** the model has to pull `ORD-00000002` out of the question and pass it correctly.
- **Errors as data:** an unknown order goes back to the model as a result ("not found") so it can tell the user. It does not crash the request.
- **Output size:** return only the fields that matter.

**Tasks**
- [x] `get_order` in `app/services/tools.py`, with a description and schema
- [x] Number formats fixed in code: `normalize_order_number()` turns `ORD-2`, `#2` and `2` into `ORD-00000002`
- [x] Not-found and bad-format results returned to the model (`ToolError`)
- [x] Output:
  - dates come with `days_ago`, computed in code
  - money includes `still_refundable_usd`
  - linked tickets are listed
  - no email, phone or address, because these questions never need them
- [x] Overlap: the overview's description points to `get_order` for single orders
- [x] Tests in `tests/test_tools.py`: the late-delivery and partial-refund scenarios, every number format, not found, bad format, and the label

**Test questions** (tried against the real model, after a reseed)
- "What's the status of ORD-00000002?": shipped 12 days ago, not delivered, with the tracking number
- "What's in order ORD-00000001?": the two items in a table, with the total
- "Check order ORD-99999999": says it can't find it and asks the user to check the number. The trace flags the tool run as an error.
- "Can you look up order #3 and tell me how much more I can refund?": $199.99, since $49.99 was already refunded
- "What's going on with order 2? Is there a ticket about it?": the order and its open ticket
- "Where's my order?": no tool call; it asks for the number

**Notes / what I learned**
- (observed) **The model only knows what the description says.** The code already accepted `#3`, but the description only showed `ORD-00001234`. So for "order #3" the model asked the user for the full number instead of calling the tool. Once the description listed the accepted forms (`ORD-00001234`, `#1234`, `order 1234`), the model passed `"3"` and the code handled the rest. If the description doesn't mention something the tool can do, the model won't use it.
- **Fix formats in code, not in the prompt.** Asking the model to pad numbers to 8 digits would be one more thing it could get wrong. This is the same principle as the dates in Step 2.
- **`days_ago` in the result** lets the model say "shipped 12 days ago" without doing date maths.
- (observed) **Whether an order is late is a business rule.** For "what's going on with order 2?", the model said the order "is on its way", although it shipped 12 days ago and hasn't arrived. The data was right, but the reading was too generous. If lateness matters, the tool should flag it (for example `delivery_late: true` after N days) instead of leaving it to the model. Done in Step 6: `delivery_late` after 7 days.
-

---

## Step 5: Search, then chain ✅

**Tools:**
- `find_customer(query)`: up to 5 matches by part of a name or email, each with id, email, tier, location and order count.
- `list_customer_orders(customer_id)`: the newest 10 orders, each with status, date placed (with days ago), item count, total, amount refunded and its tickets, plus the customer's total order count.

**What you learn**
- **Multi-step reasoning:** "What did Priya order?" means finding the customer first, then their orders.
- **Ambiguity:** when the search returns several matches, the model should ask which one.
- **Limits:** cap results, and cap loop steps so a confused model can't run forever.

**Tasks**
- [x] `find_customer` (name or email, any case, partial; at most 5 matches, plus the total)
- [x] `list_customer_orders` (newest first, at most 10, plus the total and "showing newest 10 of N")
- [x] Search outcomes:
  - **No match** is a result, not an error. A search that finds nothing is a valid answer. The result includes `next_step` ("ask for an email or another spelling").
  - **Several matches** also get a `next_step`: ask the user which one, and don't pick.
  - **An unknown customer id** is an error ("get the id from find_customer first"), because the model can fix it.
- [x] Loop cap: `MAX_STEPS = 5` from Step 1 already covers this. A search-then-list question uses 3 calls.
- [x] Tests:
  - `tests/test_tools.py`: by name or email, several matches, no match, too short, newest first, cap, bad ids
  - `tests/test_chat.py`: a fake model that reads the id out of the search result and passes it on, which is the chain itself

**Test questions** (tried against the real model, after a reseed)
- "What did priya.sharma@example.com order recently?": `find_customer`, then `list_customer_orders(1)`. Her latest order, with the open cracked-headband ticket.
- "Has Marcus Lee had any problems with his orders?": the open "Still waiting for my lamp" ticket on ORD-00000002, and his other orders have none.
- "What did Priya order?": the same chain, with 5 orders in a table.
- "What has Mark ordered?": three Marks found, so it asked which one by email. Then "the first one" worked.
- "Find customer Zebediah": no match, so it asked for an email or another spelling.
- The grounding check flagged nothing on any of them.

**Notes / what I learned**
- (observed) **The chain works without being told how.** Each tool description says what it needs and where to get it ("needs the customer id from find_customer"), and the model strings the calls together itself: search, read the id, list, answer. No prompt changes were needed.
- (observed) **`next_step` in a result steers the model at the moment it matters.** With three Marks, it asked instead of guessing. Putting the instruction in the result means it only shows up when it applies.
- (observed) **Follow-ups repeat lookups.** After "the first one", the model ran `find_customer("Mark")` again before listing orders. Old tool results aren't replayed in later turns (a Step 1 decision), so the earlier ids weren't in its context. It cost one extra call. The alternative is keeping ids in the answer text, or replaying results, which grows every prompt.
- (observed) **Rate limits look like slow calls.** Some replies took 30–40 s, while Groq's own time per call was under 1 s. The server log showed `429 Too Many Requests`, and the Groq SDK quietly waited up to 16 s before retrying. A search-then-list question uses about 6,000 tokens, so a few in a row hit the plan's tokens-per-minute limit. The trace doesn't show the retries yet. A hint would be "call time minus Groq's own time = waiting", or logging retries.
-

---

## Step 6: Tickets ✅

**Tools:**
- `get_ticket(ticket_id)`: one ticket with its message thread, the customer, and the order it's about.
- `list_tickets(status?, priority?, category?, customer_id?, limit?)`: the queue, most urgent first, then the one waiting longest.

**What you learn**
- **Summarizing real text:** a ticket thread is words a person wrote, not figures. The risk moves from made-up numbers to made-up *facts*: "we've refunded you", "it's in transit".
- **Page context:** the "Ask about this ticket" button opens the assistant with the ticket attached. The app supplies the context, so the model doesn't have to fetch it.

**Tasks**
- [x] `get_ticket`:
  - the latest 20 messages, oldest first;
  - `waiting_on`, who has to act next, worked out from who wrote last;
  - the order with `delivery_late`.
- [x] `list_tickets`:
  - filters are lists of allowed values, and typos go back to the model as `ToolError`;
  - with no status, it lists ShopDesk's "open tickets" (open or pending);
  - capped at 10, with the total and a count per priority.
- [x] **`delivery_late`** in code, also on `get_order`: shipped more than `LATE_AFTER_DAYS` (7) days ago and not delivered. In the seed data, delivery takes 2–6 days. This fixes the Step 4 "it's on its way" reading.
- [x] **Shared terms** in the system prompt ("## ShopDesk terms"): open tickets, `waiting_on` and `delivery_late`. The "open tickets" definition moved out of `get_store_overview`'s description (the Step 1 note).
- [x] **Drafting rules** in the system prompt ("## Drafting replies to customers"): only facts from the data, no claims that anything was done, placeholders instead of promises, no internal field names, and a short "decide or check before sending" list after each draft.
- [x] **Page context:**
  - `chat_conversations.ticket_id`;
  - `POST /api/chat/conversations` takes `{"ticket_id": 12}`;
  - `page_context()` in `chat.py` adds the ticket's current `get_ticket` data as a second system message on every turn;
  - the title starts with "#12:".
- [x] **UI:**
  - an "Ask about this ticket" button on the ticket page, which opens `/assistant?ticket=12`;
  - an "About ticket #12" box above the composer until the first message is sent, with an × to detach it;
  - after that, the box sits above the first message, like an attached image;
  - ticket-specific suggestions.
- [x] Field names in plain words in every answer ("the delivery is late", not `delivery_late = true`), a rule under "## ShopDesk terms"
- [x] **Grounding check now also reads** the page context and the descriptions of the tools offered. Numbers like "7 days" come from there.
- [x] Overlap: `get_order` and `get_store_overview` point to `get_ticket` and `list_tickets`.
- [x] Tests:
  - tools: thread, order, `waiting_on`, sort order, filters, the cap, bad filters, labels, `delivery_late`;
  - chat: the context is sent every turn, an unknown ticket gets a 404;
  - traces: context numbers count as grounded.

**Test questions** (tried against the real model)
- "What's urgent in the queue right now?": `list_tickets(priority=["urgent"])`, one ticket, correct.
- "How many open tickets are there?": 29 (17 open + 12 pending). The shared definition held.
- "Summarize ticket #2 and suggest a reply.": `get_ticket`, a summary with `delivery_late`, then a draft with a checklist.
- From ticket #2: "What does this customer want?", then "Draft a reply": **1 model call, no tools.** The page context was enough.
- From ticket #3 (Elena wants $249.98; $199.99 is left): "Suggest a reply". Before the drafting rules it promised the refund; after them it didn't.

**Notes / what I learned**
- (observed) **Page context saves a pass round the loop.** From the ticket page, "What does this customer want?" took 1 model call and about 2,600 tokens. Asking about "ticket #2" from a blank chat took 2 calls and about 5,200 tokens. No ambiguity either: "this customer" can only mean one person. The cost is that the ticket goes into every turn, even when it isn't needed.
- (observed) **A general rule didn't stop made-up facts in drafts.** With one line ("don't promise refunds… leave a [placeholder]"), the drafts said:
  - "I'll go ahead and initiate the refund for the remaining balance… within a few business days" (Elena);
  - "I'm contacting the carrier now", "I'll follow up within the next 24 hours" and "still marked as 'in transit'" (Marcus);
  - "currently marked as **delivery-late**", an internal field name shown to the customer.
  
  The amounts were all right; the commitments weren't. A dedicated section with concrete rules fixed most of it. The key was framing: *a draft is for the agent to send, and nothing has been done yet.* The "what to decide or check before sending" list gives the model somewhere to put the decision instead of making it.
- (observed) **What's left:** drafts still say "I'm checking with the carrier… I'll follow up shortly". That's milder, and the checklist tells the agent to check first, but the model is still speaking for the agent. Prompt rules reduce this; they don't guarantee it. Step 9 (approval before anything is sent) and Step 10 (evals) are the real safety nets.
- (observed) **The grounding check caught the made-up promise.** It flagged "24" ("within 24 hours"). It also flagged "7" from "late after 7 days", which is real: it's in the tool description. The check now reads tool descriptions too. It still can't catch claims without numbers, like "I'm contacting the carrier".
- (observed) Rate limits again: 8 retries after 429 responses during the test run, which made some single calls take about 20 s. Same cause as in Step 5.
- (decision) **The ticket goes with every message, but it's shown on the first one.** The model keeps nothing between messages: the app re-sends the conversation as text, without earlier tool data. If the ticket went only with the first message, follow-ups like "Draft a reply" would depend on whatever the first answer happened to say. In the UI it sits above the first message, like an attachment in ChatGPT. A box that stayed above the composer made every message look like it was about the ticket.
- (observed) Field names leaked into answers to the agent too ("**delivery_late = true**"), not just drafts. The rule now covers every answer.
- (decision) `ticket_id` on a conversation is a plain number, not a foreign key. Chats survive a reseed, which recreates the tickets, so after a reseed the id can point at a different ticket. The bar then shows the new ticket's subject, or "no longer exists".

---

## Step 7: Products and stock ✅

**Tool:** `search_products(query?, category?, stock?)` finds products by name, SKU, category or stock level. It returns price, stock, `stock_status` and description, at most 10, with the total.

**What you learn**
- **Inventing facts without numbers:** a restock date, a product feature, a product that doesn't exist, a store service that doesn't exist. The grounding check can't see any of these, so the tool and the prompt have to prevent them.
- **What the data doesn't record has to be said out loud.** A gap the model isn't told about is a gap it fills.

**Tasks**
- [x] One stock rule in `stats.py`, used by the dashboard and the tools:
  - `LOW_STOCK = 5`;
  - `stock_status()` returns `not_for_sale`, `out_of_stock`, `low` (1–5 left) or `in_stock`.
- [x] `search_products`:
  - `stock` filter: `available`, `out_of_stock`, `low` or `in_stock`;
  - with a stock filter, fewest left first;
  - every result includes `not_recorded`: no restock dates, incoming stock, suppliers, specs beyond the description, back-in-stock alerts or waiting lists;
  - a search with no match says not to repeat it.
- [x] `get_store_overview`'s low-stock list gets `stock_status` too, and its description points to `search_products`.
- [x] Prompt:
  - unrecorded facts: say ShopDesk doesn't have them, never "usually" or "typically";
  - "low stock" added to the terms;
  - drafts mention only products a tool returned, and offer no services the data doesn't show;
  - a "does the lamp have a dimmer?" example that is in scope.
- [x] UI: a chat opened from a ticket with no order offers "Other tickets" instead of "Check the order", and doesn't mention an order in its subtitle. Found while testing in the browser with the Playwright MCP.
- [x] Tests: search by name or SKU, the low-stock rule matching the overview and the prompt, `available` = `low` + `in_stock`, not-for-sale products, category, no match, bad filters, labels.

**Test questions** (tried against the real model)
- "Is the Grip Pro Yoga Mat in stock? When will it be back?": "out of stock (0)… ShopDesk does not record restock dates." No date given.
- "Which products are running low?": `stock="low"`, all 10, fewest first.
- "Does the Halo Desk Lamp have a dimmer?": "the description doesn't say". It still adds a line like "I can help with any order, ticket…", which is harmless but unneeded.
- From ticket #5 (the yoga mat): "Suggest a reply". The final version, 3 runs out of 3, suggests the real in-stock alternative (Foldable Yoga Mat, $30.99) and gives no restock date.

**Notes / what I learned**
- (observed) **The first draft invented a product and a feature.** It suggested a "Comfort Grip Mat" (no tool had returned it) and "sign up for a back-in-stock alert on the product page" (no such thing). It also promised to "keep an eye on the inventory". The model had only searched for the yoga mat. Fix: drafts mention only products a tool returned, and look up alternatives first.
- (observed) **Groq checks tool arguments against the schema before we see them.** The model sent `category: "sports"` where the schema said array. Groq aborted the whole reply with an error, so the user saw "Something went wrong", and our `ToolError` handling never ran. A schema mismatch is a hard failure, not a mistake the model can fix. Fix: `category` became a single value, the shape the model reached for. `list_tickets` still uses arrays (the model has sent those correctly so far); watch for the same error there.
- (observed) **A filter with the wrong meaning made the model loop.** To find alternatives it asked for `stock="in_stock"`, which means more than 5 left. That excluded the only other mat (2 left). It then repeated nearly the same search 4 times and hit `MAX_STEPS` (5 calls, 17,500 tokens). Fixes: an `available` filter (anything that can be bought now), and a no-match result that says not to repeat the search. After that: 3 calls, about 10,500 tokens, and the real alternative found.
- (observed) **Stating the gap in the tool result beat a prompt rule, again.** With only the prompt rule ("don't offer services the data doesn't show"), one draft still offered "a notification list". Its own checklist even mentioned the `[offer, if any]` placeholder. Once `not_recorded` said "no back-in-stock alerts or waiting lists", none of 3 runs offered it. Same lesson as `change_means` and `next_step`.
- (observed) **Small inventions remain:** "It's a popular option" (2 of 3 runs) and "reserve one" (1 of 3). These are mild, and Step 6 had the same kind ("I'm checking with the carrier"). Catching them reliably needs evals (Step 10), probably with a model grading the draft against the tool results.

---

## Step 8: Analytics and charts ⬜

**Tools:** `sales_by_day`, `top_products` (or similar), returning rows of data

**What you learn**
- **Structured output for the UI:** the model returns a chart spec (for example a fenced ` ```chart ` block with JSON), and the frontend renders a real chart instead of text.

**Tasks**
- [ ] Analytics tools that return compact data
- [ ] Chart block format, documented in the system prompt
- [ ] Render chart blocks in `frontend/src/components/chat/ChatMarkdown.tsx`
- [ ] Check against Step 11 first: if `query_orders` will cover "by day" and "top N", build just enough here for the charts, and avoid two tools that answer the same question.

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
- [ ] Regression cases from real failures:
  - "compare order values in September vs October", then "compare all the values". Pass: no grounding flags, and the change is reported as October vs September with revenue up.
  - From ticket #5 (the yoga mat): "Suggest a reply". Pass: no restock date, no alerts or waiting lists, and alternatives only from a `search_products` result.
  - "highest order value this year in each month". Until Step 11: pass if it says no tool can answer and invents nothing. After Step 11: one call, every month's largest order, no grounding flags.

**Results log**

| Date | Change | Scenarios passed | Notes |
|---|---|---|---|
| | | | |

---

## Step 11: Flexible queries ⬜

**Tools:** `query_orders` (structured), and optionally `run_sql` (raw, read-only) as an experiment

**Why:** one tool per question doesn't scale. "Highest order value this year in each month" failed because no tool could see individual orders across the store: `get_sales` only returns totals, and `get_order` / `list_customer_orders` need a number or a customer first. The model honestly said it couldn't answer, which was correct, but every new kind of question would otherwise need a new tool.

**What you learn**
- **Three ways to answer data questions:**
  - fixed tools (Steps 1–7): exact, but narrow;
  - a structured query, where the model fills in fields and the code writes the SQL: wide and still safe;
  - text-to-SQL, where the model writes the SQL: widest, but riskiest.
- **A semantic layer:** business terms ("revenue", "order value", "month") are defined once in code, so every answer uses the same rules (cancelled orders excluded, cents to dollars, which timezone a month is in). This is how BI tools like Looker and Cube work.
- **Quietly wrong answers:** SQL that runs and returns a number, but the wrong one (cancelled orders included, refunds counted twice by a join). The grounding check can't catch these, since the number did come from a tool. Only evals can.

**Tasks**
- [ ] `query_orders(metric, group_by?, filters?, start_date, end_date, sort?, limit?)`, built from whitelists:
  - metrics: `count`, `revenue`, `average_order_value`, `max_order_value`, `refunded`, …
  - group by: `day`, `week`, `month`, `status`, `customer_tier`, `country`, `product`, …
  - The code builds the query with SQLAlchemy, reusing the rules in `stats.py`. Each new field is one line in a whitelist, not a new tool.
- [ ] Return the order behind each `max`/`min` (number, customer, value), so the model can name it and follow up with `get_order`
- [ ] Row cap and a `total_rows` field, same as the other list tools
- [ ] Overlap: decide what `get_sales` and the Step 8 tools still do once this exists, and update the descriptions
- [ ] Optional experiment, `run_sql`, behind a setting:
  - read-only connection (`PRAGMA query_only`), `SELECT` only, row limit and timeout
  - no customer email or address columns in the schema it's shown
  - run the Step 10 evals against both `run_sql` and `query_orders` and compare where it gets things quietly wrong
- [ ] Tests: each metric and group-by against hand-counted totals, unknown fields go back as `ToolError`

**Test questions**
- "Highest order value this year in each month."
- "Revenue by customer tier last quarter."
- "Our 5 biggest orders last week, and who placed them?" (then a follow-up with `get_order`)
- "How many orders were cancelled each week in October?"

**Notes / what I learned**
-

---

## Later ideas (not scheduled)

- Approval rules per role, once the app has logins
- Hide empty conversations, and rename conversations
- Auto-titling conversations with the model instead of using the first message
