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

- **Two-step send**: draft → approve → send
- **Audit log**: Every action logged immutably
- **Recipient allowlist**: Default deny on sends
- **Daily send limit**: Configurable ceiling
- **Approval required**: Human-in-loop by default

## Usage

```bash
# Dashboard: see how bad it is
comms

# Check system status
comms status

# List pending drafts
comms drafts-list

# Review a draft
comms draft-show <id>

# Approve for sending
comms approve <id>

# View audit trail
comms audit-log
```

**Shared interface.** Both you and Claude run `comms` to see the current state. Same data, different consumption.

## Current status

**Working:**
- Schema + safety rails (audit log, approval flow, policy validation)
- Email adapters: Proton Bridge, Gmail (OAuth2), Outlook (OAuth2)
- Account management (credentials stored in system keyring)
- Message sync from all 3 providers
- Thread grouping and display
- Dashboard shows unread counts

**Next:**
- Test adapters with real accounts
- Claude mediation for draft generation
- Auto-send rules

## Setup

### Gmail
1. Create OAuth app at https://console.cloud.google.com/apis/credentials
2. Download `credentials.json`
3. Add account:
   ```bash
   comms account-add gmail you@gmail.com --credentials ~/path/to/credentials.json
   ```

### Outlook
1. Register app at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps
2. Get Client ID and Secret
3. Add account:
   ```bash
   comms account-add outlook you@outlook.com --client-id <id> --client-secret <secret>
   ```

### Proton (requires paid account + Bridge)
1. Install and run Proton Bridge app
2. Get Bridge password from app settings
3. Add account:
   ```bash
   comms account-add proton you@proton.me --password <bridge-password>
   ```

## Commands

```bash
# Dashboard
comms

# Manage accounts
comms account-add <provider> <email> [credentials]
comms account-list

# Sync messages
comms sync-now

# View threads
comms threads-list
comms thread-show <thread-id>

# Drafts (manual for now, Claude integration coming)
comms drafts-list
comms draft-show <id>
comms approve <id>
```
