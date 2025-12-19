# Context for Claude

## What this is

CLI tool for AI-mediated email/messaging management. Target user has ADHD communication patterns—messages pile up because attention doesn't naturally flow toward replying.

## Architecture decisions

**Stateless inbox:** No threads table. SQLite stores only accounts, drafts, audit_log. Provider API is source of truth. Dashboard queries Gmail directly for counts. Thread listing fetches on-demand.

**Pure functions over classes:** All adapters are pure functions. No OOP ceremony. Account ID passed explicitly, credentials fetched from keyring inside functions.

**No shared abstraction yet:** Proton, Gmail, Outlook adapters have identical function signatures but different implementations. Duplication is fine until pattern proven across 5+ providers.

**Keyring for secrets:** All credentials (passwords, OAuth tokens) stored in system keyring, never on disk as plaintext.

## Current state (2025-12-19)

**Done:**
- Database schema (accounts, drafts, send_queue, audit_log, rules, proposals)
- Stateless inbox (removed threads table, query Gmail API directly)
- Gmail adapter tested with 3 real accounts (OAuth2 + Gmail API)
- Dashboard queries live Gmail inbox count via labels API
- Account linking (`comms link gmail` auto-detects email via OAuth)
- Thread listing: `comms threads` fetches 50 most recent (snippet only, fast)
- Thread fetch: `comms thread <id>` displays full conversation
- Thread actions: archive, delete, flag, unflag, unarchive, undelete
- **Full send flow:**
  - `comms compose` - create draft with source account tracking
  - `comms approve-draft` - validate recipient, mark approved
  - `comms send` - send via Gmail API from stored account
  - `comms reply <thread_id>` - extract thread context, create reply draft
  - Draft ID prefix matching (8 chars → full UUID)
  - Account tracking: `from_account_id` + `from_addr` in drafts table
  - Case-insensitive header parsing (Gmail API quirk)
- **Proposal flow (WORKING END-TO-END):**
  - `comms propose <action> <entity_type> <entity_id> --agent "reasoning"`
  - `comms review` - list all proposals with agent/human reasoning + corrections
  - `comms approve <proposal_id> --human "reasoning"` - approve proposal
  - `comms reject <proposal_id> --human "reasoning" --correct "action"` - reject with correction
  - `comms resolve` - execute all approved proposals in batch
  - Proposal ID prefix matching (8 chars → full UUID)
  - **Validation:** Entity must exist (via Gmail API), action must be valid for entity_type
  - **Correction tracking:** Rejected proposals capture `correction` field (proposed vs actual)
  - Decision logging: agent_reasoning + user_decision + user_reasoning + correction
- **Thread views (WORKING):**
  - `comms threads --label inbox` (default)
  - `comms threads --label unread` / `--label archive` / `--label trash` / `--label starred` / `--label sent`
- **Interactive Claude triage (PRODUCTION READY):**
  - Claude reads 20 unread threads via Python API
  - Analyzes all thread content (from, subject, body preview)
  - Creates proposals with agent reasoning
  - User corrects via `reject --correct "action"`
  - Batch execution via resolve
  - Post-execution verification (trash/archive confirmed)
  - **Session 1:** 5 threads deleted, verified in trash
  - **Session 2:** 20 threads triaged (19 deleted, 1 archived for tax), verified in correct folders
  - **Correction learning:** 9 proposals rejected with corrections (archive → delete)
- Audit logging for all actions + decision trail + correction tracking
- **End-to-end tested:** compose → approve → send → **push notification on phone**
- **End-to-end tested:** Claude triage 20 threads → user correct → resolve → **verified in Gmail**

**Not done:**
- Claude mediation for draft generation
- Auto-send rules
- Proton/Outlook adapters (stubs exist, not implemented)
- Messaging adapters (Signal, WhatsApp, Messenger)

## What is now proven

**Session 1 (5 threads):**
- Proposal → approval → execution works end-to-end
- Provider mutations verified (threads confirmed in Gmail trash)
- Claude-first interface: human never touched thread IDs directly

