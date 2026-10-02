"""Lokalna lata: dodatkowe wzorce nazw Bluetooth dla modulow aiobmsble.

Dopisuje wzorce do matcher_dict_list() wskazanych modulow BMS przy starcie
integracji. Nowy wpis kopiuje pierwszy istniejacy matcher modulu (np. service_uuid,
connectable) i podmienia tylko local_name, wiec dziala dla dowolnego modulu.

Zeby dodac kolejny BMS: dopisz wpis do EXTRA_PATTERNS, np.
    "jbd_bms": ["MOJABATERIA*"],
Nazwa klucza to nazwa pliku modulu w aiobmsble/bms/ bez .py.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# modul aiobmsble.bms -> lista dodatkowych wzorcow local_name (wildcardy jak w fnmatch)
EXTRA_PATTERNS: dict[str, list[str]] = {
    "ant_bms": ["ANT?BLE2*"],
}


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


def apply() -> None:
    """Zaaplikuj dodatkowe wzorce do wszystkich modulow z EXTRA_PATTERNS."""
    for module_name, patterns in EXTRA_PATTERNS.items():
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


apply()
