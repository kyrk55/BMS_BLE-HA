"""Lokalne rozszerzenia integracji BMS_BLE: dodatkowe wzorce nazw i dodatkowe wtyczki BMS.

1. EXTRA_PATTERNS: dopisuje wzorce nazw Bluetooth do istniejacych modulow aiobmsble.
   Nowy wpis kopiuje pierwszy matcher modulu (service_uuid, connectable itd.) i podmienia
   tylko local_name. Klucz to nazwa pliku modulu w aiobmsble/bms/ bez .py, np.
       "jbd_bms": ["MOJABATERIA*"],

2. EXTRA_PLUGINS: wlasne wtyczki BMS lezace w tym folderze integracji (np. ant_old_bms.py).
   Kazda musi miec klase BMS dziedziczaca po aiobmsble.basebms.BaseBMS, a nazwa pliku
   musi konczyc sie na _bms. Wtyczki sa dopinane do listy wykrywanych BMS i dostepne
   tez pod nazwa aiobmsble.bms.<nazwa>.

Ten plik musi byc importowany w __init__.py PRZED .config_flow.
"""

from __future__ import annotations

from functools import cache
import importlib
import logging
import sys
from types import ModuleType
from typing import Any

_LOGGER = logging.getLogger(__name__)

# modul aiobmsble.bms -> lista dodatkowych wzorcow local_name
EXTRA_PATTERNS: dict[str, list[str]] = {}

# wlasne wtyczki z tego folderu
EXTRA_PLUGINS: list[str] = [
    "ant_old_bms",
]


def _make_patched(orig: Any, patterns: tuple[str, ...]) -> Any:
    def patched() -> list[dict[str, Any]]:
        base = [dict(m) for m in orig()]
        tmpl = next((m for m in base if "local_name" in m), base[0] if base else {})
        have = {m.get("local_name") for m in base}
        for pattern in patterns:
            if pattern not in have:
                new = dict(tmpl)
                new["local_name"] = pattern
                base.append(new)
        return base

    return patched


def _apply_patterns() -> None:
    for module_name, patterns in EXTRA_PATTERNS.items():
        if not patterns:
            continue
        try:
            module = importlib.import_module(f"aiobmsble.bms.{module_name}")
        except ImportError:
            _LOGGER.warning("Brak modulu aiobmsble.bms.%s, pomijam", module_name)
            continue

        bms_cls = getattr(module, "BMS", None)
        if bms_cls is None or not hasattr(bms_cls, "matcher_dict_list"):
            _LOGGER.warning("aiobmsble.bms.%s nie ma BMS.matcher_dict_list, pomijam", module_name)
            continue

        if getattr(bms_cls, "_extra_patterns_applied", False):
            continue

        orig = bms_cls.matcher_dict_list
        bms_cls.matcher_dict_list = staticmethod(_make_patched(orig, tuple(patterns)))
        bms_cls._extra_patterns_applied = True
        _LOGGER.info("aiobmsble.bms.%s: dodano wzorce nazw %s", module_name, patterns)


def _register_plugins() -> None:
    if not EXTRA_PLUGINS:
        return

    import aiobmsble.bms as bms_pkg  # noqa: PLC0415
    import aiobmsble.utils as bms_utils  # noqa: PLC0415

    if getattr(bms_utils, "_extra_plugins_applied", False):
        return

    modules: list[ModuleType] = []
    for name in EXTRA_PLUGINS:
        try:
            module = importlib.import_module(f"{__package__}.{name}")
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Nie udalo sie zaladowac wtyczki %s", name)
            continue
        if getattr(module, "BMS", None) is None:
            _LOGGER.warning("Wtyczka %s nie ma klasy BMS, pomijam", name)
            continue
        sys.modules.setdefault(f"aiobmsble.bms.{name}", module)
        setattr(bms_pkg, name, module)
        modules.append(module)
        _LOGGER.info("Zarejestrowano wtyczke BMS %s", name)

    if not modules:
        return

    orig = bms_utils.load_bms_plugins

    @cache
    def patched_load_bms_plugins() -> set[ModuleType]:
        return set(orig()) | set(modules)

    # podmien wszedzie, gdzie ktos juz trzyma referencje do oryginalu
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not (
            mod_name.startswith("aiobmsble") or mod_name.startswith(__package__ or "")
        ):
            continue
        if getattr(mod, "load_bms_plugins", None) is orig:
            setattr(mod, "load_bms_plugins", patched_load_bms_plugins)

    bms_utils._extra_plugins_applied = True


def apply() -> None:
    """Zaaplikuj wszystkie lokalne rozszerzenia."""
    _register_plugins()
    _apply_patterns()


apply()
