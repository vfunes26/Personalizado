"""Selectors for the supplied Extranjería catalog.

All labels, IDs, punctuation and accents are read verbatim. This snapshot is
historical (12 September 2026), NOT a live promise of site availability.
"""
import json
from pathlib import Path

from ..config import TIE_PROCEDURE, REGRESO_PROCEDURE
from .paths import resource_root

CATALOG_FILE = "catalogo-extranjeria-alertas-2026-09-12.json"


class AppointmentCatalog:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else resource_root() / "catalogs" / CATALOG_FILE
        self.provinces = {}
        self.available = False
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("Catálogo de Extranjería incompatible")
        for province in raw.get("provinces", []):
            name = province["name"]
            if not isinstance(name, str) or name in self.provinces:
                raise ValueError("Provincia duplicada en el catálogo")
            self.provinces[name] = province
        self.available = bool(self.provinces)

    def province_names(self):
        return sorted(self.provinces, key=str.casefold)

    def offices(self, province):
        seen = set()
        for procedure in self.provinces.get(province, {}).get("procedures", []):
            for office in procedure.get("offices", []):
                # Same name and different id is a distinct official entry.
                key = str(office["id"]), office["name"]
                if key not in seen:
                    seen.add(key)
                    yield key

    def procedures(self, province, office=None):
        seen = set()
        for procedure in self.provinces.get(province, {}).get("procedures", []):
            if office and not any(
                ((str(item["id"]), item["name"]) == office or item["name"] == office)
                for item in procedure.get("offices", [])
            ):
                continue
            value = procedure["name"]
            if str(procedure["id"]) == "4010":
                value = TIE_PROCEDURE
            elif str(procedure["id"]) in {"20", "4058"}:
                value = REGRESO_PROCEDURE
            if value not in seen:
                seen.add(value)
                yield procedure["name"], value, str(procedure["id"])

    def includes(self, province, procedure, office=None):
        return any(value == procedure for _label, value, _id
                   in self.procedures(province, office))
