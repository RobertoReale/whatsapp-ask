"""AI engines. Each module follows the engine contract in CLAUDE.md."""

from wa.engines import api, subscription

ENGINES = {"subscription": subscription, "api": api}
