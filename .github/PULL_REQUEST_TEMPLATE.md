## What does this change?

<!-- A short description, and the issue it closes if any. -->

## Why?

<!-- The problem being solved. -->

## Checklist

- [ ] `pytest` is green
- [ ] New or changed behaviour has a test
- [ ] If a catalog entry was added or changed: it cites an `official_doc` URL, and
      `processes` (or any scalar) appears **before** the first `detect.` / `redirect.` key
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] The safety model is untouched — or the change is explained below

## Safety model impact

<!--
Required if this touches dry-run semantics, the backup/undo path, the user-scope
write boundary, or the junction guard rails. Otherwise write "none".
-->
none

## How was this tested?

<!--
Commands you ran, platforms covered. `pytest -q` output is enough for small changes.
-->