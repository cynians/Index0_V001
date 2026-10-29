"""Data-backed landscape target, independent of today's procedural generator."""
from functools import lru_cache
import csv
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine import asset_files
from simulations.world_gen.reference_raster import read_numeric_tiff, NativeRasterTiles
from simulations.world_gen.regional_refinement import detail_level_spec
from simulations.world_gen.water_cycle import _koppen_geiger_class

MAP_ID = "highest_lod_example_map"
RECIPE_VERSION = "dosewallips-data-backed-target-v2"
EXTENT_M = 6000.0
SPACING_M = 1.0
DATA_ROOT = Path(__file__).resolve().parents[2] / "assets/maps/reference/dosewallips"
CLASS_COLORS = {0:(98,99,97),1:(98,99,97),2:(148,145,136),3:(147,143,128),4:(133,137,111),
    5:(118,141,84),6:(136,153,91),7:(128,148,85),8:(124,145,86),9:(76,108,66),10:(43,79,61),
    11:(58,94,63),12:(91,119,75),13:(52,89,71),14:(70,107,81),15:(112,132,88),16:(54,94,78),
    17:(72,110,84),18:(127,141,88),19:(165,160,137),20:(154,149,133),21:(44,91,111),
    22:(74,112,95),23:(64,105,112),24:(156,154,140),25:(226,232,231)}


def recipe():
    return [RECIPE_VERSION,"public measured terrain; mapped environment; explicitly derived microclimate",
            "6km aggregate footprint; retained 1m numeric terrain tiles; no invented sub-metre data"]


def monthly_climate(csv_text):
    lines = csv_text.splitlines()
    header = next(i for i,line in enumerate(lines) if line.startswith("year,yday,"))
    records = list(csv.DictReader(lines[header:]))
    def key(prefix):
        return next(k for k in records[0] if k.startswith(prefix))
    temperatures, rain = [[] for _ in range(12)], [[] for _ in range(12)]
    years = {int(r["year"]) for r in records}
    for r in records:
        month = (date(int(r["year"]),1,1)+timedelta(days=int(r["yday"])-1)).month-1
        temperatures[month].append((float(r[key("tmin")])+float(r[key("tmax")]))*.5)
        rain[month].append(float(r[key("prcp")]))
    if years != set(range(1991,2021)) or len(records) != 30*365:
        raise ValueError("Incomplete Daymet 1991–2020 normals input")
    temp = [sum(v)/len(v) for v in temperatures]
    precipitation = [sum(v)/len(years) for v in rain]
    return dict(period="1991–2020",source="Daymet v4, nearest 1km grid cell; interpolated station-based weather",
        source_elevation_m=226.,latitude=47.69,longitude=-122.93,monthly_temperature_c=temp,
        monthly_precipitation_mm=precipitation,annual_temperature_k=sum(temp)/12+273.15,
        annual_precipitation_mm=sum(precipitation),temperature_seasonality_k=max(temp)-min(temp),
        koppen=_koppen_geiger_class(temp,precipitation,[3,4,5,6,7,8],[9,10,11,0,1,2]))


def rasterize_wetlands(features, bbox, n):
    """NWI geometry in shared UTM; explicit ring orientation preserves holes."""
    water = Image.new("L",(n,n)); wetland = Image.new("L",(n,n)); channel = Image.new("L",(n,n))
    for feature in features:
        a = feature["attributes"]
        system = a.get("NWI_Wetland_Codes.SYSTEM","")
        subsystem = a.get("NWI_Wetland_Codes.SUBSYSTEM","")
        code = a.get("Wetlands.ATTRIBUTE","")
        open_water = system == "R" or code.startswith("E1") or code.startswith("PUB")
        for ring in feature.get("geometry",{}).get("rings",[]):
            if len(ring)<3:
                continue
            area = sum(x*y2-x2*y for (x,y),(x2,y2) in zip(ring,ring[1:]+ring[:1]))
            exterior = area < 0
            points = [((x-bbox[0])/(bbox[2]-bbox[0])*(n-1),
                       (bbox[3]-y)/(bbox[3]-bbox[1])*(n-1)) for x,y in ring]
            if system in {"P","E"} and subsystem != "1":
                ImageDraw.Draw(wetland).polygon(points,fill=255 if exterior else 0)
            if open_water:
                ImageDraw.Draw(water).polygon(points,fill=255 if exterior else 0)
            if system == "R":
                ImageDraw.Draw(channel).polygon(points,fill=255 if exterior else 0)
    return tuple(np.asarray(i,dtype=np.float32)/255 for i in (water,wetland,channel))