**Session 2 (20 threads):**
- Claude reads/analyzes 20 threads autonomously
- Human corrects Claude's mental model via `reject --correct`
- 9 corrections logged (archive → delete): "no value", "noise", "already know"
- All 20 threads land in correct folders (19 trash, 1 archive)
- No failures, no manual intervention after approval

**What this means:**
- This is not "AI-assisted" email
- This is AI-mediated communication with human veto
- Correction tracking enables pattern learning
- Claude learns: archive = keep for reference, delete = no value
- Audit trail captures intent + execution + correction

## Next steps

**1. Pattern learning (ENABLED BY CORRECTIONS - READY TO BUILD):**
   - 9 corrections captured: archive → delete ("no value", "noise")
   - Extract patterns from proposals table:**
   - Extract patterns from proposals table:
     - `proposed_action` vs `correction` = learning signal
     - Aggregate by sender, subject patterns, action type
   - Build confidence scores for common actions
   - Enable auto-approval for high-confidence non-send actions
   - Dashboard: "Claude accuracy: 73% (archive → delete corrections: 12)"

**3. Claude draft generation:**
   - Claude reads thread context
   - Generates reply draft with reasoning
   - User reviews/edits body
   - Diff tracking: original_body vs final_body
   - Voice pattern learning from edits

**4. Additional providers:**
   - Finish Proton adapter (Bridge IMAP)
   - Finish Outlook adapter (Microsoft Graph API)
   - Messaging: Signal CLI, WhatsApp Business API

## Vision (未锁定)

**Learned decision patterns:**
- Claude gets smarter over time by observing approve/reject decisions
- Two learning modes:
  - **Implicit:** Pattern extraction from audit log (sender trust, topic priority)
  - **Explicit:** User declares rules (`comms rule add "archive all newsletters"`)
- Pattern types: sender trust, topic priority, writing style/voice
- Confidence scores increase with repeated confirmations

**Proposed workflows:**
```bash
comms process    # Claude reads inbox, applies rules, proposes NEW actions
comms review     # Show proposed actions in batch
comms approve <id> | --all
comms sweep      # Mechanical rule execution (no Claude creativity, just deterministic rules)
```

**Pattern storage:**
- `patterns` table: pattern_type, pattern_data (JSON/embeddings), confidence, last_updated
- Rules logged to existing `rules` table
- Decisions logged to `audit_log` for pattern extraction

**Voice cloning (future):**
- Claude drafts replies that sound like you
- Trained on approved/sent emails over time
- User can reply THROUGH comms-cli, logged for training data

**Claude = stateless analyst consulting precedent:**
- Claude never "remembers" across sessions
- Your doctrine (patterns/rules) accumulates in DB
- Precedent shapes future decisions
- You always retain veto power

## Future work

**Generic undo:**
- Enhance audit log to capture pre-state (labels before action)
- `comms undo` reads last entry, computes inverse, executes
- Trade-off: +1 API call per action (fetch labels before modify)
- Alternative: rely on explicit `unarchive`/`undelete`/`unflag` (current approach)

**Threading improvements:**
- Gmail sent messages don't always thread properly (API limitation)
- May need to track `In-Reply-To` and `References` headers manually
- Consider storing thread_id → parent_message_id mapping in drafts

**Batch operations:**
- `comms approve --all` for bulk approval
- `comms archive --pattern "newsletter*"` for pattern-based actions
- `comms threads --unread | xargs -n1 comms propose ...` for piping

**Reply templates:**
- Common response patterns (ack, defer, decline, request-info)
- User can define custom templates
- Claude selects appropriate template + customizes

**Git pre-commit hook:**
- Currently: ruff formats → fails commit → requires re-commit
- Should: ruff formats → auto-adds fixes → commits in one step
- Lower priority, doesn't block functionality

## Key patterns

**Adapter interface (via function signatures, not Protocol):**
```python
def count_inbox_threads(email_addr: str) -> int
def list_inbox_threads(email_addr: str, max_results: int = 50) -> list[dict]
def fetch_thread_messages(thread_id: str, email_addr: str) -> list[dict]
def archive_thread(thread_id: str, email_addr: str) -> bool
def delete_thread(thread_id: str, email_addr: str) -> bool
def flag_thread(thread_id: str, email_addr: str) -> bool
def unflag_thread(thread_id: str, email_addr: str) -> bool
def unarchive_thread(thread_id: str, email_addr: str) -> bool
def undelete_thread(thread_id: str, email_addr: str) -> bool
def send_message(account_id: str, email_addr: str, draft: Draft) -> bool
def test_connection(account_id: str, email_addr: str, ...) -> tuple[bool, str]
```

