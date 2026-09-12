# Changelog

All notable changes to `populi-api` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-12

Extracted from the `rupo` application, where it was written to replace a vendored client for
Populi's legacy XML API — an API Populi sunset on 2026-08-01. It is 1.0.0 rather than 0.1.0
because it did not arrive untested: every function was exercised against a live instance through
real webhook delivery before the extraction, and the behaviours below were measured there.

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
