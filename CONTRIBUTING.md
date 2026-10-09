# Contributing

Thanks for helping. The most valuable contribution is **a new catalog entry**:
one TOML block that tells `devcache` where another tool keeps its cache and
which official mechanism relocates it.

Please read the [design decisions](docs/DESIGN.md) first — especially the safety
model, which is not negotiable.

## The one hard rule

> A catalog entry may only be executable if a **vendor** documents the
> mechanism.

`redirect.method = "env_var"` and `"config_file"` entries **must** carry an
`official_doc` URL, and `env_var` entries must name a real environment variable.
The loader (`catalog.py`) enforces this and will reject the entry — and the test
suite will fail — if the doc link is missing. If there is no official
mechanism, use `redirect.method = "none"`: the entry is then reported (path and
size) but never executed.

Do not submit third-party hacks, undocumented registry keys, or "it works on my
machine" recipes. If a vendor *does* provide an in-app setting but no variable,
say so in `notes` and use `none`.

## Adding an entry

1. Pick the right file in `src/devcache/data/` (or add a new one).
2. Copy an existing block as a template.
3. Fill in `detect.env` (variables to check, in order), the per-platform
   defaults, and the redirect rule.
4. Run `pytest`. `tests/test_catalog.py` validates docs, env names, config
   paths/keys and duplicate ids.
5. Sanity-check detection on a real machine: `devcache scan --json` and confirm
   your entry reports the path you expect.

```toml
[[app]]
id = "your-tool"
name = "Your Tool (what it stores)"
category = "dev"                     # dev | gui
platforms = ["windows", "macos", "linux"]
official_doc = "https://..."         # required when method != "none"
risk = "low"                         # low | medium | high
notes = "What the variable/key controls, and any migration caveat."
processes = ["yourtool.exe"]         # optional, used for running-app detection

detect.env = ["YOUR_TOOL_HOME"]
detect.windows = "%USERPROFILE%\\.your-tool"
detect.macos = "~/.your-tool"
detect.linux = "~/.your-tool"

redirect.method = "env_var"          # env_var | config_file | none
redirect.env_name = "YOUR_TOOL_HOME"
redirect.scope = "user"              # only "user" is ever written
redirect.value_template = "{target}\\your-tool"
```

### Two traps worth knowing

1. **TOML dotted keys.** Put scalars such as `processes` **before** the first
   `detect.` / `redirect.` line. After a dotted key, a bare `processes = [...]`
   becomes `app.detect.processes` and the entry will look like it is missing a
   field.
2. **Do not invent `value_template`s.** It must be where the *official*
   mechanism points, not where you think the cache would look tidy.

## Development setup

```bash
git clone https://github.com/jumppppp/devcache
cd devcache
python -m venv .venv
. .venv/Scripts/activate        # Windows
# . .venv/bin/activate          # Linux/macOS
pip install -e ".[dev]"
pytest
```

The suite runs on Windows and Linux. On non-Windows, registry access degrades to
"not set" (`winenv.IS_WINDOWS`), which keeps detection logic testable.

## Code layout

| module | responsibility |
|---|---|
| `catalog.py` | load + validate the TOML catalog; the schema gatekeeper |
| `winenv.py` | Windows env layer: expansion, registry read/write, broadcast, `.reg` backup |
| `sizing.py` | directory size accounting (never follows reparse points) |
| `detect.py` | effective path, source, size and state per entry |
| `plan.py` | plan model, JSON round-trip, backup-then-apply, undo |
| `junction.py` | NTFS junction create/remove, behind guard rails |
| `cli.py` | the six subcommands |

## Pull requests

* Keep changes focused; one concern per PR.
* `pytest` must be green, and new behaviour needs a test.
* If you touch the safety model (dry-run, backups, junction guards), say so
  explicitly in the PR description — those paths are the reason this tool is
  safe to run.
* Update `CHANGELOG.md` under `[Unreleased]`.

## Reporting a tool that moved its cache

If a vendor changes their default location or variable, open an issue with:
the tool and version, the path you observed, and a link to the vendor's current
documentation. Include the output of `devcache scan --json` for that entry if
you can.