**Approval-gated send invariant:**
1. Draft created → stored in `drafts` table with `approved_at = NULL`
2. User approves → sets `approved_at` timestamp
3. System sends → executes Gmail API send, sets `sent_at` timestamp

Audit log records all three steps immutably. No shortcuts, no bypasses.

**Draft lifecycle:**
```
compose/reply → drafts (approved_at=NULL, from_account_id set)
       ↓
  approve-draft → drafts (approved_at=NOW)
       ↓
   send → Gmail API (using from_account_id)
       ↓
  drafts (sent_at=NOW)
```

**Proposal lifecycle:**
```
propose → proposals (status=pending, agent_reasoning set)
       ↓
  review → display all proposals
       ↓
approve → proposals (status=approved, user_reasoning set)
  OR
reject --correct "action" → proposals (status=rejected, correction set, user_reasoning set)
       ↓
  resolve → execute approved proposals → mark executed
       ↓
  proposals (status=executed, executed_at=NOW)
```

Decision logging captures:
- `proposed_action` - what agent suggested
- `agent_reasoning` - why agent proposed it
- `user_decision` - approved / rejected / rejected_with_correction
- `user_reasoning` - optional explanation from human
- `correction` - corrected action if rejected (e.g., "delete" instead of "archive")

**Learning signal:**
- Approved: agent was correct
- Rejected without correction: agent was wrong, don't do this
- Rejected with correction: agent had right entity, wrong action (strongest signal)

**Observed correction patterns (Session 2):**
- archive → delete (9 instances)
- flag → delete (2 instances)
- Common reasoning: "no value", "noise", "already know"
- User preference: aggressive deletion, only archive for tax/legal/reference
- Pattern: Receipts archive if tax-relevant, delete otherwise

## Design principles

- **Functional > OOP** - No classes unless state is truly necessary
- **Explicit > implicit** - Pass account_id, don't hide it in `self`
- **Simple > clever** - Copy-paste adapter code, don't abstract prematurely
- **Safety-first** - Default deny on sends, audit everything, approval required
- **Stateless Claude** - Claude consults precedent, doesn't "remember"
- **Approval is the product** - Not ceremony, not friction—it's the safety boundary

## Pain points to watch

**OAuth token refresh:**
- Gmail: Google library handles it automatically
- Outlook: MSAL handles it automatically
- Both store tokens in keyring as JSON

**Message parsing edge cases:**
- Multipart MIME (HTML + plaintext)
- Missing Message-ID headers
- Thread-ID extraction varies by provider
- Date parsing from weird clients
- **Gmail API case sensitivity:** Headers come back lowercase (`"from"` not `"From"`)

**Provider-specific quirks:**
- Proton requires Bridge running locally
- Gmail has labelIds for read/unread status
- Outlook uses isRead boolean
- All three have different JSON response shapes
- Gmail threading may not preserve In-Reply-To for sent messages

**Rate limits (non-issue):**
- Gmail API: 1 billion quota units/day
- Per-user: 250 units/second
- `labels.get`: 1 unit
- `threads.list`: 10 units
- `threads.get`: 10 units
- `threads.modify`: 10 units
- Even processing 422 threads = ~8,500 units (0.00085% of daily quota)

## Testing strategy

No mocks. Test with real accounts when possible. Adapters are self-contained functions—easy to test in isolation by calling with real credentials.

**Proven test loop:**
1. Send from Account A → Account B
2. Wait ~10 seconds for delivery
3. Fetch inbox on Account B
4. Reply from Account B → Account A
5. Verify thread continuity

**Result:** Push notifications on phone confirm full email loop working.

## Commit style

Terse, no description body:
- `feat: send flow`
- `refactor: stateless inbox`
- `fix: case-sensitive headers`

No scopes (tiny app, not needed).
