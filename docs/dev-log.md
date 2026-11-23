# ShopDesk dev log

What each commit did and why, oldest first. Read it top to bottom to see how the agent was built. The roadmap ([agent-roadmap.md](agent-roadmap.md)) has the plan and the detailed notes for each step; this log is the short story of what actually landed.

Entries are titled with the commit's date and message; `git log --oneline` gives the hash. Earlier entries show the hash too.

Each entry covers:
- **Done:** what changed.
- **Why:** the problem it solved.
- **Learned:** the main lesson.
- **Where:** the files to read.

---

## 31967f0 · 2026-11-14 · Shopdesk setup

**Done:** the base app. FastAPI backend, SQLite with SQLAlchemy, a seed command that generates customers, orders, refunds, tickets and products, and a React (Vite) frontend with the dashboard, orders, customers and tickets pages.

**Why:** a realistic store with real-looking data, so the agent has something to answer questions about.

**Where:** `backend/app/models.py`, `backend/app/services/seed.py`, `frontend/src/pages/`

---

## 1aa0eef · 2026-11-14 · Chat UI and backend wiring for agent (Step 0)

**Done:**
- A Groq connection (`openai/gpt-oss-120b`) with `complete()` and `stream()`.
- Stored conversations (`chat_conversations`, `chat_messages`).
- Replies streamed over Server-Sent Events, with a Stop button.
- The Assistant page.
- A system prompt that keeps the assistant to support work and forbids inventing data.

**Why:** a working chat before adding any tools. At this point the assistant can't see store data.

**Where:** `backend/app/services/ai.py`, `backend/app/services/chat.py`, `backend/app/routers/chat.py`, `frontend/src/pages/Assistant.tsx`

---

## 76191a2 · 2026-11-14 · Agent roadmap

**Done:** `docs/agent-roadmap.md`, the plan of steps, each adding one new idea, plus principles that apply to every step.

---

## 8d5b7bf · 2026-11-15 · Initial agent loop setup (Step 1)

**Done:**
- **Tool registry** (`tools.py`): each tool has a name, a label for the UI, a description, a JSON schema, and the Python function it runs.
- **The first tool,** `get_store_overview`.
- **The agent loop** (`_agent_loop` in `chat.py`): ask the model, run any tools it asks for, send back the results, repeat. At most 5 passes; the last pass forces a text answer.
- **Tool chips** in the chat, sent as a new `tool` event.
- The dashboard numbers moved into `stats.py`, so the dashboard and the tool share the same code.

**Why:** the core of any agent. The model decides when it needs data and asks for it.

**Learned:**
- **Tool output is part of the prompt.** Flat keys like `revenue_usd` were misread. Grouped, clearly named fields (`last_30_days.revenue_before_refunds_usd`) fixed it.
- **A fixed tool tempts the model to do arithmetic.** It divided 30-day numbers by 3 to get "last week".
- **Old tool results aren't replayed in later turns**, only the text of answers. Data changes, so the model should look things up again.

**Where:** `backend/app/services/tools.py`, `backend/app/services/chat.py`, `backend/tests/test_chat.py`

---

## 09674c1 · 2026-11-15 · sales tool (Step 2)

**Done:**
- `get_sales(start_date, end_date, compare_start_date?, compare_end_date?)`, computed in code.
- The shared `compare()` helper for differences and percentages.
- Argument validation, with errors sent back to the model as `{"error": ...}` (`ToolError`).
- A calendar computed in code (this week, last week, this month…) at the end of the system prompt.

**Why:** "last 10 days" or "last week vs the week before" couldn't be answered from a fixed 30-day snapshot.

**Learned:**
- **The model is bad at calendar maths.** It picked Wednesday–Tuesday for "last week" and wrote 2024 for 2026. A calendar computed in code fixed it.
- **The code does the deterministic work** (dates, totals, comparisons); the model only picks arguments and writes the answer.

**Where:** `backend/app/services/tools.py`, `backend/app/services/stats.py`, `backend/tests/test_tools.py`

---

## 2d3c7aa · 2026-11-16 · AI tracing (Step 3)

**Done:**
- **Every reply is recorded as a trace:** each model call (exact messages sent, reasoning, tool requests, tokens, time) and each tool run (arguments, result, time).
- New tables `chat_traces`, `chat_model_calls` and `chat_tool_runs`. They replace `chat_tool_calls`.
- `GET /api/traces` and `GET /api/traces/{id}`.
- A **Traces** page, plus a "Details" link under each reply.

**Why:** from Step 5 on, the loop goes round several times. Without traces, finding out why the model did something meant digging through logs.

**Learned:**
- **Reasoning tokens are most of the output.** "hi" cost 89 output tokens, 76 of them hidden reasoning.
- **The model calls tools one at a time**, even when it plans two. Each pass re-sends the whole prompt.
- **The system prompt and tool definitions are most of every call's input.**

