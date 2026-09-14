# Releasing

Releases are driven by tags. Pushing a tag matching `v*` runs
[`.github/workflows/publish.yml`](.github/workflows/publish.yml), which tests, builds, and
publishes. Nothing is published by hand, and no API token exists to be leaked — see
[Trusted publishing](#trusted-publishing) below.

## The one rule: the tag and the version must agree

`v1.0.0` requires `version = "1.0.0"` in `pyproject.toml`. The workflow refuses the mismatch
before it builds anything.

That guard is not bureaucracy. **PyPI takes the version from the built artifact and never from
the tag**, so without it, tagging `v1.0.0rc1` against a `pyproject.toml` still declaring `1.0.0`
uploads `1.0.0` to TestPyPI. The later `v1.0.0` tag then builds `1.0.0` again, TestPyPI rejects it
as a duplicate, and that failure takes down the job the real publish depends on — so a release
fails for a reason with no visible connection to what you did two tags ago. Refusing the mismatch
up front costs one step and a clear error message.

So bumping the version is part of tagging, always, in the same sequence.

## Cutting a release

### 1. Rehearse with a release candidate

```
# set version = "1.0.0rc1" in pyproject.toml, commit, push
git tag v1.0.0rc1
git push origin v1.0.0rc1
```

An `rc` tag stops at TestPyPI — the `pypi` job is skipped. Confirm it installs:

```
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ populi-api==1.0.0rc1
```

`--extra-index-url` is needed because `requests` is not reliably mirrored on TestPyPI.

What this step is actually for: the package itself is already proven by the test suite and
`twine check`. What is *not* proven until a tag runs is the OIDC exchange — whether the pending
publisher's four fields match this repository, this workflow filename and this environment. A
typo there fails at publish time and nowhere earlier. Rehearse it somewhere throwaway.

### 2. Release

```
# set version = "1.0.0" in pyproject.toml, update the CHANGELOG date, commit, push
git tag v1.0.0
git push origin v1.0.0
```

This publishes to TestPyPI **and** PyPI.

### 3. Verify

```
pip install populi-api==1.0.0
```

Check <https://pypi.org/project/populi-api/> renders the README and shows the Apache-2.0 licence
and the project links.

## Version numbers are permanent

A published version can be deleted but **never re-uploaded**. If `1.0.0` ships wrong, the fix is
`1.0.1` — there is no replacing it. This is the whole reason for step 1.

The same applies on TestPyPI, which is why rc versions are real version numbers rather than
repeated uploads of the same one. The TestPyPI job sets `skip-existing` so that re-running a job
on an unchanged tag is not an error; the PyPI job deliberately does not, because there a duplicate
means something is wrong and should be loud.

## Trusted publishing

There is no PyPI API token anywhere — not in the repository, not in GitHub secrets. GitHub proves
via short-lived OIDC that it is running this workflow, and PyPI decides from that whether to accept
the upload. This also produces [PEP 740 attestations](https://docs.pypi.org/attestations/)
automatically, which PyPI accepts from trusted publishers only.

The configuration lives on PyPI, not in this repository, so it is recorded here. Both
<https://pypi.org/manage/account/publishing/> and
<https://test.pypi.org/manage/account/publishing/> hold:

| Field | Value |
|---|---|
| PyPI Project Name | `populi-api` |
| Owner | `river-creative` |
| Repository name | `populi-api` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` on PyPI, `testpypi` on TestPyPI |

**All five must match exactly.** Renaming the repository, renaming the workflow file, or changing
an environment name breaks publishing, and the error arrives at upload time rather than at the
change that caused it.

`id-token: write` is granted per job rather than per workflow, so the job that runs the test suite
never holds the credential.

## Building locally

Nothing here is required to release — the workflow does all of it — but it is how you check a
packaging change without spending a version number:

```
python -m venv .venv
.venv/bin/pip install --upgrade build twine
.venv/bin/python -m build
.venv/bin/twine check dist/*
```

`pyproject.toml` requires **setuptools >= 77**, because the metadata uses PEP 639 (`license` as an
SPDX expression, plus `license-files`). Against an older setuptools this does not quietly fall back
to the legacy `License` field — it fails with `invalid pyproject.toml config: project.license`.
`build` provisions its own environment and resolves to a current release, so this only bites when
building the sdist against a pinned or distribution-supplied setuptools.

Worth doing before a release, because it catches what a green test suite cannot — a missing
dependency, or a module left out of the wheel:

```
python -m venv .venv-smoke
.venv-smoke/bin/pip install dist/populi_api-*.whl
.venv-smoke/bin/python -c "from populi_api import PopuliClient; print('ok')"
```

That is not hypothetical. An undeclared `certifi` dependency in this client's history would have
been a 500 on every request, and no unit test would have noticed: the test environment had it
installed for other reasons.
