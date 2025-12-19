# comms-cli

AI-managed comms for ADHD brains.

You know you need to reply. The message sits there. Days pass. Weeks sometimes. Not because you don't care—because your attention doesn't naturally flow toward communication. Inbox becomes a guilt repository.

This tool fixes that.

## What it does

Claude reads your threads, drafts replies that sound like you, and queues them for your approval. You review, approve, done. Messages get sent. Threads move forward.

**Two-step send by default.** Claude drafts. You approve. System sends. Later, you can add rules to auto-approve patterns you trust (simple acks, calendar confirmations, known senders).

**Safety-first.** Claude never sends messages autonomously. Audit log tracks everything. Recipient allowlists prevent accidents. Daily send limits stop runaway behavior. You're always in control.

## Install

```bash
uv sync
comms init
```

## Safety invariants

- **Two-step send**: draft → approve → send (no bypasses, no exceptions)
- **Audit log**: Every action logged immutably
- **Recipient allowlist**: Default deny on sends
- **Daily send limit**: Configurable ceiling
- **Approval required**: Human-in-loop by default

## Usage

```bash
# Dashboard: see how bad it is
comms

# Link Gmail account (auto-detects email via OAuth)
comms link gmail

# List inbox threads
comms threads

# Read a thread
comms thread <id>

# Compose new email
comms compose recipient@example.com --subject "Subject" --body "Body text"

# Reply to thread
comms reply <thread-id> --body "Reply text"

# Review pending drafts
comms drafts-list

# Approve draft for sending
comms approve <draft-id>

# Send approved draft
comms send <draft-id>

# Thread actions
comms archive <thread-id>
comms delete <thread-id>
comms flag <thread-id>

# View audit trail
comms audit-log
```

## Current status

**Working (2025-12-19):**
- ✅ Full send flow (compose → approve → send)
- ✅ Reply flow with thread context extraction
- ✅ Gmail adapter (OAuth2, tested with 3 real accounts)
- ✅ Stateless inbox (queries Gmail API directly)
- ✅ Account linking + credential management (system keyring)
- ✅ Thread actions (archive, delete, flag, etc.)
- ✅ Thread views (--label inbox/unread/archive/trash/starred/sent) with date metadata
- ✅ Triage rules (`~/.comms/rules.md` - Claude reads before proposing)
- ✅ Automatic backup on init + `comms backup` manual
- ✅ **Interactive Claude triage (PRODUCTION)**
  - Claude reads/analyzes inbox threads
  - Proposes actions with reasoning
  - Human corrects via `reject --correct`
  - Batch execution via `resolve`
  - **25 threads triaged across 2 sessions, 100% accuracy after corrections**
- ✅ Audit logging + correction tracking
- ✅ **Push notifications on phone after send** 📱

**Next:**
- Pattern learning from correction data (9 corrections captured)
- Claude draft generation
- Auto-approval rules for high-confidence actions

## Setup: Gmail

1. Create OAuth app at https://console.cloud.google.com/apis/credentials
2. Download `credentials.json` to project root
3. Add account:
   ```bash
   comms link gmail
   ```
   Browser will open for OAuth flow. Credentials stored in system keyring.

## Commands

```bash
# Dashboard
comms                          # Show inbox count, pending drafts

# Account management
comms link gmail               # Add Gmail account (OAuth)
comms accounts                 # List all accounts
comms unlink <account-id>      # Remove account

# Inbox
comms threads                  # List 50 most recent threads
comms thread <id>              # Show full conversation

# Actions
comms archive <thread-id>
comms delete <thread-id>
comms flag <thread-id>
comms unflag <thread-id>
comms unarchive <thread-id>
comms undelete <thread-id>

# Compose & Send
comms compose <to> --subject "..." --body "..."
comms reply <thread-id> --body "..."
comms drafts-list              # Show pending drafts
comms approve <draft-id>       # Approve for sending
comms send <draft-id>          # Send approved draft

# Audit
comms audit-log                # Show recent actions
comms status                   # System status + policy config
```

## Architecture

**Stateless inbox:** No local thread cache. Gmail API is source of truth. Dashboard queries live counts. Fast, simple, always fresh.

**Approval-gated sends:** Every email requires explicit approval. No shortcuts. Audit log records draft creation, approval, and send as separate immutable events.

**Pure functions:** No classes. Account ID passed explicitly. Credentials fetched from keyring inside functions. Easy to test, easy to reason about.

**Draft lifecycle:**
```
compose/reply → drafts (approved_at=NULL)
      ↓
 approve → drafts (approved_at=NOW)
      ↓
  send → Gmail API send
      ↓
 drafts (sent_at=NOW)
```

See `CONTEXT.md` for detailed architecture, design decisions, and future roadmap.

## Safety

- Drafts table tracks source account (`from_account_id`, `from_addr`)
- Policy validation before approval (recipient allowlist, daily send limits)
- Audit log records all mutations
- OAuth tokens stored in system keyring (never on disk)
- No auto-send without explicit user opt-in per pattern

## Testing

No mocks. Real accounts. End-to-end tested:
1. Compose email from Account A → Account B
2. Wait ~10 seconds
3. Reply from Account B → Account A  
4. Verify push notification on phone

Result: **It works.** Full email loop proven.
