"""Pixel wood supports and editable bracket sprites in the shared cameras."""
import math
import random
import json
from functools import lru_cache
from pathlib import Path
from engine import asset_files
import pygame


def preview_wood_style():
    """One display reference for diagnostic wood, independent of fungus size."""
    path = Path(__file__).resolve().parents[2] / "assets/plants/preview/species_preview_wood.json"
    return _preview_wood_style(path, asset_files.revision(path))


@lru_cache(maxsize=4)
def _preview_wood_style(path, revision):
    return json.loads(asset_files.read_text(path))


def preview_wood_revision(renderer):
    root = Path(__file__).resolve().parents[2]
    style = preview_wood_style()
    return ("oak_preview_wood_v2", renderer._asset_revision(str(root/"assets/plants/preview/species_preview_wood.json")),
            renderer._asset_revision(str(root/style["bark_texture_set_ref"])))


def _draw_preview_bark(renderer, screen, wood, a, b, radius, ppm):
    # Actual host scenes retain their own host renderer. This art applies only
    # to the shared diagnostic support; its metric geometry is unchanged.
    if wood.get("id") != "wood_test_asset":
        return False
    style = preview_wood_style()
    key, texture = renderer._texture_from_ref(style["bark_texture_set_ref"])
    tile = renderer._texture_surface(key, texture)
    if tile is None:
        return False
    dx, dy = b[0]-a[0], b[1]-a[1]
    width = max(1, min(4096, round(radius*2)))
    height = max(1, min(4096, round(math.hypot(dx, dy))))
    pixel = max(1, min(32, round(ppm*style["bark_pixel_size_m"])))
    tile = pygame.transform.scale(tile, (tile.get_width()*pixel, tile.get_height()*pixel))
    strip = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(0, height, tile.get_height()):
        for x in range(0, width, tile.get_width()):
            strip.blit(tile, (x, y))
    # Cylinder shading keeps the shared bark artwork readable as round wood.
    shade = pygame.Surface((width, height), pygame.SRCALPHA)
    for x in range(width):
        edge = abs(2*x/max(1, width-1)-1)
        pygame.draw.line(shade, (0, 0, 0, round(100*edge**2)), (x, 0), (x, height))
    strip.blit(shade, (0, 0))
    strip = pygame.transform.rotate(strip, -math.degrees(math.atan2(dx, -dy)))
    screen.blit(strip, strip.get_rect(center=((a[0]+b[0])*.5, (a[1]+b[1])*.5)))
    return True


def weathered_sprite(source, palette, progress):
    """Interpolate selected authored colours without altering shape or alpha."""
    result = source.copy()
    progress = max(0., min(1., float(progress)))
    pixels = pygame.PixelArray(result)
    # Read every match from the original pixels, avoiding colour cascades
    # when one target is also another mapping's source.
    original = pygame.PixelArray(source)
    try:
        for pair in palette:
            fresh, faded = pair['fresh_rgb'], pair['weathered_rgb']
            target = [round(a+(b-a)*progress) for a, b in zip(fresh, faded)]
            mapped = source.map_rgb((*fresh, 255))
            for x in range(source.get_width()):
                for y in range(source.get_height()):
                    if original[x, y] == mapped:
                        pixels[x, y] = (*target, 255)
    finally:
        del pixels, original
    return result


