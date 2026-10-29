"""Compact, process-shaped parent contract for landscape reconstruction.

The abstraction is deliberately not a compressed photograph.  It retains the
fields and connected features that a child must honour, plus statistics that
bound (but do not prescribe) new detail.
"""
from collections import deque
import hashlib
import json
import math

import numpy as np
from PIL import Image,ImageDraw


CONTRACT_VERSION = "landscape-abstraction-v1"
PATCH_NAMES = ("unknown", "open_water", "wetland", "valley_floor",
               "forested_hillslope", "steep_hillslope", "upland")


def _as_array(rows, dtype=float):
    value = np.asarray(rows, dtype=dtype)
    if value.ndim != 2 or min(value.shape) < 2:
        raise ValueError("Landscape fields must be rectangular 2D grids")
    return value


def _resize_bilinear(values, shape):
    """Dependency-free bilinear field resampling; categorical fields use another path."""
    values = np.asarray(values, dtype=float)
    h, w = shape
    source_x = np.arange(values.shape[1], dtype=float)
    target_x = np.linspace(0, values.shape[1]-1, w)
    horizontal = np.vstack([np.interp(target_x, source_x, row) for row in values])
    source_y = np.arange(values.shape[0], dtype=float)
    target_y = np.linspace(0, values.shape[0]-1, h)
    return np.vstack([np.interp(target_y, source_y, horizontal[:, col])
                      for col in range(w)]).T


def _resize_nearest(values, shape):
    values = np.asarray(values)
    yi = np.round(np.linspace(0, values.shape[0]-1, shape[0])).astype(int)
    xi = np.round(np.linspace(0, values.shape[1]-1, shape[1])).astype(int)
    return values[np.ix_(yi, xi)]


