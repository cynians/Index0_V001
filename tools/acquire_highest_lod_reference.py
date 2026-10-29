"""Acquire bounded public GIS data; never silently substitute synthetic terrain."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image
from simulations.world_gen.reference_raster import read_numeric_tiff

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "maps" / "reference" / "dosewallips"
ELEVATION = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
LANDCOVER = "https://imagery.coast.noaa.gov/arcgis/rest/services/Landcover/CCAP_Regional_Landcover/ImageServer"
IMAGERY = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer"


def request(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent":"Index0 terrain reference acquisition"})
    try:
        with urllib.request.urlopen(req, timeout=55) as response:
            data = response.read(250_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read(1800).decode(errors='replace')}") from exc
    if len(data) > 250_000_000:
        raise ValueError("Reference response exceeds bounded download size")
    return data, url


def get_json(url, params=None):
    data, url = request(url, params)
    result = json.loads(data)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result, url


def export(service, bbox, size, pixel_type):
    params = dict(f="json", bbox=",".join(map(str,bbox)),
        bboxSR=32610, imageSR=32610, size=f"{size},{size}", format="tiff", pixelType=pixel_type,
        interpolation="RSP_NearestNeighbor", renderingRule=json.dumps({"rasterFunction":"None"}))
    if service == LANDCOVER:
        # NOAA's JSON href uses a broken reverse-proxy output-directory URL.
        params["f"] = "image"
        data, url = request(service+"/exportImage",params)
        return data, dict(direct_export_url=url,extent=dict(xmin=bbox[0],ymin=bbox[1],xmax=bbox[2],ymax=bbox[3]))
    metadata, _ = get_json(service+"/exportImage", params)
    print("Export",service.split("/")[-2],metadata.get("href"),flush=True)
    data, _ = request(metadata["href"])
    return data, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--wetlands-only", action="store_true")
    parser.add_argument("--tiles", action="store_true")
    parser.add_argument("--imagery-only",action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.imagery_only:
        manifest=json.loads((OUTPUT/"acquisition.json").read_text(encoding="utf-8"))
        bbox=manifest["bbox_utm_m"]
        metadata,_=get_json(IMAGERY,dict(f="json"))
        catalog,_=get_json(IMAGERY+"/query",dict(f="json",where="1=1",geometry=",".join(map(str,bbox)),
            geometryType="esriGeometryEnvelope",inSR=32610,spatialRel="esriSpatialRelIntersects",outFields="*",returnGeometry="false"))
        data,url=request(IMAGERY+"/exportImage",dict(f="image",bbox=",".join(map(str,bbox)),bboxSR=32610,imageSR=32610,
            size="2000,2000",format="png",interpolation="RSP_BilinearInterpolation"))
        image=Image.open(io.BytesIO(data))
        if image.size != (2000,2000) or image.mode not in {"RGB","RGBA"}:
            raise ValueError("Unexpected orthophoto export")
        (OUTPUT/"orthophoto.png").write_bytes(data)
        manifest["imagery_service"],manifest["imagery_catalog"]=metadata,catalog
        manifest["sources"]["orthophoto"]=dict(path="orthophoto.png",url=url,sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),export_resolution_m=3.,note="Aerial imagery is a reference, not simulated canopy or a species roster")
        (OUTPUT/"acquisition.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        print("Saved georeferenced orthophoto",len(data),flush=True)
        return
    if args.wetlands_only:
        manifest = json.loads((OUTPUT/"acquisition.json").read_text(encoding="utf-8"))
        bbox = manifest["bbox_utm_m"]
        data, url = request("https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query",
            dict(f="json",where="1=1",geometry=",".join(map(str,bbox)),geometryType="esriGeometryEnvelope",
                 inSR=32610,outSR=32610,spatialRel="esriSpatialRelIntersects",outFields="*",returnGeometry="true"))
        result = json.loads(data)
        if result.get("error") or result.get("exceededTransferLimit"):
            raise ValueError("Incomplete wetlands response")
        (OUTPUT/"wetlands.json").write_bytes(data)
        manifest["sources"]["wetlands"] = dict(url=url,path="wetlands.json",sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        (OUTPUT/"acquisition.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        print("Saved wetlands",len(result.get("features",[])),"features",flush=True)
        return
    if args.tiles:
        manifest = json.loads((OUTPUT/"acquisition.json").read_text(encoding="utf-8"))
        bbox = manifest["bbox_utm_m"]
        jobs = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for j in range(6):
                for i in range(6):
                    key = f"elevation_{j}_{i}"
                    if key in manifest["sources"] and (OUTPUT/manifest["sources"][key]["path"]).exists():
                        continue
                    tile_bbox = [bbox[0]+i*1000,bbox[3]-(j+1)*1000,bbox[0]+(i+1)*1000,bbox[3]-j*1000]
                    jobs[pool.submit(export,ELEVATION,tile_bbox,1000,"F32")] = (key,tile_bbox)
            for key, url, params in (("landcover",LANDCOVER,None),
                ("climate","https://daymet.ornl.gov/single-pixel/api/data",dict(lat=47.69,lon=-122.93,
                    vars="tmin,tmax,prcp,srad,dayl",start="1991-01-01",end="2020-12-31"))):
                if key not in manifest["sources"]:
                    future = pool.submit(export,url,bbox,600,"U8") if params is None else pool.submit(request,url,params)
                    jobs[future] = (key,bbox)
            errors = []
            for future in as_completed(jobs):
                key, tile_bbox = jobs[future]
                try:
                    data, response = future.result()
                    filename = key+(".csv" if key=="climate" else ".tif")
                    if key != "climate":
                        array = read_numeric_tiff(data)
                        expected = (600,600) if key=="landcover" else (1000,1000)
                        if array.shape != expected:
                            raise ValueError(f"Unexpected {key} raster {array.shape}")
                    (OUTPUT/filename).write_bytes(data)
                    # Merge sources recorded by a separate wetlands acquisition.
                    existing = json.loads((OUTPUT/"acquisition.json").read_text(encoding="utf-8"))
                    manifest["sources"].update(existing.get("sources",{}))
                    manifest["sources"][key] = dict(path=filename,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),
                        response=response,bbox_utm_m=tile_bbox,request_service=ELEVATION if key.startswith("elevation") else LANDCOVER if key=="landcover" else response)
                    (OUTPUT/"acquisition.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
                    print("Saved",key,len(data),flush=True)
                except Exception as exc:
                    errors.append((key,str(exc)))
                    print("Failed",key,str(exc),flush=True)
            if errors:
                raise RuntimeError(errors)
        return
    if (OUTPUT/"acquisition.json").exists():
        raise SystemExit("Manifest already exists; use --tiles / --wetlands-only / --imagery-only to resume without overwriting")
    if not args.metadata_only:
        raise SystemExit("First acquire --metadata-only, then --tiles and --wetlands-only")
    projected, _ = get_json("https://utility.arcgisonline.com/ArcGIS/rest/services/Geometry/GeometryServer/project",
        dict(f="json",inSR=4326,outSR=32610,geometries=json.dumps({"geometryType":"esriGeometryPoint",
            "geometries":[{"x":-122.905,"y":47.69}]})))
    point = projected["geometries"][0]
    west, south = round(point["x"])-3000, round(point["y"])-3000
    bbox = [west,south,west+6000,south+6000]
    footprint = dict(f="json", geometry=json.dumps({"xmin":bbox[0],"ymin":bbox[1],"xmax":bbox[2],"ymax":bbox[3],
        "spatialReference":{"wkid":32610}}), geometryType="esriGeometryEnvelope", spatialRel="esriSpatialRelIntersects",
        outFields="*", returnGeometry="false")
    elevation_meta, _ = get_json(ELEVATION, dict(f="json"))
    elevation_catalog, _ = get_json(ELEVATION+"/query",footprint)
    land_meta, _ = get_json(LANDCOVER, dict(f="json"))
    manifest = dict(site="Dosewallips River estuary and Olympic foothills, Washington, USA",
        bbox_utm_m=bbox, crs_epsg=32610, extent_m=6000, elevation_service=elevation_meta,
        elevation_catalog=elevation_catalog, landcover_service=land_meta, sources={})
    (OUTPUT/"acquisition.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("UTM bbox:",bbox)
    print("Elevation source records:",[(f["attributes"].get("Name"),f["attributes"].get("Resolution_X"),
        f["attributes"].get("VerticalDatum")) for f in elevation_catalog.get("features",[])][:15],flush=True)
    if args.metadata_only:
        return
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = dict(elevation=pool.submit(export,ELEVATION,bbox,6000,"F32"),
            landcover=pool.submit(export,LANDCOVER,bbox,600,"U8"),
            climate=pool.submit(request,"https://daymet.ornl.gov/single-pixel/api/data",
                dict(lat=47.69,lon=-122.93,vars="tmin,tmax,prcp,srad,dayl",start="1991-01-01",end="2020-12-31")))
        for key, future in futures.items():
            data, url = future.result()
            filename = key+(".csv" if key=="climate" else ".tif")
            if key != "climate":
                array = np.asarray(Image.open(io.BytesIO(data)))
                print(key,array.shape,array.dtype,float(np.nanmin(array)),float(np.nanmax(array)),flush=True)
                expected = (6000,6000) if key=="elevation" else (600,600)
                if array.shape != expected:
                    raise ValueError(f"Unexpected {key} raster: {array.shape}")
            (OUTPUT/filename).write_bytes(data)
            manifest["sources"][key] = dict(url=url,path=filename,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
            (OUTPUT/"acquisition.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
            print("Saved",filename,len(data),flush=True)


if __name__ == "__main__":
    main()
