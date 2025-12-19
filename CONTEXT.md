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
- Database schema (accounts, drafts, send_queue, audit_log, rules)
- Stateless inbox (removed threads table, query Gmail API directly)
- Gmail adapter tested with 3 real accounts (OAuth2 + Gmail API)
- Dashboard queries live Gmail inbox count via labels API (114 threads)
- Account linking (`comms link gmail` auto-detects email via OAuth)
- Thread listing: `comms threads` fetches 50 most recent (snippet only, fast)
- Thread fetch: `comms thread <id>` displays full conversation
- Thread actions: archive, delete, flag, unflag, unarchive, undelete
- **Full send flow:**
  - `comms compose` - create draft with source account tracking
  - `comms approve` - validate recipient, mark approved
  - `comms send` - send via Gmail API from stored account
  - `comms reply <thread_id>` - extract thread context, create reply draft
  - Draft ID prefix matching (8 chars → full UUID)
  - Account tracking: `from_account_id` + `from_addr` in drafts table
  - Case-insensitive header parsing (Gmail API quirk)
- Audit logging for all actions
- **End-to-end tested:** compose → approve → send → **push notification on phone**

**Not done:**
- Claude mediation for draft generation
- Auto-send rules
- Proton/Outlook adapters (stubs exist, not implemented)
- Messaging adapters (Signal, WhatsApp, Messenger)

## Next steps

**1. Claude integration (PRIMARY NEXT FEATURE):**
   - Claude reads inbox threads on-demand (via this interactive session)
   - Proposes actions: archive/delete/flag/reply
   - Drafts replies using thread context
   - User approves via `comms approve <id>`
   - Execute approved actions
   - **Note:** `comms process` as a standalone command is NOT needed—Claude Code session IS the processor

**2. Pattern learning (later):**
   - Log approve/reject decisions to extract patterns
   - Build confidence scores for common actions
   - Enable auto-approval for high-confidence non-send actions

**3. Additional providers:**
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

**Reply templates:**
- Common response patterns (ack, defer, decline, request-info)
- User can define custom templates
- Claude selects appropriate template + customizes

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
  approve → drafts (approved_at=NOW)
       ↓
   send → Gmail API (using from_account_id)
       ↓
  drafts (sent_at=NOW)
```

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
