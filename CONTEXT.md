# Context for Claude

## What this is

CLI tool for AI-mediated email/messaging management. Target user has ADHD communication patterns—messages pile up because attention doesn't naturally flow toward replying.

## Architecture decisions

**Inbox index, not email client:** SQLite stores thread metadata only (subject, participants, needs_reply flag). No message bodies. Providers remain source of truth. Fetch threads on-demand when needed.

**Pure functions over classes:** All adapters are pure functions. No OOP ceremony. Account ID passed explicitly, credentials fetched from keyring inside functions.

**No shared abstraction yet:** Proton, Gmail, Outlook adapters have identical function signatures but different implementations. Duplication is fine until pattern proven across 5+ providers.

**Keyring for secrets:** All credentials (passwords, OAuth tokens) stored in system keyring, never on disk as plaintext.

## Current state (2025-12-19)

**Done:**
- Database schema (accounts, threads, drafts, send_queue, audit_log, rules)
- Gmail adapter tested with 3 real accounts (OAuth2 + Gmail API)
- Inbox sync: fetches thread index from Gmail (subject snippets, needs_reply flag)
- Dashboard showing thread counts
- Account linking (`comms link gmail` auto-detects email via OAuth)
- Approval-required send flow (schema only, not implemented)
- Audit logging (schema only, not implemented)

**Not done:**
- On-demand thread fetch (full message bodies when opening a thread)
- Claude mediation for draft generation
- Send implementation
- Auto-send rules
- Proton/Outlook adapters (stubs exist, not implemented)
- Messaging adapters (Signal, WhatsApp, Messenger)

## Next steps

1. **On-demand thread fetch** - Fetch full thread bodies from Gmail API when user opens a thread
2. **Claude draft generation** - Simple Anthropic API wrapper, reads thread context + style guide
3. **Send flow** - Implement actual sending via Gmail API

## Key patterns

**Thread index (SQLite):**
```sql
threads (
  id TEXT,                -- Provider thread ID
  account_id TEXT,
  provider TEXT,
  subject TEXT,           -- Snippet from first message
  participants TEXT,      -- Comma-separated
  last_message_at TEXT,   -- RFC 2822 date string
  needs_reply INTEGER,    -- 1 if unread/needs attention
  last_seen_hash TEXT     -- Hash for dedup
)
```

**Adapter interface (via function signatures, not Protocol):**
```python
def fetch_threads(account_id: str, email_addr: str) -> list[dict]
def fetch_messages(account_id: str, email_addr: str, since_days: int = 7) -> list[Message]  # Legacy, unused
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
