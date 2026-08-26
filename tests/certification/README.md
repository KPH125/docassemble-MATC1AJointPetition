# Combined interview certification

This directory treats coverage as an auditable claim rather than a collection
of example runs.

## Proof artifacts

- `baseline.json` pins the combined source, each local included package, and
  known candidate overlays that have not yet been accepted. It also pins the
  Docker image digest and external interview package versions.
- `coverage_model.yml` declares the finite path model, input equivalence
  classes, list cardinality boundaries, and hang thresholds.
- `build_catalog.py` resolves the local include graph and catalogs declared
  screens and branch expressions.
- `generate_scenarios.py` materializes every declared path archetype.
- `runtime_driver.py` drives fresh API sessions and writes every transition,
  answer, terminal state, generated bundle member, error, and timeout to a
  ledger. Screens are keyed by package/file plus a fingerprint of the exact
  YAML block, so reused IDs cannot satisfy each other. If Docassemble reports
  an abbreviated source locator, the audit accepts it only when that exact
  fingerprint has one unambiguous catalog match.
- `verify_runtime_manifest.py` rejects image or external-package drift before
  a runtime result can count.
- `screen_classification.yml` is the only place an exact local screen block may
  be excluded, and every exclusion requires a source-backed reason.
- `audit_coverage.py` compares runtime evidence with the static denominator and
  fails if any exact source screen is missing, an exclusion is stale or
  unsupported or contradicted by runtime observation, a modeled path is absent,
  a path fails, a generated packet has a missing or extra document, or a path
  reaches the wrong terminal outcome.

Generated catalogs, scenarios, ledgers, logs, and runtime manifests are CI
artifacts. They are intentionally not committed as hand-edited evidence.

## Hang definition

A path fails when any one of these occurs:

1. an HTTP request exceeds the declared request timeout;
2. the same runtime state appears too many times consecutively;
3. a state is revisited beyond the declared limit;
4. a scenario exceeds its wall-clock budget;
5. the interview exceeds its maximum step count;
6. background document generation stays on AssemblyLine's waiting screen past
   its separate task timeout; or
7. Docassemble reports an infinite loop or another error screen.

List questions include the sought variable and index in their state
fingerprint, so legitimate repeated list screens are not mistaken for hangs.

## Local static checks

From the repository root:

```bash
python3 tests/certification/build_catalog.py
python3 tests/certification/generate_scenarios.py
python3 -m unittest discover -s tests/certification -p 'test_*.py' -v
```

Runtime tests require a Docassemble server and API key. CI supplies both using
an isolated Docker container. Terminal assertions use the interview's
authenticated, read-only `combined_certification_snapshot` action rather than
`GET /api/session`: serializing the complete interview dictionary can traverse
ALDocument objects and generate previews merely by observing them. Exact packet
membership is proved from `enabled_documents()` immediately before generation,
then corroborated against the background task's `_downloadable_files` results.

Manual workflow dispatches may set `scenario_pattern` to a full-match regular
expression for focused diagnosis. A blank pattern remains the only exhaustive
certification run; focused ledgers intentionally fail the all-path audit.
