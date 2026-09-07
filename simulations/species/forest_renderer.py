"""Forest testbed: spatial light map and paired crown response at equal scale."""
import math
import random
import pygame
from simulations.species.forest_ecology import light_at


def draw_forest(renderer, screen, sim):
    key = (screen.get_size(),sim.seed,sim.blueprint.fingerprint(),sim.forest_spacing,sim.forest_tolerance,sim.forest_view_style)
    cache = getattr(renderer,"_forest_surface",None)
    if cache and cache[0] == key:
        screen.blit(cache[1],(0,0))
        return
    if sim.forest_view_style == "isometric":
        _draw_forest_isometric(renderer, screen, sim)
    else:
        _draw_forest_light_map(renderer, screen, sim)
    renderer._forest_surface=(key,screen.copy())


def _draw_forest_light_map(renderer, screen, sim):
    from simulations.species.species_renderer import DiagnosticCamera, diagnostic_cell_bounds
    from simulations.species.species_simulation import SpeciesSimulation
    plan,cases = sim.get_forest_experiment()
    width,height = screen.get_size()
    screen.fill((15,22,19))
    font = pygame.font.SysFont("consolas",16)
    small = pygame.font.SysFont("consolas",13)
    title = pygame.font.SysFont("consolas",22)
    def label(text,x,y,color=(207,222,205),f=font):
        screen.blit(f.render(text,True,color),(x,y))
    label("Forest | "+sim.blueprint.display_name,18,34,f=title)
    source = "experiment override" if plan["tolerance_override"] else "ontology"
    label(f"Spacing: {plan['spacing']} ({plan['spacing_m']:.1f} m) | Shade tolerance: {plan['shade']['tolerance']} ({source})",18,66)
    label("S: change spacing    T: compare shade tolerance    V: isometric view    Fixed seed; established trees stay in place.",18,91,f=small)
    size = max(120,min(int(width*.46)-24,height-315))
    origin=(18,145)
    extent=plan["extent_m"]
    scale=size/(2*extent)
    def point(x,y):
        return round(origin[0]+size/2+x*scale),round(origin[1]+size/2-y*scale)
    # Sample the same light field used by recruitment. This is a map, not
    # a decorative green crown fill masquerading as measured shade.
    for px in range(0,size,6):
        for py in range(0,size,6):
            x=(px-size/2)/scale
            y=(size/2-py)/scale
            light=light_at(x,y,0.,plan["trees"])
            color=(round(22+light*58),round(35+light*66),round(28+light*34))
            pygame.draw.rect(screen,color,(origin[0]+px,origin[1]+py,6,6))
    for tree in plan["trees"]:
        p=point(tree["x"],tree["y"])
        pygame.draw.circle(screen,(115,145,110),p,round(tree["radius_m"]*scale),1)
        pygame.draw.circle(screen,(225,195,127) if tree["id"]==4 else (190,174,146),p,4)
        bias=tree["environment"]["growth_bias"]
        end=(round(p[0]+bias[0]*scale*tree["radius_m"]*2),round(p[1]-bias[1]*scale*tree["radius_m"]*2))
        if math.dist(p,end)>2:
            pygame.draw.line(screen,(240,206,112),p,end,2)
            pygame.draw.circle(screen,(240,206,112),end,2)
    for recruit in plan["recruits"]:
        p=point(recruit["x"],recruit["y"])
        if recruit["established"]:
            pygame.draw.circle(screen,(170,239,129),p,3)
        else:
            pygame.draw.line(screen,(199,130,124),(p[0]-2,p[1]-2),(p[0]+2,p[1]+2),1)
            pygame.draw.line(screen,(199,130,124),(p[0]-2,p[1]+2),(p[0]+2,p[1]-2),1)
    label("Ground light | lighter = more light",18,120)
    label(f"Seedlings established: {plan['established_count']}/36",18,origin[1]+size+13)
    label(f"Mean light at seedling sites: {plan['mean_ground_light']:.0%}",18,origin[1]+size+36)
    label("Green dots: established   Pink crosses: rejected",18,origin[1]+size+60,f=small)
    label("Circles: crown footprint   Gold lines: lightward bias",18,origin[1]+size+81,f=small)
    # Compare the centre tree to itself without neighbours, using shared
    # bounds and the same age, seed, organs and physical scale.
    actual=cases[4]
    control=SpeciesSimulation(species_entity=sim.species_entity,blueprint=sim.blueprint,seed=actual.seed)
    control.lod=1
    control.set_age(actual.age_days)
    bounds_a,bounds_b=diagnostic_cell_bounds(actual.render_snapshot),diagnostic_cell_bounds(control.render_snapshot)
    bounds=(min(bounds_a[0],bounds_b[0]),max(bounds_a[1],bounds_b[1]),min(bounds_a[2],bounds_b[2]),max(bounds_a[3],bounds_b[3]))
    x0=int(width*.48)
    cw=max(90,width-x0-20)
    ch=max(100,(height-315)//2)
    for i,(case,caption) in enumerate(((actual,"Centre tree in stand"),(control,"Same tree, no neighbours"))):
        panel=pygame.Surface((cw,ch))
        renderer._draw_individual(panel,case,camera=DiagnosticCamera(cw,ch,bounds))
        top=145+i*(ch+60)
        screen.blit(panel,(x0,top))
        label(caption,x0,top-24,f=small)
        label(f"Foliage cohorts: {len(case.render_snapshot.leaf_clusters)}",x0,top+ch+6,f=small)
    label("Shared scale | individual organ assets",x0,height-81,f=small)
    label("Light and establishment coefficients are experimental defaults.",18,height-57,f=small)
    label("No ontology values are changed by these comparisons.",18,height-35,f=small)


def _draw_forest_isometric(renderer, screen, sim):
    """Project the shared woodland plan with grounded, depth-sorted tree sprites."""
    from simulations.species.species_renderer import DiagnosticCamera, diagnostic_cell_bounds
    plan, cases = sim.get_forest_experiment()
    width, height = screen.get_size()
    screen.fill((15, 22, 19))
    font = pygame.font.SysFont("consolas", 16)
    small = pygame.font.SysFont("consolas", 13)
    title = pygame.font.SysFont("consolas", 22)

    def label(text, x, y, color=(207, 222, 205), f=font):
        screen.blit(f.render(text, True, color), (x, y))

    label("Forest | " + sim.blueprint.display_name + " (isometric)", 18, 34, f=title)
    label(f"Spacing: {plan['spacing']} ({plan['spacing_m']:.1f} m)", 18, 66)
    label("S: spacing    T: shade tolerance    V: light-map view | Seeded woodland with natural gaps", 18, 91, f=small)

    trees = plan["trees"]
    extent = max(1.0, float(plan["extent_m"]))
    max_height_m = max((float(t.get("height_m", 0.0) or 0.0) for t in trees), default=1.0)
    top, bottom_margin = 130, 60
    plot_w, plot_h = max(120.0, width - 36), max(120.0, height - top - bottom_margin)
    # Classic 2:1 isometric: a point at world (x, y) contributes to both
    # screen axes, so the plan's [-extent, extent] square traces a diamond
    # spanning 4*extent*half_w pixels wide by 2*extent*half_w pixels tall
    # (half_h = half_w/2). Trees stand on that diamond but grow straight up
    # off it (they aren't rotated into the projection), so the plot also
    # needs headroom above the diamond for the tallest canopy, at the same
    # pixels-per-metre scale used for its own sprite height below.
    half_w = max(0.1, min(plot_w / (4 * extent), plot_h / (2 * extent + max_height_m)))
    half_h = half_w * 0.5
    origin_x, origin_y = width / 2, top + (extent + max_height_m) * half_w

    def iso_point(x, y):
        return origin_x + (x - y) * half_w, origin_y + (x + y) * half_h

    corners = [iso_point(-extent, -extent), iso_point(extent, -extent),
               iso_point(extent, extent), iso_point(-extent, extent)]
    pygame.draw.polygon(screen, (26, 35, 26), corners)
    pygame.draw.polygon(screen, (52, 64, 50), corners, 1)

    rng = random.Random(sim.seed + 441)
    for _ in range(2200):
        x, y = rng.uniform(-extent, extent), rng.uniform(-extent, extent)
        px, py = iso_point(x, y)
        color = rng.choice(((39, 49, 31), (46, 55, 35), (32, 44, 30), (57, 55, 37)))
        pygame.draw.line(screen, color, (px, py), (px+2, py-1))

    # Paint every shadow before trees so foreground shade never covers trunks.
    for tree in trees:
        ax, ay = iso_point(tree["x"], tree["y"])
        radius = tree["radius_m"] * half_w
        for layer in range(5, 0, -1):
            r = radius * (.55 + layer*.12)
            pygame.draw.ellipse(screen, (20+layer, 29+layer, 21+layer),
                                (ax-r, ay-r*.4, r*2, max(2, r*.8)))

    # Painter's algorithm: no depth buffer, so trees must be drawn in
    # back-to-front order for nearer trees to correctly occlude farther ones.
    order = sorted(zip(trees, cases), key=lambda pair: pair[0]["x"] + pair[0]["y"])
    for tree, case in order:
        anchor_x, anchor_y = iso_point(tree["x"], tree["y"])
        bounds = diagnostic_cell_bounds(case.render_snapshot)
        model_w = max(0.2, bounds[1] - bounds[0])
        model_h = max(0.2, bounds[3] - bounds[2])
        # Same ground-plane pixels-per-metre as the iso projection itself,
        # so tree height reads at a consistent scale relative to spacing.
        panel_h = max(54, round(model_h * half_w) + 52)
        panel_w = max(26, round(model_w * half_w) + 24)
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        camera = DiagnosticCamera(panel_w, panel_h, bounds)
        camera.scale = half_w
        renderer._draw_individual(panel, case, camera=camera, clear=False, cache=True, draw_ground_line=False)
        root_x, root_y = camera.world_to_screen((0, 0))
        # Hide below-ground roots and anchor the actual root collar to terrain.
        panel.fill((0, 0, 0, 0), (0, root_y+1, panel_w, max(0, panel_h-root_y-1)))
        screen.blit(panel, (round(anchor_x-root_x), round(anchor_y-root_y)))

    label(f"{len(trees)} trees | {extent*2:.0f} x {extent*2:.0f} m woodland | Same positions and light response in both views.", 18, height - 35, f=small)
