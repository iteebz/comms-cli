# Context for Claude

## What this is

CLI tool for AI-mediated email/messaging management. Target user has ADHD communication patterns—messages pile up because attention doesn't naturally flow toward replying.

## Architecture decisions

**Pure functions over classes:** All adapters are pure functions. No OOP ceremony. Account ID passed explicitly, credentials fetched from keyring inside functions.

**No shared abstraction yet:** Proton, Gmail, Outlook adapters have identical function signatures but different implementations. Duplication is fine until pattern proven across 5+ providers.

**Keyring for secrets:** All credentials (passwords, OAuth tokens) stored in system keyring, never on disk as plaintext.

## Current state (2025-12-19)

**Done:**
- Database schema (accounts, threads, messages, drafts, send_queue, audit_log, rules)
- Three email adapters working (code complete, not yet tested with real accounts):
  - Proton Bridge (IMAP/SMTP on localhost)
  - Gmail (OAuth2 + Gmail API)
  - Outlook (OAuth2 + Microsoft Graph)
- Sync system that normalizes all providers → `Message` model
- Thread grouping and display
- Dashboard showing unread counts
- Approval-required send flow
- Audit logging

**Not done:**
- Real-world testing of any adapter
- Claude mediation for draft generation
- Auto-send rules
- Messaging adapters (Signal, WhatsApp, Messenger)

## Next steps

1. **Test Gmail adapter with real account** - Proves OAuth flow, message parsing, thread grouping work
2. **Claude draft generation** - Simple Anthropic API wrapper, reads thread context + style guide
3. **Auto-approve rules** - Pattern matching for trusted senders/simple acks

## Key patterns

**Message normalization:**
```python
@dataclass
class Message:
    id: str              # Hash of msg_id + from + timestamp
    thread_id: str       # Hash of conversation ID
    account_id: str      # Links to accounts table
    provider: str        # "gmail", "proton", "outlook"
    from_addr: str       # Email or phone number
    to_addr: str
    subject: str         # None for messaging
    body: str
    ...
```

**Adapter interface (via function signatures, not Protocol):**
```python
def fetch_messages(account_id: str, email_addr: str, since_days: int = 7) -> list[Message]
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