def _block_presence(values, stride):
    """Preserve narrow features which centre-point sampling would erase."""
    values = np.asarray(values, dtype=float)
    ny,nx = (values.shape[0]-1)//stride+1,(values.shape[1]-1)//stride+1
    result = np.zeros((ny,nx), dtype=float)
    for y in range(ny):
        y0, y1 = max(0,y*stride-stride//2), min(values.shape[0],y*stride+stride//2+1)
        for x in range(nx):
            x0, x1 = max(0,x*stride-stride//2), min(values.shape[1],x*stride+stride//2+1)
            result[y,x] = float(np.max(values[y0:y1,x0:x1]))
    return result


def _components(mask, prefix, spacing_m, *, minimum_cells=2):
    mask = np.asarray(mask, dtype=bool)
    seen = np.zeros(mask.shape, dtype=bool)
    result = []
    for y0,x0 in zip(*np.where(mask & ~seen)):
        if seen[y0,x0]:
            continue
        queue=deque([(int(y0),int(x0))]);seen[y0,x0]=True;cells=[];portals=set()
        while queue:
            y,x=queue.popleft();cells.append((y,x))
            if y==0: portals.add(("north",x))
            if y==mask.shape[0]-1: portals.add(("south",x))
            if x==0: portals.add(("west",y))
            if x==mask.shape[1]-1: portals.add(("east",y))
            for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
                yy,xx=y+dy,x+dx
                if 0<=yy<mask.shape[0] and 0<=xx<mask.shape[1] and mask[yy,xx] and not seen[yy,xx]:
                    seen[yy,xx]=True;queue.append((yy,xx))
        if len(cells)<minimum_cells:
            continue
        digest=hashlib.sha256(json.dumps(cells,separators=(",",":")).encode()).hexdigest()[:12]
        ys=[v[0] for v in cells];xs=[v[1] for v in cells]
        result.append(dict(id=f"{prefix}_{digest}",cell_count=len(cells),area_m2=len(cells)*spacing_m**2,
            bounds_cells=[min(xs),min(ys),max(xs),max(ys)],boundary_portals=[list(v) for v in sorted(portals)]))
    return sorted(result,key=lambda item:(-item["cell_count"],item["id"]))


def _patch_labels(elevation, valid, water, wetland, landcover, spacing_m):
    fill=np.where(valid,elevation,np.nanmedian(elevation[valid]))
    gy,gx=np.gradient(fill,spacing_m);slope=np.hypot(gx,gy)
    low=float(np.quantile(fill[valid],.32))
    labels=np.full(fill.shape,6,dtype=np.uint8)
    labels[np.isin(landcover,[9,10,11,12])]=4
    labels[slope>.42]=5
    labels[(fill<=low+18)&(slope<.15)]=3
    labels[wetland]=2;labels[water]=1;labels[~valid]=0
    return labels,slope


def _generated_hydrology(entity, shape, spacing_m, elevation):
    """Rasterize the production drainage graph without consulting a reference."""
    water_cycle=entity.get("water_cycle_model") or {}
    sea=(entity.get("heightmap_model") or {}).get("sea_level_m")
    water=np.asarray(elevation<=float(sea),dtype=bool) if sea is not None else np.zeros(shape,dtype=bool)
    channel_image=Image.new("L",(shape[1],shape[0]));draw=ImageDraw.Draw(channel_image)
    rivers=[]
    for index,river in enumerate(water_cycle.get("rivers") or []):
        points=river.get("points") or river.get("display_points") or []
        pixels=[(round(float(p["x"])*(shape[1]-1)),round(float(p["y"])*(shape[0]-1))) for p in points]
        morphology=river.get("channel_morphology") or {}
        width_m=float(morphology.get("bankfull_width_m",0.) or 0.)
        width=max(1,min(9,round(width_m/max(.001,spacing_m))))
        if len(pixels)>=2:draw.line(pixels,fill=255,width=width,joint="curve")
        river_id=str(river.get("id") or f"river_{index+1:03d}")
        rivers.append(dict(id=river_id,joins_river_id=river.get("joins_river_id"),mouth=river.get("mouth"),
            stream_order=river.get("stream_order"),flow=river.get("flow"),points=points,
            source="production drainage graph"))
    channel=np.asarray(channel_image,dtype=np.uint8)>0
    for lake in water_cycle.get("lakes") or []:
        for cell in lake.get("cells") or []:
            if len(cell)>=2 and 0<=int(cell[1])<shape[0] and 0<=int(cell[0])<shape[1]:
                water[int(cell[1]),int(cell[0])]=True
    water|=channel
    climate=water_cycle.get("climate_grid") or {}
    runoff=climate.get("annual_runoff_rows_mm")
    runoff=np.asarray(runoff,dtype=float) if isinstance(runoff,list) and runoff else np.zeros(shape)
    if runoff.shape!=shape:runoff=_resize_bilinear(runoff,shape)
    fill=np.asarray(elevation,dtype=float);gy,gx=np.gradient(fill,spacing_m);slope=np.hypot(gx,gy)
    land_runoff=runoff[~water]
    threshold=float(np.quantile(land_runoff,.72)) if len(land_runoff) else float("inf")
    shoreline=np.zeros(shape,dtype=bool)
    shoreline[:-1,:]|=water[:-1,:]!=water[1:,:];shoreline[:,:-1]|=water[:,:-1]!=water[:,1:]
    near_water=_resize_bilinear(shoreline.astype(float),shape)>.15
    rain=climate.get("annual_precipitation_rows_mm")
    rain=np.asarray(rain,dtype=float) if isinstance(rain,list) and rain else np.zeros(shape)
    if rain.shape!=shape:rain=_resize_bilinear(rain,shape)
    # Relative runoff alone labels the wettest part of even a desert.  Away
    # from mapped water, require both gentle terrain and a credible water input.
    wetland=(~water)&(slope<.08)&near_water
    wetland|=(~water)&(slope<.04)&(runoff>=max(150.,threshold))&(rain>=400.)
    return water,channel,wetland,rivers


def _generated_landcover(entity, shape, water):
    climate=(entity.get("water_cycle_model") or {}).get("climate_grid") or {}
    temperature=climate.get("temperature_rows_k")
    rain=climate.get("annual_precipitation_rows_mm")
    temperature=np.asarray(temperature,dtype=float) if isinstance(temperature,list) and temperature else np.full(shape,285.)
    rain=np.asarray(rain,dtype=float) if isinstance(rain,list) and rain else np.full(shape,700.)
    if temperature.shape!=shape:temperature=_resize_bilinear(temperature,shape)
    if rain.shape!=shape:rain=_resize_bilinear(rain,shape)
    # C-CAP-like internal codes are used only to feed generic patch classes.
    land=np.full(shape,12,dtype=int)
    land[(rain>650)&(temperature>268)&(temperature<302)]=10
    land[(rain<300)|(temperature>307)]=5
    land[water]=21
    return land


def _generated_climate_boundary(entity):
    climate=(entity.get("water_cycle_model") or {}).get("climate_grid") or {}
    def mean(key,default):
        rows=climate.get(key)
        return float(np.mean(np.asarray(rows,dtype=float))) if isinstance(rows,list) and rows else default
    classes=sorted({str(v) for row in (climate.get("koppen_rows") or []) for v in row})
    return dict(source="generated parent climate solution",annual_temperature_k=mean("temperature_rows_k",285.15),
        annual_precipitation_mm=mean("annual_precipitation_rows_mm",700.),koppen_classes=classes,
        observation_based=False)


def abstract_landscape(entity, *, parent_spacing_m=30.):
    """Extract a compact LOD3 parent from a detailed, aligned map entity."""
    height=entity["heightmap_model"]
    fine=_as_array(height["sample_grid"]["rows"])
    masks=height.get("surface_masks") or {}
    valid=_as_array(masks.get("terrain_valid_rows") or np.ones(fine.shape,dtype=bool),bool)
    source_spacing=float(height["sample_spacing_x_m"])
    stride=round(parent_spacing_m/source_spacing)
    if (stride<1 or abs(stride*source_spacing-parent_spacing_m)>1e-6 or
            (fine.shape[0]-1)%stride or (fine.shape[1]-1)%stride):
        raise ValueError("Parent spacing must be an exact divisor of the aligned source overview")
    coarse=fine[::stride,::stride]
    coarse_valid=valid[::stride,::stride]
    surface=(entity.get("water_cycle_model") or {}).get("surface_water_grid") or {}
    generated_rivers=[]
    if surface.get("water_presence_rows"):
        water_fine=_as_array(surface["water_presence_rows"])
        channel_fine=_as_array(entity["water_cycle_model"]["runoff_grid"]["channel_presence_rows"])
        wetland_fine=_as_array(entity["wetlands_model"]["grid"]["wetland_presence_rows"])
    else:
        water_fine,channel_fine,wetland_fine,generated_rivers=_generated_hydrology(entity,fine.shape,source_spacing,fine)
    water=_block_presence(water_fine,stride)>.5
    channel=_block_presence(channel_fine,stride)>.5
    wetland=_block_presence(wetland_fine,stride)>.5
    land_rows=((entity.get("landcover_model") or {}).get("grid") or {}).get("class_rows")
    land_fine=_as_array(land_rows,int) if land_rows else _generated_landcover(entity,fine.shape,water_fine>.5)
    land=land_fine[::stride,::stride]
    labels,slope=_patch_labels(coarse,coarse_valid,water,wetland,land,parent_spacing_m)
    # The reference residual is reduced to distributions by landscape class.
    inherited=_resize_bilinear(coarse,fine.shape)
    residual=np.where(valid,fine-inherited,np.nan)
    fine_labels=_resize_nearest(labels,fine.shape)
    statistics={}
    for code,name in enumerate(PATCH_NAMES):
        values=residual[(fine_labels==code)&valid]
        if len(values):
            statistics[name]=dict(sample_count=int(len(values)),mean_m=float(np.mean(values)),
                rms_m=float(np.sqrt(np.mean(values*values))),p95_absolute_m=float(np.quantile(np.abs(values),.95)))
    land_values=residual[(fine_labels!=0)&valid]
    if stride==1:
        priors={"unknown":0.,"open_water":0.,"wetland":.12,"valley_floor":.28,
                "forested_hillslope":.72,"steep_hillslope":1.35,"upland":.58}
        statistics={name:dict(sample_count=0,mean_m=0.,rms_m=value,p95_absolute_m=value*2.2,
            source="scale-specific procedural prior") for name,value in priors.items()}
        budget=3.5
    else:
        budget=max(.05,float(np.quantile(np.abs(land_values),.98)))
    shore=np.zeros(water.shape,dtype=bool)
    shore[:-1,:] |= water[:-1,:] != water[1:,:];shore[:,:-1] |= water[:,:-1] != water[:,1:]
    patch_components=[]
    for code,name in enumerate(PATCH_NAMES[1:],1):
        patch_components.extend(dict(component,patch_class=name) for component in _components(labels==code,"patch",parent_spacing_m,minimum_cells=4))
    source_fp=height.get("input_fingerprint") or hashlib.sha256(json.dumps({
        "model_version":height.get("model_version"),"generated_truth_lineage":height.get("generated_truth_lineage"),
        "sample_grid":height.get("sample_grid")},sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    payload=dict(contract_version=CONTRACT_VERSION,source_map_id=entity.get("id"),source_fingerprint=source_fp,
        calibration_kind="observed_reference" if entity.get("reference_environment_model") else "generated_parent",
        detail_level=3,coordinate_space=entity.get("map_coordinate_space"),bounds=entity["bounds"],
        width=int(coarse.shape[1]),height=int(coarse.shape[0]),spacing_m=parent_spacing_m,
        broad_fields=dict(elevation_rows_m=coarse.tolist(),terrain_valid_rows=coarse_valid.tolist(),
            dominant_landcover_rows=land.tolist(),landscape_patch_rows=labels.tolist(),slope_rows=slope.tolist()),
        feature_network=dict(water_corridor_rows=water.tolist(),river_corridor_rows=channel.tolist(),
            wetland_rows=wetland.tolist(),shoreline_rows=shore.tolist(),
            water_components=_components(water,"water",parent_spacing_m),
            river_components=_components(channel,"river",parent_spacing_m),river_graph=generated_rivers),
        landscape_patches=patch_components,
        climate_boundary=((entity.get("water_cycle_model") or {}).get("climate_grid") or {}).get("source_normals") or _generated_climate_boundary(entity),
        residual_statistics=statistics,residual_budget_m=budget,
        unknown=list((entity.get("reference_environment_model") or {}).get("unknown") or
            ["sub-grid soil horizons","resolved channel cross-sections","individual organisms"]),
        contract="children inherit fields and connected-feature identities; only scale-specific residuals vary")
    fp_payload={k:v for k,v in payload.items() if k not in {"source_map_id","source_fingerprint"}}
    payload["fingerprint"]=hashlib.sha256(json.dumps(fp_payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    return payload


def _value_noise(shape, rng, anchors):
    small=rng.normal(0,1,(anchors,anchors))
    return _resize_bilinear(small,shape)


def reconstruct_landscape(abstraction, *, seed=1, output_spacing_m=6.):
    """Create one plausible child using the abstraction only."""
    if abstraction.get("contract_version")!=CONTRACT_VERSION:
        raise ValueError("Unsupported landscape abstraction")
    parent=np.asarray(abstraction["broad_fields"]["elevation_rows_m"],dtype=float)
    width_m=(parent.shape[1]-1)*float(abstraction["spacing_m"])
    height_m=(parent.shape[0]-1)*float(abstraction["spacing_m"])
    w,h=round(width_m/output_spacing_m)+1,round(height_m/output_spacing_m)+1
    if w>2049 or h>2049:
        raise ValueError("Reconstruction exceeds bounded working grid")
    inherited=_resize_bilinear(parent,(h,w))
    rng=np.random.default_rng(int(seed))
    # Only wavelengths below the parent's reliable support are newly sampled.
    noise=.58*_value_noise((h,w),rng,151)+.29*_value_noise((h,w),rng,301)+.13*_value_noise((h,w),rng,501)
    stride=round(float(abstraction["spacing_m"])/output_spacing_m)
    rms=math.sqrt(float(np.mean(noise*noise))) or 1.
    parent_labels=np.asarray(abstraction["broad_fields"]["landscape_patch_rows"])
    labels=_resize_nearest(parent_labels,(h,w))
    parent_amplitude=np.zeros(parent_labels.shape,dtype=float)
    stats=abstraction["residual_statistics"]
    for code,name in enumerate(PATCH_NAMES):
        parent_amplitude[parent_labels==code]=min(abstraction["residual_budget_m"],stats.get(name,{}).get("rms_m",0.))
    amplitude=_resize_bilinear(parent_amplitude,(h,w))
    residual=noise/rms*amplitude
    # Smoothly reduce only at the child footprint boundary; tiled generation uses
    # an overlap halo before cropping, so internal tile edges never receive this taper.
    yy,xx=np.indices((h,w));distance=np.minimum.reduce([yy,xx,h-1-yy,w-1-xx])
    t=np.clip(distance/max(1,4*stride),0,1);residual*=.5-.5*np.cos(np.pi*t)
    budget=float(abstraction["residual_budget_m"])
    residual=np.clip(residual,-budget,budget)
    reconstructed=inherited+residual
    valid=_resize_nearest(abstraction["broad_fields"]["terrain_valid_rows"],(h,w)).astype(bool)
    water=_resize_nearest(abstraction["feature_network"]["water_corridor_rows"],(h,w)).astype(bool)
    river=_resize_nearest(abstraction["feature_network"]["river_corridor_rows"],(h,w)).astype(bool)
    wetland=_resize_nearest(abstraction["feature_network"]["wetland_rows"],(h,w)).astype(bool)
    return dict(contract_version="landscape-reconstruction-v1",parent_fingerprint=abstraction["fingerprint"],seed=int(seed),
        width=w,height=h,spacing_m=float(output_spacing_m),elevation_rows_m=reconstructed.tolist(),
        terrain_valid_rows=valid.tolist(),landscape_patch_rows=labels.tolist(),water_corridor_rows=water.tolist(),
        river_corridor_rows=river.tolist(),wetland_rows=wetland.tolist(),residual_rows_m=residual.tolist(),
        maximum_absolute_residual_m=float(np.max(np.abs(residual))))


def evaluate_reconstruction(abstraction, reconstruction, reference_entity):
    """Score structure separately from stochastic pixel agreement."""
    candidate=np.asarray(reconstruction["elevation_rows_m"],dtype=float)
    reference=_as_array(reference_entity["heightmap_model"]["sample_grid"]["rows"])
    valid=_as_array(reference_entity["heightmap_model"]["surface_masks"]["terrain_valid_rows"],bool)
    if candidate.shape!=reference.shape:
        reference=_resize_bilinear(reference,candidate.shape);valid=_resize_nearest(valid,candidate.shape).astype(bool)
    parent=np.asarray(abstraction["broad_fields"]["elevation_rows_m"])
    stride=round(abstraction["spacing_m"]/reconstruction["spacing_m"])
    parent_difference=candidate[::stride,::stride]-parent
    difference=(candidate-reference)[valid]
    ref_residual=(reference-_resize_bilinear(parent,reference.shape))[valid]
    candidate_residual=np.asarray(reconstruction["residual_rows_m"])[valid]
    def rms(values): return float(np.sqrt(np.mean(values*values)))
    river_components=_components(np.asarray(reconstruction["river_corridor_rows"])[::stride,::stride],"river",abstraction["spacing_m"])
    portals=sorted(p for c in river_components for p in c["boundary_portals"])
    expected=sorted(p for c in abstraction["feature_network"]["river_components"] for p in c["boundary_portals"])
    return dict(parent_sample_difference_rmse_m=rms(parent_difference),
        parent_sample_max_difference_m=float(np.max(np.abs(parent_difference))),reference_pixel_rmse_m=rms(difference),
        residual_rms_ratio=rms(candidate_residual)/max(.001,rms(ref_residual)),
        residual_budget_respected=reconstruction["maximum_absolute_residual_m"]<=abstraction["residual_budget_m"]+1e-9,
        river_component_count=len(river_components),river_boundary_portals_preserved=portals==expected,
        note="Pixel RMSE is diagnostic only: stochastic child detail is not expected to reproduce the reference pixelwise.")
