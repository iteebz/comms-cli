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

## Stage 1 — Multi-Provider ✅

- Gmail adapter (3 accounts, full flow)
- Outlook adapter (Graph API)
- Signal adapter (send, receive, reply, storage)
- Signal daemon mode (background polling)
- Unified triage for email + Signal
- Launchd auto-start for daemon

---

## Stage 2 — Learning Loop ✅

- Correction tracking in proposals
- `comms stats` shows accuracy + patterns
- Sender stats + priority scoring (`comms senders`)
- Confidence calculation per action
- Auto-approve high-confidence actions (configurable threshold)
- `comms auto-approve --enable --threshold 0.95`

---

## Stage 3 — Draft Generation ✅

- Claude drafts email replies: `comms draft-reply <thread-id>`
- Claude drafts Signal replies: `comms signal-draft <contact>`
- Reply templates for common responses
- Headless Claude via subprocess
- Thread summarization: `comms summarize <thread-id>`

---

## Stage 4 — Triage Automation ✅

- `comms triage` — Claude scans inbox, bulk-proposes actions
- Rules engine reads `~/.comms/rules.md`
- Confidence thresholds for auto-create
- Dry-run mode
- Pattern-based auto-actions (noise + urgency)
- Snooze + resurface support
- One-command inbox clear: `comms clear`

---

## Stage 5 — Agent Bus ✅

comms-cli as the communication layer for agents:

```bash
# Commands via Signal
!inbox              # show unified inbox
!triage             # AI triage dry-run
!status             # system status
!archive <id>       # archive thread
!help               # list commands

# NLP mode (optional)
"check my email"    # → !inbox
"show me status"    # → !status
```

**Features:**
- Daemon responds to Signal commands
- Authorized senders whitelist
- NLP mode via Claude Haiku
- `comms agent-config --nlp` to enable

---

## Stage 6 — Provider Expansion (next)

- Calendar integration (propose meeting times)

---

## Future

- Voice memos → transcribed drafts
- Slack/Discord adapters
- Cross-device sync
