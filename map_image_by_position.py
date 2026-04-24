from __future__ import annotations

import argparse
import csv
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "matplotlib is required to generate map images. Install with: pip install matplotlib"
    ) from exc


def _plot_world_basemap(ax) -> bool:
    """
    Draw world land boundaries using free Natural Earth data via GeoPandas.
    Returns True when basemap is drawn, False when unavailable.
    """
    try:
        import geopandas as gpd
    except ModuleNotFoundError:
        return False

    world = None
    try:
        world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
    except Exception:
        # Fallback path used by newer GeoPandas ecosystems.
        try:
            import geodatasets

            world = gpd.read_file(geodatasets.get_path("naturalearth.land"))
        except Exception:
            return False

    if world is None or world.empty:
        return False

    world.plot(
        ax=ax,
        color="#e9efe5",
        edgecolor="#5f6a5f",
        linewidth=0.45,
        alpha=0.9,
        zorder=0,
    )
    return True


def _read_lat_lon_points(csv_path: Path, max_points: int | None = None) -> tuple[list[float], list[float]]:
    if not csv_path.exists():
        return [], []

    lats: list[float] = []
    lons: list[float] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row.get("latitude", ""))
                lon = float(row.get("longitude", ""))
            except (TypeError, ValueError):
                continue
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            lats.append(lat)
            lons.append(lon)

    if max_points is not None and max_points > 0 and len(lats) > max_points:
        step = max(1, len(lats) // int(max_points))
        lats = lats[::step][: int(max_points)]
        lons = lons[::step][: int(max_points)]

    return lats, lons


def create_map_image(
    latitude: float,
    longitude: float,
    output_path: str | Path,
    population_csv: str | Path | None = None,
    ocean_csv: str | Path | None = None,
    include_population: bool = True,
    include_ocean: bool = True,
    max_background_points: int = 10000,
    title: str | None = None,
    world_map_mode: str = "auto",
) -> Path:
    lat = float(latitude)
    lon = float(longitude)
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude must be in [-90, 90], got {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude must be in [-180, 180], got {lon}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_facecolor("#f6fbff")
    fig.patch.set_facecolor("white")
    world_drawn = False
    if world_map_mode not in {"auto", "on", "off"}:
        raise ValueError("world_map_mode must be one of: auto, on, off")
    if world_map_mode in {"auto", "on"}:
        world_drawn = _plot_world_basemap(ax)
        if world_map_mode == "on" and not world_drawn:
            raise ModuleNotFoundError(
                "World map basemap requested but unavailable. Install with: pip install geopandas geodatasets"
            )

    if include_ocean and ocean_csv is not None:
        ocean_lats, ocean_lons = _read_lat_lon_points(Path(ocean_csv), max_points=max_background_points)
        if ocean_lats:
            ax.scatter(
                ocean_lons,
                ocean_lats,
                s=2,
                c="#a8d5ff",
                alpha=0.25,
                edgecolors="none",
                label="ocean points",
            )

    if include_population and population_csv is not None:
        pop_lats, pop_lons = _read_lat_lon_points(Path(population_csv), max_points=max_background_points)
        if pop_lats:
            ax.scatter(
                pop_lons,
                pop_lats,
                s=3,
                c="#6ea96d",
                alpha=0.35,
                edgecolors="none",
                label="population points",
            )

    ax.scatter(
        [lon],
        [lat],
        s=150,
        c="#d62728",
        marker="*",
        edgecolors="black",
        linewidths=0.8,
        zorder=5,
        label="target position",
    )

    ax.axhline(0.0, color="#9aa0a6", linewidth=0.7, alpha=0.7)
    ax.axvline(0.0, color="#9aa0a6", linewidth=0.7, alpha=0.7)
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xticks(range(-180, 181, 30))
    ax.set_yticks(range(-90, 91, 15))
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.45)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")

    if title is None:
        title = f"Map Position: lat={lat:.6f}, lon={lon:.6f}"
    if world_map_mode == "auto" and not world_drawn:
        title = f"{title} (no world basemap)"
    ax.set_title(title)
    ax.legend(loc="lower left", fontsize=8)

    fig.tight_layout()
    fig.savefig(out, dpi=220)
    plt.close(fig)
    return out


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Create a map image for a given latitude/longitude.")
    parser.add_argument("--lat", type=float, required=True, help="Latitude in degrees [-90, 90].")
    parser.add_argument("--lon", type=float, required=True, help="Longitude in degrees [-180, 180].")
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "results" / "maps" / "given_position_map.png",
        help="Output PNG path.",
    )
    parser.add_argument(
        "--population-csv",
        type=Path,
        default=root / "Data" / "csv" / "population_data.csv",
        help="Population CSV with latitude/longitude columns.",
    )
    parser.add_argument(
        "--ocean-csv",
        type=Path,
        default=root / "Data" / "csv" / "ocean_data.csv",
        help="Ocean CSV with latitude/longitude columns.",
    )
    parser.add_argument(
        "--background",
        type=str,
        choices=["both", "population", "ocean", "none"],
        default="both",
        help="Background points to render on the map.",
    )
    parser.add_argument(
        "--max-background-points",
        type=int,
        default=10000,
        help="Maximum points per background dataset to draw.",
    )
    parser.add_argument("--title", type=str, default=None, help="Optional custom title.")
    parser.add_argument(
        "--world-map",
        type=str,
        choices=["auto", "on", "off"],
        default="auto",
        help="Use free world basemap via GeoPandas/Natural Earth: auto (try), on (require), off (disable).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    include_population = args.background in {"both", "population"}
    include_ocean = args.background in {"both", "ocean"}

    out = create_map_image(
        latitude=float(args.lat),
        longitude=float(args.lon),
        output_path=Path(args.output),
        population_csv=Path(args.population_csv),
        ocean_csv=Path(args.ocean_csv),
        include_population=bool(include_population),
        include_ocean=bool(include_ocean),
        max_background_points=max(1, int(args.max_background_points)),
        title=args.title,
        world_map_mode=str(args.world_map),
    )
    print(f"map_image= {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
