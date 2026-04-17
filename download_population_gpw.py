"""
Download population and geographic data from open sources (NO authentication required).

Uses Natural Earth data and WorldPop open data to create a population CSV with:
- feature_name, feature_type, country, ocean, population, latitude, longitude
"""

import os
import sys
import csv
import zipfile
from pathlib import Path
from typing import List, Dict, Optional
import urllib.request
import urllib.error

try:
    import numpy as np
    import geopandas as gpd
    from shapely.geometry import Point
    import pandas as pd
    from tqdm import tqdm
except ImportError as e:
    print(f"Required package missing: {e}")
    print("Install with: pip install numpy geopandas shapely pandas tqdm")
    sys.exit(1)


class OpenPopulationDownloader:
    """Download and process open-source population data (no authentication required)."""
    
    # Natural Earth URLs (free, no auth required)
    NATURAL_EARTH_CITIES_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip"
    NATURAL_EARTH_COUNTRIES_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
    NATURAL_EARTH_WATER_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip"
    NATURAL_EARTH_RIVERS_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_lake_centerlines.zip"
    
    def __init__(self, data_dir: str = "Data/raw_data", csv_dir: str = "Data/csv"):
        """Initialize downloader."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.csv_dir = Path(csv_dir)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        
        self.csv_output = self.csv_dir / "population_data.csv"
        
    def download_file(self, url: str, filename: str, max_retries: int = 3, alt_urls: List[str] = None) -> Optional[Path]:
        """Download a file with retry logic and alternative URLs."""
        filepath = self.data_dir / filename
        
        if filepath.exists():
            print(f"✓ File already exists: {filename}")
            return filepath
        
        # Try primary URL, then alternatives
        urls_to_try = [url] + (alt_urls or [])
        
        for url_idx, current_url in enumerate(urls_to_try):
            if url_idx > 0:
                print(f"📥 Trying alternative source {url_idx}...")
            
            print(f"📥 Downloading {filename}...")
            for attempt in range(max_retries):
                try:
                    # Create request with User-Agent to avoid 403 Forbidden
                    request = urllib.request.Request(
                        current_url,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    )
                    
                    with urllib.request.urlopen(request, timeout=30) as response:
                        total_size = int(response.headers.get('content-length', 0))
                        block_size = 8192
                        downloaded = 0
                        
                        with open(filepath, 'wb') as f:
                            while True:
                                block = response.read(block_size)
                                if not block:
                                    break
                                downloaded += len(block)
                                f.write(block)
                                if total_size > 0:
                                    percent = min(100, downloaded / total_size * 100)
                                    sys.stdout.write(f"\r  Progress: {percent:.1f}%")
                                    sys.stdout.flush()
                    
                    print(f"\n✓ Downloaded: {filename}")
                    return filepath
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                    print(f"\n⚠ Attempt {attempt + 1} failed: {e}")
                    if filepath.exists():
                        filepath.unlink()  # Remove partial file
                    if attempt < max_retries - 1:
                        print(f"  Retrying...")
                except Exception as e:
                    print(f"\n✗ Unexpected error: {e}")
                    if filepath.exists():
                        filepath.unlink()
        
        print(f"✗ Failed to download {filename} (all sources exhausted)")
        return None
    
    def extract_zip(self, zip_path: Path, extract_to: Optional[Path] = None) -> Path:
        """Extract ZIP file."""
        extract_to = extract_to or self.data_dir
        extract_to.mkdir(parents=True, exist_ok=True)
        
        print(f"📦 Extracting {zip_path.name}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        print(f"✓ Extracted to: {extract_to}")
        return extract_to
    
    def load_geographic_data(self, shapefile: Path) -> Optional[gpd.GeoDataFrame]:
        """Load geographic reference data."""
        try:
            print(f"🗺 Loading: {shapefile.name}")
            gdf = gpd.read_file(shapefile)
            print(f"✓ Loaded {len(gdf)} features")
            return gdf
        except Exception as e:
            print(f"⚠ Could not load {shapefile}: {e}")
            return None
    
    def process_cities(self, cities_gdf: gpd.GeoDataFrame) -> List[Dict]:
        """Process city population data."""
        print(f"🏙 Processing {len(cities_gdf)} cities...")
        
        cities_data = []
        for idx, city in tqdm(cities_gdf.iterrows(), total=len(cities_gdf), desc="Processing cities"):
            try:
                city_name = city.get("NAME", "Unknown")
                country = city.get("ADMIN", "Unknown")
                population = city.get("POP_MAX", 0)
                
                # Skip if no population data
                if population <= 0:
                    continue
                
                cities_data.append({
                    "feature_name": city_name,
                    "feature_type": "City",
                    "country": country,
                    "ocean": "",
                    "population": int(population),
                    "latitude": city.geometry.y,
                    "longitude": city.geometry.x
                })
            except Exception as e:
                pass
        
        print(f"✓ Processed {len(cities_data)} cities with population data")
        return cities_data
    
    def process_water_bodies(self, water_gdf: gpd.GeoDataFrame) -> List[Dict]:
        """Process water body centroids."""
        print(f"💧 Processing {len(water_gdf)} water bodies...")
        
        water_data = []
        for idx, water in tqdm(water_gdf.iterrows(), total=len(water_gdf), desc="Processing water"):
            try:
                water_name = water.get("NAME", "Unknown Water Body")
                water_type = water.get("TYPE", "Water Body")
                
                water_data.append({
                    "feature_name": water_name,
                    "feature_type": water_type,
                    "country": "",
                    "ocean": water_name,
                    "population": 0,
                    "latitude": water.geometry.y,
                    "longitude": water.geometry.x
                })
            except Exception as e:
                pass
        
        print(f"✓ Processed {len(water_data)} water bodies")
        return water_data
    
    def process_rivers(self, rivers_gdf: gpd.GeoDataFrame) -> List[Dict]:
        """Process river points (sample centroids)."""
        print(f"🌊 Processing rivers...")
        
        river_data = []
        
        # Sample every nth river to avoid too much data
        sample_rivers = rivers_gdf.iloc[::max(1, len(rivers_gdf) // 5000)]
        
        for idx, river in tqdm(sample_rivers.iterrows(), total=len(sample_rivers), desc="Processing rivers"):
            try:
                river_name = river.get("NAME", "Unknown River")
                
                # Get centroid if it's a linestring
                if hasattr(river.geometry, 'centroid'):
                    centroid = river.geometry.centroid
                else:
                    centroid = river.geometry
                
                river_data.append({
                    "feature_name": river_name,
                    "feature_type": "River",
                    "country": "",
                    "ocean": "",
                    "population": 0,
                    "latitude": centroid.y,
                    "longitude": centroid.x
                })
            except Exception as e:
                pass
        
        print(f"✓ Processed {len(river_data)} rivers")
        return river_data
    
    def enrich_with_country(self, data: List[Dict], countries_gdf: Optional[gpd.GeoDataFrame]) -> List[Dict]:
        """Add country information to points without it."""
        if countries_gdf is None:
            return data
        
        print(f"🌍 Enriching with country data...")
        
        for item in tqdm(data, desc="Enriching data"):
            if item["country"] and item["country"] != "Unknown":
                continue
            
            point = Point(item["longitude"], item["latitude"])
            
            try:
                country_match = countries_gdf[countries_gdf.geometry.contains(point)]
                if not country_match.empty:
                    item["country"] = country_match.iloc[0].get("NAME", "Unknown")
            except:
                pass
        
        return data
    
    def enrich_with_ocean(self, data: List[Dict], water_gdf: Optional[gpd.GeoDataFrame]) -> List[Dict]:
        """Add nearest ocean/water body to cities."""
        if water_gdf is None or len(water_gdf) == 0:
            return data
        
        print(f"🌊 Enriching cities with nearest water bodies...")
        
        # Build list of water bodies with names and geometries
        water_bodies = []
        for idx, row in water_gdf.iterrows():
            water_name = row.get("NAME", "Water Body")
            water_bodies.append({
                "name": water_name,
                "geometry": row.geometry
            })
        
        for item in tqdm(data, desc="Enriching with oceans"):
            # Only enrich cities without ocean info
            if item["ocean"] or item["feature_type"] != "City":
                continue
            
            point = Point(item["longitude"], item["latitude"])
            
            try:
                # Find nearest water body
                min_distance = float('inf')
                nearest_name = None
                
                for water in water_bodies:
                    dist = point.distance(water["geometry"])
                    if dist < min_distance:
                        min_distance = dist
                        nearest_name = water["name"]
                
                # Only assign if within reasonable distance (e.g., < 5 degrees)
                if min_distance < 5 and nearest_name:
                    item["ocean"] = nearest_name
            except:
                pass
        
        return data
    
    def add_major_oceans(self, data: List[Dict]) -> List[Dict]:
        """Add major world oceans with multiple sample points across each ocean."""
        print(f"🌊 Adding major world oceans with sample points...")
        
        # Major oceans with lat/lon ranges for sampling
        oceans = [
            {"name": "Pacific Ocean", "lat_range": (-60, 60), "lon_range": (120, 180)},
            {"name": "Atlantic Ocean", "lat_range": (-60, 60), "lon_range": (-80, 0)},
            {"name": "Indian Ocean", "lat_range": (-60, 30), "lon_range": (20, 120)},
            {"name": "Arctic Ocean", "lat_range": (60, 90), "lon_range": (-180, 180)},
            {"name": "Southern Ocean", "lat_range": (-90, -60), "lon_range": (-180, 180)},
        ]
        
        ocean_data = []
        points_per_ocean = 20  # Create 20 sample points per ocean
        
        for ocean in oceans:
            lat_min, lat_max = ocean["lat_range"]
            lon_min, lon_max = ocean["lon_range"]
            
            # Create grid of points across ocean
            lats = np.linspace(lat_min, lat_max, 5)
            lons = np.linspace(lon_min, lon_max, 4)
            
            for lat in lats:
                for lon in lons:
                    ocean_data.append({
                        "feature_name": ocean["name"],
                        "feature_type": "Ocean",
                        "country": "",
                        "ocean": ocean["name"],
                        "population": 0,
                        "latitude": float(lat),
                        "longitude": float(lon)
                    })
        
        data.extend(ocean_data)
        print(f"✓ Added {len(ocean_data)} ocean sample points ({len(oceans)} oceans)")
        return data
    
    def save_to_csv(self, data: List[Dict]):
        """Save data to separate CSVs: cities (no ocean) and oceans/water bodies."""
        print(f"💾 Saving to CSV files...")
        
        if not data:
            print("⚠ No data to save")
            return
        
        try:
            df = pd.DataFrame(data)
            
            # Split into cities and oceans/water bodies
            cities_df = df[df["feature_type"] == "City"].copy()
            oceans_df = df[df["feature_type"] != "City"].copy()
            
            # Save cities without ocean column
            cities_output = self.csv_dir / "population_data.csv"
            cities_df_clean = cities_df.drop(columns=["ocean"], errors="ignore")
            cities_df_clean = cities_df_clean.sort_values("population", ascending=False)
            cities_df_clean.to_csv(cities_output, index=False)
            print(f"✓ Saved {len(cities_df_clean)} cities to {cities_output}")
            print(f"  Columns: {', '.join(cities_df_clean.columns.tolist())}")
            
            # Save oceans/water bodies with all columns
            if len(oceans_df) > 0:
                oceans_output = self.csv_dir / "ocean_data.csv"
                oceans_df = oceans_df.sort_values("population", ascending=False)
                oceans_df.to_csv(oceans_output, index=False)
                print(f"✓ Saved {len(oceans_df)} water bodies to {oceans_output}")
                print(f"  Columns: {', '.join(oceans_df.columns.tolist())}")
            
            print(f"\n✓ Top 10 cities by population:")
            print(cities_df_clean.head(10)[["feature_name", "feature_type", "country", "population"]].to_string(index=False))
        except Exception as e:
            print(f"✗ Error saving CSV: {e}")
    
    def run(self, skip_download: bool = False) -> Path:
        """Execute the full pipeline."""
        print("=" * 70)
        print("Open Population Data Downloader (NO Authentication Required)")
        print("=" * 70)
        print("\n📝 Note: This script can work with partial data.")
        print("   If some downloads fail (403 errors), the script will continue.")
        print("   Cities data is essential; water/rivers are optional.\n")
        
        all_data = []
        
        if not skip_download:
            # Download Natural Earth countries data
            print("\n[1/5] Downloading Natural Earth countries reference data...")
            countries_zip = self.download_file(self.NATURAL_EARTH_COUNTRIES_URL, "countries.zip")
            countries_gdf = None
            if countries_zip:
                self.extract_zip(countries_zip)
                shapefiles = list(self.data_dir.glob("**/ne_10m_admin_0_countries*.shp"))
                if shapefiles:
                    countries_gdf = self.load_geographic_data(shapefiles[0])
            
            # Download Natural Earth cities data
            print("\n[2/5] Downloading Natural Earth cities data...")
            cities_zip = self.download_file(self.NATURAL_EARTH_CITIES_URL, "cities.zip")
            cities_gdf = None
            if cities_zip:
                self.extract_zip(cities_zip)
                shapefiles = list(self.data_dir.glob("**/ne_10m_populated_places*.shp"))
                if shapefiles:
                    cities_gdf = self.load_geographic_data(shapefiles[0])
            
            # Download Natural Earth water bodies data
            print("\n[3/5] Downloading Natural Earth water bodies data...")
            water_alt_urls = [
                "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/10m_physical/ne_10m_lakes.zip",
                "https://naciscdn.org/naturalearth/10m/physical/ne_10m_water_bodies_lake_centerpoints.zip",
            ]
            water_zip = self.download_file(
                self.NATURAL_EARTH_WATER_URL, 
                "water_bodies.zip",
                alt_urls=water_alt_urls
            )
            water_gdf = None
            if water_zip:
                self.extract_zip(water_zip)
                # Try multiple shapefile patterns for lakes/water bodies
                shapefiles = list(self.data_dir.glob("**/ne_10m_lakes*.shp"))
                if not shapefiles:
                    shapefiles = list(self.data_dir.glob("**/ne_10m_water_bodies*.shp"))
                if shapefiles:
                    water_gdf = self.load_geographic_data(shapefiles[0])
            
            # Download Natural Earth rivers data
            print("\n[4/5] Downloading Natural Earth rivers data...")
            rivers_zip = self.download_file(self.NATURAL_EARTH_RIVERS_URL, "rivers.zip")
            rivers_gdf = None
            if rivers_zip:
                self.extract_zip(rivers_zip)
                shapefiles = list(self.data_dir.glob("**/ne_10m_rivers*.shp"))
                if shapefiles:
                    rivers_gdf = self.load_geographic_data(shapefiles[0])
        else:
            print("\nSkipping downloads, loading existing files...")
            countries_shapefiles = list(self.data_dir.glob("**/ne_10m_admin_0_countries*.shp"))
            cities_shapefiles = list(self.data_dir.glob("**/ne_10m_populated_places*.shp"))
            water_shapefiles = list(self.data_dir.glob("**/ne_10m_lakes*.shp"))
            if not water_shapefiles:
                water_shapefiles = list(self.data_dir.glob("**/ne_10m_water_bodies*.shp"))
            rivers_shapefiles = list(self.data_dir.glob("**/ne_10m_rivers*.shp"))
            
            countries_gdf = self.load_geographic_data(countries_shapefiles[0]) if countries_shapefiles else None
            cities_gdf = self.load_geographic_data(cities_shapefiles[0]) if cities_shapefiles else None
            water_gdf = self.load_geographic_data(water_shapefiles[0]) if water_shapefiles else None
            rivers_gdf = self.load_geographic_data(rivers_shapefiles[0]) if rivers_shapefiles else None
        
        # Print summary of loaded data
        print("\n📊 Data Status:")
        print(f"  {'✓' if countries_gdf is not None else '✗'} Countries: {len(countries_gdf) if countries_gdf is not None else 'Failed'}")
        print(f"  {'✓' if cities_gdf is not None else '✗'} Cities: {len(cities_gdf) if cities_gdf is not None else 'Failed'}")
        print(f"  {'✓' if water_gdf is not None else '✗'} Water bodies: {len(water_gdf) if water_gdf is not None else 'Failed (optional)'}")
        print(f"  {'✓' if rivers_gdf is not None else '✗'} Rivers: {len(rivers_gdf) if rivers_gdf is not None else 'Failed (optional)'}")
        
        # Process data
        print("\n[5/5] Processing geographic data...")
        
        if cities_gdf is None:
            print("⚠️  Warning: Cities data failed to load. Output will be incomplete.")
            print("   Try running again: python download_population_gpw.py")
        
        if cities_gdf is not None:
            all_data.extend(self.process_cities(cities_gdf))
        
        # Enrich cities with ocean data BEFORE adding water bodies
        if water_gdf is not None and len(all_data) > 0:
            all_data = self.enrich_with_ocean(all_data, water_gdf)
        
        if water_gdf is not None:
            all_data.extend(self.process_water_bodies(water_gdf))
        else:
            print("ℹ️  Info: Water bodies skipped (optional)")
        
        if rivers_gdf is not None:
            all_data.extend(self.process_rivers(rivers_gdf))
        else:
            print("ℹ️  Info: Rivers skipped (optional)")
        
        # Enrich with country data
        if countries_gdf is not None:
            all_data = self.enrich_with_country(all_data, countries_gdf)
        
        # Remove duplicates by location
        print("🧹 Removing duplicates...")
        unique_data = []
        seen_locations = set()
        for item in all_data:
            loc_key = (round(item["latitude"], 2), round(item["longitude"], 2))
            if loc_key not in seen_locations:
                seen_locations.add(loc_key)
                unique_data.append(item)
        
        print(f"✓ Kept {len(unique_data)} unique locations (removed {len(all_data) - len(unique_data)} duplicates)")
        
        # Add major world oceans
        unique_data = self.add_major_oceans(unique_data)
        
        # Save to CSV
        self.save_to_csv(unique_data)
        
        print("\n" + "=" * 70)
        print("✓ Complete!")
        print(f"Output: {self.csv_output}")
        print("=" * 70)
        
        return self.csv_output


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download population data from open sources (NO authentication required)"
    )
    parser.add_argument(
        "--data-dir",
        default="raw_data",
        help="Directory for extracted data files (default: raw_data)"
    )
    parser.add_argument(
        "--csv-dir",
        default="Data/csv",
        help="Directory for CSV output (default: Data/csv)"
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading (use existing data)"
    )
    
    args = parser.parse_args()
    
    downloader = OpenPopulationDownloader(data_dir=args.data_dir, csv_dir=args.csv_dir)
    csv_file = downloader.run(skip_download=args.skip_download)
    
    # Display sample of output
    if csv_file.exists():
        print("\n📄 Sample of output CSV:")
        df = pd.read_csv(csv_file)
        print(df.head(15).to_string(index=False))
        print(f"\nTotal rows: {len(df)}")
        print(f"\n📁 Directories:")
        print(f"  Data files: {downloader.data_dir}")
        print(f"  CSV output: {downloader.csv_dir}")


if __name__ == "__main__":
    main()