**Where:** `backend/app/services/tracing.py`, `backend/app/routers/traces.py`, `frontend/src/pages/Traces.tsx`, `backend/tests/test_traces.py`

---

## 794bb0e · 2026-11-17 · Order level details tools (Step 4, trace breakdown, made-up number fixes)

**Done, Step 4:** `get_order(order_number)`. It accepts the number in any form (`ORD-00000002`, `#2`, `2`) and normalizes it in code. It returns status, customer, dates with "days ago", items, totals, what's still refundable, refunds and tickets. An unknown number is an error the model can explain.

**Done, traces:**
- **"Where the tokens went"** on the trace page: output split into reasoning and answer, and Groq's own timings per call (queue, reading input, writing output, speed). It uses only what Groq reports; an estimated split of the input was tried and removed.
- `_add_new_columns` in `db.py` adds new nullable columns to an existing database. It's a minimal migration.

**Done, made-up numbers:** asked to "compare all the values" for September vs October, the model invented rows (tickets, stock, refunds) that no tool had returned. Three fixes:
1. `get_sales` now returns more real figures: average order value, cancelled orders, refunds issued and refunded amount.
2. A prompt rule: report what the tools returned, list what isn't available, never fill a cell with a number from nowhere.
3. **The grounding check** (`grounding.py`). The trace page flags numbers in the answer that appear in no tool result, and highlights them.

**Done, comparison direction:** the model reported September minus October as "October vs September". Now the description says to put the later period first, and the result includes `change_means`, which states which way round the change is.

**Learned:**
- **A prompt rule doesn't hold when the user asks for more than the tools have.** Give the tools the data, and add a check.
- **The grounding check catches invented numbers, but not real numbers used wrongly.**

**Where:** `backend/app/services/tools.py`, `backend/app/services/grounding.py`, `backend/app/services/stats.py`, `backend/app/db.py`, `frontend/src/pages/Traces.tsx`, `backend/tests/test_grounding.py`

---

## 2026-11-17 · Customer search and chained tools (Step 5, Step 11 plan, this log)

**Done, Step 5:**
- **`find_customer(query)`:** a partial, case-insensitive match on name or email. It returns at most 5 matches with the total count.
- **`list_customer_orders(customer_id)`:** the newest 10 orders, each with totals, refunds and its tickets.
- **Results that steer the model** (`next_step`):
  - no match: ask for another spelling;
  - several matches: ask which one.
- **No match is a result; an unknown ID is an error.**
- A chain test with a fake model: search, read the ID from the result, list the orders, answer.

**Why:** real questions name a person ("What did Priya order?"), not an ID. The agent has to search, then use what it found in a second call.

**Learned:**
- **Chaining needed no prompt change.** Descriptions that say where an argument comes from ("the id from `find_customer`") were enough.
- **Follow-ups repeat lookups.** After "the first one", it searched again, because old tool results aren't replayed.
- **Slow replies were Groq rate limits.** The SDK quietly waited up to 16 s and retried. Traces don't show this yet.

**Where:** `backend/app/services/tools.py`, `backend/tests/test_tools.py`, `backend/tests/test_chat.py`

**Done, planning:**
- **Roadmap Step 11, Flexible queries.** Prompted by "highest order value this year in each month", which no tool can answer.
  - The plan: a structured `query_orders` tool, where the model picks the metric, grouping and filters from fixed options, and the code writes the SQL.
  - Optionally, a raw `run_sql` experiment to compare against it.
- **The same question added to the Step 10 regression cases.**
- **This dev log.**

---

## 2026-11-22 · Tickets and page context (Step 6)

**Done:**
- **`get_ticket(ticket_id)`:** the thread, the customer, the order, and `waiting_on` (who has to act next).
- **`list_tickets(...)`:** the queue, most urgent first, then the one waiting longest. It's capped at 10, with a count per priority.
- **`delivery_late`, worked out in code** (shipped more than 7 days ago and not delivered), also on `get_order`.
- **"## ShopDesk terms"** in the system prompt: open tickets, `waiting_on`, `delivery_late`.
- **"## Drafting replies to customers":** only facts from the data, nothing claimed as done, placeholders instead of promises, a checklist after the draft.
- **Page context:**
  - an "Ask about this ticket" button on the ticket page;
  - the conversation remembers the ticket (`ticket_id`), and the ticket's current data goes into the prompt on every turn;
  - in the assistant, the ticket appears above the first message, like an attached image; before sending, it sits above the message box with an ×.
- **The grounding check also reads** the page context and the tool descriptions.

**Why:** support work is mostly tickets. A ticket is text a person wrote, so this is the first step where the model has to understand and summarize rather than report numbers.

