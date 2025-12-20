# Context for Claude

## What this is

CLI tool for AI-mediated communication. Target user has ADHD—messages pile up because attention doesn't flow toward replying. Claude triages, drafts, sends. Human approves.

## Current state (2025-12-20)

**Email (Gmail):**
- 3 accounts linked, OAuth2, stateless inbox
- Full send flow: compose → approve → send
- Triage flow: propose → review → approve/reject → resolve
- Thread actions: archive, delete, flag, unflag, unarchive, undelete
- Correction tracking for learning

**Signal:**
- Linked as secondary device via signal-cli
- Send/receive messages
- Local message storage (signal-cli doesn't persist)
- Conversation inbox + history views

**Not done:**
- Outlook adapter (stub exists)
- Proton adapter (requires paid Bridge)
- WhatsApp/Messenger (no API access)
- Draft generation
- Pattern learning from corrections

## Architecture

```
~/.comms/
  store.db      # SQLite: accounts, drafts, proposals, audit_log, signal_messages
  config.yaml   # Policy settings
  rules.md      # Triage rules (Claude reads before proposing)

~/.comms_backups/{timestamp}/
  store.db      # Auto-backup on init
```

**Stateless inbox:** No email cache. Gmail API is source of truth.

**Signal storage:** Messages stored locally because signal-cli consumes on receive.

**Keyring:** All credentials (OAuth tokens, passwords) in system keyring, never on disk.

## Key flows

**Email send:**
```
compose → drafts (approved_at=NULL)
    ↓
approve → drafts (approved_at=NOW)
    ↓
send → Gmail API → drafts (sent_at=NOW)
```

**Triage:**
```
propose → proposals (status=pending)
    ↓
review → human sees grouped by action
    ↓
approve/reject --correct → proposals (status=approved|rejected)
    ↓
resolve → execute all approved → proposals (status=executed)
```

**Signal:**
```
comms messages          # receive + store
comms signal-inbox      # view conversations
comms signal-history    # view thread with contact
comms signal-send       # send message
```

## Adapter signatures

```python
# Email
def list_threads(email: str, label: str, max_results: int) -> list[dict]
def fetch_thread_messages(thread_id: str, email: str) -> list[dict]
def archive_thread(thread_id: str, email: str) -> bool
def delete_thread(thread_id: str, email: str) -> bool
def send_message(account_id: str, email: str, draft: Draft) -> bool

# Signal
def receive(phone: str, timeout: int, store: bool) -> list[dict]
def send(phone: str, recipient: str, message: str) -> tuple[bool, str]
def get_messages(phone: str, sender: str, limit: int) -> list[dict]
def get_conversations(phone: str) -> list[dict]
```

## Design principles

- **Functional > OOP** — Pure functions, explicit args
- **Approval is sacred** — No send without human approval
- **Stateless Claude** — Consults DB precedent, doesn't remember
- **Delete by default** — Archive only for tax/legal/reference
- **Simple > clever** — Copy-paste over premature abstraction

## Commands

```bash
# Dashboard
comms                    # inbox count, pending drafts

# Email
comms link gmail
comms threads [--label inbox|unread|archive|trash|starred|sent]
comms thread <id>
comms compose <to> --subject "..." --body "..."
comms reply <thread-id> --body "..."
comms approve <draft-id>
comms send <draft-id>
comms archive|delete|flag <thread-id>

# Signal
comms link signal        # QR code link
comms messages           # receive + store new
comms signal-inbox       # conversations
comms signal-history <phone>
comms signal-send <phone> -m "..."
comms signal-contacts
comms signal-groups

# Triage
comms propose <action> <entity_type> <entity_id> --agent "reasoning"
comms review [--action delete|archive|flag]
comms approve <proposal-id>
comms reject <proposal-id> --correct "action"
comms resolve

# System
comms accounts
comms backup
comms rules
comms audit-log
```

## Commit style

Terse, title only:
- `feat: signal integration`
- `fix: thread ID prefix`
- `refactor: service layer`
