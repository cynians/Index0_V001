"""Bounded two-level umbel display geometry, in metres.

Rays and florets are renderer samples, not additional ecological organs.
Counts and head flattening are qualitative visual fits.
"""
import math


def compound_umbel_profile(value):
    if not isinstance(value,dict) or value.get("unit") != "individual_flower":
        return None
    keys = ("length_m","width_m","flower_size_m","umbellet_diameter_m")
    if any(isinstance(value.get(k),bool) or not isinstance(value.get(k),(int,float))
           or not math.isfinite(value[k]) for k in keys):
        return None
    if not (.005 <= value["length_m"] <= .5 and .005 <= value["width_m"] <= .5
            and 0 < value["flower_size_m"] <= value["umbellet_diameter_m"]
            <= min(value["width_m"],value["length_m"])*.5):
        return None
    rays,flowers = value.get("ray_count"),value.get("flowers_per_umbellet")
    if any(isinstance(n,bool) or not isinstance(n,int) for n in (rays,flowers)):
        return None
    if not (2 <= rays <= 16 and 3 <= flowers <= 32):
        return None
    result = {k:float(value[k]) for k in keys}
    for key in ("axis_color","flower_color","bud_color"):
        color=value.get(key)
        if not (isinstance(color,list) and len(color)==3
                and all(isinstance(c,int) and not isinstance(c,bool) and 0<=c<=255 for c in color)):
            return None
        result[key]=list(color)
    result.update(form="compound_umbel",unit="individual_flower",ray_count=rays,
                  flowers_per_umbellet=flowers,version=1,
                  status=str(value.get("status") or "qualitative_display_recipe"))
    return result


def compound_umbel_layout(profile):
    """Two shared-socket ray levels, with all endpoints inside the envelope."""
    width,height=profile["width_m"],profile["length_m"]
    flower=profile["flower_size_m"]
    radius=profile["umbellet_diameter_m"]*.5
    centers_radius=max(0,width*.5-radius)
    for ray in range(profile["ray_count"]):
        theta=ray*math.tau/profile["ray_count"]+.3
        spread=centers_radius*(.78+.22*((ray*.61803398875)%1))
        x=math.cos(theta)*spread
        z=height*.68+math.sin(theta)*min(height*.16,spread*.35)
        margin=radius*.5+flower*.25
        z=max(margin,min(height-margin,z))
        florets=[]
        for index in range(profile["flowers_per_umbellet"]):
            angle=index*2.3999632297+theta
            r=max(0,radius-flower*.5)*math.sqrt((index+.5)/profile["flowers_per_umbellet"])
            florets.append((x+math.cos(angle)*r,z+math.sin(angle)*r*.5))
        yield {"fork":(0,height*.12),"center":(x,z),"flowers":florets}


def compound_umbel_surface(profile,pixels_per_meter,progress,flower_surface=None):
    import pygame
    ppm=min(1024/max(profile["width_m"],profile["length_m"]),max(1,pixels_per_meter))
    width,height=max(2,round(profile["width_m"]*ppm)),max(2,round(profile["length_m"]*ppm))
    canvas=pygame.Surface((width+6,height+6),pygame.SRCALPHA)
    anchor=((width+6)/2,height+3)
    point=lambda p:(round(anchor[0]+p[0]*ppm),round(anchor[1]-p[1]*ppm))
    glyph=None
    if flower_surface is not None:
        bounds=flower_surface.get_bounding_rect()
        if bounds.width and bounds.height:
            source=flower_surface.subsurface(bounds)
            size=max(1,round(profile["flower_size_m"]*ppm))
            glyph=pygame.transform.smoothscale(source,(size,size))
    for ray in compound_umbel_layout(profile):
        fork,center=point(ray["fork"]),point(ray["center"])
        pygame.draw.line(canvas,profile["axis_color"],point((0,0)),fork,1)
        pygame.draw.line(canvas,profile["axis_color"],fork,center,1)
        for index,floret in enumerate(ray["flowers"]):
            pos=point(floret)
            pygame.draw.line(canvas,profile["axis_color"],center,pos,1)
            # A neutral opening display; no researched opening sequence is
            # inferred from these static reference photographs.
            opening=(index*.61803398875)%1 < .25+.75*max(0,min(1,progress))
            if opening and glyph is not None:
                canvas.blit(glyph,glyph.get_rect(center=pos))
            else:
                color=profile["flower_color"] if opening else profile["bud_color"]
                pygame.draw.circle(canvas,color,pos,max(1,round(profile["flower_size_m"]*ppm*.35)))
    return canvas,anchor
