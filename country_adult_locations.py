from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import geonamescache
except ImportError:  # pragma: no cover
    geonamescache = None


@dataclass(frozen=True)
class CountryAdultLocation:
    country_code: str
    country_name: str
    latitude: float
    longitude: float
    adult_population: int

    def to_dict(self) -> dict[str, object]:
        return {
            "country_code": self.country_code,
            "country_name": self.country_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "adult_population": self.adult_population,
        }


DEFAULT_COUNTRY_LOCATIONS: list[CountryAdultLocation] = [
    CountryAdultLocation("US", "United States", 38.9072, -77.0369, 258_000_000),
    CountryAdultLocation("CN", "China", 39.9042, 116.4074, 980_000_000),
    CountryAdultLocation("IN", "India", 28.6139, 77.2090, 800_000_000),
    CountryAdultLocation("BR", "Brazil", -15.7939, -47.8828, 150_000_000),
    CountryAdultLocation("RU", "Russia", 55.7558, 37.6173, 110_000_000),
    CountryAdultLocation("NG", "Nigeria", 9.0765, 7.3986, 110_000_000),
    CountryAdultLocation("DE", "Germany", 52.5200, 13.4050, 55_000_000),
    CountryAdultLocation("JP", "Japan", 35.6762, 139.6503, 100_000_000),
    CountryAdultLocation("GB", "United Kingdom", 51.5074, -0.1278, 45_000_000),
    CountryAdultLocation("FR", "France", 48.8566, 2.3522, 45_000_000),
    CountryAdultLocation("CA", "Canada", 45.4215, -75.6972, 27_000_000),
    CountryAdultLocation("AU", "Australia", -35.2809, 149.1300, 16_000_000),
    CountryAdultLocation("ZA", "South Africa", -25.7461, 28.1881, 30_000_000),
    CountryAdultLocation("MX", "Mexico", 19.4326, -99.1332, 80_000_000),
    CountryAdultLocation("ID", "Indonesia", -6.2088, 106.8456, 140_000_000),
    CountryAdultLocation("AR", "Argentina", -34.6037, -58.3816, 30_000_000),
    CountryAdultLocation("EG", "Egypt", 30.0444, 31.2357, 50_000_000),
    CountryAdultLocation("TR", "Turkey", 39.9334, 32.8597, 60_000_000),
    CountryAdultLocation("IR", "Iran", 35.6892, 51.3890, 55_000_000),
    CountryAdultLocation("PK", "Pakistan", 33.6844, 73.0479, 120_000_000),
    CountryAdultLocation("BD", "Bangladesh", 23.8103, 90.4125, 100_000_000),
    CountryAdultLocation("ES", "Spain", 40.4168, -3.7038, 28_000_000),
    CountryAdultLocation("IT", "Italy", 41.9028, 12.4964, 35_000_000),
    CountryAdultLocation("KR", "South Korea", 37.5665, 126.9780, 35_000_000),
    CountryAdultLocation("SA", "Saudi Arabia", 24.7136, 46.6753, 22_000_000),
    CountryAdultLocation("CO", "Colombia", 4.7110, -74.0721, 20_000_000),
    CountryAdultLocation("KE", "Kenya", -1.2921, 36.8219, 22_000_000),
    CountryAdultLocation("VN", "Vietnam", 21.0278, 105.8342, 70_000_000),
    CountryAdultLocation("CH", "Switzerland", 46.9480, 7.4474, 7_000_000),
    CountryAdultLocation("SE", "Sweden", 59.3293, 18.0686, 7_000_000),
    CountryAdultLocation("PL", "Poland", 52.2297, 21.0122, 24_000_000),
    CountryAdultLocation("NO", "Norway", 59.9139, 10.7522, 5_000_000),
]


def haversine_distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_km = 6371.0
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius_km * c


def load_country_locations_from_csv(path: Path) -> list[CountryAdultLocation]:
    records: list[CountryAdultLocation] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("country_code") or not row.get("latitude") or not row.get("longitude"):
                continue
            records.append(
                CountryAdultLocation(
                    country_code=row["country_code"].strip().upper(),
                    country_name=row.get("country_name", "").strip(),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    adult_population=int(float(row.get("adult_population", "0"))),
                )
            )
    return records


def load_country_locations_from_geonames() -> list[CountryAdultLocation]:
    if geonamescache is None:
        raise RuntimeError("geonamescache is not installed; install it to load full country coverage.")

    gc = geonamescache.GeonamesCache()
    countries = gc.get_countries()
    records: list[CountryAdultLocation] = []
    for iso2, meta in sorted(countries.items(), key=lambda item: item[1]["name"]):
        population = int(meta.get("population", 0) or 0)
        adult_population = int(round(population * 0.70)) if population else 0
        records.append(
            CountryAdultLocation(
                country_code=iso2.upper(),
                country_name=meta.get("name", "").strip(),
                latitude=float(meta["latitude"]),
                longitude=float(meta["longitude"]),
                adult_population=adult_population,
            )
        )
    return records


def load_country_adult_locations(override_csv: Path | None = None) -> list[CountryAdultLocation]:
    if override_csv is not None and override_csv.exists():
        return load_country_locations_from_csv(override_csv)

    if geonamescache is not None:
        try:
            return load_country_locations_from_geonames()
        except Exception:
            pass

    return DEFAULT_COUNTRY_LOCATIONS


def find_countries_within_coverage(
    country_locations: Iterable[CountryAdultLocation],
    center_lat: float,
    center_lon: float,
    coverage_radius_km: float,
) -> list[CountryAdultLocation]:
    return [
        country
        for country in country_locations
        if haversine_distance_km(country.latitude, country.longitude, center_lat, center_lon)
        <= coverage_radius_km
    ]


def get_country_location(
    country_locations: Iterable[CountryAdultLocation],
    country_name_or_code: str,
) -> CountryAdultLocation | None:
    key = country_name_or_code.strip().lower()
    for country in country_locations:
        if country.country_code.lower() == key or country.country_name.lower() == key:
            return country
    return None


def generate_adult_person_location(
    country: CountryAdultLocation,
    max_offset_degrees: float = 0.5,
    seed: int | None = None,
) -> CountryAdultLocation:
    rng = random.Random(seed)
    offset_lat = rng.uniform(-max_offset_degrees, max_offset_degrees)
    offset_lon = rng.uniform(-max_offset_degrees, max_offset_degrees)
    return CountryAdultLocation(
        country_code=country.country_code,
        country_name=country.country_name,
        latitude=country.latitude + offset_lat,
        longitude=country.longitude + offset_lon,
        adult_population=country.adult_population,
    )


def save_country_locations_to_csv(path: Path, country_locations: Iterable[CountryAdultLocation]) -> None:
    fieldnames = ["country_code", "country_name", "latitude", "longitude", "adult_population"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for country in country_locations:
            writer.writerow(country.to_dict())


def main() -> None:
    root = Path(__file__).resolve().parent
    sample_csv = root / "Data" / "country_adult_locations.csv"
    country_locations = load_country_adult_locations(sample_csv if sample_csv.exists() else None)

    coverage_center = (35.6762, 139.6503)
    coverage_radius_km = 1000.0
    covered = find_countries_within_coverage(
        country_locations, coverage_center[0], coverage_center[1], coverage_radius_km
    )

    print("Coverage center:", coverage_center)
    print(f"Countries within {coverage_radius_km} km:")
    for country in covered:
        print(
            f"{country.country_code} - {country.country_name}: {country.latitude:.4f}, {country.longitude:.4f} ({country.adult_population:,} adults)"
        )


if __name__ == "__main__":
    main()
