# Agent Workflow Rules

## Ticket-First Policy

Every task **must** have a ticket before any work begins. No code changes, file creation, or structural modifications without a corresponding ticket.

### Creating Tickets

Use `mt.py` for all ticket operations:

```bash
# Create a new ticket
python3 tickets/mt/muontickets/muontickets/mt.py new "Title" --priority p1 --type code --effort s --goal "One-sentence goal"

# Claim a ticket before starting work
python3 tickets/mt/muontickets/muontickets/mt.py claim <TICKET-ID> --owner <agent-name>

# Add progress notes
python3 tickets/mt/muontickets/muontickets/mt.py comment <TICKET-ID> "Progress update"

# Mark for review then done
python3 tickets/mt/muontickets/muontickets/mt.py set-status <TICKET-ID> needs_review
python3 tickets/mt/muontickets/muontickets/mt.py done <TICKET-ID>

# Archive completed tickets
python3 tickets/mt/muontickets/muontickets/mt.py archive <TICKET-ID>
```

### Workflow

1. **Before starting any task**: Create or find an existing ticket.
2. **Claim the ticket**: Assign yourself as the owner.
3. **Do the work**: Implement the changes described in the ticket.
4. **Commit per ticket**: Each ticket should result in a single, focused commit. The commit message must reference the ticket ID (e.g., `T-000004: Set up port/ folder structure`).
5. **Push per ticket**: Push immediately after committing so each ticket's work is individually trackable.
6. **Close the ticket**: Move through `needs_review` -> `done` -> `archive`.

### Commit Convention

```
T-NNNNNN: Short description of what was done

- Detail 1
- Detail 2
```

### Ticket Types

| Type     | Use for                                    |
|----------|--------------------------------------------|
| code     | Feature implementation, bug fixes          |
| chore    | Project setup, config, dependency changes  |
| docs     | Documentation updates                      |
| tests    | Test additions or modifications            |
| refactor | Code restructuring without behavior change |
| spec     | Design specifications and planning         |

### Priority Levels

| Priority | Meaning                        |
|----------|--------------------------------|
| p0       | Critical / blocking other work |
| p1       | Important / should do next     |
| p2       | Nice to have / backlog         |

### Listing and Checking Tickets

```bash
# List all open tickets
python3 tickets/mt/muontickets/muontickets/mt.py ls

# Show a specific ticket
python3 tickets/mt/muontickets/muontickets/mt.py show <TICKET-ID>

# Board stats
python3 tickets/mt/muontickets/muontickets/mt.py stats
```

## Temporary Files

Use `tmp/` in the project root for any scratch or temporary files. **Never** write to `/tmp` or any path outside the project sandbox.

## Project Structure

```
muonledger/
├── agents.md              # This file - agent workflow rules
├── Makefile               # Build, test, clean targets
├── vendor/ledger/         # Original C++ ledger (submodule)
├── port/
│   ├── rust/              # Rust port
│   ├── python/            # Python port
│   ├── swift/             # Swift port
│   └── kotlin/            # Kotlin port
├── testing/
│   ├── parity/            # Cross-language parity tests
│   └── benchmarks/        # Performance benchmarks
├── verification/
│   ├── tlaplus/           # TLA+ formal specifications
│   └── z3/                # Z3 SMT solver proofs
├── tickets/               # MuonTickets task tracking
├── tmp/                   # Temporary/scratch files (gitignored)
└── .gitmodules            # Git submodule config
```
