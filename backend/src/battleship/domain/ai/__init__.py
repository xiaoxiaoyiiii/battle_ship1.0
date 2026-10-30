"""AI decision layer and turn driver (ticket #13).

Submodules import each other explicitly; this package deliberately re-exports
nothing at import time, because domain.magic.chain imports
battleship.domain.ai.difficulty and an eager re-export would create an import
cycle through the magic rules.

* difficulty -- per-seat AI tier resolution (the single implementation)
* policies   -- easy/normal/hard decisions + the difficulty dispatcher
* master     -- master-tier decisions, card pool and trial-play gate
* services.ai -- the turn driver (service layer)
"""

__all__: list[str] = []
