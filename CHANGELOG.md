# Changelog

All notable changes to `populi-api` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-14

Most of the surface that shipped in 1.0.0 as contract-only has now been driven against a live
instance. No code changed as a result — the routes behaved as written — but two undocumented
behaviours turned up that callers need, and the coverage table in the README now reflects what is
actually proven rather than what was intended.

### Documented, each measured rather than inferred
- **A course enrollment's `student_id` is a PERSON id.** A row reporting `student_id: 24564256`
  resolves at `GET /people/24564256`; `by_student_id(24564256)` finds nobody. The rows carry no
  `person_id` at all, so the only identifier present is named after the scheme it does not belong
  to. It is the correct argument for the grade routes and the wrong one for anything resolving a
  visible student id, which finds nothing rather than failing.
- **An honoured `expand` can still be null.** `expand: ["student"]` adds the key to every
  `/people` row and sets it to `null` for non-students, which is a different thing from the key
  being absent because the expand was dropped.
- **`people.with_role()` walks every page.** On a role the size of Student that is thousands of
  people and dozens of requests against a budget shared with everything else using the key.

### Verified live
`academic_terms` (list/get/current), `courses` (offerings/assignments/enrollments), `data_slicer`
(reports/results), `files.download_link`, `people.online_payment_link`, `people.list` with
expands, `custom_fields.definitions_for_scope` and `definition()` including the options expand,
and `PopuliFilter` — the last confirmed by checking that a negated condition and its positive
partition the directory exactly (2,843 + 27,596 = 30,439), which a dropped filter cannot do.

Still unproven, and marked ○ in the README: the grade writes, file upload, term-scoped writes,
`people.update` and `by_student_ids`. Every one of them is a write or a bulk walk.

## [1.0.1] - 2026-09-14

### Fixed
- `custom_fields.definition()` requested `…/{field_id}/` with a trailing slash — the only call in
  the client that did, and the only spelling of that route never driven against a live instance.
  It now matches the form that has been. Nothing asserted the URL, which is how two spellings of
  one route coexisted unnoticed; there is now a test that fails on either one changing.

### Changed
- The verification claim below, which was broader than the evidence. See it for what is measured
  and what is not.

## [1.0.0] - 2026-09-14

Extracted from the `rupo` application, where it was written to replace a vendored client for
Populi's legacy XML API — an API Populi sunset on 2026-08-01.

**What is measured and what is not.** The core lifted out of `rupo` — people, tags, custom fields,
leads, communication plans, notes — was exercised against a live instance through real webhook
delivery before the extraction, and every behaviour noted below was measured there. The surface
added afterwards for parity with the .NET client — `courses`, `files`, `data_slicer`,
`academic_terms`, `PopuliFilter`, and the term-scoped and definition helpers on `custom_fields` —
was written from Populi's documented contract and covered by unit tests, but has **not** been
driven against a live instance. Given how many of the behaviours below are undocumented and
fail open, treat that half as unproven and verify it against your own instance before relying on
it. Reports of what it actually does are welcome.

It was built framework-free from the first commit specifically so this extraction would be a
directory move rather than a rewrite. Verified at the point of extraction: constructing a client
with no Django settings configured loads zero `django` modules.

### Added
- **`PopuliClient`** — transport with bearer auth, error-object detection regardless of HTTP
  status, an idempotency-aware retry policy, and paged reads that verify the page echo and refuse
  a short read.
- **Resource groups** — `people`, `tags`, `custom_fields`, `leads`, `communication_plans`,
  `notes`, `academic_terms`, `courses`, `files`, `data_slicer`.
- **`PopuliFilter`** — builds the filter envelope and refuses an empty filter or an empty group,
  both of which Populi ignores. An ignored filter matches everyone, which is the difference
  between a report about forty people and one about forty thousand. It removes the structural
  mistakes only; a misspelled condition name is structurally perfect and still discarded, so a
  new filter still has to be verified against the live API.
- **`test_connection()`**, which raises rather than returning False — a malformed key, a key for
  the wrong API, a base URL missing its `/api2/` suffix and an unreachable network are four
  different problems, and a bare boolean makes them one.
- **`with_pacing(utilisation)`** — a view claiming a share of the key's budget, sharing the
  session and credentials. Pacing the process taxes every interactive lookup in order to slow the
  one bulk job that needed slowing.
- **`Pacer` / `RateSchedule`** — a minimum interval between request starts, against a budget that
  is re-read per request so a long run widens by itself at the Pacific boundary. `utilisation`
  has no default: the budget belongs to the API key, not to one caller.
- **`populi_api.integration.django`** — the only Django-aware module, building the client from
  settings and holding it process-wide so the pacer is shared. A pacer created per request paces
  nothing.
- An exception hierarchy mirroring the .NET `Populi.Client`, so the two can be reasoned about
  together.

### Notes on behaviour that is not in Populi's documentation

Each of these was a defect first. They are listed because a future reader will otherwise
"simplify" one of them back:

- A **checkbox write replaces the whole selection**, so `add_option` reads the current set and
  posts the complete array. Measured: one option id sent to a field holding three left one row.
- **`input_type` decides whether a field is multi-valued**, never the row count. A checkbox
  holding exactly one option looks single-valued and a scalar write destroys it. The .NET client
  carried this same defect and fixed it in v3.0.1.
- **Custom info data is scoped**, and scope is a required argument with no default. Reading the
  wrong scope returns no rows rather than erroring.
- **`POST /notes` takes `note`**, while the read returns `content`.
- **An option field accepts a label and reports an id**, so write verification compares against
  both — otherwise every successful write reports as a failure.
- **Tag writes are not verified by re-reading.** That index lags an add by minutes while
  reflecting a remove in seconds; Populi's `"Tag already added"` 400 is the authoritative signal.
- **Adding a nonexistent tag succeeds and does nothing.** No guard is possible at write time;
  validate ids against `GET /tags`.
