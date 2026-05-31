## ADDED Requirements

### Requirement: Task schema conformance

Every line of `measurement/tasks.jsonl` SHALL be a JSON object matching the task schema defined in `measurement/tasks.md`. Required fields: `task_id`, `class`, `user_message`, `expected_answer_summary`, `expected_citations`, `policy_classes_invoked`, `booking_data_required`, `rubric`. The `rubric` object MUST contain `factual_correctness`, `citation_accuracy`, `no_fabrication`.

#### Scenario: Valid task passes validator

- **WHEN** a task line contains all required fields with correct types
- **THEN** the validator records a pass for that line

#### Scenario: Missing field is rejected

- **WHEN** a task line omits any required field
- **THEN** the validator fails with a message identifying the line and the missing field

#### Scenario: Unknown field is rejected

- **WHEN** a task line contains a field not in the schema
- **THEN** the validator fails — the schema is closed, not open. New fields require a schema update first.

### Requirement: Task ID stability and uniqueness

Every `task_id` SHALL match the regex `^(POL|TXN|MIX|EDGE)-\d{3}$` and SHALL be unique across the file. Once a task ID is committed to `main`, its content is immutable — edits create a new ID and the old ID is recorded as deprecated in `measurement/tasks_expected_answers.md`.

#### Scenario: Duplicate IDs are rejected

- **WHEN** two lines share the same `task_id`
- **THEN** the validator fails identifying both line numbers

#### Scenario: Malformed ID is rejected

- **WHEN** a `task_id` does not match the prefix pattern (e.g., `POL-1`, `Mix-001`, `EDGE-0010`)
- **THEN** the validator fails

#### Scenario: ID prefix matches class

- **WHEN** a task has `class: "policy"` but `task_id: "MIX-001"`
- **THEN** the validator fails — prefix and class must agree (POL↔policy, TXN↔transactional, MIX↔mixed, EDGE↔edge)

### Requirement: Class distribution

The complete task file SHALL contain exactly 3 `policy`, 3 `transactional`, 8 `mixed`, and 3 `edge` tasks (17 total). Mid-draft states (partial files) are permitted; the distribution check is enforced when the file is marked complete via a `# COMPLETE` marker on the final line or via a CI flag.

#### Scenario: Final distribution check

- **WHEN** the validator runs in `--strict` mode (CI) and the file is marked complete
- **THEN** counts must match 3/3/8/3 exactly; any deviation fails

#### Scenario: Mid-draft permitted

- **WHEN** the validator runs without `--strict` (local development, partial file)
- **THEN** distribution is reported but not enforced

### Requirement: Controlled vocabulary for policy classes

Values in `policy_classes_invoked` and `expected_citations` SHALL be drawn from `measurement/policy_classes.json`, a controlled list derived from H2 sections of `corpus/swiss_faq.md`. New values require updating the vocabulary file with a justification comment.

#### Scenario: Unknown policy class is rejected

- **WHEN** a task uses a `policy_classes_invoked` value not in `policy_classes.json`
- **THEN** the validator fails and lists the closest valid values

#### Scenario: Vocabulary is decoupled from validator

- **WHEN** corpus sections change and `policy_classes.json` is updated
- **THEN** the validator picks up new values without code changes

### Requirement: Check 2 phrasing rule

Per `METHODOLOGY.md` §"Check 2 — Task-set neutrality," `user_message` SHALL NOT contain architect-style category names or grep-friendly policy vocabulary. The validator MAINTAINS a blacklist of disallowed substrings (case-insensitive): "rebooking policy", "cancellation policy", "refund policy", "baggage policy", "what is your policy on", "what's your policy on", "according to your policy", "per your policy", "your policy on". Additions to the blacklist require updating `measurement/check2_blacklist.json`.

#### Scenario: Architect phrasing is rejected

- **WHEN** a `user_message` contains a blacklisted substring
- **THEN** the validator fails with the matched phrase and a rewrite hint

#### Scenario: Customer phrasing passes

- **WHEN** a `user_message` uses colloquial language describing the situation (e.g., "I need to push my departure back two days")
- **THEN** the validator does not object on Check 2 grounds

### Requirement: Referential integrity to booking data

Any `book_ref`, `flight_no`, or `ticket_no` mentioned in `user_message` SHALL resolve to a row in `data/travel.sqlite`. The set of fixture values that may be referenced is recorded in `measurement/task_fixtures.json` and is sampled once via `measurement/scripts/sample_fixtures.py` for reproducibility.

#### Scenario: Referenced booking exists

- **WHEN** `user_message` mentions `book_ref` "ABC123"
- **THEN** the validator queries `bookings` table and confirms a matching row exists

#### Scenario: Phantom booking is rejected

- **WHEN** `user_message` mentions a `book_ref` not in `bookings`
- **THEN** the validator fails

#### Scenario: Fixtures file is the only sanctioned source

- **WHEN** a task references a value present in `data/travel.sqlite` but not in `task_fixtures.json`
- **THEN** the validator warns (not fails) — encourages adding to fixtures so the choice is documented and reproducible

### Requirement: Booking data flag accuracy

`booking_data_required` SHALL be `true` for every task whose `user_message` references a specific booking, flight, ticket, or customer-specific data. It SHALL be `true` for all `transactional` tasks. It MAY be `false` only for `policy` tasks and for `edge` tasks whose design specifically does not depend on booking data.

#### Scenario: Transactional task without booking flag

- **WHEN** a task with `class: "transactional"` has `booking_data_required: false`
- **THEN** the validator fails

#### Scenario: Policy task referencing booking

- **WHEN** a task with `class: "policy"` includes a `book_ref` in `user_message`
- **THEN** the validator fails — it should be reclassified as `mixed`

### Requirement: Expected citations match class

For tasks where `class` is `policy`, `mixed`, or `edge`, `expected_citations` SHALL be a non-empty list. For `transactional` tasks, `expected_citations` MAY be empty.

#### Scenario: Empty citations on policy task

- **WHEN** a `policy` task has `expected_citations: []`
- **THEN** the validator fails

#### Scenario: Transactional task with no citations

- **WHEN** a `transactional` task has `expected_citations: []`
- **THEN** the validator passes

### Requirement: Expected answers documented separately

For every task in `tasks.jsonl`, an entry SHALL exist in `measurement/tasks_expected_answers.md` containing: the task ID, the human-derived expected answer, a verbatim quote from `corpus/swiss_faq.md` supporting any policy claim, and the SQL queries (if any) used to derive the transactional portion. This is the answer key for manual verification and for adjudicating LLM-as-judge disputes.

#### Scenario: Task missing answer entry

- **WHEN** `tasks.jsonl` contains `MIX-007` but `tasks_expected_answers.md` has no entry for `MIX-007`
- **THEN** the validator fails

#### Scenario: Answer entry without task

- **WHEN** `tasks_expected_answers.md` contains an entry for `MIX-099` not present in `tasks.jsonl`
- **THEN** the validator fails (orphaned answer — likely a deprecated/typo'd ID)

### Requirement: Validator runs in CI

The validator SHALL run as part of the project's test suite (`pytest tests/test_tasks.py`) and SHALL fail the build on any violation. The validator MUST also be invokable standalone (`python measurement/scripts/validate_tasks.py`) for fast local iteration.

#### Scenario: CI rejects malformed task

- **WHEN** a pull request modifies `tasks.jsonl` introducing a violation
- **THEN** the CI test fails and blocks merge

#### Scenario: Local fast-iteration mode

- **WHEN** a contributor runs the standalone validator
- **THEN** all violations are reported in a single pass with line numbers, without requiring pytest setup
