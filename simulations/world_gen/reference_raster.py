"""Bounded numeric GeoTIFF reading, including sparse ArcGIS NoData tiles.

Pillow handles ordinary rasters, but its image decoder rejects all-sparse TIFFs.
Keep their absent numeric samples unknown rather than manufacturing ocean bed.
"""
import io
import hashlib
from collections import OrderedDict
from pathlib import Path

from engine import asset_files
import numpy as np
from PIL import Image


def read_numeric_tiff(path_or_bytes):
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    image = Image.open(io.BytesIO(data))
    tags = image.tag_v2
    if tags.get(259) == 1 and tags.get(339) == (3,) and tags.get(258) == (32,) and 324 in tags:
        width, height = image.size
        if width*height > 40_000_000:
            raise ValueError("Numeric reference raster exceeds supported size")
        tw, th = tags[322], tags[323]
        result = np.full((height,width),np.nan,dtype=np.float32)
        offsets, counts = tags[324],tags[325]
        cols = (width+tw-1)//tw
        for index, (offset,count) in enumerate(zip(offsets,counts)):
            if offset == 0 and count == 0:
                continue
            if count != tw*th*4 or offset+count > len(data):
                raise ValueError("Truncated numeric reference tile")
            tile = np.frombuffer(data,dtype="<f4" if data[:2]==b"II" else ">f4",count=tw*th,offset=offset).reshape(th,tw)
            y,x = index//cols*th,index%cols*tw
            hh,ww = min(th,height-y),min(tw,width-x)
            result[y:y+hh,x:x+ww] = tile[:hh,:ww]
        nodata = tags.get(42113)
        if nodata is not None:
            try:
                result[result==float(nodata)] = np.nan
            except ValueError:
                pass
        result[~np.isfinite(result) | (result < -1000) | (result > 10000)] = np.nan
        return result
    return np.asarray(image)


class NativeRasterTiles:
    """Lazy, checksum-verified physical sampler; at most 12 decoded tiles retained."""
    def __init__(self, descriptor, bounds):
        self.descriptor = descriptor
        self.bounds = descriptor.get("bounds") or bounds
        self.root = Path(__file__).resolve().parents[2]
        self.tiles = {(t["row"], t["column"]): t for t in descriptor["tiles"]}
        self.cache = OrderedDict()

    def _tile(self, row, column):
        key = row, column
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        record = self.tiles[key]
        path = (self.root / record["path"]).resolve()
        if not path.is_relative_to(self.root / "assets/maps/reference"):
            raise ValueError("Reference raster path escapes reference assets")
        data = asset_files.read_bytes(path)
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Reference raster checksum mismatch")
        tile = read_numeric_tiff(data)
        if tile.shape != (record["height"], record["width"]):
            raise ValueError("Reference tile dimensions do not match descriptor")
        self.cache[key] = tile
        if len(self.cache) > 12:
            self.cache.popitem(last=False)
        return tile

    def sample_many(self, x, y):
        """Bilinear numeric sampling across tile seams, preserving NoData."""
        x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        b, d = self.bounds, self.descriptor
        gx = np.clip((x-b["min_x"])/(b["max_x"]-b["min_x"])*d["width"]-.5, 0, d["width"]-1)
        gy = np.clip((y-b["min_y"])/(b["max_y"]-b["min_y"])*d["height"]-.5, 0, d["height"]-1)
        ix, iy = np.floor(gx).astype(int), np.floor(gy).astype(int)
        fx, fy = gx-ix, gy-iy
        size = d["tile_size"]
        result = np.zeros(x.shape, dtype=float)
        unknown = np.zeros(x.shape, dtype=bool)
        for xx, yy, weight in ((ix,iy,(1-fx)*(1-fy)), (np.minimum(ix+1,d["width"]-1),iy,fx*(1-fy)),
                               (ix,np.minimum(iy+1,d["height"]-1),(1-fx)*fy),
                               (np.minimum(ix+1,d["width"]-1),np.minimum(iy+1,d["height"]-1),fx*fy)):
            for row, column in set(zip((yy//size).ravel(), (xx//size).ravel())):
                mask = (yy//size==row) & (xx//size==column) & (weight>0)
                if not np.any(mask):
                    continue
                values = self._tile(int(row),int(column))[yy[mask]%size,xx[mask]%size]
                unknown[mask] |= ~np.isfinite(values)
                result[mask] += np.nan_to_num(values, nan=0.)*weight[mask]
        return np.where(unknown, np.nan, result)

    def sample(self, x, y):
        # Scalar hot path avoids constructing vector masks on every rendered vertex.
        b, d = self.bounds, self.descriptor
        gx = max(0., min(d["width"]-1., (x-b["min_x"])/(b["max_x"]-b["min_x"])*d["width"]-.5))
        gy = max(0., min(d["height"]-1., (y-b["min_y"])/(b["max_y"]-b["min_y"])*d["height"]-.5))
        ix, iy = int(gx), int(gy)
        fx, fy, size = gx-ix, gy-iy, d["tile_size"]
        result = 0.
        for xx, yy, w in ((ix,iy,(1-fx)*(1-fy)),(min(ix+1,d["width"]-1),iy,fx*(1-fy)),
                         (ix,min(iy+1,d["height"]-1),(1-fx)*fy),(min(ix+1,d["width"]-1),min(iy+1,d["height"]-1),fx*fy)):
            if w <= 0:
                continue
            value = float(self._tile(yy//size,xx//size)[yy%size,xx%size])
            if not np.isfinite(value):
                return float("nan")
            result += value*w
        return result
