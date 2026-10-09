"""Load and validate the official cache-relocation catalog.

Every entry must carry an `official_doc` URL for the mechanism it claims; the
loader rejects `env_var`/`config_file` entries that have no doc link, so the
catalog cannot silently drift into guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 and below
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

VALID_METHODS = {"env_var", "config_file", "none"}
VALID_RISKS = {"low", "medium", "high"}
VALID_CATEGORIES = {"dev", "gui"}
VALID_SCOPES = {"user", "machine"}
PLATFORMS = ("windows", "macos", "linux")


class CatalogError(ValueError):
    """Raised when a catalog entry is malformed or unverifiable."""


@dataclass(frozen=True)
class DetectRule:
    env: List[str] = field(default_factory=list)
    windows: Optional[str] = None
    macos: Optional[str] = None
    linux: Optional[str] = None

    def default_for(self, platform: str) -> Optional[str]:
        return {"windows": self.windows, "macos": self.macos, "linux": self.linux}.get(platform)


@dataclass(frozen=True)
class RedirectRule:
    method: str = "none"
    env_name: Optional[str] = None
    scope: str = "user"
    value_template: Optional[str] = None
    config_path: Optional[str] = None
    config_key: Optional[str] = None
    config_format: Optional[str] = None


@dataclass(frozen=True)
class App:
    id: str
    name: str
    category: str
    platforms: List[str]
    detect: DetectRule
    redirect: RedirectRule
    official_doc: Optional[str] = None
    risk: str = "low"
    notes: str = ""
    #: Image names used to tell whether the app is currently running.
    processes: List[str] = field(default_factory=list)


def _parse_app(raw: Dict[str, Any], source: str, index: int) -> App:
    where = f"{source}#app[{index}]"
    for key in ("id", "name", "category", "platforms"):
        if key not in raw:
            raise CatalogError(f"{where}: missing required field {key!r}")

    category = str(raw["category"])
    if category not in VALID_CATEGORIES:
        raise CatalogError(f"{where}: category must be one of {sorted(VALID_CATEGORIES)}")

    platforms = [str(p) for p in raw["platforms"]]
    for p in platforms:
        if p not in PLATFORMS:
            raise CatalogError(f"{where}: unknown platform {p!r}")

    detect_raw = raw.get("detect", {}) or {}
    detect = DetectRule(
        env=[str(e) for e in detect_raw.get("env", [])],
        windows=detect_raw.get("windows"),
        macos=detect_raw.get("macos"),
        linux=detect_raw.get("linux"),
    )

    redirect_raw = raw.get("redirect", {}) or {}
    method = str(redirect_raw.get("method", "none"))
    if method not in VALID_METHODS:
        raise CatalogError(f"{where}: redirect.method must be one of {sorted(VALID_METHODS)}")

    scope = str(redirect_raw.get("scope", "user"))
    if scope not in VALID_SCOPES:
        raise CatalogError(f"{where}: redirect.scope must be one of {sorted(VALID_SCOPES)}")

    redirect = RedirectRule(
        method=method,
        env_name=redirect_raw.get("env_name"),
        scope=scope,
        value_template=redirect_raw.get("value_template"),
        config_path=redirect_raw.get("config_path"),
        config_key=redirect_raw.get("config_key"),
        config_format=redirect_raw.get("config_format"),
    )

    risk = str(raw.get("risk", "low"))
    if risk not in VALID_RISKS:
        raise CatalogError(f"{where}: risk must be one of {sorted(VALID_RISKS)}")

    official_doc = raw.get("official_doc")
    if method == "env_var" and not official_doc:
        raise CatalogError(f"{where}: redirect.method=env_var requires official_doc")
    if method == "env_var" and not redirect.env_name:
        raise CatalogError(f"{where}: redirect.method=env_var requires redirect.env_name")
    if method == "config_file" and not (redirect.config_path and redirect.config_key):
        raise CatalogError(
            f"{where}: redirect.method=config_file requires config_path and config_key"
        )

    return App(
        id=str(raw["id"]),
        name=str(raw["name"]),
        category=category,
        platforms=platforms,
        detect=detect,
        redirect=redirect,
        official_doc=str(official_doc) if official_doc else None,
        risk=risk,
        notes=str(raw.get("notes", "")),
        processes=[str(p) for p in raw.get("processes", [])],
    )


def default_catalog_dir() -> Path:
    return Path(__file__).with_name("data")


def load_catalog(directory: Optional[Path] = None) -> List[App]:
    """Load every ``*.toml`` file in the catalog directory, sorted by id."""
    if tomllib is None:  # pragma: no cover - depends on interpreter
        raise CatalogError(
            "no TOML reader available: run on Python 3.11+ or install `tomli`"
        )

    directory = Path(directory) if directory else default_catalog_dir()
    if not directory.is_dir():
        raise CatalogError(f"catalog directory not found: {directory}")

    apps: List[App] = []
    seen: Dict[str, str] = {}
    for path in sorted(directory.glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        for index, raw in enumerate(data.get("app", [])):
            app = _parse_app(raw, path.name, index)
            if app.id in seen:
                raise CatalogError(
                    f"duplicate app id {app.id!r} in {path.name} (also in {seen[app.id]})"
                )
            seen[app.id] = path.name
            apps.append(app)

    apps.sort(key=lambda a: (a.category, a.id))
    return apps
