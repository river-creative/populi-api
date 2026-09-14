# populi-api

[![PyPI](https://img.shields.io/pypi/v/populi-api.svg)](https://pypi.org/project/populi-api/)
[![Python versions](https://img.shields.io/pypi/pyversions/populi-api.svg)](https://pypi.org/project/populi-api/)
[![Licence](https://img.shields.io/pypi/l/populi-api.svg)](LICENSE)
[![Publish](https://github.com/river-creative/populi-api/actions/workflows/publish.yml/badge.svg)](https://github.com/river-creative/populi-api/actions/workflows/publish.yml)

A Populi API2 client for Python.

Populi's API fails open in a number of places — a request it cannot read is answered with
HTTP 200 and quietly ignored. This client is built around that: the behaviours documented
below were each a defect before they were a paragraph, measured against a live instance
rather than read in the reference.

## Install

```
pip install populi-api
```

Requires Python 3.9+ and `requests`. Nothing else — the Django adapter is optional and imports
Django only if you use it.

## Use

```python
from populi_api import Populi, PopuliClient
from populi_api.pacing import Pacer

populi = Populi(PopuliClient(
    base_url="https://school.populiweb.com/api2/",   # note /api2/ — see below
    access_key=key,
    pacer=Pacer(utilisation=0.8),
))

person = populi.people.by_student_id("101")
populi.tags.add(person["id"], 700010)
populi.custom_fields.add_option(person["id"], 900010, "admissions", 500010)
```

### What it covers

| Group | | Driven live? |
|---|---|---|
| `people` | get, list (filtered), `by_student_id`, `by_student_ids` (bulk), `with_role`, update, online payment link | ◐ |
| `tags` | list, add, remove | ✅ |
| `custom_fields` | read/write per scope, checkbox options, field definitions, term-scoped data | ◐ |
| `leads` | list, current, current status, set status | ✅ |
| `notes` | list, create | ✅ |
| `communication_plans` | list, delete | ✅ |
| `academic_terms` | list, get, current | ✅ |
| `courses` | offerings, assignments, enrollments | ✅ |
| `courses` | grades (set / excuse / clear) | ○ |
| `files` | presigned download link | ✅ |
| `files` | download bytes, profile picture upload | ○ |
| `data_slicer` | reports, results | ✅ |

Plus `populi.test_connection()` and `populi.with_pacing(0.8)` — and `PopuliFilter` (✅).

**✅ driven against a live instance.** **○ written from Populi's documented contract** and
unit-tested, but never sent to a real server. **◐ mixed** — `people`'s `by_student_id`, `list`
with expands, and `online_payment_link` are proven, as are the custom-field read/write, checkbox
and `definition` paths; `by_student_ids`, `with_role`, `update` and the term-scoped write helpers
are not.

Everything still marked ○ is a **write** or a bulk walk, which is why it is unproven rather than
untried — verifying those means changing data on somebody's live instance.

This distinction is in the table rather than a footnote because of what the next section says: on
this API a wrong request is answered with a 200, so "it compiles and the unit tests pass" is
weaker evidence here than it would be almost anywhere else. If you exercise one of the ○ paths,
a report saying what Populi actually did is the single most useful contribution available.

### Filters

Populi filters **fail open** — a condition it cannot read is discarded and the request answers
200 with the entire unfiltered list. Build them rather than writing the JSON:

```python
from populi_api import PopuliFilter

people = populi.people.list(
    PopuliFilter().all_of().where_custom_field(212516)      # has an answer
)
```

`PopuliFilter` refuses an empty filter and an empty group, because Populi ignores both and an
ignored filter matches everyone. It cannot check a condition *name* against a route, so verify a
new filter against the live API and confirm the result set actually **narrowed** — a query
returning more than you expected is the signature of a dropped condition.

The reliable way to discover a shape is Populi's own UI: build the filter on an index page, save
it as a preset, edit the preset, and use **"Show JSON for API"**.

**Django applications** use the adapter instead, which builds the same object from settings and
holds it process-wide:

```python
from populi_api.integration.django import get_populi
```

It needs `POPULI_BASE_URL` and `POPULI_ACCESS_KEY` in settings, and reads
`POPULI_PACING_UTILISATION` (default 0.8). The client itself imports no Django — verified, not
just intended: constructing one with no settings module configured loads zero `django` modules.
That is what makes this package portable, and it is worth keeping true.

## Populi fails open. Read this before trusting a 200.

Every item below was measured against a live instance, not read in the documentation, and each
one succeeds as far as the caller can see while doing nothing it was asked to do.

- **Adding a tag that does not exist returns success.** No error, no effect. A stale id in a caller's config is not an
  error anywhere — it is an automation that silently stops applying a tag, for as long as nobody
  notices the absence. There is no guard available at
  write time — validate ids against `GET /tags`.
- **A checkbox write REPLACES the whole selection.** POSTing one option id to a field holding
  three leaves one row, not four. `add_option` reads the current set and posts the complete
  array for exactly this reason.
- **Row count cannot tell you a field is a checkbox.** One holding exactly one option looks
  single-valued, and a scalar write destroys it. `input_type` decides, and is cached per client.
  The .NET client had this defect and fixed it in v3.0.1.
- **Custom info data is SCOPED** — `person`, `admissions`, `student`, `campuslife`,
  `financial`, `financialaid`, or a term. Reading the wrong scope returns **no rows**, not an
  error, so code that treats absence as "not set" then overwrites. Scope is a required argument
  here; it has no default on purpose.
- **`POST /people/{id}/notes` takes `note`; the read returns `content`.** Sending `content` is
  answered with `Missing required parameter: note`.
- **An option field accepts a label and reports an id.** Writing `"In Progress"` reads back as
  `458178`. Verification compares against both, or every successful write looks like a failure.
- **The tags index lags an add by minutes**, while a remove appears in seconds. `tags.add` does
  not verify by re-reading; Populi's own `"Tag already added"` 400 is the authoritative signal.
- **Error objects arrive with HTTP 200.** On a list route that deserializes to an empty `data`
  array — indistinguishable from "no results". Every response is checked for
  `{"object": "error"}` regardless of status.
- **Assignment grades take POINTS and answer in PERCENT.** Write 1 to a 1-point assignment and
  Populi replies `grade: 100`, so a verifying read comparing against what it sent fails on every
  success. Excusing is the *grade* `"E"` — the route also takes an `excused` parameter, returns
  200, and ignores it.
- **An `expand` Populi does not recognise is dropped, still answering 200.** A missing `options`
  key therefore means "not honoured", never "this field has none".
- **A course enrollment's `student_id` is a PERSON id.** Measured: a row reporting
  `student_id: 24564256` resolves at `GET /people/24564256`, while `by_student_id(24564256)`
  finds nobody. The rows carry no `person_id` key at all, so the only identifier present is the
  one whose name describes the other scheme. Pass it straight to the grade routes, which take a
  person id; never to anything resolving a visible student id, which will find nothing rather
  than fail.
- **An expand that IS honoured can still be null.** `expand: ["student"]` on `/people` adds the
  `student` key to every row and sets it to `null` for non-students. Absent key and null value
  mean different things — dropped expand versus "this person is not a student" — and only
  checking for the key distinguishes them.

## Failures

Everything raises `PopuliApiError` or a subclass: `PopuliAuthError`, `PopuliNotFoundError`,
`PopuliRateLimitError`, `PopuliIncompleteReadError`, `PopuliPagingError`. Members mirror the
.NET client — `status_code` (`None` when no response arrived), `populi_code`, `populi_type`,
`endpoint`, `was_reported_with_success_status`, `raw_body`, and `is_client_error`, which reads
Populi's own code in preference to the HTTP status because a 200 can carry `"code": 400`.

**Paged reads refuse a short read** (`PopuliIncompleteReadError`) rather than returning a partial
list, and check the page echo on every page. Both failures are otherwise silent: a paging
parameter that never reaches Populi returns page 1 forever while looking healthy, and a dropped
page returns a shorter list. Callers act on absence, so a short read is not a smaller answer —
it is a wrong one.

## Rate limits

50 requests/minute 03:00–19:00 Pacific, 100/minute outside, **per API key across every process
using it**. `Pacer` enforces a minimum interval between request *starts* — a concurrency cap is
not a rate limit; five concurrent requests at 200ms is thirty times the daytime budget. The
budget is re-read per request, so a long run widens by itself at the boundary instead of staying
pinned to whichever window it started in.

`utilisation` has no default. The allowance belongs to the key, not to one caller, so a caller
states the share it is taking rather than taking all of it by omission.

## Licence and contributing

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Use it for anything, including
commercially and in closed-source work.

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Apache-2.0 was chosen over MIT
for one specific reason: its section 5 says contributions are under the same terms unless stated
otherwise, so contributing needs no separate agreement and no ambiguity about what was granted. It
also carries an explicit patent grant, which MIT is silent on.

Not affiliated with or endorsed by Populi.

## Tests

```
python -m unittest discover -s populi_api/tests -t .
```

No Django, no network, no test runner beyond the standard library — which is the point.

**They are written from Populi's contract, not from this implementation.** That distinction is
not pedantic: the notes bug above shipped with a passing unit test asserting `{'content': ...}`,
because the test checked that the client sent what the client intended to send. A test written
from the implementation cannot discover that the implementation disagrees with the service.
