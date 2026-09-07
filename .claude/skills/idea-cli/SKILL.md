---
name: idea-cli
description: Capture, list, search, edit, move, and delete ideas, and manage daily/one-off goals, in this user's personal idea-bank database via the `idea` command-line tool (already on PATH, no setup needed). Use this whenever the user asks to save/jot down/capture an idea, wants to see, search, or review their ideas or goals, asks to move an idea between statuses (inbox/active/queued/horizon/frontier/archive), wants to mark a goal or habit done/undone, or asks about their goal streak -- even if they don't say "idea bank" or "CLI" explicitly, e.g. "note this down for later", "what's on my queued list", "did I hit my streak today", "add a daily habit to walk 10k steps". Every subcommand supports --json for reliable machine-readable output; always use it when parsing results programmatically instead of scraping the human-readable text.
---

# idea CLI

`idea` is this user's personal system for capturing ideas and tracking the
goals they take toward them. It's a single executable (`cli/idea`, symlinked
onto `PATH`) that talks straight to a local SQLite database — it does not
need the Flask server or GUI running, and nothing it does touches the
network. Content is encrypted at rest transparently; you never need to think
about that when using the CLI, it reads/writes plain text same as always.

**The CLI and the GUI are mostly equivalent, with two deliberate
exceptions.** Anything doable by clicking around the board (moving,
editing, completing, deleting, and capturing a new idea) is doable from
here, and vice versa. But linking a goal to an idea is **CLI-only** — the
GUI has no input for it, by design, so that can *only* be done here, not
"also" done here. The reverse also happens: display-only GUI features with
no data behind them (the theme toggle, the smart-default-date cutoff) have
no CLI equivalent, because there's nothing to script against. If a user
describes something they did or want to do in the GUI, there's almost
always a CLI command for it below — the two exceptions above are the only
things this CLI can do that the GUI flatly cannot, and vice versa.

Bare `idea some text` (no subcommand) is shorthand for `idea capture some
text` — the fastest way to save a thought.

## Ideas: the six statuses

Ideas move through six statuses, roughly by time horizon:

| status     | flag | meaning |
|------------|------|---------|
| `inbox`    | (default) | just captured, not yet sorted |
| `active`   | `-a` | currently being worked on |
| `queued`   | `-q` | worth doing, not now — auto-archives after 8 weeks untouched |
| `horizon`  | `-H` | medium-term / someday, reviewed quarterly |
| `frontier` | `-f` | very long-term — a moonshot, no review cadence |
| `archive`  | `-x` | done, shelved, or expired |

```
idea "ship the migration"              # capture -> inbox (bare text = capture)
idea -q "revisit nvim config"          # capture straight -> queued
idea list                              # all ideas, newest-updated first
idea list -q --json                    # only queued, machine-readable
idea show 12 --json                    # full detail for one idea
idea move 12 active                    # change status
idea move 12 13 14 -x                  # move several at once (or a status flag)
idea edit 12 "new text"                # rewrite text
idea edit 12 --field due=2026-10-01    # add/overwrite a structured key=value field
idea edit 12 --unset-field due         # remove a field
idea edit 12 --notes "waiting on x"    # set freeform notes (replaces existing)
idea edit 12 --unset-notes             # clear notes
idea delete 12 13                      # delete one or more (irreversible, no confirm)
printf "one\ntwo\n" | idea capture --stdin -q   # bulk capture, one per line
```

`show`, `move`, and `delete` all accept multiple ids in one call, and the
whole call is **atomic**: if any id doesn't exist, nothing is changed and
the error names which id(s) were bad. Don't retry with just the valid ids
unless that's actually what the user wants — surface the mismatch first.

Structured fields (`--field key=value`) are freeform metadata (due dates,
priority, owner, whatever) — entirely optional, no fixed schema.

## Goals: separate from ideas, self-reported

A goal is its own thing — its own text (e.g. "walk 10000 steps"), not a
tagged idea — and *optionally* links to one. Ideas are long-term
objectives; goals are the milestones you reach toward one. It's either
**recurring** (due on whichever day(s) of the week you give it, via
`--weekdays` -- "daily" is all seven, a single day is a weekly check-in,
any other subset like `mon,wed,fri` is a milestone schedule) or **one-off**
(due on a single date, given with `--date` -- any date at all, not just
today; defaults to today if omitted). Completion is always
**self-reported**: a goal never auto-completes because a linked idea
changed status, since most goals (a step count, say) have no idea behind
them at all.

```
idea goal add "walk 10000 steps" --weekdays daily      # every day
idea goal add "gym" --weekdays mon,wed,fri              # specific weekdays
idea goal add "draft the proposal" --idea 12 --date 2026-10-01   # one-off, any date
idea goal list --json                            # today's due goals + completion
idea goal done 5                                  # mark goal #5 done for today
idea goal undo 5                                  # unmark it
idea goal stop 5                                  # stop a recurring goal (keeps history)
idea goal remove 5                                # delete a goal and its history
idea goal link 5 12                               # link existing goal #5 to idea #12
idea goal unlink 5                                # remove goal #5's idea link
idea goal streak --json                           # current streak, longest, lifetime xp
```

`--weekdays` also accepts `weekdays` (Mon-Fri) and `weekends` (Sat-Sun) as
shorthands. `--weekdays` and `--date` are mutually exclusive on one goal.
A goal doesn't need its idea to exist first -- add the goal, capture the
idea whenever, then `goal link` them.

**Linking a goal to an idea is CLI-only** — the GUI has no input for it
(a goal row there only *shows* its linked idea, read-only), so if a user
describes wanting to link a goal to an idea "in the app" or asks why they
can't find a link control in the GUI, this CLI is the way to do it, not a
GUI gap to work around. Capturing a new idea, on the other hand, works from
both surfaces now.

Streak math: an unfinished *today* doesn't break the streak (it's just not
counted yet), and a day with nothing due at all is skipped rather than
counted as a miss. Only a day where something was due and left undone
breaks it.

## Working programmatically

- Pass `--json` on every call whose output you need to parse. The
  human-readable text output is for people at a keyboard and its wording
  isn't a stable contract; the JSON shape is.
- Exit codes are meaningful and worth checking instead of just grepping
  output: `0` succeeded, `1` well-formed request that was rejected (e.g. an
  id that doesn't exist), `2` bad arguments (argparse-level).
- Don't guess ids. If you're not sure an id exists or what its current
  status/text is, `idea show <id> --json` first rather than assuming.
- Run `idea --help` or `idea <command> --help` (e.g. `idea goal --help`)
  for the exhaustive, always-current flag reference — it's generated from
  the same source as this skill and won't drift out of sync with it.
