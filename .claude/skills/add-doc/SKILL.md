---
name: add-doc
description: Store a hackathon/project document the user pastes or attaches (event pages, proposals, organizer feedback, dataset pages, reference/tutorial pages, emails, meeting notes) into docs/ with the repo's conventions, then update the docs index and CONTEXT.md. Use when the user says "new document", "next doc", "here is document N", "store this", or pastes a long page meant for the docs folder.
---

# add-doc

Ingest one or more documents into `docs/`. The user often pastes several documents in one message and marks where each one
starts ("Document 2:", "next document", "here is a dump"). Split on those markers. One source page = one file.

## Steps

1. **Classify each document** and choose its path (see `docs/README.md` → Conventions):
   - Core document the user numbers or treats as primary (event page, proposal, feedback, dataset page, rules update):
     `docs/NN-short-kebab-title.md`, using the next unused number (`ls docs/`).
   - Page that a core doc links to (guides, tutorials, vendor docs): `docs/references/short-kebab-title.md`.
   - Our own write-up (design note, test plan, meeting notes, summary): `docs/notes/YYYY-MM-DD-short-title.md`.
   - Feedback on an existing doc (e.g. organizer feedback on the plan): append it to that doc under a dated
     `## ... feedback` heading instead of creating a new file, unless the user asks for a separate file.
   - If a file for the same source already exists, update it in place rather than duplicating it.
2. **Write the file** with front matter:

   ```yaml
   ---
   title: <title>
   source: <URL, or where it came from, e.g. "ALL AI Network team plan checkpoint">
   author: <author/org if known>
   received: <today, YYYY-MM-DD>
   kind: event | proposal | dataset | reference | feedback | note
   linked_from: <optional: which doc links to it>
   status: <optional: PARTIAL if truncated>
   ---
   ```

   Never invent a URL. If the source URL isn't known, describe the source in words.
3. **Fidelity:** keep the source wording and order. Convert to clean Markdown (headings, lists, tables, fenced code with a
   language). Strip site chrome: nav sidebars, "Skip to main content", social links, "Is this page helpful?", prev/next links,
   footers (keep a copyright line if present). Replace images or videos you don't have with an italic placeholder
   `*(Image: description)*`.
4. **Our commentary stays separate:** put relevance notes, such as conflicts with what we know (e.g. SCHUNK vs SMC gripper)
   or "this applies to us because…", in a quoted block starting with `**Our notes (not part of the source):**` at the top.
   Keep it to a few bullets.
5. **Truncation:** if the paste is cut off (mid-sentence, mid-code-block, or the message says it was truncated), set
   `status: PARTIAL`, mark the cut point in the file, add it to "Not yet received" in `docs/README.md`, and tell the user
   exactly where it stopped.
6. **Images:** if the user attaches images that belong to a doc, copy them into `docs/images/` with descriptive kebab-case
   names (the attachment paths are given in the conversation) and reference them relatively.
7. **Update the index** in `docs/README.md`: add a row (core docs or references table). Remove items from "Not yet received"
   once they arrive, and add newly linked-but-missing pages to it.
8. **Update `CONTEXT.md`** if the document changes facts, constraints, deadlines, decisions, contacts or open questions.
   Bump its "Last updated" date. Don't copy whole documents into CONTEXT.md; summarise and link.
9. **Report back** briefly: which files were created or updated, anything truncated or missing, and any conflicts with
   what we already knew (these matter most).
