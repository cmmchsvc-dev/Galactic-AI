"""
Galactic AI — version single source of truth.

Everything reads from here: the core (GalacticCore.VERSION), the splash,
the Control Deck /api/status, and the release builder. Bump THIS file
(or run scripts/release.py --set-version X.Y.Z, which rewrites it) and
every surface updates together. config.yaml's system.version is stamped
from this value at load time, so stale configs can no longer win.
"""

VERSION = "2.1.7"
