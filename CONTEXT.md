# Context for Claude

## What this is

CLI tool for AI-mediated communication. Target user has ADHD—messages pile up because attention doesn't flow toward replying. Claude triages, drafts, sends. Human approves.

## Current state (2025-12-21)

**Email (Gmail + Outlook):**
- 3 accounts linked, OAuth2, stateless inbox
- Full send flow: compose → approve → send
- Thread actions: archive, delete, flag, unflag, unarchive, undelete
- Claude drafts replies: `comms draft-reply <thread-id>`
- Thread summarization: `comms summarize <thread-id>`
- Snooze threads: `comms snooze <thread-id> --until monday`
- Outlook adapter via Graph API (device flow + send/archive/delete/flag)

**Signal:**
- Linked as secondary device via signal-cli
- Send/receive/reply messages
- Daemon mode (background polling)
- Local message storage (signal-cli consumes on receive)
- Conversation inbox + history views
- Claude drafts replies: `comms signal-draft <contact>`
- Launchd auto-start: `comms daemon-install`

**Triage:**
- `comms triage` — Claude bulk-proposes actions for inbox
- Unified proposal flow for email + Signal
- propose → review → approve/reject → resolve
- Correction tracking with pattern learning
- `comms stats` shows accuracy + correction patterns
- Auto-approve high-confidence actions
- Pattern-based auto-actions for obvious noise + urgency

**Agent Bus:**
- Daemon responds to Signal commands
- Explicit: `!inbox`, `!status`, `!triage`, `!help`
- NLP mode: "check my email" → parsed via Claude Haiku
- Authorized senders whitelist
- `comms agent-config --nlp` to enable

**Not done:**
- Proton adapter (requires paid Bridge)
- Calendar integration
- Voice memos → transcribed drafts

## Architecture

```
~/.comms/
  store.db              # SQLite: accounts, drafts, proposals, audit_log, signal_messages
  config.yaml           # Policy + agent settings
  rules.md              # Triage rules (Claude reads before proposing)
  authorized_senders.txt # Agent command whitelist
  daemon.pid            # Daemon process ID
  daemon.log            # Daemon activity log

~/Library/LaunchAgents/com.comms-cli.daemon.plist  # Launchd auto-start
```

**Stateless inbox:** No email cache. Gmail API is source of truth.

**Signal storage:** Messages stored locally because signal-cli consumes on receive.

**Keyring:** All credentials (OAuth tokens, passwords) in system keyring, never on disk.

**Daily helpers:**
- One-command inbox clear: `comms clear`
- Weekly digest: `comms digest`
- Sender stats: `comms senders`
- Reply templates: `comms templates --init`
- Contact notes for Claude: `comms contacts`

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
comms triage           # Claude proposes actions
    ↓
proposals (status=pending)
    ↓
review → human sees grouped by action
    ↓
approve/reject --correct → proposals (status=approved|rejected)
    ↓
resolve → execute all approved → proposals (status=executed)
```

**Agent bus:**
```
Signal message received
    ↓
Is command? (!inbox, "check my email")
    ↓
Parse → Execute → Respond via Signal
```

## CLI structure

```
comms/cli/
├── __init__.py   # app entry, dashboard callback
├── accounts.py   # link, unlink, accounts
├── daemon.py     # daemon-*, agent-*
├── drafts.py     # compose, reply, send, draft-reply
├── email.py      # threads, archive, delete
├── helpers.py    # run_service, get_signal_phone
├── proposals.py  # review, propose, approve, reject
├── signal.py     # signal-*
└── system.py     # init, inbox, triage, status, stats
```

## Adapter signatures

```python
# Email
def list_threads(email: str, label: str, max_results: int) -> list[dict]
def fetch_thread_messages(thread_id: str, email: str) -> list[dict]
def archive_thread(thread_id: str, email: str) -> bool
def send_message(account_id: str, email: str, draft: Draft) -> bool

# Signal
def receive(phone: str, timeout: int, store: bool) -> list[dict]
def send(phone: str, recipient: str, message: str) -> tuple[bool, str]
def get_messages(phone: str, sender: str, limit: int) -> list[dict]

# Claude (headless)
def generate_reply(context: str, instructions: str) -> tuple[str, str]
def generate_signal_reply(conversation: list[dict], instructions: str) -> tuple[str, str]
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
comms draft-reply <thread-id> [--instructions "..."]
comms approve-draft <draft-id>
comms send <draft-id>
comms archive|delete|flag <thread-id>
comms summarize <thread-id>
comms snooze <thread-id> [--until monday]
comms snoozed

# Signal
comms link signal        # QR code link
comms messages           # receive + store new
comms signal-inbox       # conversations
comms signal-history <phone>
comms signal-send <phone> -m "..."
comms signal-reply <msg-id> -m "..."
comms signal-draft <phone> [--instructions "..."]

# Daemon + Agent
comms daemon-start [--foreground]
comms daemon-stop
comms daemon-status
comms daemon-install     # launchd auto-start
comms daemon-uninstall
comms agent-authorize <phone>
comms agent-revoke <phone>
comms agent-list
comms agent-config [--enable|--disable] [--nlp|--no-nlp]

# Triage
comms triage [--dry-run] [--execute] [--confidence 0.7]
comms propose <action> <entity_type> <entity_id> --agent "reasoning"
comms review [--action delete|archive|flag]
comms approve <proposal-id>
comms reject <proposal-id> --correct "action"
comms resolve

# System
comms inbox              # unified inbox
comms accounts
comms backup
comms rules
comms status
comms auto-approve [--enable|--disable] [--threshold 0.95]
comms audit-log
comms stats              # learning stats
comms senders            # sender stats + priority
comms digest             # weekly activity digest
comms templates [--init] # reply templates
comms contacts           # contact notes
comms clear              # triage → approve → execute
```

## Commit style

Terse, title only:
- `feat: signal integration`
- `fix: thread ID prefix`
- `refactor: service layer`
