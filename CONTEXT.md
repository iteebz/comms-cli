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
- Dashboard queries live Gmail inbox count via labels API
- Account linking (`comms link gmail` auto-detects email via OAuth)
- Thread listing: `comms threads` fetches 50 most recent (snippet only, fast)
- Thread fetch: `comms thread <id>` displays full conversation
- Thread actions: archive, delete, flag, unflag, unarchive, undelete
- Audit logging for all actions
- Approval-required send flow (schema only, not implemented)

**Not done:**
- Claude mediation for draft generation
- Send implementation
- Auto-send rules
- Proton/Outlook adapters (stubs exist, not implemented)
- Messaging adapters (Signal, WhatsApp, Messenger)

## Next steps

**1. Claude integration:**
   - Read threads via API calls
   - Propose actions (stored in drafts table with action_type)
   - User approves via `comms approve <id>`
   - Execute approved actions

**2. Send implementation:**
   - Draft reply via Gmail API
   - Approval workflow
   - Send execution

**Long-term goal:** User runs `comms`, I process inbox to zero autonomously with approval gates on sends.

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

**Two-step send invariant:**
1. Claude drafts → stored in `drafts` table with `approved_at = NULL`
2. User approves → sets `approved_at`
3. System sends → sets `sent_at`

Audit log records all three steps immutably.

## Design principles

- **Functional > OOP** - No classes unless state is truly necessary
- **Explicit > implicit** - Pass account_id, don't hide it in `self`
- **Simple > clever** - Copy-paste adapter code, don't abstract prematurely
- **Safety-first** - Default deny on sends, audit everything, approval required

## Pain points to watch

**OAuth token refresh:**
- Gmail: Google library handles it
- Outlook: MSAL handles it
- Both store tokens in keyring as JSON

**Message parsing edge cases:**
- Multipart MIME (HTML + plaintext)
- Missing Message-ID headers
- Thread-ID extraction varies by provider
- Date parsing from weird clients

**Provider-specific quirks:**
- Proton requires Bridge running locally
- Gmail has labelIds for read/unread status
- Outlook uses isRead boolean
- All three have different JSON response shapes

## Testing strategy

No mocks. Test with real accounts when possible. Adapters are self-contained functions—easy to test in isolation by calling with real credentials.

## Commit style

Terse, no description body:
- `feat: gmail integration`
- `fix: outlook token refresh`
- `chore: cleanup imports`

No scopes (tiny app, not needed).
