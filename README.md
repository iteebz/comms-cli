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

## Roadmap

- [x] Phase 0: Schema + safety rails
- [ ] Phase 1: Email adapters (Gmail, Outlook, Proton)
- [ ] Phase 2: Claude mediation + draft generation
- [ ] Phase 3: Auto-send rules (trusted senders, simple acks)
- [ ] Phase 4: Signal adapter
- [ ] Phase 5: WhatsApp/Messenger (fragile, best-effort)
