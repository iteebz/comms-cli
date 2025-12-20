# Roadmap

## Vision

Attention scaffolding for ADHD brains. Not "AI email"—AI-mediated communication with human veto.

**Principles:**
- Approval is sacred. No surprise sends.
- Delete by default. Archive only for tax/legal/reference.
- Learn from corrections. System gets smarter over time.
- Audit trail is trust.

**Success:**
- Inbox feels light daily
- Minutes not hours
- Accuracy improves with use

---

## Stage 0 — Core Invariants ✅

- Approval-gated sends
- Explicit account routing
- Clear error reporting
- Audit logging

---

## Stage 1 — Multi-Provider (current)

**Done:**
- Gmail adapter (3 accounts, full flow)
- Signal adapter (send, receive, storage)

**Next:**
- Signal daemon mode (continuous receive)
- Signal reply flow with context
- Group message support

---

## Stage 2 — Learning Loop

- Confidence scores from approve/reject history
- Auto-approve safe actions (archive/delete)
- Dashboard: accuracy trends, correction patterns

---

## Stage 3 — Draft Generation

- Claude drafts replies
- Diff tracking: proposed vs final
- Voice learning from edits

---

## Stage 4 — Agent Bus

comms-cli as the communication layer for agents:

```bash
# Agent notifies you
comms signal-send +... -m "Build complete: ✅"

# You command agent via Signal
"check my emails" → agent triages
"reply to john saying yes" → agent drafts + sends
```

**Requires:**
- Daemon mode (always listening)
- Command parsing from messages
- Agent handoff protocol

---

## Future

- Outlook adapter (Graph API)
- Calendar integration
- Voice memos → transcribed drafts
- Cross-provider unified inbox