@lru_cache(maxsize=1)
def build_models():
    manifest = json.loads(asset_files.read_text(DATA_ROOT/"acquisition.json"))
    sources = manifest["sources"]
    needed = {f"elevation_{j}_{i}" for j in range(6) for i in range(6)} | {"landcover","wetlands","climate","orthophoto"}
    if not needed <= sources.keys():
        raise ValueError("Incomplete reference assets; run tools.acquire_highest_lod_reference --tiles / --wetlands-only")
    n = 1001
    elevation = np.full((n,n),np.nan,dtype=np.float32)
    indices = np.minimum(5999,np.round(np.linspace(-.5,5999.5,n)).astype(int)).clip(0,5999)
    descriptors = []
    native_min, native_max = float("inf"), float("-inf")
    for j in range(6):
        for i in range(6):
            record = sources[f"elevation_{j}_{i}"]
            data = asset_files.read_bytes(DATA_ROOT/record["path"])
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Reference asset checksum mismatch: {record['path']}")
            tile = read_numeric_tiff(data)
            if np.any(np.isfinite(tile)):
                native_min, native_max = min(native_min,float(np.nanmin(tile))), max(native_max,float(np.nanmax(tile)))
            jy,ix = np.where(indices//1000==j)[0],np.where(indices//1000==i)[0]
            elevation[np.ix_(jy,ix)] = tile[np.ix_(indices[jy]%1000,indices[ix]%1000)]
            descriptors.append(dict(path="assets/maps/reference/dosewallips/"+record["path"],
                row=j,column=i,sha256=record["sha256"],width=1000,height=1000))
    for key in ("landcover","wetlands","climate","orthophoto"):
        data = asset_files.read_bytes(DATA_ROOT/sources[key]["path"])
        if hashlib.sha256(data).hexdigest() != sources[key]["sha256"]:
            raise ValueError(f"Reference asset checksum mismatch: {key}")
    land = read_numeric_tiff(asset_files.read_bytes(DATA_ROOT/"landcover.tif"))
    li = np.minimum(599,np.floor(np.linspace(0,600,n)).astype(int))
    classes = land[np.ix_(li,li)]
    vectors = json.loads(asset_files.read_text(DATA_ROOT/"wetlands.json"))
    water, wetland, channel = rasterize_wetlands(vectors["features"],manifest["bbox_utm_m"],n)
    water = np.maximum(water,np.isin(classes,[21,22,23]))
    wetland = np.maximum(wetland,np.isin(classes,[13,14,15,16,17,18]))
    valid = np.isfinite(elevation)
    display_height = np.where(valid,elevation,0.)
    climate = monthly_climate(asset_files.read_text(DATA_ROOT/"climate.csv"))
    gy,gx = np.gradient(display_height,EXTENT_M/(n-1))
    slope = np.hypot(gx,gy)
    exposure = np.clip((.82+.2*gx-.3*gy)/np.sqrt(1+slope*slope),.08,1.)
    moisture = np.clip(.55-.2*np.minimum(1,slope)+.38*wetland+.45*water,0,1)
    lut = np.array([CLASS_COLORS.get(i,CLASS_COLORS[0]) for i in range(256)],dtype=np.uint8)
    rgb = lut[classes]
    shade = np.clip((.70+.50*gx-.45*gy)/np.sqrt(1+slope*slope),.22,1.)
    altitude = np.clip(display_height/1200,0,1)[...,None]
    relief = np.array([179,190,153])*(1-altitude)+np.array([211,202,177])*altitude
    relief = (relief*shade[...,None]).clip(0,255).astype(np.uint8)
    # Bare-earth relief must not hide known bank/bed samples behind coarse water masks.
    relief[~valid & (water>.5)] = (53,91,108)
    relief[~valid & (water<.5)] = (119,119,125)
    fingerprint = hashlib.sha256((RECIPE_VERSION+json.dumps({k:sources[k]["sha256"] for k in sorted(needed)},sort_keys=True)).encode()).hexdigest()
    common = dict(status="data_backed_reference_target",model_version=RECIPE_VERSION,input_fingerprint=fingerprint)
    height = dict(common,map_detail_level=7,detail_level_name="tiled_reference_landscape",projection="local_cartesian",
        wrap_x=False,wrap_y=False,region_width_m=EXTENT_M,region_height_m=EXTENT_M,
        sample_spacing_x_m=6.,sample_spacing_y_m=6.,vertical_datum="NAVD88 (not local mean sea level)",
        elevation_unit="m",sea_level_m=None,min_elevation_m=native_min,max_elevation_m=native_max,
        sample_grid=dict(width=n,height=n,rows=display_height.tolist(),purpose="6m display/derived-field overview of retained 1m reference tiles"),
        native_raster_tiles=dict(width=6000,height=6000,tile_size=1000,sample_spacing_m=1.,tiles=descriptors,
            bounds=dict(min_x=0.,max_x=EXTENT_M,min_y=0.,max_y=EXTENT_M),
            nodata_policy="unknown numeric terrain; marine rendering plane is not bathymetry"),
        surface_masks=dict(terrain_valid_rows=valid.tolist()),abiotic_rgb_rows=rgb.tolist(),reference_relief_rgb_rows=relief.tolist(),
        reference_orthophoto=dict(path="assets/maps/reference/dosewallips/orthophoto.png",sha256=sources["orthophoto"]["sha256"],
            export_resolution_m=3.,source="USGS NAIP Plus aerial-image mosaic; acquisition dates differ from DEM/land cover",
            uv_bounds=[0.,0.,1.,1.]),
        scientific_source=dict(provider="USGS 3DEP",source_resolution_m=1.,export_resolution_m=1.,bbox_utm_m=manifest["bbox_utm_m"],
            crs_epsg=32610,axes="x east from west edge; y south from north edge",raw_samples_preserved=True))
    temperature = climate["annual_temperature_k"]-.0065*(display_height-climate["source_elevation_m"])
    climate_grid = dict(width=n,height=n,temperature_rows_k=temperature.tolist(),
        annual_precipitation_rows_mm=[[climate["annual_precipitation_mm"]]*n for _ in range(n)],
        temperature_seasonality_rows_k=[[climate["temperature_seasonality_k"]]*n for _ in range(n)],
        koppen_rows=[[climate["koppen"]]*n for _ in range(n)],surface_solar_exposure_rows=exposure.tolist(),
        source_normals=climate,downscaling="Illustrative fixed 6.5K/km lapse rate; not observed 1m climate. No invented rainfall gradient.")
    return dict(heightmap_model=height,
        water_cycle_model=dict(common,hydrology_cycle="active",liquid_water_possible=True,climate_grid=climate_grid,
            runoff_grid=dict(width=n,height=n,channel_presence_rows=channel.tolist(),wetness_index_rows=moisture.tolist()),
            surface_water_grid=dict(width=n,height=n,water_presence_rows=water.tolist()),
            boundary_conditions=dict(hydraulic_solution=False,water_depth="unknown",tidal_datum="unknown; NAVD88 not treated as sea level",salinity="unknown")),
        koppen_climate_model=dict(common,climate_grid=climate_grid),
        regolith_soil_model=dict(common,status="not_measured_in_reference",grid={},
            notes="Soil pH/depth/fertility/permeability not fabricated. Habitat wetness is a labelled proxy; species physiology remains qualitative."),
        river_model=dict(common,source="NWI riverine polygons",mapped_channel_feature_count=sum(f['attributes'].get('NWI_Wetland_Codes.SYSTEM')=='R' for f in vectors['features'])),
        landcover_model=dict(common,provider="NOAA C-CAP",source_resolution_m=30.,export_resolution_m=10.,
            grid=dict(width=n,height=n,class_rows=classes.tolist()),class_colors={str(k):list(v) for k,v in CLASS_COLORS.items()}),
        wetlands_model=dict(common,provider="USFWS NWI",feature_count=len(vectors['features']),
            source_asset="assets/maps/reference/dosewallips/wetlands.json",grid=dict(width=n,height=n,wetland_presence_rows=wetland.tolist())),
        true_color_model=dict(common,vegetation=True,vegetation_policy="Reference aerial imagery includes real canopy, not simulated vegetation; Biosphere ground uses labelled land-cover classes",
            heightfield_fingerprint=fingerprint),
        reference_environment_model=dict(common,observed=["numeric terrain","mapped land cover","mapped wetland/river geometry"],
            observation_based=["Daymet 1km station-interpolated climate normals"],derived=["slope/exposure","lapse-rate temperature","habitat wetness proxy"],
            unknown=["marine bathymetry","river depth/discharge","local tide","salinity","soil profiles","natural species composition"]))


def hydrate_entity(entity):
    if RECIPE_VERSION in (entity.get("map_generation_recipe") or []):
        for key,value in build_models().items():
            entity.setdefault(key,value)
    return entity


def reference_window_entity(x, y, width_m=600., height_m=600.):
    """Read-only native-detail window of the same map, not a new generated landscape."""
    if not (1 <= width_m <= 700 and 1 <= height_m <= 700 and
            0 <= x <= EXTENT_M-width_m and 0 <= y <= EXTENT_M-height_m):
        raise ValueError("Reference window must fit the source and be 1–700m across")
    root = target_entity()
    bounds = dict(type="bbox",min_x=x,max_x=x+width_m,min_y=y,max_y=y+height_m)
    xs, ys = np.linspace(x,x+width_m,int(np.ceil(width_m))+1), np.linspace(y,y+height_m,int(np.ceil(height_m))+1)
    xx, yy = np.meshgrid(xs,ys)
    models = build_models()
    sampler = NativeRasterTiles(models["heightmap_model"]["native_raster_tiles"],root["bounds"])
    elevation = sampler.sample_many(xx,yy)
    gx, gy = xx/6., yy/6.
    ix, iy = np.floor(gx).astype(int).clip(0,999), np.floor(gy).astype(int).clip(0,999)
    fx, fy = gx-ix, gy-iy
    def crop(value, key=""):
        if isinstance(value,dict):
            result = {k:crop(v,k) for k,v in value.items()}
            if result.get("width") == 1001 and result.get("height") == 1001:
                result.update(width=len(xs),height=len(ys))
            return result
        if isinstance(value,list) and len(value)==1001 and isinstance(value[0],list) and len(value[0])==1001:
            # Convert only the window's overview subregion, not every full field.
            x0,y0=int(ix.min()),int(iy.min())
            a=np.asarray([row[x0:int(ix.max())+2] for row in value[y0:int(iy.max())+2]])
            px,py=ix-x0,iy-y0
            if a.dtype.kind in "bUS" or key in {"class_rows","water_presence_rows","channel_presence_rows","wetland_presence_rows","abiotic_rgb_rows"}:
                return a[py+(fy>=.5),px+(fx>=.5)].tolist()
            tx,ty=(fx[...,None],fy[...,None]) if a.ndim==3 else (fx,fy)
            return ((a[py,px]*(1-tx)+a[py,px+1]*tx)*(1-ty)+(a[py+1,px]*(1-tx)+a[py+1,px+1]*tx)*ty).tolist()
        return value
    root.update({k:crop(v) for k,v in models.items()})
    height=root["heightmap_model"]
    height.update(region_width_m=width_m,region_height_m=height_m,
        sample_spacing_x_m=width_m/(len(xs)-1),sample_spacing_y_m=height_m/(len(ys)-1))
    height["sample_grid"].update(rows=np.nan_to_num(elevation,nan=0.).tolist(),purpose="Native 1m terrain reference window")
    height["reference_orthophoto"]["uv_bounds"]=[x/EXTENT_M,y/EXTENT_M,(x+width_m)/EXTENT_M,(y+height_m)/EXTENT_M]
    height["surface_masks"]["terrain_valid_rows"]=np.isfinite(elevation).tolist()
    gy1,gx1=np.gradient(np.nan_to_num(elevation,nan=0.),height["sample_spacing_y_m"],height["sample_spacing_x_m"])
    shade=np.clip((.70+.50*gx1-.45*gy1)/np.sqrt(1+gx1*gx1+gy1*gy1),.22,1.)
    rgb=np.clip(np.array([179,190,153])*shade[...,None],0,255).astype(np.uint8)
    water=np.asarray(root["water_cycle_model"]["surface_water_grid"]["water_presence_rows"])>.5
    rgb[~np.isfinite(elevation)&water]=(53,91,108); rgb[~np.isfinite(elevation)&~water]=(119,119,125)
    height["reference_relief_rgb_rows"]=rgb.tolist()
    root.update(id=MAP_ID+"_window",name="Native-detail reference window",pretty_name="Native-detail reference window",bounds=bounds,
        reference_source_map_id=MAP_ID,biosphere_width_m=width_m,biosphere_height_m=height_m,biosphere_area_m2=width_m*height_m)
    root.pop("biosphere_entity_id",None)
    return root


def target_entity():
    profile = detail_level_spec(7)
    profile.update(label="Highest-detail reference landscape",footprint_policy="aggregate tiled landscape, not one survey patch",
                   typical_footprint_km="6km aggregate; local survey windows retain their normal scale",measurement_floor_m=1.)
    return dict(id=MAP_ID,type="location",_dataset="locations",name=MAP_ID,pretty_name=MAP_ID,location_class="site",
        location_role="data_backed_worldgen_target",map_coordinate_space="site_meters",map_detail_level=7,
        map_context_detail_level=3,map_detail_profile=profile,map_generation_recipe=recipe(),
        map_status="data-backed 36km² reference landscape; procedural lineage pending",
        bounds=dict(type="bbox",min_x=0.,max_x=EXTENT_M,min_y=0.,max_y=EXTENT_M),display_color=[72,100,71],
        biosphere_entity_id="biosphere_highest_lod_example_map",biosphere_width_m=EXTENT_M,biosphere_height_m=EXTENT_M,
        biosphere_area_m2=EXTENT_M**2,biosphere_initial_extent_m=EXTENT_M,
        wiki_entry="Dosewallips coast, estuary/wetlands and Olympic foothill valley. A 6km tiled reference landscape with retained 1m USGS numeric terrain, NOAA land cover, NWI wetland/river mapping, Daymet climate normals. Real terrain, but derived microclimate and unknown soils/hydraulics are labelled. No generated parent lineage or invented 10cm measurement.")


def inspection_overlay():
    return dict(id="biosphere_highest_lod_example_map",type="biosphere",_dataset="biospheres",
        name="Highest LOD real-landscape inspection overlay",overlay_location=MAP_ID,establishment_status="draft",
        inspection_introductions=[],
        wiki_entry="Inspect the real-landscape substrate before introducing species. C-CAP classes are not a species roster; old European demo populations have been removed from this American reference site.")
