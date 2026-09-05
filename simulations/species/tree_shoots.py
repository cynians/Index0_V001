"""Woody crown with current shoots and node-based foliage cohorts."""
import math
import random


def grow_tree_shoots(sim, placements, maturity, lod, clusters, attachments, paths):
    g = sim.blueprint.growth
    h = float(g["max_height_m"]) * max(.025, maturity)
    def trait(name, default):
        value = g.get(name)
        return max(0., min(1., float(default if value is None else value)))
    openness, droop = trait("crown_openness",.5), trait("branch_droop",.3)
    density, twig_density = trait("leaf_cluster_density",.5), trait("fine_twig_density",.5)
    spacing = trait("leaf_spacing_bias",.5)
    distribution = g.get("leaf_distribution", "along_shoot")
    dimorphic = g.get("shoot_dimorphism") == "long_and_short_shoots"
    leaf_length = sim.blueprint.module("leaf").length_m
    root = sim._add(placements,"root",-1,0,0,-.08,0,1,0)

    def segment(parent, end, order, radius, curved=False):
        start = placements[parent][2:5]
        path = sim._curved_segment_path(start,end,bend=math.dist(start,end)*.06,
                                       direction=1 if parent%2 else -1) if curved else None
        return sim._add(placements,"stem_section" if order==0 else "branch_section",
                        parent,*end,0,radius,order+1,placement_paths=paths,path=path)

    def axis(parent,end,order,radius,steps=3):
        start = placements[parent][2:5]
        nodes=[]
        for i in range(1,steps+1):
            t=i/steps
            point=[start[j]+(end[j]-start[j])*t for j in range(3)]
            point[2]+=math.sin(t*math.pi)*math.dist(start,end)*.09
            parent=segment(parent,point,order,radius*(1-.55*t),curved=order<2)
            nodes.append(parent)
        return nodes

    trunk=axis(root,(h*.012,0,h*.92),0,max(.04,h*.014),12)
    if maturity<.04:
        return

    def leafy_shoot(parent,angle,length,short,identity):
        local=random.Random(sim.seed*1009+identity)
        start=placements[parent][2:5]
        count=4 if short else 7
        target=(start[0]+math.cos(angle)*length,start[1]+math.sin(angle)*length,
                start[2]+length*(.32-droop*.5))
        tangent=sim._normalise_vector(tuple(target[j]-start[j] for j in range(3)))
        side=sim._normalise_vector((-tangent[1],tangent[0],0))
        up=(-tangent[2]*side[1],tangent[2]*side[0],tangent[0]*side[1]-tangent[1]*side[0])
        shoot_parent=parent
        points,leaves,hosts=[],[],[]
        for i in range(count):
            f=(i+1)/count
            if distribution in {"terminal_cluster","branch_tips"} or short:
                f=.55+.45*f
            else:
                f=.12+.88*f**(1.7-spacing)
            point=[start[j]+(target[j]-start[j])*f for j in range(3)]
            shoot_parent=segment(shoot_parent,point,4 if short else 3,.0015*(1-.6*f))
            azimuth=i*math.radians(float(g.get("phyllotaxis_deg",137.5)))+.7
            forward=sim._normalise_vector(tuple(side[j]*math.cos(azimuth)+up[j]*math.sin(azimuth)+tangent[j]*.35 for j in range(3)))
            rotation=math.degrees(math.atan2(-(forward[0]+forward[1]*1.8),forward[2]))
            scale=local.uniform(.82,1.08)*(.65+.35*maturity)
            points.append(point)
            hosts.append(shoot_parent)
            if lod==0 or (lod==1 and i%2):
                continue
            leaf=sim._add(placements,"leaf",shoot_parent,*point,rotation,scale,6)
            sim._placement_orientation_hints[str(leaf)]=sim._orientation_frame(forward)
            leaves.append(leaf)
        midpoint=points[len(points)//2]
        estimated=count*(2+round(10*density))
        cluster_id=sim._add_leaf_cluster(clusters,hosts[0],*midpoint,estimated,
                                         estimated*leaf_length**2*.45,4 if short else 3,density)
        clusters[-1].update({"explicit_samples":True,"sample_placement_indices":leaves,
                             "shoot_type":"short" if short else "long"})
        for leaf in leaves:
            host=placements[leaf][1]
            attachments.append({"stem_placement_index":host,"leaf_placement_index":leaf,
                                "cluster_id":cluster_id,"socket":"leaf","position_m":list(placements[host][2:5]),
                                "shoot_type":"short" if short else "long"})

    branch_count=max(3,round((15-5*openness)*maturity))
    for b in range(branch_count):
        local=random.Random(sim.seed*65537+b)
        fraction=b/max(1,branch_count-1)
        host=trunk[min(10,2+round(fraction*8))]
        start=placements[host][2:5]
        angle=b*2.39996+local.uniform(-.2,.2)
        envelope=math.sqrt(max(.08,1-((fraction-.42)/.70)**2))
        reach=h*.25*envelope*(1.12-.4*openness)*local.uniform(.82,1.18)
        end=(start[0]+math.cos(angle)*reach,start[1]+math.sin(angle)*reach,
             min(h,start[2]+h*(.10+.06*fraction)-droop*h*.10))
        primary=axis(host,end,1,max(.012,h*.005),4)
        for s in range(2+round(3*twig_density)):
            host2=primary[min(3,1+s//2)]
            anchor=placements[host2][2:5]
            a2=angle+(-1 if s%2 else 1)*local.uniform(.45,1.1)
            reach2=reach*local.uniform(.30,.58)
            end2=(anchor[0]+math.cos(a2)*reach2,anchor[1]+math.sin(a2)*reach2,
                  min(h*1.03,anchor[2]+reach2*(local.uniform(.1,1.35)-droop*.3)))
            secondary=axis(host2,end2,2,max(.004,h*.0014),3)
            for t in range(3+round(3*twig_density)):
                host3=secondary[t%3]
                p=placements[host3][2:5]
                a3=a2+local.uniform(-1.3,1.3)
                reach3=min(1.5,h*.055)*local.uniform(.55,1.)
                p3=(p[0]+math.cos(a3)*reach3,p[1]+math.sin(a3)*reach3,
                    p[2]+reach3*local.uniform(-droop,.65))
                twig_nodes=axis(host3,p3,3,.003,3)
                identity=b*100000+s*1000+t*10
                leafy_shoot(twig_nodes[-1],a3,min(.65,leaf_length*5),False,identity)
                if dimorphic and distribution=="mixed_long_short_shoots":
                    for n,host4 in enumerate(twig_nodes[1:]):
                        leafy_shoot(host4,a3+(-1 if n else 1)*.85,leaf_length*1.6,True,identity+n+1)
