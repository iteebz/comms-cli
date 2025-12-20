"""Contact context — user notes about senders for Claude to consider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CONTACTS_PATH = Path.home() / ".comms" / "contacts.md"


@dataclass
class ContactNote:
    pattern: str
    tags: list[str]
    notes: str


def _load_contacts() -> list[ContactNote]:
    if not CONTACTS_PATH.exists():
        return []

    contacts = []
    current_pattern = None
    current_tags: list[str] = []
    current_notes: list[str] = []

    for line in CONTACTS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("## "):
            if current_pattern:
                contacts.append(
                    ContactNote(
                        pattern=current_pattern,
                        tags=current_tags,
                        notes="\n".join(current_notes).strip(),
                    )
                )
            current_pattern = line[3:].strip()
            current_tags = []
            current_notes = []
        elif line.startswith("tags:"):
            tag_str = line[5:].strip()
            current_tags = [t.strip() for t in tag_str.split(",") if t.strip()]
        elif current_pattern:
            current_notes.append(line)

    if current_pattern:
        contacts.append(
            ContactNote(
                pattern=current_pattern,
                tags=current_tags,
                notes="\n".join(current_notes).strip(),
            )
        )

    return contacts


def _match_sender(pattern: str, sender: str) -> bool:
    sender_lower = sender.lower()
    pattern_lower = pattern.lower()

    if "@" in pattern_lower:
        return pattern_lower in sender_lower

    if pattern_lower.startswith("*"):
        return sender_lower.endswith(pattern_lower[1:])

    return pattern_lower in sender_lower


def get_contact_context(sender: str) -> ContactNote | None:
    contacts = _load_contacts()
    for contact in contacts:
        if _match_sender(contact.pattern, sender):
            return contact
    return None


def get_all_contacts() -> list[ContactNote]:
    return _load_contacts()


def format_contacts_for_prompt() -> str:
    contacts = _load_contacts()
    if not contacts:
        return ""

    lines = ["CONTACT CONTEXT (your notes about specific senders):"]
    for c in contacts:
        tag_str = f" [{', '.join(c.tags)}]" if c.tags else ""
        lines.append(f"- {c.pattern}{tag_str}: {c.notes}")

    return "\n".join(lines)
