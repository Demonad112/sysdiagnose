"""Claude-facing analysis layer over the Sysdiagnose Analysis Framework.

This package is deliberately outside ``src/sysdiagnose`` so the fork can keep
merging upstream cleanly. It reuses SAF's parsers, analysers and utils rather
than reimplementing them.
"""

SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION"]
