"""devcache — detect and relocate developer-tool caches.

Only official mechanisms are used for relocation: documented environment
variables and official config files, each backed by an `official_doc` URL in
the catalog. Junction-based relocation is opt-in (--allow-destructive) and
heavily guarded; it is refused in non-interactive runs.
"""

__version__ = "0.1.0"