def _sprite(renderer, screen, sim, camera, role, point, width_m, flip=False, weathering=0, height_m=None, cap_height_m=None, stipe_width_m=None):
    module = sim.blueprint.module(role)
    source = renderer._module_asset(sim, role)
    if source is None:
        return False
    bounds = source.get_bounding_rect()
    if not bounds.width or not bounds.height:
        return False
    palette = sim.blueprint.growth['fungal_growth_profile'].get('visual_calibration', {}).get('weathering_palette')
    if weathering and palette:
        source = weathered_sprite(source, palette, weathering)
    ppm = renderer._projection_pixels_per_meter(camera)
    width = max(1, min(2048, round(width_m*ppm)))
    height = max(1, round(width*bounds.height/bounds.width))
    if height_m is not None:
        height = max(1, min(2048, round(height_m*ppm)))
    anchor = module.attachment_point
    ax = (anchor[0]*(source.get_width()-1)-bounds.x)/bounds.width
    ay = (anchor[1]*(source.get_height()-1)-bounds.y)/bounds.height
    sprite = pygame.transform.scale(source.subsurface(bounds), (width,height))
    if cap_height_m is not None and height_m and bounds.height >= 2:
        # Whole editable ascocarp art, split at an explicit anatomical join so
        # cap and stalk lengths respond independently to metric trait fields.
        join = max(1,min(bounds.height-1,round(bounds.height*module.visual['cap_join_fraction'])))
        cap_h = max(1,min(height-1,round(cap_height_m*ppm))) if height > 1 else 1
        crop = source.subsurface(bounds)
        sprite = pygame.Surface((width,max(2,height)),pygame.SRCALPHA)
        sprite.blit(pygame.transform.scale(crop.subsurface((0,0,bounds.width,join)),(width,cap_h)),(0,0))
        stem_h = max(1,height-cap_h)
        stem = crop.subsurface((0,join,bounds.width,bounds.height-join))
        stem_bounds = stem.get_bounding_rect()
        stem_width = max(1,min(width,round(stipe_width_m*ppm)))
        if stem_bounds.width and stem_bounds.height:
            sprite.blit(pygame.transform.scale(stem.subsurface(stem_bounds),(stem_width,stem_h)),
                        ((width-stem_width)//2,cap_h))
        height = sprite.get_height()
    if flip:
        sprite = pygame.transform.flip(sprite,True,False); ax = 1-ax
    if weathering and not palette:
        tint = max(110, round(255-100*weathering))
        sprite.fill((tint,tint,round(tint*.85),255),special_flags=pygame.BLEND_RGBA_MULT)
    screen.blit(sprite,(round(point[0]-ax*width),round(point[1]-ay*height)))
    return True


class MetricPreviewCamera:
    """Normalize the diagnostic horizontal basis to metres for flat cap art.

    x + depth*y and isometric x-y otherwise magnify a round trunk's width,
    while the billboard cap remains width_m*ppm. Keep the existing camera's
    framing and vertical projection, but use a unit horizontal basis.
    Actual generated-host scenes retain their original shared projection.
    """
    def __init__(self, camera, horizontal_norm):
        self.camera = camera
        self.scale = camera.scale
        self.view_direction = getattr(camera, "view_direction", (0, -1, 0))
        self.horizontal_norm = horizontal_norm

    def world_to_screen_3d(self, position):
        point = self.camera.world_to_screen_3d(position)
        origin = self.camera.world_to_screen_3d((0., 0., float(position[2])))
        return (round(origin[0]+(point[0]-origin[0])/self.horizontal_norm), point[1])

    def world_to_screen(self, position):
        return self.world_to_screen_3d((position[0], 0., position[1]))


def draw_fungal_individual(renderer, screen, sim, camera, snapshot, clear=True,
                           visible_indices=None, draw_environment=True, cutaway=False):
    from simulations.species.species_renderer import TopDownDiagnosticCamera, PixelSceneCamera, DiagnosticCamera, IsometricDiagnosticCamera
    from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION
    woods = snapshot.stats.get("fungal_substrates", [])
    if draw_environment and woods and all(w.get("id") == "wood_test_asset" for w in woods):
        if isinstance(camera, DiagnosticCamera):
            camera = MetricPreviewCamera(camera, math.sqrt(1+SCREEN_DEPTH_PROJECTION**2))
        elif isinstance(camera, IsometricDiagnosticCamera):
            camera = MetricPreviewCamera(camera, math.sqrt(2.))
    top = isinstance(camera,TopDownDiagnosticCamera) or (isinstance(camera,PixelSceneCamera) and isinstance(camera.camera,TopDownDiagnosticCamera))
    ppm = renderer._projection_pixels_per_meter(camera)
    # Reuse the scene pixel-grid projection used by lichen support previews.
    pixel_scale = max(1,min(8,round(ppm*.0025)))
    if pixel_scale > 1 and not isinstance(camera,PixelSceneCamera):
        size = tuple(math.ceil(v/pixel_scale) for v in screen.get_size())
        canvas = pygame.Surface(size,pygame.SRCALPHA)
        if not clear: canvas.blit(pygame.transform.scale(screen,size),(0,0))
        draw_fungal_individual(renderer,canvas,sim,PixelSceneCamera(camera,pixel_scale),snapshot,
                              clear,visible_indices,draw_environment,cutaway)
        screen.blit(pygame.transform.scale(canvas,tuple(v*pixel_scale for v in size)),(0,0))
        return
    if clear: screen.fill((18,23,20))
    if draw_environment and sim.blueprint.growth.get('ground_fungal_version'):
        radius = sim.blueprint.growth['fungal_growth_profile']['resolved']['colony_radius_m']
        corners = [renderer._path_screen(camera,(x,y,0.))
                   for x,y in ((-radius,-radius),(radius,-radius),(radius,radius),(-radius,radius))]
        if not cutaway:
            pygame.draw.polygon(screen,(41,39,27),corners)
        pygame.draw.polygon(screen,(89,79,51),corners,1)
    if draw_environment:
        for wood in snapshot.stats.get("fungal_substrates",[]):
            from simulations.species.fungal_growth import _frame
            _, radial_a, radial_b = _frame(wood)
            a,b = (renderer._path_screen(camera,wood[k]) for k in ("start_m","end_m"))
            dx,dy = b[0]-a[0],b[1]-a[1]; length=max(1,math.hypot(dx,dy))
            nx,ny = -dy/length,dx/length
            radial_screen=[]
            for radial in (radial_a,radial_b):
                q=renderer._path_screen(camera,[wood["end_m"][i]+radial[i]*wood["radius_m"] for i in range(3)])
                radial_screen.append((q[0]-b[0],q[1]-b[1]))
            radius=max(1,math.sqrt(sum((v[0]*nx+v[1]*ny)**2 for v in radial_screen)))
            polygon = [(a[0]+nx*radius,a[1]+ny*radius),(b[0]+nx*radius,b[1]+ny*radius),
                       (b[0]-nx*radius,b[1]-ny*radius),(a[0]-nx*radius,a[1]-ny*radius)]
            pygame.draw.polygon(screen,(68,52,39) if not cutaway else (62,55,44),polygon)
            textured = not cutaway and _draw_preview_bark(renderer, screen, wood, a, b, radius, ppm)
            rng = random.Random(wood["id"])
            for groove in range(0 if textured else 21):
                offset=(groove/20*2-1)*radius
                begin=rng.uniform(0,.3);end=rng.uniform(.7,1)
                p=(a[0]+dx*begin+nx*offset,a[1]+dy*begin+ny*offset)
                q=(a[0]+dx*end+nx*offset,a[1]+dy*end+ny*offset)
                color=(91,72,50) if groove%3 else (43,34,28)
                pygame.draw.line(screen,color,p,q,max(1,round(ppm*.003)))
            # Angular end-grain facet, retaining the established pixel style.
            for endpoint in ("start_m","end_m"):
                cap=[renderer._path_screen(camera,[wood[endpoint][axis]+wood["radius_m"]*(radial_a[axis]*math.cos(i*math.tau/8)+radial_b[axis]*math.sin(i*math.tau/8)) for axis in range(3)]) for i in range(8)]
                exposed = endpoint == "end_m" or top
                pygame.draw.polygon(screen,(118,91,60) if exposed else (68,52,39),cap)
                pygame.draw.polygon(screen,(62,46,34),cap,1)
                center=renderer._path_screen(camera,wood[endpoint])
                for fraction in ((.38,.68) if exposed else ()):
                    ring=[(center[0]+(pt[0]-center[0])*fraction,center[1]+(pt[1]-center[1])*fraction) for pt in cap]
                    pygame.draw.polygon(screen,(87,64,44),ring,1)
    if cutaway:
        for index,path in snapshot.placement_paths.items():
            if visible_indices is not None and int(index) not in visible_indices: continue
            points=[renderer._path_screen(camera,p) for p in path]
            if len(points)>1: pygame.draw.lines(screen,(196,196,147),False,points,max(1,round(ppm*.0015)))
    for body in sorted(snapshot.stats.get("fungal_bodies",[]),key=lambda b:(b["socket_m"][1] if sim.blueprint.growth.get('ground_fungal_version') else b["socket_m"][2])):
        index=body["placement_index"]
        if index is None or (visible_indices is not None and index not in visible_indices):continue
        base=renderer._path_screen(camera,body["socket_m"])
        if sim.blueprint.growth.get('ground_fungal_version'):
            cup = body.get('body_form') == 'sessile_cup'
            role = 'fruiting_cap' if top else 'fruiting_body'
            if cup and sim.blueprint.module(f"{role}:{body.get('variant_key')}") is not None:
                role=f"{role}:{body['variant_key']}"
            height = body['cap_width_m'] if top else body['cap_height_m'] + body['stipe_length_m']
            if not _sprite(renderer,screen,sim,camera,role,base,body['cap_width_m'],
                           weathering=body['weathering_factor'],height_m=height,
                           cap_height_m=None if top or cup else body['cap_height_m'],
                           stipe_width_m=None if top or cup else body['stipe_diameter_m']):
                # Deliberate missing-asset diagnostic, without plant organs.
                w=max(1,round(body['cap_width_m']*ppm)); h=max(1,round(height*ppm))
                pygame.draw.ellipse(screen,(173,143,91),(base[0]-w//2,base[1]-h,w,h))
            continue
        point=renderer._path_screen(camera,body["cap_socket_m"])
        if body["stipe_length_m"] > 0 and body["stipe_diameter_m"] > 0:
            stem_width=max(1,round(body["stipe_diameter_m"]*ppm))
            pygame.draw.line(screen,(69,53,38),base,point,stem_width)
            pygame.draw.line(screen,(217,208,176),base,point,max(1,round(stem_width*.7)))
        role="fruiting_cap" if top else "fruiting_body"
        variant_role = f"{role}:{body.get('variant_key')}"
        if sim.blueprint.module(variant_role) is not None:
            role = variant_role
        normal=body["normal"]; flip=normal[0]+normal[1]*1.8<0
        if not _sprite(renderer,screen,sim,camera,role,point,body["cap_width_m"],flip,body["weathering_factor"]):
            # Bounded diagnostic silhouette when an asset is deliberately removed.
            width=max(1,round(body["cap_width_m"]*ppm));height=max(1,round(width*.28))
            pygame.draw.ellipse(screen,(195,164,109),(point[0]-width*.3,point[1]-height,width,height))
