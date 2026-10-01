from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConstraintAliases:
    property_aliases: dict[str, str]
    target_aliases: dict[str, str]


# Risolto rispetto a questo file (non tramite importlib.resources con un nome di
# pacchetto punteggiato) perche' in questo repo i moduli non vengono sempre
# importati con lo stesso percorso qualificato (es. `src.morph_kgc_changes_...`
# da uno script lanciato dalla root, vs `morph_kgc_changes_...` da un test) —
# un path relativo a __file__ funziona in entrambi i casi.
DEFAULT_ALIAS_RESOURCE = Path(__file__).parent / "resources" / "chad_ap_aliases.json"


def load_constraint_aliases(path: str | Path | None = None) -> ConstraintAliases:
    if path is None:
        resource = DEFAULT_ALIAS_RESOURCE
        data = json.loads(resource.read_text(encoding="utf-8"))
    else:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ConstraintAliases(
        property_aliases=dict(data.get("property_aliases", {})),
        target_aliases=dict(data.get("target_aliases", {})),
    )


def _apply_alias(symbol: str, aliases: dict[str, str]) -> str:
    return aliases.get(symbol, symbol)


def apply_property_alias(symbol: str, aliases: ConstraintAliases | None) -> str:
    if aliases is None:
        return symbol
    return _apply_alias(symbol, aliases.property_aliases)


def apply_target_alias(symbol: str, aliases: ConstraintAliases | None) -> str:
    if aliases is None:
        return symbol
    return _apply_alias(symbol, aliases.target_aliases)
