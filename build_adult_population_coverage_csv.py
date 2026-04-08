#!/usr/bin/env python3
"""
Build a country-level adult-population CSV for satellite coverage checks.

Input:
- WPP2024_F02_Metadata.xlsx (default: Data/WPP2024_F02_Metadata.xlsx)

Output columns:
- country
- iso3
- loc_id
- total_population_2022
- adult_population_estimated
- adult_ratio_used
- latitude
- longitude
- area_km2

Notes:
- The provided WPP F02 file is metadata and does not include direct adult population
  counts by country. This script estimates adult population from total population
  using `adult_ratio` (default: 0.65).
- Coordinates are resolved by ISO3 code via Rest Countries API and cached locally.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

NS_MAIN = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


@dataclass(frozen=True)
class CountryRecord:
    country: str
    iso3: str
    loc_id: int
    total_population_2022: Optional[int] = None


def _to_int(value: str) -> Optional[int]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        if "." in cleaned:
            return int(float(cleaned))
        return int(cleaned)
    except ValueError:
        return None


def _to_float(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _column_from_ref(cell_ref: str) -> str:
    letters = []
    for ch in cell_ref:
        if ch.isalpha():
            letters.append(ch)
        else:
            break
    return "".join(letters)


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    path = "xl/sharedStrings.xml"
    if path not in zf.namelist():
        return []
    root = ET.fromstring(zf.read(path))
    values: List[str] = []
    for si in root.findall("a:si", NS_MAIN):
        text = "".join((t.text or "") for t in si.findall(".//a:t", NS_MAIN))
        values.append(text)
    return values


def _sheet_target_by_name(zf: zipfile.ZipFile, sheet_name: str) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall(PKG_REL)}

    for sheet in wb.findall("a:sheets/a:sheet", NS_MAIN):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if not rel_id or rel_id not in rel_map:
                raise ValueError(f"Missing workbook relationship for sheet '{sheet_name}'.")
            target = rel_map[rel_id]
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError(f"Sheet '{sheet_name}' not found in workbook.")


def _cell_text(cell: ET.Element, shared_strings: List[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS_MAIN)
    if value is None:
        inline = cell.find("a:is", NS_MAIN)
        if inline is None:
            return ""
        t = inline.find(".//a:t", NS_MAIN)
        return (t.text or "").strip() if t is not None else ""

    raw = (value.text or "").strip()
    if cell_type == "s":
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(shared_strings):
                return shared_strings[idx].strip()
        return raw
    return raw


def _iter_sheet_rows(
    zf: zipfile.ZipFile, sheet_xml_path: str, shared_strings: List[str]
) -> Iterable[Dict[str, str]]:
    root = ET.fromstring(zf.read(sheet_xml_path))
    for row in root.findall("a:sheetData/a:row", NS_MAIN):
        row_map: Dict[str, str] = {}
        for cell in row.findall("a:c", NS_MAIN):
            ref = cell.attrib.get("r", "")
            col = _column_from_ref(ref)
            if not col:
                continue
            row_map[col] = _cell_text(cell, shared_strings)
        if row_map:
            yield row_map


def _build_header_index(header_row: Dict[str, str]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for col, header in header_row.items():
        key = header.strip()
        if key:
            index[key] = col
    return index


def load_country_records_from_wpp_overall(xlsx_path: Path) -> List[CountryRecord]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings = _load_shared_strings(zf)
        target = _sheet_target_by_name(zf, "Overall")
        rows = list(_iter_sheet_rows(zf, target, shared_strings))

    header_row = None
    header_index: Dict[str, str] = {}
    for row in rows:
        if "Location" in row.values() and "ISO3_Code" in row.values() and "TotPop2022LessThan1k" in row.values():
            header_row = row
            header_index = _build_header_index(row)
            break
    if header_row is None:
        raise ValueError("Could not find header row in 'Overall' sheet.")

    required = ["Location", "ISO3_Code", "LocID"]
    missing = [name for name in required if name not in header_index]
    if missing:
        raise ValueError(f"Missing required columns in Overall sheet: {missing}")

    country_by_iso3: Dict[str, CountryRecord] = {}
    for row in rows:
        country = row.get(header_index["Location"], "").strip()
        iso3 = row.get(header_index["ISO3_Code"], "").strip().upper()
        loc_id = _to_int(row.get(header_index["LocID"], ""))
        pop_thousands = None
        if "TotPop2022LessThan1k" in header_index:
            pop_thousands = _to_int(row.get(header_index["TotPop2022LessThan1k"], ""))

        if not country or not iso3 or loc_id is None:
            continue

        # Country-level records are typically 3-letter ISO codes.
        if len(iso3) != 3:
            continue

        total_population = pop_thousands * 1000 if pop_thousands is not None else None
        current = country_by_iso3.get(iso3)
        candidate = CountryRecord(
            country=country,
            iso3=iso3,
            loc_id=loc_id,
            total_population_2022=total_population,
        )
        # Keep a row containing population if available; otherwise keep first seen.
        if current is None:
            country_by_iso3[iso3] = candidate
        elif current.total_population_2022 is None and candidate.total_population_2022 is not None:
            country_by_iso3[iso3] = candidate

    return sorted(country_by_iso3.values(), key=lambda x: x.country.lower())


def load_country_facts_cache(cache_path: Path) -> Dict[str, Dict[str, float]]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    for iso3, facts in data.items():
        if not isinstance(facts, dict):
            continue
        lat = facts.get("latitude")
        lon = facts.get("longitude")
        pop = facts.get("population")
        area_km2 = facts.get("area_km2")
        row: Dict[str, float] = {}
        if isinstance(lat, (int, float)):
            row["latitude"] = float(lat)
        if isinstance(lon, (int, float)):
            row["longitude"] = float(lon)
        if isinstance(pop, (int, float)):
            row["population"] = int(pop)
        if isinstance(area_km2, (int, float)):
            row["area_km2"] = float(area_km2)
        if row:
            out[iso3.upper()] = row
    return out


def save_country_facts_cache(cache_path: Path, cache: Dict[str, Dict[str, float]]) -> None:
    serializable = {k: v for k, v in sorted(cache.items())}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def load_country_facts_from_csv(csv_path: Path) -> Dict[str, Dict[str, float]]:
    facts: Dict[str, Dict[str, float]] = {}
    if not csv_path.exists():
        return facts
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iso3 = str(row.get("iso3", "")).strip().upper()
            if len(iso3) != 3:
                continue
            item: Dict[str, float] = {}
            lat = _to_int(row.get("latitude", ""))
            lon = _to_int(row.get("longitude", ""))
            pop = _to_int(row.get("population", ""))
            area_km2 = _to_float(row.get("area_km2", ""))

            # Try float parse for latitude/longitude before integer fallback.
            lat_raw = str(row.get("latitude", "")).strip()
            lon_raw = str(row.get("longitude", "")).strip()
            if lat_raw:
                try:
                    item["latitude"] = float(lat_raw)
                except ValueError:
                    if lat is not None:
                        item["latitude"] = float(lat)
            if lon_raw:
                try:
                    item["longitude"] = float(lon_raw)
                except ValueError:
                    if lon is not None:
                        item["longitude"] = float(lon)
            if pop is not None:
                item["population"] = int(pop)
            if area_km2 is not None and area_km2 > 0.0:
                item["area_km2"] = float(area_km2)
            if item:
                facts[iso3] = item
    return facts


def fetch_restcountries_country_facts(timeout_sec: int = 30) -> Dict[str, Dict[str, float]]:
    url = "https://restcountries.com/v3.1/all?fields=cca3,latlng,population,area"
    req = urllib.request.Request(
        url=url,
        headers={"User-Agent": "satellite-coverage-adult-population-export/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    facts: Dict[str, Dict[str, float]] = {}
    for item in payload:
        iso3 = str(item.get("cca3", "")).upper().strip()
        latlng = item.get("latlng", [])
        population = item.get("population")
        area = item.get("area")
        row: Dict[str, float] = {}
        if len(iso3) == 3 and isinstance(latlng, list) and len(latlng) >= 2:
            lat = latlng[0]
            lon = latlng[1]
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                row["latitude"] = float(lat)
                row["longitude"] = float(lon)
        if isinstance(population, (int, float)):
            row["population"] = int(population)
        if isinstance(area, (int, float)) and area > 0:
            row["area_km2"] = float(area)
        if len(iso3) == 3 and row:
            facts[iso3] = row
    return facts


def export_csv(
    rows: List[CountryRecord],
    output_csv: Path,
    adult_ratio: float,
    country_facts: Dict[str, Dict[str, float]],
) -> Tuple[int, int, int, int]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    missing_coords = 0
    missing_population = 0
    missing_area = 0

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "country",
                "iso3",
                "loc_id",
                "total_population_2022",
                "adult_population_estimated",
                "adult_ratio_used",
                "latitude",
                "longitude",
                "area_km2",
            ],
        )
        writer.writeheader()

        for row in rows:
            facts = country_facts.get(row.iso3, {})
            total_population = (
                row.total_population_2022
                if row.total_population_2022 is not None
                else int(facts["population"]) if "population" in facts else None
            )
            adult_pop = int(round(total_population * adult_ratio)) if total_population is not None else None

            lat = facts.get("latitude")
            lon = facts.get("longitude")
            area_km2 = facts.get("area_km2")
            if lat is None or lon is None:
                missing_coords += 1
            if total_population is None:
                missing_population += 1
            if area_km2 is None:
                missing_area += 1
            writer.writerow(
                {
                    "country": row.country,
                    "iso3": row.iso3,
                    "loc_id": row.loc_id,
                    "total_population_2022": "" if total_population is None else total_population,
                    "adult_population_estimated": "" if adult_pop is None else adult_pop,
                    "adult_ratio_used": adult_ratio,
                    "latitude": "" if lat is None else f"{lat:.6f}",
                    "longitude": "" if lon is None else f"{lon:.6f}",
                    "area_km2": "" if area_km2 is None else f"{float(area_km2):.3f}",
                }
            )
    return len(rows), missing_coords, missing_population, missing_area


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export country-level adult population + coordinates CSV for satellite coverage checks."
    )
    parser.add_argument(
        "--input-xlsx",
        type=Path,
        default=Path("Data/WPP2024_F02_Metadata.xlsx"),
        help="Path to WPP metadata workbook.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("Data/adult_population_country_coordinates.csv"),
        help="Path to output CSV.",
    )
    parser.add_argument(
        "--adult-ratio",
        type=float,
        default=0.65,
        help="Adult share used to estimate adult population from total population.",
    )
    parser.add_argument(
        "--cache-json",
        type=Path,
        default=Path("Data/country_facts_cache.json"),
        help="Local cache file for ISO3 -> {latitude, longitude, population}.",
    )
    parser.add_argument(
        "--country-facts-csv",
        type=Path,
        default=None,
        help="Optional local CSV with columns: iso3,latitude,longitude,population,area_km2.",
    )
    parser.add_argument(
        "--skip-online-coordinates",
        action="store_true",
        help="Do not call Rest Countries API. Only use cached country facts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input_xlsx.exists():
        raise FileNotFoundError(f"Input file not found: {args.input_xlsx}")
    if not (0.0 < args.adult_ratio <= 1.0):
        raise ValueError("--adult-ratio must be > 0 and <= 1.")

    records = load_country_records_from_wpp_overall(args.input_xlsx)
    if not records:
        raise RuntimeError(
            "No country records parsed from WPP workbook; aborting to avoid overwriting output CSV with empty data."
        )
    country_facts_cache = load_country_facts_cache(args.cache_json)
    if args.country_facts_csv is not None:
        country_facts_cache.update(load_country_facts_from_csv(args.country_facts_csv))

    if not args.skip_online_coordinates:
        try:
            online_facts = fetch_restcountries_country_facts()
            country_facts_cache.update(online_facts)
            save_country_facts_cache(args.cache_json, country_facts_cache)
            # Friendly delay so repeated runs right after each other remain API-gentle.
            time.sleep(0.2)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Warning: could not fetch online country facts ({exc}). Using cache only.")

    total_rows, missing_coords, missing_population, missing_area = export_csv(
        rows=records,
        output_csv=args.output_csv,
        adult_ratio=args.adult_ratio,
        country_facts=country_facts_cache,
    )

    print(f"Exported {total_rows} countries to: {args.output_csv}")
    if missing_coords:
        print(f"Countries without coordinates: {missing_coords}")
    else:
        print("All exported countries have coordinates.")
    if missing_population:
        print(f"Countries without population value: {missing_population}")
    else:
        print("All exported countries have a population value.")
    if missing_area:
        print(f"Countries without area value: {missing_area}")
    else:
        print("All exported countries have an area value.")
    print("Note: adult_population_estimated = total_population_2022 * adult_ratio_used")


if __name__ == "__main__":
    main()
