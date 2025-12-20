# comms-cli

AI-managed comms for ADHD brains.

Messages pile up. Not because you don't care—because attention doesn't flow toward replying. This tool fixes that.

## What it does

Claude reads your inbox, proposes actions, drafts replies. You approve. System executes. Threads move forward.

**Safety-first.** Nothing sends without approval. Audit log tracks everything.

## Install

```bash
uv sync
comms init
```

## Quick start

```bash
# Link accounts
comms link gmail              # OAuth flow, auto-detects email
comms link signal             # QR code, links as secondary device

# Check inbox
comms                         # Dashboard: counts + pending
comms threads                 # List recent threads
comms messages                # Receive Signal messages

# Compose + send
comms compose to@example.com --subject "Hi" --body "..."
comms approve <draft-id>
comms send <draft-id>

# Signal
comms signal-send +1234567890 -m "Hello"
comms signal-inbox            # View conversations
comms signal-history +123...  # Message history
```

## Current status (2025-12-21)

**Working:**
- ✅ Gmail (3 accounts, OAuth2, stateless inbox)
- ✅ Signal (send, receive, reply, local storage, conversations)
- ✅ Signal daemon mode (background polling)
- ✅ Full send flow (compose → approve → send)
- ✅ Unified triage (email + Signal proposals)
- ✅ Pattern learning from corrections
- ✅ Audit logging

**Not done:**
- Outlook/Proton adapters
- Draft generation
- Auto-approve based on confidence

## Commands

```bash
# Email
comms threads [--label inbox|unread|archive|trash|starred|sent]
comms thread <id>
comms compose <to> --subject "..." --body "..."
comms reply <thread-id> --body "..."
comms archive|delete|flag <thread-id>

# Signal
comms messages [--timeout 10]
comms signal-inbox
comms signal-history <phone>
comms signal-send <phone> -m "..."
comms signal-reply <msg-id> -m "..."
comms signal-contacts
comms signal-groups
comms daemon-start [--interval 5]
comms daemon-stop
comms daemon-status

# Drafts
comms drafts-list
comms approve <draft-id>
comms send <draft-id>

# Triage
comms propose <action> thread <id> --agent "reasoning"
comms review [--action delete|archive|flag]
comms approve <proposal-id>
comms reject <proposal-id> --correct "action"
comms resolve

# System
comms accounts
comms backup
comms rules
comms audit-log
comms stats                  # Learning stats from corrections
```

## Setup

**Gmail:**
1. Create OAuth app at https://console.cloud.google.com/apis/credentials
2. Download `credentials.json` to project root
3. Run `comms link gmail`

**Signal:**
1. Run `comms link signal`
2. Scan QR code with Signal app (Settings → Linked Devices)

## Safety invariants

- Two-step send: draft → approve → send
- Audit log: every action logged immutably
- Keyring storage: credentials never on disk
- No auto-send without explicit opt-in

## Architecture

- `~/.comms/store.db` — SQLite (accounts, drafts, proposals, messages)
- `~/.comms/rules.md` — Triage rules Claude reads
- `~/.comms_backups/` — Auto-backup on init

Stateless inbox. Gmail API is source of truth. Signal messages stored locally (signal-cli consumes on receive).

See `CONTEXT.md` for technical details, `ROADMAP.md` for vision.