**Learned:**
- **Page context halves the cost:** 1 call instead of 2, and no ambiguity about which ticket.
- **One general prompt rule didn't stop made-up facts in drafts.** They promised a refund ("I'll initiate the refund…"), invented actions ("contacting the carrier now"), and showed an internal field name. Concrete rules plus the framing "nothing has been done yet" fixed most of it. Some soft claims are left for Steps 9 and 10.
- **The grounding check catches invented numbers** ("within 24 hours"), **but not invented actions without numbers.**
- **Context goes with every message; the UI shows it once.** The model keeps nothing between messages, so the ticket is re-sent each turn. The screen shows it on the first message, so the chat doesn't look like every question is about the ticket.

**Where:** `backend/app/services/tools.py`, `backend/app/services/chat.py` (prompt, `page_context`), `backend/app/routers/chat.py`, `frontend/src/pages/TicketDetail.tsx`, `frontend/src/pages/Assistant.tsx`

---

## 2026-11-22 · Products and stock (Step 7)

**Done:**
- **`search_products`:** by name, SKU, category or stock (`available`, `low`, `out_of_stock`, `in_stock`).
- **One "low stock" rule** (1–5 left) in `stats.py`, shared by the dashboard and the tools.
- **Every result says what ShopDesk doesn't record** (`not_recorded`): restock dates, suppliers, specs, back-in-stock alerts.
- **Prompt rules:** unrecorded facts get "ShopDesk doesn't have that"; drafts mention only products a tool returned, and no made-up services.
- **Browser testing with the Playwright MCP** (`.mcp.json`; its output folder is ignored by git). It found that a ticket without an order still offered "Check the order", which is now fixed.

**Why:** product questions are where the model invents facts that contain no numbers: restock dates, features, other products. The grounding check can't catch those.

**Learned:**
- **The first draft invented a product** ("Comfort Grip Mat") **and a feature** (back-in-stock alerts). Stating the gap in the tool result stopped the feature; a rule plus looking up alternatives stopped the made-up product.
- **Groq rejects tool arguments that don't match the schema**, and that kills the whole reply. Keep schemas as simple as what the model naturally sends.
- **A filter with the wrong meaning made the model loop** to the step limit. The fixes were an `available` filter and "don't repeat the search".

**Where:** `backend/app/services/tools.py` (`search_products`), `backend/app/services/stats.py` (`LOW_STOCK`, `stock_status`), `backend/app/services/chat.py` (prompt)

---

## 2026-11-22 · Analytics and charts (Step 8)

**Done:**
- **`sales_over_time`** returns orders and revenue per day, week or month; **`top_products`** returns best sellers. Both are computed in code, with totals.
- **Charts in the chat:** the model writes a ` ```chart ` block that names a tool result (`data_ref`) and its columns. The app draws a line or bar chart from the tool's own rows. Every chart has a table view and works in dark mode.
- **Chart data is sent with the tool events and saved with each message**, so charts survive a reload.

**Why:** "show revenue as a chart" should give a chart, not a wall of numbers. It's also the first time the model produces something the app renders, not just text.

**Learned:**
- **The model points at data instead of copying it.** It can't mistype a point, and a chart costs one line of output.
- **It added up rows itself and got 29 instead of 22.** The tools now return the totals.
- **A note in the tool result** ("don't also list these rows in a table") **worked where the prompt rule didn't**, the third time this has happened.

**Where:** `backend/app/services/tools.py` (`sales_over_time`, `top_products`, `chart_data`), `backend/app/services/stats.py`, `backend/app/routers/chat.py`, `frontend/src/components/chat/ChatChart.tsx`, `ChatMarkdown.tsx`

---

## 2026-11-24 · Actions with approval (Step 9)

**Done:**
- **Three action tools that only propose:** `create_refund`, `cancel_order` and `draft_ticket_reply`. Each checks the request, saves it as a pending action and tells the model "nothing has happened yet".
- **An Approve / Reject card in the chat.** Approve runs the action through the store's normal rules. It runs exactly once: a second approval gets 409.
- **The model hears the outcome** in a note each turn, because the click happens outside the chat.
- **Tickets get a draft reply box:** an approved draft lands there, flags `[placeholders]` still to fill in, and is cleared when an agent replies.

**Why:** the first step where the assistant changes data. A person has to say yes first, and the code, not the model, enforces the rules.

**Learned:**
- **Exactly once is a database guarantee:** a conditional `UPDATE ... WHERE status = 'pending'` in the same transaction as the change.
- **Check when proposing and again when approving:** the data can change in between.
- **Approval caught a real mistake:** a draft called $49.98 (the amount left) "the refund". Sending the refunds list with the ticket fixed it.
- **A failed reply left an orphan proposal** with no card. Failed or stopped replies now drop their proposals.

**Where:** `backend/app/services/actions.py`, `backend/app/services/tools.py` (action tools), `backend/app/routers/chat.py` (`/api/chat/actions`), `backend/app/models.py` (`ChatAction`, `Ticket.draft_reply`), `frontend/src/components/chat/ActionCard.tsx`, `frontend/src/pages/TicketDetail.tsx`
