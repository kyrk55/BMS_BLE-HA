"""ANT BMS, stary protokol BLE (np. ANT-BLE20A, MAC w stylu AA:BB:CC:xx:23:45).

Lokalna wtyczka dla integracji BMS_BLE (patman15), rejestrowana przez extra_patterns.py.

Protokol wg syssi/esphome-ant-bms (komponent ant_bms_old_ble):
  zadanie statusu:  DB DB 00 00 00 00  zapisane na charakterystyke FFE1
  odpowiedz:        140 bajtow w notyfikacjach FFE1, naglowek AA 55 AA FF,
                    liczby big endian, na koncu 16 bitowa suma kontrolna.
"""

from __future__ import annotations

from typing import Any, Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample
from aiobmsble.basebms import BaseBMS

# Wzorce nazw Bluetooth, po ktorych wtyczka rozpoznaje BMS (wildcardy jak w fnmatch).
# Nowe ANT (nowy protokol) maja nazwy typu ANT-BLE16ZMUB / ANT-BLE24BHUB i tu NIE pasuja.
NAME_PATTERNS: Final[tuple[str, ...]] = ("ANT?BLE??A",)

# Jesli prad wychodzi z odwrotnym znakiem (ladowanie ujemne), zmien na -1.
CURRENT_SIGN: Final[int] = 1

_SERVICE: Final[str] = normalize_uuid_str("ffe0")
_HEAD: Final[bytes] = b"\xaa\x55\xaa"
_FRAME_LEN: Final[int] = 140
_CMD_STATUS: Final[bytes] = bytes([0xDB, 0xDB, 0x00, 0x00, 0x00, 0x00])
_MAX_CELLS: Final[int] = 32
_TEMP_SENSORS: Final[int] = 6

# kody stanu MOSFET, ktore nie oznaczaja problemu
_CHG_OK: Final[frozenset[int]] = frozenset({0x00, 0x01, 0x04, 0x0F})
_DSG_OK: Final[frozenset[int]] = frozenset({0x00, 0x01, 0x0B, 0x0F})


class BMS(BaseBMS):
    """ANT BMS ze starym protokolem BLE."""

    INFO: BMSInfo = {  # type: ignore[typeddict-unknown-key]
        "default_manufacturer": "ANT",
        "default_model": "BMS (old BLE protocol)",
        "manufacturer": "ANT",
        "model": "BMS (old BLE protocol)",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Inicjalizacja, argumenty przekazywane bez zmian do BaseBMS."""
        super().__init__(*args, **kwargs)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[dict[str, Any]]:
        """Wzorce ogloszen Bluetooth."""
        return [
            {"local_name": pattern, "service_uuid": _SERVICE, "connectable": True}
            for pattern in NAME_PATTERNS
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Wymagane serwisy."""
        return (_SERVICE,)

    @staticmethod
    def uuid_rx() -> str:
        """Charakterystyka notyfikacji."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Charakterystyka zapisu."""
        return "ffe1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Stary ANT nie ma serwisu informacji o urzadzeniu."""
        return BMSInfo()

    @staticmethod
    def _checksum_ok(frame: bytes) -> bool:
        expected: int = int.from_bytes(frame[-2:], "big")
        return expected in (
            sum(frame[4:-2]) & 0xFFFF,
            sum(frame[:-2]) & 0xFFFF,
        )

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Skladanie ramki 140 bajtow z kawalkow notyfikacji."""
        if bytes(data[:3]) == _HEAD:
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug(
            "RX BLE data (%i/%i): %s", len(self._frame), _FRAME_LEN, data.hex(" ")
        )

        if len(self._frame) < _FRAME_LEN:
            return

        if len(self._frame) > _FRAME_LEN:
            self._log.debug("frame too long (%i), dropping", len(self._frame))
            self._frame.clear()
            return

        frame: bytes = bytes(self._frame)
        self._frame.clear()

        if not frame.startswith(_HEAD):
            self._log.debug("invalid frame header %s", frame[:4].hex(" "))
            return

        if not self._checksum_ok(frame):
            self._log.debug("invalid checksum %s", frame[-2:].hex(" "))
            return

        self._msg = frame
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Odczyt statusu."""
        await self._await_msg(_CMD_STATUS)
        d: bytes = self._msg

        def u16(i: int) -> int:
            return int.from_bytes(d[i : i + 2], "big")

        def u32(i: int) -> int:
            return int.from_bytes(d[i : i + 4], "big")

        def s32(i: int) -> int:
            return int.from_bytes(d[i : i + 4], "big", signed=True)

        cells: int = min(d[123], _MAX_CELLS)
        chg: int = d[103]
        dsg: int = d[104]
        bal: int = d[105]

        result: BMSSample = {
            "voltage": u16(4) / 10,
            "current": CURRENT_SIGN * s32(70) / 10,
            "battery_level": d[74],
            "cycle_charge": u32(79) / 1_000_000,
            "total_charge": u32(83) // 1000,
            "power": float(CURRENT_SIGN * s32(111)),
            "cell_count": cells,
            "cell_voltages": self._cell_voltages(
                d, cells=cells, start=6, byteorder="big"
            ),
            "temp_sensors": _TEMP_SENSORS,
            "temp_values": self._temp_values(
                d, start=91, values=_TEMP_SENSORS, byteorder="big", signed=True
            ),
            "chrg_mosfet": chg == 0x01,
            "dischrg_mosfet": dsg == 0x01,
            "balancer": bal != 0x00,
            "problem_code": ((chg if chg not in _CHG_OK else 0) << 8)
            | (dsg if dsg not in _DSG_OK else 0),
        }

        design_capacity: int = u32(75) // 1_000_000
        if design_capacity > 0:
            result["design_capacity"] = design_capacity

        return result
