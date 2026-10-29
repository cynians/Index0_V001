"""Fine pendent axes beneath a supporting scaffold, independent of taxon.

One representative axis stands for a bounded group of parallel fine shoots.
Its canonical leaves/area are counted once; distant foliage is a group view,
never a physically enlarged individual leaf. Counts and curves are calibration.
"""
import math
import random

PENDANT_BRANCHLET_VERSION = 1


def grow_pendant_branchlet(sim, placements, parent, azimuth, length, identity,
                           maturity, lod, clusters, attachments, paths,
                           leaf_factor, flowering_factor, fruiting_factor, detail=False):
    g = sim.blueprint.growth
    rng = random.Random(sim.seed*1009+identity)
    start = placements[parent][2:5]
    droop = g['branch_droop']*max(.05, min(1., maturity))**.6
    droop *= rng.uniform(.4,1.1)
    bend_phase = rng.uniform(0.,math.tau)
    density = g['leaf_cluster_density']
    leaf = sim.blueprint.module('leaf')
    groups = max(1,round((2+round(4*density))*max(.04,min(1.,maturity))**.6))
    # A tiny juvenile axis cannot carry a mature shoot-group/node budget.
    # Scale topology rather than enlarging leaves or packing adult cohorts
    # into a seedling-sized crown.
    nodes = max(2,min(8+round(4*g['leaf_spacing_bias']),
                      round(length/max(.01,leaf.length_m*1.8))))
    leaf_area = leaf.length_m**2*.45
    leaves_per_node = max(1,min(3,int(g.get('leaves_per_node',1))))
    dimorphic = g.get('shoot_dimorphism') == 'long_and_short_shoots'
    sites = []; hosts = []; node_counts = []; axis_length = 0.
    previous = start
    for j in range(nodes):
        t = (j+1)/nodes
        reach = length*(.55*math.sin(t*math.pi*.5)+.12*t)
        a = azimuth+.22*math.sin(t*math.pi+bend_phase)
        point = (start[0]+math.cos(a)*reach,
                 start[1]+math.sin(a)*reach,
                 start[2]+length*(.12*t-1.35*droop*t**1.8))
        idx = sim._add(placements, 'branch_section', parent, *point, math.degrees(azimuth),
                       .003*(1-.75*t), 4, paths, [previous, point])
        sim._placement_orientation_hints[str(idx)] = {
            **sim._orientation_frame(tuple(point[a]-previous[a] for a in range(3))),
            'pendant_axis_role': 'branchlet', 'branchlet_identity': identity}
        attachments.append({'placement_index': idx, 'host_placement_index': parent,
                            'socket': 'branchlet_base', 'position_m': list(previous)})
        axis_length += math.dist(previous, point)
        parent = idx; previous = point
        # Alternate long-axis leaves and short-shoot sockets. The short
        # shoot's 2–3-leaf description is shared with the source mechanism;
        # the displayed number of represented parallel shoots is not a census.
        node_leaves = ((2+j%2) if j%3 == 0 and dimorphic else 1)*leaves_per_node
        if j%3 == 0 and dimorphic:
            a = azimuth+(-1 if j%2 else 1)*1.2
            spur_tip = (point[0]+math.cos(a)*.004, point[1]+math.sin(a)*.004, point[2]+.001)
            spur = sim._add(placements, 'branch_section', idx, *spur_tip, 0., .0007, 5, paths, [point, spur_tip])
            sim._placement_orientation_hints[str(spur)] = {'pendant_axis_role': 'short_shoot',
                'branchlet_identity': identity, **sim._orientation_frame(tuple(spur_tip[a]-point[a] for a in range(3)))}
            attachments.append({'placement_index': spur, 'host_placement_index': idx,
                                'socket': 'short_shoot_base', 'position_m': list(point)})
            axis_length += math.dist(point, spur_tip)
            point = spur_tip; idx = spur
        sites.append(list(point)); hosts.append(idx); node_counts.append(node_leaves)
    estimate = round(sum(node_counts)*groups*leaf_factor)
    area = estimate*leaf_area*.95**2
    midpoint = sites[len(sites)//2]
    cid = sim._add_leaf_cluster(clusters, hosts[0], *midpoint, estimate, area, 3,
                               density, allow_empty=True)
    cohort = clusters[-1]
    extent = max(leaf.length_m*1.2, math.sqrt(max(0., area)/max(1,len(sites))/math.pi))
    cohort.update(pendant_branchlet_sites_m=sites, represented_shoots=groups,
                  representative_node_leaf_counts=node_counts, identity=identity,
                  explicit_samples=bool(detail), sample_placement_indices=[],
                  phenology_factor=leaf_factor,
                  organ_bounds_m=[(min(p[a] for p in sites)-extent if side==0 else max(p[a] for p in sites)+extent)
                                  for a in range(3) for side in (0,1)])
    if detail and lod >= 1:
        for j,(point,host,count) in enumerate(zip(sites,hosts,node_counts)):
            for k in range(count):
                if (j*.61803398875+k*.37)%1 >= leaf_factor or (lod==1 and j%2):
                    continue
                a = azimuth+(1 if j%2 else -1)*1.2+k*2.4
                index = sim._add(placements, 'leaf', host, *point, math.degrees(a), .95, 6)
                sim._placement_orientation_hints[str(index)] = sim._orientation_frame((math.cos(a),math.sin(a),-.15))
                cohort['sample_placement_indices'].append(index)
                attachments.append({'stem_placement_index':host,'leaf_placement_index':index,
                    'socket':'leaf_base','position_m':point,'cluster_id':cid})
    # Only authored reproductive modules are displayed by this opt-in recipe.
    # Missing fruit morphology stays unresolved rather than becoming a berry.
    if lod >= 2 and g.get('reproductive_mode') in {'sexual','both','apomictic'}:
        for kind,factor in (('flower',flowering_factor),('fruit',fruiting_factor)):
            module = sim.blueprint.module(kind)
            if module and module.asset_ref and rng.random() < max(0.,factor)*.28:
                host = hosts[-1]; point = sites[-1]
                idx = sim._add(placements,kind,host,*point,0.,1.,6)
                sim._placement_orientation_hints[str(idx)] = {**sim._orientation_frame((0.,0.,-1.)),
                    'visual_unit':'catkin_display' if kind=='flower' else 'authored_fruiting_display'}
                attachments.append({'placement_index':idx,'host_placement_index':host,
                                    'socket':kind+'_base','position_m':point})
    return {'axis_length_m':axis_length, 'drop_m':start[2]-previous[2],
            'start_m':list(start),'tip_m':list(previous),'identity':identity,
            'represented_shoots':groups}


def draw_pendant_cohort(renderer, screen, sim, camera, cluster, sample_cap=None):
    """Production collective view follows actual curved shoot sockets."""
    import pygame
    sites = cluster['pendant_branchlet_sites_m']
    estimate = cluster['estimated_leaf_count']
    if not estimate or (sample_cap is not None and sample_cap <= 0):
        return
    ppm = renderer._projection_pixels_per_meter(camera)
    length = sim.blueprint.module('leaf').length_m
    per_site_area = cluster['leaf_area_m2']/max(1,len(sites))
    radius = min(length*3., math.sqrt(per_site_area/math.pi))
    for j,pos in enumerate(sites):
        point = renderer._path_screen(camera,pos)
        if point is None:
            continue
        if length*ppm/renderer._pixel_scale(camera) < 2.:
            # This footprint depicts a cohort of several normal-sized leaves.
            r = max(round(renderer._pixel_scale(camera)),round(radius*ppm))
            color = renderer._color('leaf',sim,int(cluster['identity'])+j)
            pygame.draw.ellipse(screen,color,(point[0]-r,point[1]-r,2*r,max(1,round(r*1.5))))
        else:
            count = cluster['representative_node_leaf_counts'][j]
            if sample_cap is not None:
                count = min(count,max(1,int(sample_cap)))
            for k in range(count):
                rotation = (-55 if j%2 else 55)+k*115
                if not renderer._draw_module_asset(screen,sim,camera,'leaf',point,rotation,.95):
                    renderer._draw_fallback_leaf(screen,sim,camera,sim.render_snapshot,
                        cluster['host_placement_index'],point,rotation,.95,rotation_only=True)
