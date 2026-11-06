"""
core.py - NFS Most Wanted / Carbon vehicle collision viewer and editor.

Copyright (c) 2026 GHOST-si
Released under the MIT License with the Commons Clause (see LICENSE).
Unofficial fan-made tool, not affiliated with Electronic Arts Inc.

Reads a vehicle "Collision" chunk (id 0x0003B901: per-vehicle body/part bounds,
not the world WCollisionPack) from a Binarius extraction or a Binary export
(gMpB container) and writes one self-contained, offline HTML page (three.js).
In the page, bounds and collision clouds can be inspected, edited, added,
deleted and exported back to .bin.

Field layout and precision follow CollisionGeometry::Bounds in the decompiled
game (Speed/Indep/Src/Physics/Bounds.h). The container layouts follow the
Binary/Binarius file formats.

Raw chunk layout (Binarius)
---------------------------
    id u32 (0x0003B901), size u32
    0x11111111 alignment words (the parser skips however many exist)
    collectionNameHash u32, NumberOfBounds i32, IsResolved i32, pad 4
    NumberOfBounds x CollisionBound (48 bytes)
    NumberOfClouds i32, pad 12
    per cloud: NumberOfVertices i32, pad 12, then float4 (x, y, z, w) vertices

Binary export layout (gMpB)
---------------------------
    'gMpB', size, version, collection hash, size, 'RAWW', flags, size, size
    NUL-terminated collection name
    NumberOfBounds i32, NumberOfClouds i32
    NumberOfBounds x CollisionBound (48 bytes)
    per cloud: NumberOfVertices i32, then float4 vertices
There is no chunk id, alignment word, IsResolved/padding or cloud padding, and
the bounds start at an offset that depends on the name length. The size words
are at +4, +16, +28 and +32. Bytes after the parsed data are preserved on export.

CollisionBound (48 bytes)
-------------------------
    0x00 Orientation x, y, z, w  int16 x4, raw / 32767 (unit quaternion)
    0x08 Position x, y, z        int16 x3, raw / 1000
    0x0E BoundType               uint16 flags (0x40 Box, 0x80 Sphere; Box wins if both are set)
    0x10 HalfDimension x, y, z   int16 x3, raw / 1000
    0x16 NumberOfChildren        uint8
    0x17 CollisionCloudIndex     int8, -1 = none (so at most 127 clouds)
    0x18 Pivot x, y, z           int16 x3, raw / 1000
    0x1E ChildrenIndex           int16
    0x20 Radius                  float32 (Most Wanted) or AttributeName hash (Carbon+)
    0x24 SurfaceName             uint32 hash
    0x28 NameHash                uint32 hash
    0x2C padding                 Collection* pointer in memory, unused on disk

Radius slot (0x20)
------------------
In Most Wanted this is `float fRadius` and equals max(HalfDimension) for every
bound checked. RigidBody::AddCollisionPrimitive builds a box from HalfDimension
if the Box flag is set, otherwise a sphere from Radius only. From Carbon on the
same slot holds an AttributeName hash. The rest of the chunk is identical, so the
format is detected once per file (_radius_is_float): the slot counts as a float
when it matches max(HalfDimension) for at least half of the bounds.
    "float": sphere HalfDimension is locked to mirror Radius, and export writes
             HalfDimension = (Radius, Radius, Radius) once Radius was edited.
    "hash":  the slot is never modified and HalfDimension is edited directly.

Precision
---------
Position, HalfDimension and Pivot are int16 / 1000 (COLLISION_GEOM_VECTOR_PRESSICION),
not / 1024 (used by tools written for Carbon and later).
Orientation uses int16 / 32767 (COLLISION_GEOM_QUAT_PRECISION). Values past +-32.767
(+-1 for quaternion components) cannot be stored; the page clamps them with a warning.

Why Radius is a float in Most Wanted
------------------------------------
- Bounds.h declares `float fRadius` at this offset.
- AddCollisionPrimitive takes `radius` as a parameter separate from `dim`.
- Read as float32 on the sample vehicles, it equals max(HalfDimension) within ~0.001 on
  every bound, sphere or not.
- Carbon turned the slot into an AttributeName hash, so tools written for Carbon+ treat it
  as a hash even for Most Wanted data.
Because the engine reads only Radius for a sphere, editing HalfDimension alone
would leave the exported size unchanged. Hence the "float" rules above.

Orientation
-----------
A unit quaternion decoded like _Q4c::Decompress, all four components at the same
scale (it is not an axis + angle pair). The game builds the matrix transposed
(VU0_quattom4) but multiplies row vectors (VU0_MATRIX4_vect3mult), so the effective
rotation is the standard R(q) (see quatToRotMat()). A convention that negates the
imaginary part mirrors the tilt of every bound with W != 0.

Pivot
-----
Pivot does not affect collision geometry: Collection::AddTo (Most Wanted: speed.exe
0x672050/0x66a890, Carbon: NFSC.exe, same flow around 0x6c1f30) never reads it. In both
games it only offsets render models:
    root bound    the car model is drawn at body - R * Pivot
                  (VehicleRenderConn: offset = (Pivot.z, -Pivot.x, Pivot.y))
    smackables    same relation, offset = (-Pivot.z, Pivot.x, -Pivot.y)
    named parts   the part model is placed by the inverse of [Orientation | Pivot] of the
                  bound found by name (VehicleFragmentConn); Position is not used
Only the root's Pivot matters for the car body. In the 911TURBO files of both games every
bound's Pivot equals its Position plus the root's Pivot.
The page offers two display frames (preview only, never exported):
    Body frame    the frame the collision shapes are built in
    Model frame   body frame + the root's Pivot, the frame of the render model; lines up a
                  reference .obj (default)
New bounds are created with Pivot (0, 0, 0).

Game placement
--------------
Shapes are placed the way Collection::AddTo builds them:
    - only the root's direct children (ChildrenIndex .. + NumberOfChildren) are added;
      deeper bounds are not (they can still serve as named parts);
    - the root is added only when no child yields a shape, at the origin with identity
      orientation (its own Position/Orientation are ignored);
    - a child's Position/Orientation are used as stored, in the body frame; the root's
      transform never reaches its children;
    - a child with the Internal flag (0x20) is skipped;
    - a bound yields a shape when (BoundType & 0x0E) and Box or Sphere are set (primitive),
      or MeshVsGround (0x10) is set and its cloud has vertices (mesh). PrimVsOwnParts
      (0x4000) is not part of this decision.
Legend tags:
    grey H     helper, no collision flags
    violet H   a bound the game does not add (the root while its children are, an Internal
               bound, a bound deeper than the root's children); hover for the reason
    blue dot   the root is the only shape
An unassigned bound carries only the unassigned tag.

Radius
------
Most Wanted reads the float at offset 0x20 as the sphere radius and as the render radius of
the root. Carbon ignores that slot: spheres use max(HalfDimension) and the root's render
radius is |HalfDimension|.

Parent/child hierarchy
----------------------
Bound i is a child of p when p.NumberOfChildren > 0 and
p.ChildrenIndex <= i < p.ChildrenIndex + p.NumberOfChildren (usually Bound_0 is
the parent; Bound 0 is always the root, even if a typed range happens to include index 0).
A child's Position/Orientation are relative to its parent's, composed up to but not
including the root (worldPoint()/localFromWorld()); the root is the body frame. A rotated
intermediate parent still rotates its children. Editing a bound refreshes all of its descendants, and a
sphere-center edit maps the requested world delta back through the ancestors'
rotation. Box corner edits stay in the bound's own frame and are unaffected. The
legend shows the hierarchy as a tree and rebuilds it from the current
ChildrenIndex/NumberOfChildren values. A bound outside the root's tree (no parent, or
caught in a parent loop by malformed ranges) is listed as an extra root, so no bound
ever disappears from the legend.

Unresolved items
----------------
Tools that append raw records, or manual edits of the advanced fields, can leave
entries the hierarchy and the cloud table do not account for. The page detects
four kinds (findUnresolved()), shows a banner above the legend, and offers a
resolve panel:
    child range         NumberOfChildren runs past the last bound (bounds removed by other
                        tools leave this behind) or ChildrenIndex is negative
    unassigned bound    no bound lists it as a child
    unassigned cloud    no record references it (empty clouds are the usual case)
    cloud reference     CollisionCloudIndex names a cloud another bound holds (zero-filled
                        records all carry index 0), a cloud nobody holds, one that does not
                        exist, or a different cloud than the bound's own
When several bounds claim a cloud at load, the lowest index keeps its points.
Per item: trim a child range to the bounds that exist or clear its children, attach a
bound (with its subtree) under a chosen bound, delete it, assign a cloud to a bound
without one, delete a cloud, clear or repair a reference. "Fix all recommended" trims
child ranges that can be trimmed, repairs or clears references, deletes empty clouds and
empty bounds, and attaches the other unassigned bounds to the root; clouds with vertices are left to the
user. Every action is one undo step.
CollisionCloudIndex is written exactly as typed. Which bound holds a cloud's points is
tracked separately (cloudSlot), so editing the field never moves or overwrites points.
Radius on boxes follows max(HalfDimension) automatically; once edited by hand it keeps the
typed value for good, independent of the "Edit advanced fields" checkbox (Undo restores
the automatic mode).

Collision clouds
----------------
Vertices are stored as world floats that are already composed with the owning
bound's own Position/Orientation only (the parent's frame), not with the whole
ancestor chain, and without Pivot.
- Pivot: decoding with Pivot shifts the vertex range by the root's Pivot; without it the
  range matches HalfDimension.
- Chain depth: undoing the whole ancestor chain pushes the range far outside HalfDimension;
  undoing only the owner's own transform matches.
The page keeps each vertex as a local offset of
its bound (localToParentFrame()/parentFrameToLocal()) and composes it
through the ancestors (the root excluded) only for display. A new cloud starts with one vertex at
(0, 0, 0).

Editing
-------
1. Pins: click a marker to pin it. A box corner shows local coordinates; editing
   one resizes the box along that axis, keeping the opposite face fixed in world
   space (HalfDimension and Position change together). A sphere center only
   translates the sphere.
   The two modes differ on purpose: dragging a corner moves Position to keep the
   opposite face fixed, while typing HalfDimension in the field panel changes only
   that field, so the box grows or shrinks symmetrically.
2. Field panel (click a bound's name): every field is a direct single-field
   assignment. The Box/Sphere flags are locked, as is PrimVsOwnParts on Most
   Wanted. BoundType 64 (Box only) usually has Position (0, 0, 0); a hint shows when
   it differs, but the value is saved as typed. The advanced fields (ChildrenIndex, NumberOfChildren,
   CollisionCloudIndex, Radius, hashes) are locked until "Edit advanced fields" is
   checked. SurfaceName is a dropdown fed by Engine/SurfaceNames.txt ("name = 0xHASH"
   per line, '#' starts a comment; path overridable via COLLISIONTOOL_SURFACE_NAMES)
   with a "Custom hash" entry; the stored value is always the raw hash.

Saving
------
"Export Collision" (or Ctrl+S) writes nothing until clicked. Without structural
edits, only the changed 48-byte records and cloud vertices are patched into a
copy of the original bytes. After adding or deleting bounds or clouds, the chunk
is re-serialised (header counts and size words, records, cloud section, trailing
bytes). A new bound is the last child of the selected bound; deleting a bound also
removes its descendants, and ChildrenIndex/NumberOfChildren/CollisionCloudIndex
are renumbered. The browser's native Save dialog is used where available;
otherwise a patched copy is downloaded.

Display orientation
-------------------
The game stores length along Z, height along Y and width along X. For display
only, axes are swapped (screen X = game Z, screen Y = game Y, screen Z = game X).
Stored and edited values are not affected.

Setup
-----
Needs three@0.128.0 in a "Dependencies" folder next to this script (or directly
next to it):
    Dependencies/three.min.js        https://unpkg.com/three@0.128.0/build/three.min.js
    Dependencies/OrbitControls.js    https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js
Optional, only for importing a reference .obj model:
    Dependencies/OBJLoader.js        https://raw.githubusercontent.com/mrdoob/three.js/r128/examples/js/loaders/OBJLoader.js

Usage
-----
    python core.py <collision.bin> [output.html] [reference.obj]
Without a .bin argument, a single *.bin in the current folder is used. Without an
output path, collision_bounds_3d.html is written next to the .bin. Only the
standard library is required.
"""

import sys
import glob
import os
import struct
import json
import base64
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
THREE_JS_FILENAME = "three.min.js"
ORBIT_JS_FILENAME = "OrbitControls.js"
# Optional: only needed for importing a reference .obj model.
OBJ_LOADER_FILENAME = "OBJLoader.js"

COLLISION_CHUNK_ID = 0x0003B901
ALIGN_MARK = 0x11111111
# "Binary" export container; same bound and cloud records as the raw chunk.
BINARY_MAGIC = 0x42704D67  # b"gMpB" as little-endian u32
KBOUNDS_SPHERE_FLAG = 0x80
KBOUNDS_BOX_FLAG = 0x40
KBOUNDS_PRIM_VS_OWN_PARTS = 0x4000
KBOUNDS_ACTIVE_MASK = 0x02 | 0x04 | 0x08 | 0x10

import colorsys


def color_for_index(i):
    """Distinct color per index (golden-angle hue step keeps consecutive hues far apart)."""
    hue = (i * 0.6180339887498949) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


BOUND_STRUCT = "<hhhh hhh H hhh Bb hhh h III i".replace(" ", "")
BOUND_SIZE = struct.calcsize(BOUND_STRUCT)
assert BOUND_SIZE == 48, BOUND_SIZE


def bound_is_sphere(bound_type):
    return bool(bound_type & KBOUNDS_SPHERE_FLAG) and not (bound_type & KBOUNDS_BOX_FLAG)


def bound_is_inactive(bound_type, radius_is_float):
    mask = KBOUNDS_ACTIVE_MASK if radius_is_float else KBOUNDS_ACTIVE_MASK | KBOUNDS_PRIM_VS_OWN_PARTS
    return not (bound_type & mask)


# ----------------------------------------------------------------------
# Binary parsing
# ----------------------------------------------------------------------

def _read_bounds(data, off, num_bounds):
    bounds = []
    for _ in range(num_bounds):
        b_off = off
        (ox, oy, oz, ow, px, py, pz, bound_type, hx, hy, hz,
         num_children, cloud_index, pvx, pvy, pvz, children_index,
         radius_raw, surf_hash, name_hash, _pad) = struct.unpack_from(BOUND_STRUCT, data, b_off)
        # radius_raw: uint32 at 0x20 = fRadius (float) in MW, AttributeName hash on Carbon+
        # (see _radius_is_float()). Kept raw for exact export, decoded as float here.
        radius = struct.unpack("<f", struct.pack("<I", radius_raw & 0xFFFFFFFF))[0]
        bounds.append({
            "offset": b_off,
            # unit quaternion (x, y, z, w), int16 / 32767
            "orientation": [ox / 32767.0, oy / 32767.0, oz / 32767.0, ow / 32767.0],
            "position": [px / 1000.0, py / 1000.0, pz / 1000.0],
            "boundType": bound_type,
            "halfDim": [hx / 1000.0, hy / 1000.0, hz / 1000.0],
            "numberOfChildren": num_children,
            "collisionCloudIndex": cloud_index,
            "pivot": [pvx / 1000.0, pvy / 1000.0, pvz / 1000.0],
            "childrenIndex": children_index,
            "radius": radius,
            "radiusRaw": radius_raw,  # original 4 bytes
            "surfaceNameHash": surf_hash,
            "nameHash": name_hash,
        })
        off += BOUND_SIZE
    return bounds, off


def _radius_is_float(bounds):
    # Carbon+ stores an AttributeName hash in the fRadius slot. A real fRadius equals
    # max(HalfDimension) within int16/1000 rounding; a hash practically never does.
    # Decided once per file.
    radius_is_float = True
    if bounds:
        matches = 0
        for b in bounds:
            max_half = max(abs(v) for v in b["halfDim"])
            tolerance = max(0.01, max_half * 0.02)
            if abs(b["radius"] - max_half) <= tolerance:
                matches += 1
        radius_is_float = matches >= (len(bounds) - matches)
    return radius_is_float


def parse_collision_bin(data):
    """Dispatches on the file's first 4 bytes: a raw game/Binarius chunk
    (0x0003B901) or a "Binary" tool export (b"gMpB")."""
    try:
        if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == BINARY_MAGIC:
            return parse_binary_export(data)
        return parse_binarius_chunk(data)
    except struct.error as e:
        # A count in the header promises more data than the file holds.
        raise ValueError(f"The file is truncated or corrupted: it ends before the data its header describes ({e}).") from e


def parse_binary_export(data):
    """"Binary"-tool export layout (different from the raw chunk!):
        0x00 'gMpB' magic | u32 size | u32 version | u32 collection hash
        u32 size | 'RAWW' | u32 flags | u32 size | u32 size
        NUL-terminated collection name (e.g. '911TURBO')
        i32 numBounds | i32 numClouds
        numBounds x 48-byte bound   (identical record to the chunk format)
        per cloud: i32 numVerts, then numVerts x 16-byte (x,y,z,w) floats
    Differences vs the raw chunk: no 0x0003B901 id, no 0x11111111 marks, no
    isResolved/padding, no alignment padding around clouds, and the bounds
    start at a variable offset (depends on the name length)."""
    if len(data) < 40:
        raise ValueError("File too small to be a Binary export.")
    _, _size, _version, collection_hash = struct.unpack_from("<IIII", data, 0)
    if data[20:24] != b"RAWW":
        raise ValueError("Binary export ('gMpB') found, but the 'RAWW' block is missing - unsupported variant.")
    name_start = 36
    name_end = data.find(b"\x00", name_start)
    if name_end < 0:
        raise ValueError("Binary export: collection name is not terminated.")
    off = name_end + 1
    num_bounds_offset = off
    num_bounds, num_clouds = struct.unpack_from("<ii", data, off); off += 8
    if not (0 <= num_bounds < 10000 and 0 <= num_clouds < 1000):
        raise ValueError(f"Binary export: implausible counts (bounds={num_bounds}, clouds={num_clouds}).")

    bounds, off = _read_bounds(data, off, num_bounds)
    clouds = []
    for _ in range(num_clouds):
        num_verts, = struct.unpack_from("<i", data, off); off += 4
        verts = []
        for _ in range(num_verts):
            vx, vy, vz, vw = struct.unpack_from("<ffff", data, off)
            verts.append({"offset": off, "pos": [vx, vy, vz, vw]})
            off += 16
        clouds.append(verts)

    return {
        "collection_hash": collection_hash,
        "num_bounds": num_bounds,
        "is_resolved": 0,
        "bounds": bounds,
        "clouds": clouds,
        "consumed_bytes": off,
        "declared_size": _size,
        "radius_is_float": _radius_is_float(bounds),
        "num_bounds_offset": num_bounds_offset,
    }


def parse_binarius_chunk(data):
    if len(data) < 8:
        raise ValueError("File too small to be a Collision chunk.")
    chunk_id, size = struct.unpack_from("<II", data, 0)
    if chunk_id != COLLISION_CHUNK_ID:
        raise ValueError(
            f"Not a Collision chunk: expected id {COLLISION_CHUNK_ID:#010x}, "
            f"got {chunk_id:#010x}. Make sure this is an extracted, "
            f"decompressed single Collision chunk, not the full GLOBALB.LZC."
        )

    off = 8
    while off + 4 <= len(data) and struct.unpack_from("<I", data, off)[0] == ALIGN_MARK:
        off += 4
    if off + 16 > len(data):
        raise ValueError("File too small to hold a Collision header after the alignment padding.")

    collection_hash, = struct.unpack_from("<I", data, off); off += 4
    num_bounds_offset = off
    num_bounds, = struct.unpack_from("<i", data, off); off += 4
    is_resolved, = struct.unpack_from("<i", data, off); off += 4
    off += 4  # padding
    if not (0 <= num_bounds < 10000) or off + num_bounds * BOUND_SIZE > len(data):
        raise ValueError(
            f"Implausible bound count ({num_bounds}) for a {len(data)}-byte file - "
            f"file may be corrupt or a different format."
        )

    bounds, off = _read_bounds(data, off, num_bounds)
    radius_is_float = _radius_is_float(bounds)

    clouds = []
    if off + 4 <= len(data):
        num_clouds, = struct.unpack_from("<i", data, off); off += 4
        off += 12
        for _ in range(num_clouds):
            num_verts, = struct.unpack_from("<i", data, off); off += 4
            off += 12
            verts = []
            for _ in range(num_verts):
                vx, vy, vz, vw = struct.unpack_from("<ffff", data, off)
                verts.append({"offset": off, "pos": [vx, vy, vz, vw]})
                off += 16
            clouds.append(verts)

    return {
        "collection_hash": collection_hash,
        "num_bounds": num_bounds,
        "is_resolved": is_resolved,
        "bounds": bounds,
        "clouds": clouds,
        "consumed_bytes": off,
        "declared_size": size,
        "radius_is_float": radius_is_float,
        "num_bounds_offset": num_bounds_offset,
    }


def build_bound_json(bound, index, color, clouds, radius_is_float):
    is_sphere = bound_is_sphere(bound["boundType"])
    cloud_idx = bound["collisionCloudIndex"]
    cloud_verts = None
    if 0 <= cloud_idx < len(clouds):
        # Cloud vertices are absolute points. Each carries its byte offset so the page can
        # convert to bound-local offsets and write edits back to the right 12 bytes
        # (x/y/z floats; w untouched).
        cloud_verts = [{"pos": v["pos"][:3], "byteOffset": v["offset"]} for v in clouds[cloud_idx]]

    return {
        "type": "sphere" if is_sphere else "box",
        "inactive": bound_is_inactive(bound["boundType"], radius_is_float),
        "name": f"Bound_{index}",
        "color": color,
        "byteOffset": bound["offset"],  # start of this 48-byte record in the embedded blob
        "halfDim": bound["halfDim"],
        "quat": bound["orientation"],  # [x, y, z, w] unit quaternion
        "pivot": bound["pivot"],
        "position": bound["position"],
        "radius": bound["radius"],  # fRadius (see _radius_is_float()); sphere geometry, read-only display for every type
        "boundType": bound["boundType"],
        "childrenIndex": bound["childrenIndex"],
        "numberOfChildren": bound["numberOfChildren"],
        "collisionCloudIndex": bound["collisionCloudIndex"],
        "radiusRaw": bound["radiusRaw"],
        "surfaceNameHash": bound["surfaceNameHash"],
        "nameHash": bound["nameHash"],
        "cloudVertices": cloud_verts,
    }


# ----------------------------------------------------------------------
# HTML / Three.js output
# ----------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Collision Bounds - 3D View</title>
<style>
  html, body {
    margin: 0; height: 100%; background: #11151c; overflow: hidden; font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    user-select: none; -webkit-user-select: none; -moz-user-select: none; -ms-user-select: none;
    -webkit-touch-callout: none;
  }
  #canvas-holder { position: absolute; inset: 0; }
  #legend {
    position: absolute; top: 14px; left: 14px; background: rgba(20, 24, 32, 0.75);
    backdrop-filter: blur(6px); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px; padding: 12px 16px; color: #e8e8e8; font-size: 13px;
    min-width: 190px; max-width: calc(100vw - 28px); box-sizing: border-box;
  }
  #legend-files {
    font-size: 10.5px; color: #7d8ba1; margin: -2px 0 8px 0; padding-bottom: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.08); word-break: break-word; line-height: 1.4;
  }
  #legend-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
  #legend-head h3 { margin: 0; font-size: 13px; font-weight: 600; color: #9fb3d1; letter-spacing: .03em; text-transform: uppercase;}
  /* Only the bound rows scroll; clamp() keeps a long list from pushing the mode panel off short windows. */
  #legend-rows { max-height: clamp(120px, 38vh, 400px); overflow-y: auto; padding-right: 4px; }
  #toggle-all-btn {
    background: #232a38; color: #cfd8e6; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px;
    font-size: 11px; padding: 3px 8px; cursor: pointer;
  }
  #toggle-all-btn:hover { background: #2d3648; }
  #mesh-toggle-all-btn {
    background: #232a38; color: #cfd8e6; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px;
    font-size: 11px; padding: 3px 8px; cursor: pointer; flex-shrink: 0;
  }
  #mesh-toggle-all-btn:hover { background: #2d3648; }
  /* Mesh list scrolls independently, like #legend-rows. */
  #mesh-panel-rows { max-height: clamp(120px, 38vh, 400px); overflow-y: auto; padding-right: 4px; margin-top: 6px; }
  .legend-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; cursor: pointer; user-select: none; }
  #legend-bound-tree .legend-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
  .legend-row.off { opacity: 0.35; }
  /* Tag: one SVG on a 16x16 grid, so the glyph stays centered at any zoom/DPR. */
  .legend-tag { flex-shrink: 0; display: block; width: 16px; height: 16px; line-height: 0; color: #9aa6ba; --tag-border: #4a5468; }
  .legend-tag svg { display: block; width: 16px; height: 16px; shape-rendering: geometricPrecision; }
  .legend-tag .tb { fill: none; stroke: var(--tag-border); stroke-width: 1; }
  .legend-tag.warn { color: #f0cf8a; --tag-border: #a67c1f; }
  .legend-tag.note { color: #b9a8ee; --tag-border: #6f5fb0; }
  .legend-tag.alone { color: #8fc7ee; --tag-border: #3f7ba6; }
  #unresolved-banner {
    display: none; align-items: center; gap: 8px; margin: -2px 0 8px; padding: 4px 6px 4px 8px;
    border-radius: 6px; font-size: 11px; color: #f0cf8a; background: rgba(217, 164, 65, 0.12);
    border: 1px solid rgba(217, 164, 65, 0.45);
  }
  #unresolved-banner.show { display: flex; }
  #unresolved-banner .ub-text { flex: 1; }
  #unresolved-banner .ub-open {
    background: transparent; color: #f0cf8a; border: 1px solid rgba(217, 164, 65, 0.6);
    border-radius: 4px; padding: 3px 9px; font: inherit; line-height: 1; cursor: pointer;
  }
  #unresolved-banner .ub-open:hover, #unresolved-banner .ub-open.open { background: rgba(217, 164, 65, 0.2); }
  .legend-row.editing { background: rgba(230, 180, 80, 0.14); box-shadow: inset 2px 0 0 #e6b450; border-radius: 3px; }
  .legend-row.editing .legend-name { color: #fff; }
  .legend-row.legend-tree-root, .legend-row.legend-tree-child { padding-left: 6px; }
  .legend-row.dirty .legend-name::after { content: " *"; color: #e6b450; }
  /* Bound tree: children nest under a guide line, each child row draws a tick (::before). */
  .legend-tree-root.legend-tree-parent > .legend-name { color: #cfe0ff; font-weight: 700; }
  .legend-tree-children {
    margin: 2px 0 4px 5px;
    padding-left: 14px;
    border-left: 1px solid rgba(159, 179, 209, 0.28);
  }
  .legend-row.legend-tree-child { position: relative; margin: 3px 0; }
  .legend-row.legend-tree-child::before {
    content: ""; position: absolute; left: -14px; top: 50%;
    width: 10px; height: 1px; background: rgba(159, 179, 209, 0.28);
  }
  .legend-row.legend-tree-child .legend-name { font-size: 12px; color: #aebcd4; }
  .legend-row.legend-tree-child.legend-tree-parent .legend-name { color: #cfe0ff; font-weight: 600; }
  .legend-tree-caret {
    width: 12px; text-align: center; flex-shrink: 0; font-size: 10px;
    color: #9fb3d1; cursor: pointer; user-select: none;
  }
  .legend-tree-caret:hover { color: #fff; }
  .legend-tree-badge {
    display: inline-flex; align-items: center; gap: 3px;
    margin-left: auto; font-size: 10px; color: #7d8ba1; background: rgba(255,255,255,0.06);
    border-radius: 8px; padding: 1px 4px 1px 6px; flex-shrink: 0; white-space: nowrap;
  }
  #mode-box {
    position: absolute; top: 14px; left: 14px; margin-top: 0;
  }
  #mode-toggle-wrap {
    position: absolute; left: 14px; background: rgba(20,24,32,0.75); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px; padding: 8px 12px; color: #cfd8e6; font-size: 12px; box-sizing: border-box;
    max-width: calc(100vw - 28px); overflow-y: auto;
    /* max-height is set from JS (positionModeToggle). */
  }
  #mode-toggle-wrap > label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  #model-rotate-panel { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); }
  #mode-toggle-wrap .mr-title { color: #9fb3d1; font-size: 10px; margin-bottom: 3px; }
  #model-rotate-panel .mr-axis-readout { font-weight: 700; margin-left: 3px; }
  #model-rotate-panel .mr-axis-readout-x { color: #ff5555; }
  #model-rotate-panel .mr-axis-readout-y { color: #55e07a; }
  #model-rotate-panel .mr-axis-readout-z { color: #5599ff; }
  #model-rotate-panel .mr-checkbox-row {
    display: flex; align-items: center; gap: 8px; font-size: 12px; color: #cfd8e6;
    cursor: pointer; margin: 0 0 12px 0;
  }
  #model-rotate-panel .mr-checkbox-row input { margin: 0; }
  #model-rotate-panel .mr-row { display: flex; gap: 5px; margin: 4px 0; }
  #model-rotate-panel button {
    flex: 1; background: #232a38; color: #cfd8e6; border: 1px solid rgba(255,255,255,0.12); border-radius: 4px;
    font-size: 12.1px; padding: 4px 6px; cursor: pointer;
  }
  #model-rotate-panel button:hover { background: #2d3648; }
  #model-rotate-panel .mr-axis-btn-x { color: #ff5555; }
  #model-rotate-panel .mr-axis-btn-y { color: #55e07a; }
  #model-rotate-panel .mr-axis-btn-z { color: #5599ff; }
  #model-rotate-panel .mr-axis-btn-x.mr-active { background: #ff5555; color: #11151c; font-weight: 700; }
  #model-rotate-panel .mr-axis-btn-y.mr-active { background: #55e07a; color: #11151c; font-weight: 700; }
  #model-rotate-panel .mr-axis-btn-z.mr-active { background: #5599ff; color: #11151c; font-weight: 700; }
  #hint {
    position: absolute; bottom: 14px; left: 14px; color: #7d8ba1; font-size: 12px;
    background: rgba(20, 24, 32, 0.6); padding: 6px 10px; border-radius: 8px;
    max-width: min(460px, calc(100vw - 28px)); box-sizing: border-box;
  }
  #axis-gizmo {
    position: absolute; bottom: 14px; right: 14px; width: 92px; height: 92px;
    background: rgba(20, 24, 32, 0.55); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 50%; cursor: pointer;
  }
  #axis-gizmo canvas { width: 100%; height: 100%; display: block; }
  #tooltip {
    position: absolute; pointer-events: none; display: none; z-index: 50;
    background: rgba(15, 18, 24, 0.92); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px; padding: 8px 12px; color: #f0f0f0; font-size: 12px;
    line-height: 1.5; white-space: pre; box-shadow: 0 4px 14px rgba(0,0,0,0.4);
  }
  #tooltip .t-name { color: #9fb3d1; font-weight: 600; margin-bottom: 2px; display: block; }

  #save-bar {
    position: absolute; top: 14px; right: 14px; display: flex; flex-direction: column;
    align-items: flex-end; gap: 6px; max-width: calc(100vw - 28px); box-sizing: border-box;
  }
  #save-bar button {
    background: #2a3140; color: #e8e8e8; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer;
  }
  #save-bar button:hover { background: #333c4f; }
  #save-bar button:disabled, #save-btn.idle { opacity: 0.4; cursor: default; }
  #save-btn:not(.idle) { background: #2f6f4f; border-color: rgba(255,255,255,0.2); }
  #save-btn:not(.idle):hover { background: #37845c; }
  #save-status { color: #7d8ba1; font-size: 11px; background: rgba(20,24,32,0.6); padding: 4px 8px; border-radius: 6px; max-width: 260px; text-align: right; }

  #model-toast {
    position: absolute; left: 50%; bottom: 24px; transform: translateX(-50%);
    z-index: 60; max-width: 360px; padding: 8px 12px; border-radius: 8px;
    font-size: 12px; line-height: 1.45; white-space: pre-line; box-shadow: 0 4px 14px rgba(0,0,0,0.45);
    display: none; align-items: center; gap: 10px;
  }
  #model-toast.show { display: flex; }
  #model-toast.info { background: rgba(38,58,48,0.95); border: 1px solid rgba(120,220,160,0.3); color: #d6f5e3; }
  #model-toast.warn { background: rgba(58,44,28,0.95); border: 1px solid rgba(230,170,90,0.35); color: #ffe3bd; }
  #model-toast .mt-close { cursor: pointer; color: inherit; opacity: 0.7; flex-shrink: 0; }
  #model-toast .mt-close:hover { opacity: 1; }

  .pin-panel {
    position: absolute; z-index: 40; background: rgba(15, 18, 24, 0.95);
    border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 8px 10px;
    color: #f0f0f0; font-size: 12px; box-shadow: 0 4px 14px rgba(0,0,0,0.45);
    transform: translate(14px, 14px); min-width: 190px;
    max-width: calc(100vw - 28px); box-sizing: border-box;
  }
  .pin-panel .p-name { color: #9fb3d1; font-weight: 600; display: flex; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
  .pin-panel .p-close { cursor: pointer; color: #7d8ba1; }
  .pin-panel .p-close:hover { color: #fff; }
  .pin-panel .p-section-label { color: #6c7688; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; margin: 6px 0 2px; }
  .pin-panel .p-note { color: #7d8ba1; font-size: 10.5px; line-height: 1.4; margin: -1px 0 6px; }
  .pin-panel .p-row { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
  .pin-panel .p-row label { width: 12px; color: #9fb3d1; }
  .pin-panel .p-row input {
    width: 102px; background: #1a1f29; border: 1px solid rgba(255,255,255,0.15);
    color: #f0f0f0; border-radius: 5px; padding: 3px 14px 3px 6px; font-size: 12px;
  }
  .pin-panel .p-row .p-readonly {
    width: 110px; color: #9aa4b5; padding: 3px 0; font-family: monospace; font-size: 11.5px;
  }

  #info-panel {
    position: absolute; top: 14px; right: 14px; z-index: 60; width: 300px;
    max-width: calc(100vw - 28px); max-height: calc(100vh - 28px); overflow-y: auto;
    /* Reserve the scrollbar width so rows do not shift when it appears (Chromium/Firefox). */
    scrollbar-gutter: stable;
    background: rgba(13, 16, 22, 0.97); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px; padding: 14px 16px; color: #f0f0f0; font-size: 12.5px;
    box-shadow: 0 8px 28px rgba(0,0,0,0.5); box-sizing: border-box; display: none;
  }
  #info-panel .i-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  #info-panel .i-title span:first-child { font-weight: 700; font-size: 14px; }
  #info-panel .i-close { cursor: pointer; color: #7d8ba1; font-size: 16px; }
  #info-panel .i-close:hover { color: #fff; }
  #info-panel .i-note { color: #7d8ba1; font-size: 11px; margin-bottom: 10px; line-height: 1.5; }
  #info-panel .i-note:empty { display: none; margin-bottom: 0; }
  /* Per-field warning line (setFieldWarn()); collapsed by :empty. */
  #info-panel .i-note.i-field-warn { margin-bottom: 4px; line-height: 1.3; }
  #info-panel .i-section { color: #6c7688; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; margin: 12px 0 4px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 8px; }
  #info-panel .i-section:first-of-type { border-top: none; margin-top: 4px; }
  #info-panel .i-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 3px 0; }
  #info-panel .i-row label { color: #9fb3d1; flex-shrink: 0; }
  #info-panel .i-row input {
    width: 102px; background: #1a1f29; border: 1px solid rgba(255,255,255,0.15);
    color: #f0f0f0; border-radius: 5px; padding: 3px 14px 3px 6px; font-size: 12px; text-align: right;
  }
  #info-panel .i-row .i-readonly {
    color: #9aa4b5; font-family: monospace; font-size: 11.5px; text-align: right; word-break: break-word; max-width: 180px;
  }
  /* Advanced fields are dimmed until unlocked (.unlocked is set by the checkbox handler). */
  #info-panel .i-row-advanced { opacity: 0.4; transition: opacity .15s ease; }
  #info-panel .i-row-advanced.unlocked { opacity: 1; }
  .legend-more {
    flex-shrink: 0; margin-left: auto; padding: 0 5px; border-radius: 4px; color: #7d8ba1;
    font-size: 14px; line-height: 16px; visibility: hidden; cursor: pointer;
  }
  .legend-tree-badge ~ .legend-more { margin-left: 0; }
  .legend-row:hover .legend-more, .legend-row.menu-target .legend-more, .legend-row.editing .legend-more { visibility: visible; }
  .legend-more:hover { color: #fff; background: rgba(255,255,255,0.12); }
  .legend-row.menu-target { outline: 1px solid rgba(159, 179, 209, 0.6); border-radius: 3px; }
  #structure-menu, #cloud-panel, #resolve-panel {
    display: none; position: fixed; box-sizing: border-box; background: rgba(20, 24, 32, 0.96);
    backdrop-filter: blur(6px); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.45); color: #e8e8e8; font-size: 12px;
  }
  #structure-menu { z-index: 70; min-width: 190px; max-width: 250px; padding: 6px; }
  #structure-menu.open { display: block; }
  #structure-menu .sm-title { padding: 2px 6px 6px; color: #7d8ba1; font-size: 11px; letter-spacing: 0.04em; }
  #structure-menu .sm-item {
    display: block; width: 100%; text-align: left; background: transparent; border: 0; color: #e8e8e8;
    padding: 6px 8px; border-radius: 6px; font: inherit; cursor: pointer;
  }
  #structure-menu .sm-item:hover:not(:disabled) { background: rgba(255,255,255,0.08); }
  #structure-menu .sm-item.danger { color: #ffb4b4; }
  #structure-menu .sm-item.danger:hover:not(:disabled) { background: rgba(217, 108, 108, 0.18); }
  #structure-menu .sm-item:disabled { opacity: 0.4; cursor: default; }
  #structure-menu .sm-sep { height: 1px; margin: 4px 2px; background: rgba(255,255,255,0.1); }
  #structure-menu .sm-text { padding: 2px 8px 8px; color: #c3d0e6; line-height: 1.4; }
  #structure-menu .sm-row { display: flex; gap: 6px; }
  #structure-menu .sm-row .sm-item { text-align: center; border: 1px solid rgba(255,255,255,0.15); }
  #cloud-panel { z-index: 61; width: 360px; max-width: calc(100vw - 16px); padding: 12px 14px; flex-direction: column; }
  #cloud-panel.open { display: flex; }
  #cloud-panel .c-title { display: flex; justify-content: space-between; align-items: center; font-size: 15px; font-weight: 700; margin-bottom: 6px; }
  #cloud-panel .c-close { cursor: pointer; color: #7d8ba1; }
  #cloud-panel .c-close:hover { color: #fff; }
  #cloud-panel .c-note { color: #9fb3d1; font-size: 11px; margin-bottom: 8px; }
  #cloud-panel .c-actions { display: flex; gap: 6px; margin-bottom: 8px; }
  #cloud-panel .c-btn {
    flex: 1; background: #1a1f29; color: #e8e8e8; border: 1px solid rgba(255,255,255,0.15);
    border-radius: 5px; padding: 4px 6px; font: inherit; cursor: pointer;
  }
  #cloud-panel .c-btn:hover { border-color: rgba(159, 179, 209, 0.7); }
  #cloud-panel .c-btn.danger:hover, #cloud-panel .c-btn.armed { border-color: #d96c6c; color: #ffb4b4; }
  #cloud-panel .c-head, #cloud-panel .c-row {
    display: grid; grid-template-columns: 28px repeat(3, minmax(0, 1fr)) 22px; gap: 6px; align-items: center;
  }
  #cloud-panel .c-head { color: #7d8ba1; font-size: 11px; padding-bottom: 4px; }
  #cloud-panel .c-rows { overflow-y: auto; min-height: 0; padding-right: 2px; }
  #cloud-panel .c-row { margin: 3px 0; }
  #cloud-panel .c-idx { color: #7d8ba1; font-size: 11px; }
  #cloud-panel input {
    width: 100%; box-sizing: border-box; background: #1a1f29; border: 1px solid rgba(255,255,255,0.15);
    color: #f0f0f0; border-radius: 5px; padding: 3px 6px; font-size: 12px; text-align: right; font-family: inherit;
  }
  #cloud-panel .c-del { background: transparent; border: 0; color: #7d8ba1; font-size: 15px; line-height: 1; cursor: pointer; }
  #cloud-panel .c-del:hover { color: #ffb4b4; }
  #resolve-panel { z-index: 62; width: 390px; max-width: calc(100vw - 16px); padding: 12px 14px; flex-direction: column; }
  #resolve-panel.open { display: flex; }
  #resolve-panel .r-title { display: flex; justify-content: space-between; align-items: center; font-size: 15px; font-weight: 700; margin-bottom: 6px; }
  #resolve-panel .r-close { cursor: pointer; color: #7d8ba1; }
  #resolve-panel .r-close:hover { color: #fff; }
  #resolve-panel .r-note { color: #9fb3d1; font-size: 11px; line-height: 1.4; margin-bottom: 8px; }
  #resolve-panel .r-body { overflow-y: auto; min-height: 0; padding-right: 2px; }
  #resolve-panel .r-sec { margin: 10px 0 4px; color: #7d8ba1; font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; }
  #resolve-panel .r-item { padding: 6px 8px; margin: 4px 0; border-radius: 6px; background: rgba(255,255,255,0.04); }
  #resolve-panel .r-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  #resolve-panel .r-line + .r-line { margin-top: 5px; }
  #resolve-panel .r-name { font-weight: 600; }
  #resolve-panel .r-meta { color: #9fb3d1; font-size: 11px; }
  #resolve-panel .r-coords { color: #7d8ba1; font-size: 10px; font-family: monospace; word-break: break-all; margin: 3px 0 5px; }
  #resolve-panel .r-btn, #resolve-panel .r-sel {
    background: #1a1f29; color: #e8e8e8; border: 1px solid rgba(255,255,255,0.15);
    border-radius: 5px; padding: 3px 8px; font: inherit; font-size: 12px; cursor: pointer;
  }
  #resolve-panel .r-sel { flex: 1; min-width: 0; }
  #resolve-panel .r-btn { line-height: 1; }
  #resolve-panel .r-btn:hover:not(:disabled) { border-color: rgba(159, 179, 209, 0.7); }
  #resolve-panel .r-btn:disabled, #resolve-panel .r-sel:disabled { opacity: 0.4; cursor: default; }
  #resolve-panel .r-btn.danger:hover:not(:disabled), #resolve-panel .r-btn.armed { border-color: #d96c6c; color: #ffb4b4; }
  #resolve-panel .r-fix { width: 100%; margin-bottom: 4px; padding: 6px 8px; border-color: rgba(217, 164, 65, 0.6); color: #f0cf8a; }
  /* Trim boxed labels to cap height/baseline where text-box is supported, so text is centered
     whatever the font metrics. Padding accounts for the trimmed box. */
  @supports (text-box: trim-both cap alphabetic) {
    .legend-tree-badge .lb-text, #toggle-all-btn, #unresolved-banner .ub-text,
    #unresolved-banner .ub-open, #resolve-panel .r-btn { text-box: trim-both cap alphabetic; }
    #toggle-all-btn { padding: 5px 9px; }
    #unresolved-banner .ub-open { padding: 5px 10px; }
    #resolve-panel .r-btn { padding: 5.5px 10px; }
    #resolve-panel .r-fix { padding: 8.5px 8px; }
  }
  .pin-panel .p-del {
    margin-top: 8px; width: 100%; background: #1a1f29; color: #e8e8e8; border: 1px solid rgba(255,255,255,0.15);
    border-radius: 5px; padding: 4px 6px; font-size: 12px; font-family: inherit; cursor: pointer;
  }
  .pin-panel .p-del:hover { border-color: #d96c6c; color: #ffb4b4; }
  #info-panel .i-bt-box {
    width: 102px; box-sizing: content-box; background: #1a1f29; border: 1px solid rgba(255,255,255,0.15);
    color: #f0f0f0; border-radius: 5px; padding: 3px 14px 3px 6px; font-size: 12px; font-family: inherit;
    display: flex; align-items: center; justify-content: flex-end; gap: 6px;
  }
  #info-panel .i-bt-box:not(:disabled) { cursor: pointer; }
  #info-panel .i-bt-box:not(:disabled):hover, #info-panel .i-bt-box.open { border-color: rgba(159, 179, 209, 0.7); }
  #info-panel .i-bt-box:focus-visible { outline: 1px solid rgba(159, 179, 209, 0.6); outline-offset: 1px; }
  #info-panel .i-bt-caret { font-size: 10px; color: #7d8ba1; transition: transform .15s ease; }
  #info-panel .i-bt-box.open .i-bt-caret { transform: rotate(180deg); }
  #info-panel .i-bt-names { margin: 0 0 4px; color: #7d8ba1; font-size: 11px; word-break: break-word; }
  #boundtype-menu {
    display: none; position: fixed; z-index: 70; width: 210px; max-width: calc(100vw - 16px); box-sizing: border-box;
    padding: 10px 12px; background: rgba(20, 24, 32, 0.96); backdrop-filter: blur(6px);
    border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.45);
    color: #c3d0e6; font-size: 12px;
  }
  #boundtype-menu.open { display: block; }
  #boundtype-menu .bt-flags { display: flex; flex-direction: column; gap: 7px; }
  #boundtype-menu .bt-flags label { display: flex; align-items: center; gap: 6px; white-space: nowrap; cursor: pointer; }
  #boundtype-menu .bt-flags label.locked { opacity: 0.45; cursor: not-allowed; }
  #boundtype-menu .bt-flags input { margin: 0; }
  #boundtype-menu .bt-flags input:disabled { cursor: not-allowed; }
  #boundtype-menu .bt-warn { margin-top: 8px; color: #e6b450; font-size: 11px; }
  #boundtype-menu .bt-warn:empty { display: none; }
  input[type=number] { -moz-appearance: textfield; appearance: textfield; }
  input[type=number]::-webkit-inner-spin-button, input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
  #info-panel .i-bt-box .i-bt-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #info-panel .i-bt-box .i-bt-caret { flex-shrink: 0; }
  #surface-menu {
    display: none; flex-direction: column; position: fixed; z-index: 70; width: 230px; max-width: calc(100vw - 16px);
    max-height: min(360px, calc(100vh - 16px)); box-sizing: border-box; padding: 8px;
    background: rgba(20, 24, 32, 0.96); backdrop-filter: blur(6px); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.45); color: #c3d0e6; font-size: 12px;
  }
  #surface-menu.open { display: flex; }
  #surface-menu .sf-search, #surface-menu .sf-custom-input {
    width: 100%; box-sizing: border-box; background: #1a1f29; border: 1px solid rgba(255,255,255,0.15);
    color: #f0f0f0; border-radius: 5px; padding: 4px 6px; font-size: 12px; font-family: inherit;
  }
  #surface-menu .sf-search { margin-bottom: 6px; flex-shrink: 0; }
  #surface-menu .sf-list { position: relative; flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
  #surface-menu .sf-item {
    display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; box-sizing: border-box;
    background: transparent; border: 0; border-radius: 5px; padding: 5px 8px; color: #e8e8e8; font-size: 12px;
    font-family: inherit; text-align: left; cursor: pointer;
  }
  #surface-menu .sf-item:hover { background: rgba(255,255,255,0.08); }
  #surface-menu .sf-item.active { background: rgba(159, 179, 209, 0.18); }
  #surface-menu .sf-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #surface-menu .sf-hex { flex-shrink: 0; color: #7d8ba1; font-family: monospace; font-size: 11px; }
  #surface-menu .sf-empty { padding: 6px 8px; color: #7d8ba1; font-size: 11px; line-height: 1.4; }
  #surface-menu .sf-sep { flex-shrink: 0; height: 1px; margin: 6px 2px; background: rgba(255,255,255,0.1); }
  #surface-menu .sf-custom { flex-shrink: 0; }
  #surface-menu .sf-custom-row { display: flex; flex-shrink: 0; gap: 6px; margin-top: 6px; }
  #surface-menu .sf-custom-input { flex: 1 1 auto; min-width: 0; font-family: monospace; }
  #surface-menu .sf-set {
    flex-shrink: 0; background: #1a1f29; color: #e8e8e8; border: 1px solid rgba(255,255,255,0.15);
    border-radius: 5px; padding: 4px 10px; font-size: 12px; font-family: inherit; cursor: pointer;
  }
  #surface-menu .sf-set:hover { border-color: rgba(159, 179, 209, 0.7); }
  #surface-menu .sf-warn { flex-shrink: 0; margin-top: 6px; color: #e6b450; font-size: 11px; line-height: 1.3; }
  #surface-menu .sf-warn:empty { display: none; }

  /* Compact padding and gizmo on small windows. */
  @media (max-width: 480px) {
    #legend, #mode-toggle-wrap, #info-panel, .pin-panel { padding: 8px 10px; }
    #legend { min-width: 150px; }
    #axis-gizmo { width: 72px; height: 72px; }
  }
</style>
</head>
<body>
<div id="canvas-holder"></div>
<div id="legend"><div id="legend-files"></div><div id="legend-head"><h3>Collision Bounds</h3><button id="toggle-all-btn" title="Show/hide every bound at once">Hide all</button></div><div id="unresolved-banner"><span class="ub-text"></span><button type="button" class="ub-open">Resolve</button></div><div id="legend-rows"></div></div>
<div id="mode-toggle-wrap" style="top: calc(14px + var(--legend-h, 160px));">
  <div class="mr-title" style="margin-bottom:6px;">Pivot</div>
  <label style="display:flex; align-items:flex-start; gap:8px; cursor:pointer; margin-bottom:6px;" title="The frame the game builds collision in. Pivot is not applied.">
    <input type="radio" name="pivot-mode" id="mode-radio-off" style="margin-top:2px; flex-shrink:0;" />
    <span>Body frame<br>(as the game builds collision)</span>
  </label>
  <label style="display:flex; align-items:flex-start; gap:8px; cursor:pointer; margin-bottom:6px;" title="Every bound shifted by the root Pivot: the frame of the render model. Use it to line the bounds up with a reference model.">
    <input type="radio" name="pivot-mode" id="mode-radio-model" style="margin-top:2px; flex-shrink:0;" checked />
    <span>Model frame<br>(+ root Pivot, as the game renders)</span>
  </label>
  <div id="model-rotate-panel" style="display:none;"></div>
</div>
<div id="hint">Drag: rotate &middot; Scroll: zoom &middot; Click a dot: pin/resize &middot; Click a name: edit fields</div>
<div id="axis-gizmo" title="Click an axis to snap the view - like Blender"></div>
<div id="tooltip"></div>
<div id="save-bar">
  <button id="save-btn" class="idle" aria-disabled="true">Export Collision</button>
  <div id="save-status">No unsaved changes.</div>
</div>
<div id="pins-holder"></div>
<div id="info-panel"></div>
<div id="boundtype-menu"></div>
<div id="surface-menu"></div>
<div id="structure-menu"></div>
<div id="cloud-panel"></div>
<div id="resolve-panel"></div>
<div id="model-toast"><span id="model-toast-text"></span><span class="mt-close" id="model-toast-close">&#10005;</span></div>

<script>
__THREE_JS_CODE__
</script>
<script>
__ORBIT_CONTROLS_CODE__
</script>
<script>
__MODEL_LOADER_CODE__
</script>
<script>
const BOUNDS = __DATA_JSON__;
const ORIGINAL_BIN_B64 = "__ORIGINAL_BIN_B64__";
const ORIGINAL_FILENAME = "__ORIGINAL_FILENAME__";
const ORIGINAL_NUM_BOUNDS = __ORIGINAL_NUM_BOUNDS__;
const CLOUD_META = __CLOUD_META_JSON__;  // {count, consumed, orphans (clouds without an owner)}
const NUM_BOUNDS_OFFSET = __NUM_BOUNDS_OFFSET__; // 20 in a raw chunk, variable in a "Binary" export
const MODEL_B64 = "__MODEL_B64__";
const MODEL_FILENAME = "__MODEL_FILENAME__";
const MODEL_EXT = "__MODEL_EXT__";
const MODEL_LIB_STATUS = __MODEL_LIB_STATUS_JSON__;  // {filename: resolved path or null}
const RADIUS_FORMAT = __RADIUS_FORMAT_JSON__;  // "float" (fRadius, Most Wanted) or "hash" (AttributeName, Carbon+); detected per file

const legendFilesEl = document.getElementById("legend-files");
// Updates the "<collision file>, <model file>" header; also called on every model swap.
function updateLegendFilesText(currentModelFilename) {
  legendFilesEl.textContent =
    ORIGINAL_FILENAME + (currentModelFilename ? ", " + currentModelFilename : "");
}
updateLegendFilesText(MODEL_FILENAME);

function base64ToBytes(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}
// Working copy of the loaded file. In-place saves patch the changed bound records here.
const fileBytes = base64ToBytes(ORIGINAL_BIN_B64);
const fileView = new DataView(fileBytes.buffer);
const IS_BINARY_EXPORT = fileView.getUint32(0, true) === 0x42704D67; // "gMpB" container (vs the raw 0x0003B901 chunk)

// --------------------------------------------------------------
// Math helpers
// --------------------------------------------------------------
// Orientation: unit quaternion (x, y, z, w), int16 / 32767 per component (_Q4c::Decompress,
// Bounds.h).
function quatToRotMat(x, y, z, w) {
  const n = Math.hypot(x, y, z, w);
  if (n < 1e-9) return [[1,0,0],[0,1,0],[0,0,1]]; // degenerate/zero quaternion -> identity
  x/=n; y/=n; z/=n; w/=n;
  // The game builds the matrix transposed (VU0_quattom4) but applies it to row vectors
  // (VU0_MATRIX4_vect3mult), so the effective rotation is plain R(q). Negating the imaginary
  // part would invert every rotation with W != 0.
  return [
    [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
    [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
    [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)],
  ];
}
function matVec(m, v) {
  return [
    m[0][0]*v[0]+m[0][1]*v[1]+m[0][2]*v[2],
    m[1][0]*v[0]+m[1][1]*v[1]+m[1][2]*v[2],
    m[2][0]*v[0]+m[2][1]*v[1]+m[2][2]*v[2],
  ];
}
function vsub(a,b){ return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
function vadd(a,b){ return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }
function remapVec(v) { return [v[2], v[1], v[0]]; } // self-inverse game<->display swap

// A shape's own transform: parent-frame point = R @ local + position.
function transformPoint(local, R, position) {
  return vadd(matVec(R, local), position);
}
// R is orthonormal, so its transpose is its inverse.
function matTVec(m, v) {
  return [
    m[0][0]*v[0]+m[1][0]*v[1]+m[2][0]*v[2],
    m[0][1]*v[0]+m[1][1]*v[1]+m[2][1]*v[2],
    m[0][2]*v[0]+m[1][2]*v[1]+m[2][2]*v[2],
  ];
}
function inverseTransformPoint(world, R, position) {
  return matTVec(R, vsub(world, position));
}

// --------------------------------------------------------------
// Parent/child hierarchy
// --------------------------------------------------------------
// i is a child of p when p.childrenIndex <= i < p.childrenIndex + p.numberOfChildren.
// Position is relative to the parent. Evaluated live, so index/count edits apply at once.
function findParentShape(shape) {
  if (shape.index === 0) return null;
  for (const key in shapes) {
    const candidate = shapes[key];
    if (candidate === shape) continue;
    if (candidate.numberOfChildren > 0) {
      const start = candidate.childrenIndex;
      const end = start + candidate.numberOfChildren;
      if (shape.index >= start && shape.index < end) return candidate;
    }
  }
  return null;
}

// Ancestors from the immediate parent up to the root; stops on a cycle in malformed data.
function ancestorChain(shape) {
  const chain = [];
  const seen = new Set([shape.index]);
  let anc = findParentShape(shape);
  while (anc) {
    if (seen.has(anc.index)) break;
    seen.add(anc.index);
    chain.push(anc);
    anc = findParentShape(anc);
  }
  return chain;
}

// True when following parent links from `shape` leads back to it (malformed child ranges).
function inParentLoop(shape) {
  const seen = new Set();
  let cur = findParentShape(shape);
  while (cur && !seen.has(cur)) {
    if (cur === shape) return true;
    seen.add(cur);
    cur = findParentShape(cur);
  }
  return false;
}

// Parent -> children map and roots. Bounds outside the root's tree (no parent, or in a parent
// loop) become extra roots, so every bound stays listed.
function buildHierarchy() {
  const childrenOf = new Map();
  const roots = [];
  const sorted = Object.values(shapes).sort((a, b) => a.index - b.index);
  sorted.forEach((s) => {
    const parent = findParentShape(s);
    if (parent) {
      if (!childrenOf.has(parent)) childrenOf.set(parent, []);
      childrenOf.get(parent).push(s);
    } else {
      roots.push(s);
    }
  });
  const reached = new Set();
  const mark = (s) => {
    if (reached.has(s)) return;
    reached.add(s);
    (childrenOf.get(s) || []).forEach(mark);
  };
  roots.forEach(mark);
  sorted.forEach((s) => {
    if (reached.has(s)) return;
    const parent = findParentShape(s);
    childrenOf.set(parent, childrenOf.get(parent).filter((c) => c !== s));
    roots.push(s);
    mark(s);
  });
  return { childrenOf, roots };
}

// All shapes whose worldPoint() chain passes through `shape`.
function descendantsOf(shape) {
  return Object.values(shapes).filter((s) => s !== shape && ancestorChain(s).includes(shape));
}

// Descendants compose through this shape's transform: refresh them when it changes.
function refreshShapeAndDescendants(shape) {
  updateShapeGeometry(shape);
  refreshPinsForShape(shape.name);
  // The root Pivot shifts every bound in the model frame, including bounds outside its tree.
  const dependents = shape.index === 0 ? Object.values(shapes).filter((s) => s !== shape) : descendantsOf(shape);
  dependents.forEach((d) => {
    updateShapeGeometry(d);
    refreshPinsForShape(d.name);
  });
}

function matMul3(a, b) {
  const r = [[0,0,0],[0,0,0],[0,0,0]];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
    r[i][j] = a[i][0]*b[0][j] + a[i][1]*b[1][j] + a[i][2]*b[2][j];
  }
  return r;
}

// Combined ancestor rotation (R_root @ ... @ R_parent); maps a world delta back to shape.position.
function ancestorRotationProduct(shape) {
  let product = [[1,0,0],[0,1,0],[0,0,1]];
  ancestorChain(shape).forEach((anc) => {
    // The root is the body frame: its rotation is not applied to descendants.
    if (anc.index === 0) return;
    product = matMul3(anc.R, product);
  });
  return product;
}

const ZERO3 = [0,0,0];

// Display position of a point in the shape's local frame: own transform, then the ancestors'
// (root excluded, it is the body frame). A root that is the only shape sits at the origin.
// mode: "body" or "model" (model adds the root Pivot).
function worldPoint(shape, local, mode) {
  let p = gameRootAlone(shape) ? local : transformPoint(local, shape.R, shape.position);
  ancestorChain(shape).forEach((anc) => {
    if (anc.index !== 0) p = transformPoint(p, anc.R, anc.position);
  });
  return mode === "model" ? vadd(p, modelFrameShift()) : p;
}

// Inverse of worldPoint().
function localFromWorld(shape, worldPt, mode) {
  const chain = [shape, ...ancestorChain(shape)]; // shape, parent, ..., root
  let p = mode === "model" ? vsub(worldPt, modelFrameShift()) : worldPt;
  for (let i = chain.length - 1; i >= 0; i--) {
    const s = chain[i];
    if (i > 0 ? s.index === 0 : gameRootAlone(s)) continue;
    p = inverseTransformPoint(p, s.R, s.position);
  }
  return p;
}


// --------------------------------------------------------------
// Game placement
// --------------------------------------------------------------
// Mirrors Collection::AddTo (speed.exe 0x672050, per bound 0x66a890; NFSC.exe ~0x6c1f30):
//   - the root's direct children are added one by one;
//   - the root is added only when no child yields a shape (at the origin, identity rotation);
//   - children with the Internal flag are skipped;
//   - a bound yields a primitive when (flags & 0x0E) and Box or Sphere are set, or a mesh when
//     MeshVsGround is set and its cloud has vertices.
// Bounds deeper than the root's children are never added.
function rootShape() {
  return Object.values(shapes).find((s) => s.index === 0) || null;
}

function shapeAtIndex(i) {
  return Object.values(shapes).find((s) => s.index === i) || null;
}

// Vertex count of cloud k in the cloud table; 0 if the cloud does not exist.
function gameCloudVertexCount(k) {
  if (!Number.isInteger(k) || k < 0 || k >= cloudTable.length) return 0;
  const holder = cloudHolderOf(k);
  if (holder && holder.cloudLocal) return holder.cloudLocal.length;
  const entry = cloudTable[k];
  return entry && entry.orphan ? entry.orphan.length : 0;
}

// The root's children as the game enumerates them; none when ChildrenIndex is negative.
function gameRootChildren() {
  const root = rootShape();
  if (!root || root.numberOfChildren <= 0 || root.childrenIndex < 0) return [];
  const list = [];
  for (let i = 0; i < root.numberOfChildren; i++) {
    const c = shapeAtIndex(root.childrenIndex + i);
    if (c && c !== root && !list.includes(c)) list.push(c);
  }
  return list;
}

// True if the game builds a shape from `s`. `asChild` applies the Internal-flag skip.
function gameBoundContributes(s, asChild) {
  const f = s.boundType;
  if (asChild && (f & GAME_INTERNAL_FLAG)) return false;
  const primitive = (f & GAME_PRIM_MASK) !== 0 && (f & (KBOUNDS_BOX_FLAG | KBOUNDS_SPHERE_FLAG)) !== 0;
  if (primitive) return true;
  return (f & GAME_MESH_FLAG) !== 0 && gameCloudVertexCount(s.collisionCloudIndex) > 0;
}

// True for the root when none of its children yields a shape.
function gameRootAlone(shape) {
  if (shape.index !== 0) return false;
  return !gameRootChildren().some((c) => gameBoundContributes(c, true));
}

// Offset applied in the model frame: the root Pivot.
function modelFrameShift() {
  const root = rootShape();
  return root ? root.pivot : ZERO3;
}

// How the game treats `shape` when building the body, or null if it is added normally.
// kind: "ignored" or "alone"; tip: legend tooltip; text: panel note.
function gameStatus(shape) {
  const root = rootShape();
  if (!root) return null;
  const note = (kind, reason, tip) => ({ kind, reason, tip, text: tip + "." });
  if (shape === root) {
    if (gameRootChildren().some((c) => gameBoundContributes(c, true))) {
      return note("ignored", "root-skipped", "Helper bound: its children are added instead");
    }
    if (gameBoundContributes(root, false)) {
      return note("alone", "root-alone", "Only shape: placed at the origin");
    }
    return note("ignored", "no-shape", "Helper bound: it creates no collision shape");
  }
  if (!gameRootChildren().includes(shape)) {
    return findParentShape(shape)
      ? note("ignored", "deep", "Helper bound: only the root's children are added")
      : note("ignored", "unreachable", "Helper bound: no bound lists it as a child");
  }
  if (shape.boundType & GAME_INTERNAL_FLAG) {
    return note("ignored", "internal", "Helper bound: its Internal flag skips it");
  }
  if (!gameBoundContributes(shape, true)) {
    return note("ignored", "no-shape", "Helper bound: it creates no collision shape");
  }
  return null;
}

// Legend tag of a bound (the unassigned tag is separate):
//   helper  grey H, no collision flags
//   note    violet H, a bound the game does not add (replaces the grey H on the root)
//   alone   the root is the only shape
// Unassigned bounds get no note; the unassigned tag covers them.
function legendTagSpec(s) {
  const st = s.gameStatus;
  if (st) {
    if (st.kind === "alone") return { kind: "alone", tip: st.tip };
    if (s.index === 0) return { kind: "note", tip: st.tip };
    if (!s.inactive) {
      if (st.reason === "unreachable" && unassignedSet.has(s)) return null;
      return { kind: "note", tip: st.tip };
    }
  }
  return s.inactive ? { kind: "helper", tip: LEGEND_TAGS.helper.title } : null;
}

let gameRootKey = null;  // root placement at the last refresh
let gameUiReady = false; // true once the info panel and pins exist

// Recomputes legend tags, dimmed edges and field-panel notes for every bound, and the root's
// geometry if its placement changed.
function refreshGameState() {
  const root = rootShape();
  const key = root ? String(gameRootAlone(root)) : "none";
  const flipped = gameRootKey !== null && key !== gameRootKey;
  gameRootKey = key;
  if (flipped && gameUiReady && root && root.mainMesh) {
    updateShapeGeometry(root);
    refreshPinsForShape(root.name);
  }
  Object.values(shapes).forEach((s) => {
    const st = gameStatus(s);
    s.gameStatus = st;
    const row = s.legendRow;
    const nameSpan = row ? row.querySelector(".legend-name") : null;
    if (nameSpan) {
      row.querySelectorAll(".legend-tag:not(.warn)").forEach((t) => t.remove());
      const spec = legendTagSpec(s);
      if (spec) {
        const tag = makeLegendTag(spec.kind);
        tag.title = spec.tip;
        nameSpan.after(tag);
      }
    }
    if (s.edges) {
      const dim = s.inactive || (st && st.kind === "ignored");
      s.edges.material.transparent = !!dim;
      s.edges.material.opacity = dim ? 0.35 : 1;
      s.edges.material.needsUpdate = true;
    }
  });
  if (gameUiReady && openInfoShape) refreshShapeHints(openInfoShape);
}

// Field-panel note for a bound.
function gameHintText(shape) {
  const st = shape.gameStatus !== undefined ? shape.gameStatus : gameStatus(shape);
  return st ? st.text : "";
}

const BOX_SIGNS = [
  [-1,-1,-1], [1,-1,-1], [1,1,-1], [-1,1,-1],
  [-1,-1,1], [1,-1,1], [1,1,1], [-1,1,1],
];
const BOX_TRIANGLES = [
  0,1,2, 0,2,3,   4,5,6, 4,6,7,
  0,1,5, 0,5,4,   3,2,6, 3,6,7,
  1,2,6, 1,6,5,   0,3,7, 0,7,4,
];

// Display frame (not exported): "body" is the collision frame, "model" adds the root Pivot.
let pivotMode = "model";

// Cloud vertices are stored in the owner's parent frame: only the owner's own transform
// applies (no ancestors, no Pivot), whatever the display frame is.
function localToParentFrame(shape, local) {
  return transformPoint(local, shape.R, shape.position);
}
function parentFrameToLocal(shape, parentPt) {
  return inverseTransformPoint(parentPt, shape.R, shape.position);
}

// Bits 1-8192 follow enum BoundFlags (Bounds.h). 16384 (PrimVsOwnParts) is not in the MW enum.
// Used for the BoundType display and the flag checkboxes.
const BOUND_FLAGS = [
  [1, "Disabled"], [2, "PrimVsWorld"], [4, "PrimVsObjects"], [8, "PrimVsGround"],
  [16, "MeshVsGround"], [32, "Internal"], [64, "Box"], [128, "Sphere"],
  [256, "Constraint_Conical"], [512, "Constraint_Prismatic"], [1024, "Joint_Female"],
  [2048, "Joint_Male"], [4096, "Male_Post"], [8192, "Joint_Invert"], [16384, "PrimVsOwnParts"],
];
function decodeBoundType(v) {
  const names = BOUND_FLAGS.filter(([bit]) => v & bit).map(([, name]) => name);
  return names.length ? names.join(", ") : "(none)";
}
const KBOUNDS_SPHERE_FLAG = 0x80;
const KBOUNDS_BOX_FLAG = 0x40;
const KBOUNDS_PRIM_VS_OWN_PARTS = 0x4000;
const KBOUNDS_ACTIVE_MASK = 0x02 | 0x04 | 0x08 | 0x10 | (RADIUS_FORMAT === "float" ? 0 : KBOUNDS_PRIM_VS_OWN_PARTS);
// Collection::AddTo gating, same in Most Wanted (speed.exe 0x66a890) and Carbon (NFSC.exe).
const GAME_PRIM_MASK = 0x0E;      // PrimVsWorld | PrimVsObjects | PrimVsGround
const GAME_MESH_FLAG = 0x10;      // MeshVsGround
const GAME_INTERNAL_FLAG = 0x20;  // Internal
// Box/Sphere pick the primitive (AddCollisionPrimitive: box if Box is set, else sphere), so they
// are fixed after creation. PrimVsOwnParts (bit 14) is not read in MW: editable on Carbon+ only.
const BOUNDTYPE_LOCKED_MASK = KBOUNDS_BOX_FLAG | KBOUNDS_SPHERE_FLAG | (RADIUS_FORMAT === "float" ? KBOUNDS_PRIM_VS_OWN_PARTS : 0);
function toHex32(v) { return "0x" + (v >>> 0).toString(16).toUpperCase().padStart(8, "0"); }
// SurfaceName hash -> name, from Engine/SurfaceNames.txt. Unlisted hashes display as hex.
const SURFACE_NAMES = __SURFACE_NAMES_JSON__;
const SURFACE_NAME_BY_HASH = new Map();
SURFACE_NAMES.forEach(([name, hash]) => { if (!SURFACE_NAME_BY_HASH.has(hash >>> 0)) SURFACE_NAME_BY_HASH.set(hash >>> 0, name); });
const SURFACE_SEARCH_MIN_ITEMS = 10;
function surfaceLabel(hash) {
  const name = SURFACE_NAME_BY_HASH.get(hash >>> 0);
  return name !== undefined ? name : toHex32(hash);
}
// Inverse of the radius decode in parse_collision_bin: float -> raw IEEE-754 uint32.
function floatToRawUint32(f) {
  const buf = new ArrayBuffer(4);
  new Float32Array(buf)[0] = f;
  return new Uint32Array(buf)[0];
}

// --------------------------------------------------------------
// Scene setup
// --------------------------------------------------------------
const holder = document.getElementById("canvas-holder");
const tooltip = document.getElementById("tooltip");
const pinsHolder = document.getElementById("pins-holder");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x11151c);
scene.fog = new THREE.Fog(0x11151c, 15, 60);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.01, 50000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
holder.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 0.9);
key.position.set(6, 10, 8);
scene.add(key);
const fill = new THREE.DirectionalLight(0x8fb3ff, 0.35);
fill.position.set(-8, 4, -6);
scene.add(fill);

// Markers share one unit sphere, scaled per bound (shapeMarkerRadius()/applyMarkerScale()) and
// rescaled when HalfDimension or Radius changes.
const markerGeom = new THREE.SphereGeometry(1, 16, 12);
const cloudGeom = new THREE.SphereGeometry(1, 8, 6);
const MARKER_SIZE_RATIO = 0.012;
const MARKER_MIN_RADIUS = 0.01;
function shapeMarkerRadius(shape) {
  const dim = shape.type === "box" ? Math.max(shape.halfDim[0], shape.halfDim[1], shape.halfDim[2]) : shape.radiusDecoded;
  return Math.max(dim * MARKER_SIZE_RATIO, MARKER_MIN_RADIUS);
}
function applyMarkerScale(marker) {
  marker.scale.setScalar(marker.userData.baseScale * (marker.userData.scaleMult || 1));
}

// --------------------------------------------------------------
// Build shapes
// --------------------------------------------------------------
const shapes = {};
const markerMeshes = [];

// "hash" format: the slot is an AttributeName, not a size; fall back to max(HalfDimension).
function effectiveRadius(b) {
  if (RADIUS_FORMAT === "float") return b.radius;
  return Math.max(b.halfDim[0], b.halfDim[1], b.halfDim[2]);
}

function buildCloudPoints(shape) {
  const cloudMat = new THREE.MeshBasicMaterial({ color: 0xcfd8e6 });
  shape.cloudPoints = shape.cloudLocal.map((local, i) => {
    const m = new THREE.Mesh(cloudGeom, cloudMat.clone());
    m.userData.shapeName = shape.name;
    m.userData.isCloud = true;
    m.userData.pointIndex = i;
    // 0-based vertex index within the cloud, in file order.
    m.userData.cloudVertexCount = shape.cloudLocal.length;
    m.userData.pinned = false;
    m.userData.scaleMult = 1;
    m.userData.baseScale = shape.markerRadius * 0.7;
    applyMarkerScale(m);
    shape.group.add(m);
    markerMeshes.push(m);
    return m;
  });
}

function disposeCloudPoints(shape) {
  if (!shape.cloudPoints) return;
  shape.cloudPoints.forEach((m) => {
    shape.group.remove(m);
    const at = markerMeshes.indexOf(m);
    if (at >= 0) markerMeshes.splice(at, 1);
    m.material.dispose();
  });
  shape.cloudPoints = null;
}

function createShape(b, boundIndex) {
  const color = new THREE.Color(b.color);
  const R = quatToRotMat(b.quat[0], b.quat[1], b.quat[2], b.quat[3]);
  const radiusValue = effectiveRadius(b);

  const shape = {
    name: b.name,
    index: boundIndex,  // index in the file's array; resolves ChildrenIndex links
    sourceIndex: b.byteOffset === null ? null : boundIndex,  // index in the loaded file; null for bounds added this session
    type: b.type,
    inactive: !!b.inactive,
    byteOffset: b.byteOffset,
    color: "#" + color.getHexString(),
    R,
    pivot: b.pivot.slice(),
    quat: b.quat.slice(),
    halfDim: b.halfDim.slice(),
    radius: b.type === "sphere" ? radiusValue : null,  // sphere bounds only (SphereGeometry)
    radiusDecoded: radiusValue,  // all bound types; shown read-only in the advanced panel
    originalRadiusDecoded: radiusValue,  // baseline for the sphere scale in updateShapeGeometry()
    position: b.position.slice(),
    originalHalfDim: b.halfDim.slice(),
    originalPosition: b.position.slice(),
    originalPivot: b.pivot.slice(),
    originalQuat: b.quat.slice(),
    boundType: b.boundType,
    originalBoundType: b.boundType,
    childrenIndex: b.childrenIndex,
    numberOfChildren: b.numberOfChildren,
    collisionCloudIndex: b.collisionCloudIndex,
    // Cloud-table index whose points this shape holds (-1 = none). collisionCloudIndex is just
    // the record field; the points always follow cloudSlot.
    cloudSlot: b.cloudVertices ? b.collisionCloudIndex : -1,
    radiusRaw: b.radiusRaw,
    surfaceNameHash: b.surfaceNameHash,
    nameHash: b.nameHash,
    originalChildrenIndex: b.childrenIndex,
    originalNumberOfChildren: b.numberOfChildren,
    originalCollisionCloudIndex: b.collisionCloudIndex,
    originalRadiusRaw: b.radiusRaw,
    originalSurfaceNameHash: b.surfaceNameHash,
    originalNameHash: b.nameHash,
    // True once Radius is edited manually; it then stops following max(HalfDimension).
    radiusManual: false,
    visible: true,
    dirty: false,
    group: new THREE.Group(),
    markers: [],
  };
  shape.markerRadius = shapeMarkerRadius(shape);

  if (b.type === "box") {
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(24), 3));
    geom.setIndex(BOX_TRIANGLES);
    // flatShading: BOX_TRIANGLES has mixed winding (6 of 12 faces point inward), and smoothed
    // normals flip with the view under DoubleSide. depthWrite off: transparent surfaces that
    // write depth hide later faces.
    const mat = new THREE.MeshStandardMaterial({
      color, transparent: true, opacity: 0.4, side: THREE.DoubleSide, roughness: 0.5, metalness: 0.05,
      flatShading: true, depthWrite: false,
    });
    shape.mainMesh = new THREE.Mesh(geom, mat);
    shape.edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom), new THREE.LineBasicMaterial({ color, transparent: shape.inactive, opacity: shape.inactive ? 0.35 : 1 }));
    shape.mainMesh.add(shape.edges);
  } else {
    const geom = new THREE.SphereGeometry(radiusValue, 28, 20);
    const mat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.4, roughness: 0.5, metalness: 0.05, depthWrite: false });  // depthWrite off, as for boxes
    shape.mainMesh = new THREE.Mesh(geom, mat);
  }
  shape.group.add(shape.mainMesh);

  // Cloud points are absolute in the file; they are converted once to local offsets of the
  // bound so they follow it and can be pinned/edited.
  if (b.cloudVertices) {
    // Needs the parent in `shapes` already (parent index < child index), true for files rooted
    // at Bound_0.
    shape.cloudLocal = b.cloudVertices.map((v) => parentFrameToLocal(shape, v.pos));
    shape.originalCloudLocal = shape.cloudLocal.map((v) => v.slice());
    shape.cloudByteOffset = b.cloudVertices.map((v) => v.byteOffset);
    buildCloudPoints(shape);
  }

  const markerMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const pointCount = b.type === "box" ? 8 : 1;
  for (let i = 0; i < pointCount; i++) {
    const marker = new THREE.Mesh(markerGeom, markerMat.clone());
    marker.userData.shapeName = b.name;
    marker.userData.pointIndex = i;
    marker.userData.pinned = false;
    marker.userData.scaleMult = 1;
    marker.userData.baseScale = shape.markerRadius;
    applyMarkerScale(marker);
    shape.group.add(marker);
    shape.markers.push(marker);
    markerMeshes.push(marker);
  }

  scene.add(shape.group);
  shapes[b.name] = shape;
  return shape;
}

// Several bounds can claim one cloud (zero-filled records from other tools all carry index 0).
// The lowest index gets the points; the others keep the index but no points (see findUnresolved()).
(() => {
  const claimed = new Set();
  BOUNDS.forEach((b) => {
    if (!b.cloudVertices) return;
    if (claimed.has(b.collisionCloudIndex)) b.cloudVertices = null;
    else claimed.add(b.collisionCloudIndex);
  });
})();

BOUNDS.forEach((b, boundIndex) => createShape(b, boundIndex));

// One entry per cloud in file order. `orphan` lists the vertex offsets of a cloud no bound
// references (kept verbatim on structural export).
const structureMenuEl = document.getElementById("structure-menu");
const cloudPanelEl = document.getElementById("cloud-panel");
let structureMenuTarget = null;
let cloudPanelShapeName = null;

const cloudTable = [];
(() => {
  const referenced = new Set(Object.values(shapes).map((s) => s.collisionCloudIndex));
  for (let k = 0; k < CLOUD_META.count; k++) {
    const orphan = CLOUD_META.orphans.find((o) => o.index === k);
    cloudTable.push({ orphan: referenced.has(k) || !orphan ? null : orphan.offsets });
  }
})();

function structureSignature() {
  return JSON.stringify([
    Object.values(shapes).sort((a, b) => a.index - b.index).map((s) => [s.name, s.index, s.cloudLocal ? s.cloudLocal.length : -1]),
    cloudTable.map((e) => (e.orphan ? e.orphan.length : -1)),
  ]);
}
const baselineSignature = structureSignature();
let lastSavedSignature = baselineSignature;
const structureDiffersFromFile = () => structureSignature() !== baselineSignature;
const structureUnsaved = () => structureSignature() !== lastSavedSignature;

// Recomputes a shape's world geometry from its current halfDim/position and pivotMode. Called after
// every edit and pivot-mode change.
function updateShapeGeometry(shape) {
  // Marker size follows this bound's current size.
  shape.markerRadius = shapeMarkerRadius(shape);
  if (shape.type === "box") {
    const worldCorners = BOX_SIGNS.map((signs) => {
      const local = [signs[0]*shape.halfDim[0], signs[1]*shape.halfDim[1], signs[2]*shape.halfDim[2]];
      return worldPoint(shape, local, pivotMode);
    });
    const displayCorners = worldCorners.map(remapVec);

    const posAttr = shape.mainMesh.geometry.attributes.position;
    displayCorners.forEach((c, i) => { posAttr.setXYZ(i, c[0], c[1], c[2]); });
    posAttr.needsUpdate = true;
    shape.mainMesh.geometry.computeVertexNormals();
    shape.mainMesh.geometry.computeBoundingSphere();
    shape.edges.geometry.dispose();
    shape.edges.geometry = new THREE.EdgesGeometry(shape.mainMesh.geometry);

    shape.markers.forEach((marker, i) => {
      marker.position.set(displayCorners[i][0], displayCorners[i][1], displayCorners[i][2]);
      marker.userData.baseScale = shape.markerRadius;
      applyMarkerScale(marker);
    });
  } else {
    const worldCenter = worldPoint(shape, [0,0,0], pivotMode);
    const displayCenter = remapVec(worldCenter);
    shape.mainMesh.position.set(displayCenter[0], displayCenter[1], displayCenter[2]);
    // Most Wanted ("float"): scaled from fRadius, the only size the engine reads for spheres
    // (HalfDimension mirrors it). Carbon+ ("hash"): radiusDecoded tracks max(HalfDimension).
    const scale = shape.originalRadiusDecoded > 1e-9 ? shape.radiusDecoded / shape.originalRadiusDecoded : 1;
    shape.mainMesh.scale.setScalar(scale);
    shape.markers[0].position.set(displayCenter[0], displayCenter[1], displayCenter[2]);
    shape.markers[0].userData.baseScale = shape.markerRadius;
    applyMarkerScale(shape.markers[0]);
  }

  if (shape.cloudPoints) {
    shape.cloudPoints.forEach((point, i) => {
      const world = worldPoint(shape, shape.cloudLocal[i], pivotMode);
      const disp = remapVec(world);
      point.position.set(disp[0], disp[1], disp[2]);
      point.userData.baseScale = shape.markerRadius * 0.7;
      applyMarkerScale(point);
    });
  }
}

Object.values(shapes).forEach(updateShapeGeometry);

// camera fit
const overallBox = new THREE.Box3();
Object.values(shapes).forEach((s) => {
  overallBox.union(new THREE.Box3().setFromObject(s.mainMesh));
  if (s.cloudPoints) s.cloudPoints.forEach((p) => overallBox.expandByPoint(p.position));
});
const size = new THREE.Vector3(), center = new THREE.Vector3();
overallBox.getSize(size); overallBox.getCenter(center);
const maxDim = Math.max(size.x, size.y, size.z, 0.5);
const dist = maxDim * 1;
camera.position.set(center.x + dist*0.7, center.y + dist*0.55, center.z + dist*0.9);
camera.lookAt(center);

const grid = new THREE.GridHelper(60, 30, 0x2a3140, 0x1c212b);
scene.add(grid);
// The grid stays at the world origin; axis-snap views align to it.
const gridCenter = grid.position.clone();

// Fog range scales with the model size; a short fixed range fades large models out.
scene.fog.near = maxDim * 1.4;
scene.fog.far = maxDim * 12;

// Near/far follow the scene size; a fixed 0.01..50000 range gives poor depth precision
// (z-fighting) at car distance. Covers distances from maxDim*0.1 to maxDim*20.
camera.near = Math.max(maxDim * 0.02, 0.01);
camera.far = Math.max(maxDim * 100, 500);
camera.updateProjectionMatrix();

let controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.target.copy(center);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = maxDim * 0.1;
controls.maxDistance = maxDim * 20;
controls.update();

// OrbitControls binds its orbit axis to camera.up at construction: recreate it whenever camera.up
// changes.
function rebuildControls() {
  const target = controls.target.clone();
  controls.dispose();
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.target.copy(target);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = maxDim * 0.1;
  controls.maxDistance = maxDim * 20;
  controls.update();
}

// --------------------------------------------------------------
// Axis gizmo (bottom-right)
// --------------------------------------------------------------
// Mirrors the camera orientation; clicking an axis dot snaps the view.
const gizCanvas = document.createElement("canvas");
document.getElementById("axis-gizmo").appendChild(gizCanvas);
const gizR = new THREE.WebGLRenderer({ canvas: gizCanvas, alpha: true, antialias: true });
gizR.setPixelRatio(window.devicePixelRatio);
gizR.setSize(92, 92);
const gizScene = new THREE.Scene();
const gizCam = new THREE.OrthographicCamera(-1.7, 1.7, 1.7, -1.7, 0.1, 10);

const AXIS_COLORS = { x: 0xff5555, y: 0x55e07a, z: 0x5599ff };
const gizDots = [];
["x", "y", "z"].forEach((axis) => [1, -1].forEach((sign) => {
  const end = new THREE.Vector3(axis === "x" ? sign : 0, axis === "y" ? sign : 0, axis === "z" ? sign : 0).multiplyScalar(0.9);
  gizScene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), end]),
    new THREE.LineBasicMaterial({ color: AXIS_COLORS[axis] })));
  const dotColor = sign > 0 ? new THREE.Color(AXIS_COLORS[axis]) : new THREE.Color(AXIS_COLORS[axis]).lerp(new THREE.Color(0x11151c), 0.55);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(sign > 0 ? 0.24 : 0.17, 16, 12), new THREE.MeshBasicMaterial({ color: dotColor }));
  dot.position.copy(end);
  dot.userData = { axis, sign };
  gizScene.add(dot);
  gizDots.push(dot);
  if (sign > 0) {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const cx = c.getContext("2d");
    cx.fillStyle = "#" + AXIS_COLORS[axis].toString(16).padStart(6, "0");
    cx.beginPath(); cx.arc(32, 32, 30, 0, 7); cx.fill();
    cx.fillStyle = "#11151c"; cx.font = "bold 30px sans-serif"; cx.textAlign = "center"; cx.textBaseline = "middle";
    cx.fillText(axis.toUpperCase(), 32, 34);
    const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
    label.scale.set(0.42, 0.42, 1);
    label.position.copy(end);
    gizScene.add(label);
  }
}));

function axisDir(axis, sign) {
  return new THREE.Vector3(axis === "x" ? sign : 0, axis === "y" ? sign : 0, axis === "z" ? sign : 0);
}
// Top/bottom views sit on the OrbitControls pole, where float noise flips the azimuth between
// frames. Stop slightly off the pole.
const POLE_EPS = 0.02;
function snapAxisDir(axis, sign) {
  return axis === "y" ? new THREE.Vector3(POLE_EPS, sign, 0).normalize() : axisDir(axis, sign);
}
let gizAnim = null;
function snapCameraToAxis(axis, sign) {
  // Keep camera.up at (0,1,0) (OrbitControls assumes it is constant); lookAt() handles straight
  // up/down.
  const up = new THREE.Vector3(0, 1, 0);
  gizAnim = {
    t0: performance.now(), dur: 260, dist: camera.position.distanceTo(controls.target) || dist,
    // Re-center on the grid origin and keep the current distance.
    fromTarget: controls.target.clone(), toTarget: gridCenter.clone(),
    fromDir: camera.position.clone().sub(controls.target).normalize(), toDir: snapAxisDir(axis, sign),
    fromUp: camera.up.clone(), toUp: up,
  };
}
function tickGizAnim() {
  if (!gizAnim) return;
  const k = Math.min(1, (performance.now() - gizAnim.t0) / gizAnim.dur);
  const e = 1 - Math.pow(1 - k, 3); // quick ease-out
  const dir = gizAnim.fromDir.clone().lerp(gizAnim.toDir, e).normalize();
  const tgt = gizAnim.fromTarget.clone().lerp(gizAnim.toTarget, e);
  // Update controls.target together with camera.position every frame; OrbitControls.update()
  // derives its state from their offset.
  controls.target.copy(tgt);
  camera.position.copy(tgt).addScaledVector(dir, gizAnim.dist);
  camera.up.copy(gizAnim.fromUp.clone().lerp(gizAnim.toUp, e).normalize());
  camera.lookAt(tgt);
  if (k === 1) {
    gizAnim = null;
    rebuildControls();  // resync OrbitControls
  }
}

const gizRay = new THREE.Raycaster();
gizCanvas.addEventListener("click", (e) => {
  const r = gizCanvas.getBoundingClientRect();
  gizRay.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), gizCam);
  const hit = gizRay.intersectObjects(gizDots)[0];
  if (hit) snapCameraToAxis(hit.object.userData.axis, hit.object.userData.sign);
});

function updateGizmo() {
  const camDir = camera.position.clone().sub(controls.target);
  gizCam.position.copy((camDir.lengthSq() ? camDir : new THREE.Vector3(0, 0, 1)).normalize().multiplyScalar(4));
  gizCam.up.copy(camera.up);
  gizCam.lookAt(0, 0, 0);
  gizR.render(gizScene, gizCam);
}

// --------------------------------------------------------------
// Mode panel position (below the legend)
// --------------------------------------------------------------
const legendEl = document.getElementById("legend");
const modeWrap = document.getElementById("mode-toggle-wrap");
function positionModeToggle() {
  // Top is the legend's bottom edge plus a gap. Limited room below is absorbed by this panel's own
  // scroll, not by moving the panel up over the legend.
  const top = Math.max(14, legendEl.offsetTop + legendEl.offsetHeight + 8);
  modeWrap.style.top = top + "px";
  modeWrap.style.width = legendEl.offsetWidth + "px";
  // The height left below `top` is this panel's scroll area.
  modeWrap.style.maxHeight = Math.max(90, window.innerHeight - top - 14) + "px";
}
const legendRows = document.getElementById("legend-rows");
// Separate container: rebuildLegendTree() redraws it without touching the "Reference: <model.obj>"
// row.
const legendBoundTree = document.createElement("div");
legendBoundTree.id = "legend-bound-tree";
legendRows.appendChild(legendBoundTree);

const unresolvedBannerEl = document.getElementById("unresolved-banner");
const resolvePanelEl = document.getElementById("resolve-panel");
let resolvePanelOpen = false;
let unassignedSet = new Set(); // bounds rebuildLegendTree() found outside the root's tree

// Tag icons next to a bound's name: helper (H) for inactive bounds, warn for bounds outside the
// root's tree. Glyphs are centered on (8, 8) of the 16x16 box.
const LEGEND_TAGS = {
  helper: {
    title: "Helper bound: no collision flags",
    glyph: '<path d="M5.5 4.8v6.4M10.5 4.8v6.4M5.5 8h5" fill="none" stroke="currentColor" stroke-width="1"/>',
  },
  note: {
    title: "Helper bound",
    glyph: '<path d="M5.5 4.8v6.4M10.5 4.8v6.4M5.5 8h5" fill="none" stroke="currentColor" stroke-width="1"/>',
  },
  alone: {
    title: "Only collision shape",
    glyph: '<circle cx="8" cy="8" r="2.4" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M8 4v1.4M8 10.6V12M4 8h1.4M10.6 8H12" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round"/>',
  },
  warn: {
    title: "Unassigned: no bound lists it, so it is skipped",
    glyph: '<path d="M8 4.8 11.6 11.2H4.4Z" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/><path d="M8 7.1v1.8M8 10.1v.05" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
  },
};

function makeLegendTag(kind) {
  const tag = document.createElement("span");
  tag.className = kind === "warn" ? "legend-tag warn" : kind === "note" ? "legend-tag note" : kind === "alone" ? "legend-tag alone" : "legend-tag";
  tag.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true"><rect class="tb" x="0.5" y="0.5" width="15" height="15" rx="3.5"/>${LEGEND_TAGS[kind].glyph}</svg>`;
  tag.title = LEGEND_TAGS[kind].title;
  return tag;
}

// One legend row: swatch (show/hide) and name (opens the field panel). Called for every bound at
// any depth.
function buildLegendRow(s) {
  const row = document.createElement("div");
  row.className = "legend-row" + (s.visible ? "" : " off") + (s.dirty ? " dirty" : "") + (s.infoOpen ? " editing" : "");
  const swatch = document.createElement("span");
  swatch.className = "legend-swatch";
  swatch.style.background = s.color;
  swatch.title = "Click to show/hide";
  const nameSpan = document.createElement("span");
  nameSpan.className = "legend-name";
  nameSpan.textContent = shapeLabel(s) + (s.cloudPoints ? " (+cloud)" : "");
  nameSpan.style.textDecoration = "underline dotted";
  nameSpan.style.cursor = "pointer";
  nameSpan.title = "Click to see/edit all fields";
  if (s.inactive) nameSpan.title += " - helper bound";
  row.appendChild(swatch);
  row.appendChild(nameSpan);
  if (s.inactive) row.appendChild(makeLegendTag("helper"));
  if (unassignedSet.has(s)) row.appendChild(makeLegendTag("warn"));

  swatch.addEventListener("click", (e) => {
    e.stopPropagation();
    s.visible = !s.visible;
    s.group.visible = s.visible;
    row.classList.toggle("off", !s.visible);
    updateToggleAllLabel();
  });
  nameSpan.addEventListener("click", () => openInfoPanel(s));

  s.legendRow = row;
  return row;
}

// --------------------------------------------------------------
// Bound tree
// --------------------------------------------------------------
// Nesting follows findParentShape(); rebuilt from childrenIndex/numberOfChildren.
function rebuildLegendTree() {
  closeStructureMenu();
  legendBoundTree.innerHTML = "";

  const { childrenOf, roots } = buildHierarchy();
  unassignedSet = new Set(roots.filter((s) => s.index !== 0));

  // Renders a bound, then its subtree in a nested .legend-tree-children box. Indentation comes from
  // DOM nesting; depth only selects the font style.
  function appendNode(container, s, depth) {
    const row = buildLegendRow(s);
    row.classList.add(depth === 0 ? "legend-tree-root" : "legend-tree-child");
    container.appendChild(row);

    const kids = childrenOf.get(s) || [];
    if (kids.length) {
      row.classList.add("legend-tree-parent");

      const caret = document.createElement("span");
      caret.className = "legend-tree-caret";
      caret.textContent = "\u25BE"; // "▾" (expanded)
      caret.title = "Collapse/expand children";

      const badge = document.createElement("span");
      badge.className = "legend-tree-badge";
      const badgeText = document.createElement("span");
      badgeText.className = "lb-text";
      badgeText.textContent = kids.length + (kids.length === 1 ? " child" : " children");
      badge.appendChild(badgeText);
      badge.appendChild(caret);
      row.appendChild(badge);

      const childBox = document.createElement("div");
      childBox.className = "legend-tree-children";
      container.appendChild(childBox);
      kids.forEach((child) => appendNode(childBox, child, depth + 1));

      caret.addEventListener("click", (e) => {
        e.stopPropagation();
        const collapsed = caret.classList.toggle("collapsed");
        caret.textContent = collapsed ? "\u25B8" : "\u25BE"; // "▸" : "▾"
        childBox.style.display = collapsed ? "none" : "";
      });
    }

    const more = document.createElement("span");
    more.className = "legend-more";
    more.textContent = "\u22EF";
    more.title = "Add / delete bounds";
    more.addEventListener("pointerdown", (e) => e.stopPropagation());
    more.addEventListener("click", (e) => {
      e.stopPropagation();
      if (structureMenuTarget === s.name) closeStructureMenu(); else openStructureMenu(s, row);
    });
    row.appendChild(more);
    row.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openStructureMenu(s, row);
    });
  }

  roots.forEach((s) => appendNode(legendBoundTree, s, 0));
  syncUnresolved();
  refreshGameState();
  positionModeToggle(); // tree height can change on rebuild (e.g. a hierarchy edit)
}
rebuildLegendTree();
window.addEventListener("resize", positionModeToggle);

// --------------------------------------------------------------
// Hide all / Show all
// --------------------------------------------------------------
// Hide everything if anything is visible, else show everything.
const toggleAllBtn = document.getElementById("toggle-all-btn");
function updateToggleAllLabel() {
  const anyVisible = Object.values(shapes).some((s) => s.visible);
  toggleAllBtn.textContent = anyVisible ? "Hide all" : "Show all";
}
toggleAllBtn.addEventListener("click", () => {
  const anyVisible = Object.values(shapes).some((s) => s.visible);
  const newVisible = !anyVisible;
  Object.values(shapes).forEach((s) => {
    s.visible = newVisible;
    s.group.visible = newVisible;
    s.legendRow.classList.toggle("off", !newVisible);
  });
  updateToggleAllLabel();
});
updateToggleAllLabel();

// --------------------------------------------------------------
// Reference car model (.obj)
// --------------------------------------------------------------
// Imported from the host as base64. Visual only: not raycast, never touches collision data.
// Placed at the world origin after the axis swap; recentering uses only the model's own bounding box.
const MODEL_AXIS_SWAP = new THREE.Matrix4().set(
  0, 0, 1, 0,
  0, 1, 0, 0,
  -1, 0, 0, 0,
  0, 0, 0, 1
);  // axis swap with Z negated so the model is not mirrored (bounds use the plain swap)
// Fixed 90 degree yaw baked into the geometry on import (reference models face 90 degrees off
// here). Separate from carModelGroup.rotation, so Reset keeps it.
const MODEL_DEFAULT_YAW = new THREE.Matrix4().makeRotationY(-Math.PI / 2);
let carModelGroup = null;
let carModelLegendRow = null;  // legend row for carModelGroup; replaced on re-import
let carModelMeshes = [];  // meshes of the current model (read by openModelMeshPanel())
let modelMeshPanelOpen = false;  // right panel shows the mesh list instead of a bound's fields

let modelEnvMap;
function getModelEnvMap() {
  if (modelEnvMap !== undefined) return modelEnvMap;
  modelEnvMap = null;
  try {
    const env = new THREE.Scene();
    const sky = new THREE.SphereGeometry(50, 32, 16);
    const pos = sky.attributes.position;
    const colors = new Float32Array(pos.count * 3);
    const top = new THREE.Color(0x56667a), mid = new THREE.Color(0x2f3844), bottom = new THREE.Color(0x0d1015);
    const c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const t = pos.getY(i) / 50;
      if (t >= 0) c.copy(mid).lerp(top, t); else c.copy(mid).lerp(bottom, -t);
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
    }
    sky.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    env.add(new THREE.Mesh(sky, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
    const softbox = (w, h, x, y, z, power) => {
      const panel = new THREE.Mesh(
        new THREE.PlaneGeometry(w, h),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(0xffffff).multiplyScalar(power), side: THREE.DoubleSide })
      );
      panel.position.set(x, y, z);
      panel.lookAt(0, 0, 0);
      env.add(panel);
    };
    softbox(36, 36, 0, 40, 0, 1.5);
    softbox(40, 8, -40, 14, 0, 1.6);
    softbox(40, 8, 40, 14, 0, 1.6);
    softbox(40, 6, 0, 10, -40, 1.1);
    softbox(40, 6, 0, 10, 40, 0.8);
    const pmrem = new THREE.PMREMGenerator(renderer);
    modelEnvMap = pmrem.fromScene(env, 0.04).texture;
    pmrem.dispose();
  } catch (err) {
    console.warn("Model environment map unavailable:", err);
    modelEnvMap = null;
  }
  return modelEnvMap;
}

function buildModelMaterial(matName) {
  const n = (matName || "").toUpperCase();
  const envMap = getModelEnvMap();
  const side = THREE.DoubleSide;
  if (!envMap) return new THREE.MeshStandardMaterial({ color: 0x9aa4b2, roughness: 0.35, metalness: 0.5, side });
  const standard = (p) => new THREE.MeshStandardMaterial(Object.assign({ side, envMap }, p));
  if (/^CARSKIN/.test(n)) {
    return new THREE.MeshPhysicalMaterial({
      side, envMap, envMapIntensity: 0.7, color: 0x8e98a5, metalness: 0.55, roughness: 0.38, clearcoat: 0.6, clearcoatRoughness: 0.14,
    });
  }
  if (/^(CHROME|MAGCHROME|HEADLIGHTREFLECTOR)/.test(n)) return standard({ color: 0xe2e7ee, metalness: 1, roughness: 0.1 });
  if (/^(ALUMINUM|MAGSILVER|BRAKEDISC)/.test(n)) return standard({ color: 0xc4cad4, metalness: 1, roughness: 0.3 });
  if (/^RUBBER/.test(n) || n.indexOf("TIRE") !== -1) return standard({ color: 0x16181c, metalness: 0, roughness: 0.9 });
  if (/^BRAKELIGHT/.test(n)) return standard({ color: 0xa8242c, emissive: 0x2c070a, metalness: 0.1, roughness: 0.3 });
  if (/^(INTERIOR|DRIVER|MOLDINGS|DULLPLASTIC|GRILL|BOTTOM|CALIPER)/.test(n)) {
    return standard({ color: 0x2b3038, metalness: 0.1, roughness: 0.7 });
  }
  return standard({ color: 0x9aa4b2, metalness: 0.5, roughness: 0.35, envMapIntensity: 0.7 });
}

// Meshes named with a leading "_" always render as faint light-blue.
function isUnderscoreNamedMesh(child) {
  return !!(child.name && child.name.charAt(0) === "_");
}
function isGlassName(name) {
  const n = (name || "").toUpperCase();
  return (n.indexOf("WINDOW") !== -1 && n.indexOf("MASK") === -1)
    || n.indexOf("WINDSHIELD") !== -1 || n.indexOf("HEADLIGHTGLASS") !== -1;
}
function buildGlassMaterial(geometry) {
  return new THREE.MeshPhongMaterial({
    color: 0x000000, emissive: 0x1c2429,
    specular: new THREE.Color(0xffffff).multiplyScalar(2), shininess: 120,
    transparent: true, opacity: 0.3,
    side: THREE.DoubleSide, depthWrite: false,
    flatShading: !(geometry && geometry.attributes && geometry.attributes.normal),
  });
}
function buildMeshMaterial(child) {
  if (isGlassName(child.name)) return buildGlassMaterial(child.geometry);
  if (isUnderscoreNamedMesh(child)) {
    return new THREE.MeshStandardMaterial({
      color: 0x6fa8ff, transparent: true, opacity: 0.18,
      roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide, depthWrite: false,
      // flatShading: an OBJ without normals (or with inverted ones) would otherwise flicker.
      flatShading: true,
    });
  }
  const pick = (mat) => (isGlassName(mat && mat.name) ? buildGlassMaterial(child.geometry) : buildModelMaterial(mat && mat.name));
  return Array.isArray(child.material) ? child.material.map(pick) : pick(child.material);
}

const modelToastEl = document.getElementById("model-toast");
const modelToastTextEl = document.getElementById("model-toast-text");
let modelToastTimer = null;
function showModelToast(message, kind) {
  modelToastTextEl.textContent = message;
  modelToastEl.className = "show " + kind;
  if (modelToastTimer) clearTimeout(modelToastTimer);
  if (kind === "info") modelToastTimer = setTimeout(hideModelToast, 5000);
}
function hideModelToast() {
  modelToastEl.classList.remove("show");
  if (modelToastTimer) { clearTimeout(modelToastTimer); modelToastTimer = null; }
}
document.getElementById("model-toast-close").addEventListener("click", hideModelToast);

// Loader diagnostic: tells a file Python never found from one that was embedded but did not define
// its global (see the DevTools console).
function describeMissingLib(names) {
  return names.map((name) => {
    const foundPath = MODEL_LIB_STATUS[name];
    return foundPath
      ? name + " (found at " + foundPath + ", but failed to initialize - check DevTools console, F12, for the exact error)"
      : name + " (not found by the engine - place it next to core.py)";
  }).join("; ");
}

// Defaults to the model embedded at generation time. The setCarModel bridge passes arguments to
// swap models on an open page.
function loadCarModelIfPresent(b64 = MODEL_B64, filename = MODEL_FILENAME, extRaw = MODEL_EXT) {
  // Clear any previous model.
  if (carModelGroup) {
    // Dispose GPU buffers.
    carModelGroup.traverse((child) => {
      if (!child.isMesh) return;
      child.geometry.dispose();
      const mats = Array.isArray(child.material) ? child.material : [child.material];
      mats.forEach((mat) => {
        if (!mat) return;
        Object.values(mat).forEach((v) => { if (v && v.isTexture && v !== modelEnvMap) v.dispose(); });
        mat.dispose();
      });
    });
    scene.remove(carModelGroup);
    carModelGroup = null;
  }
  if (carModelLegendRow) {
    carModelLegendRow.remove();
    carModelLegendRow = null;
  }
  document.getElementById("model-rotate-panel").style.display = "none";
  document.getElementById("model-rotate-panel").innerHTML = "";
  // Close the mesh panel; its rows point at disposed meshes.
  if (modelMeshPanelOpen) {
    document.getElementById("info-panel").style.display = "none";
    modelMeshPanelOpen = false;
  }
  carModelMeshes = [];
  updateLegendFilesText("");  // no model shown until a new one loads

  if (!b64) return;
  const ext = (extRaw || "").toLowerCase();
  if (ext !== "obj") {
    const msg = "Unsupported car model file type: ." + ext + " (only .obj reference models are supported)";
    console.warn(msg);
    showModelToast(msg, "warn");
    return;
  }
  if (typeof THREE.OBJLoader === "undefined") {
    const msg = "Can't show the car model: " + describeMissingLib(["OBJLoader.js"]);
    console.warn(msg);
    showModelToast(msg, "warn");
    return;
  }

  let object;
  try {
    const bytes = base64ToBytes(b64);
    object = new THREE.OBJLoader().parse(new TextDecoder("utf-8").decode(bytes));
  } catch (err) {
    console.error("Failed to parse car model '" + filename + "':", err);
    showModelToast("Couldn't read '" + filename + "' as an OBJ file: " + (err && err.message ? err.message : err), "warn");
    return;
  }

  let meshCount = 0;
  const modelMeshes = carModelMeshes;
  object.traverse((child) => {
    if (!child.isMesh) return;
    meshCount++;
    child.material = buildMeshMaterial(child);
    child.renderOrder = -1;
    modelMeshes.push(child);
  });

  if (meshCount === 0) {
    const msg = "'" + filename + "' loaded but contains no visible geometry.";
    console.warn(msg);
    showModelToast(msg, "warn");
    return;
  }

  object.applyMatrix4(MODEL_AXIS_SWAP);
  object.applyMatrix4(MODEL_DEFAULT_YAW);

  // Optional recentering on the model's bounding-box center (collision data is not read):
  //   "normal" - as loaded (default)
  //   "height" - zero the height component only (MODEL_AXIS_SWAP leaves Y alone: height is Y, not Z)
  //   "xyz"    - zero all three components
  let centerMode = "normal";
  let ownCenter = new THREE.Vector3();
  function recomputeOwnCenter() {
    object.position.set(0, 0, 0);
    const box = new THREE.Box3().setFromObject(object);
    ownCenter = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
  }
  function applyOwnCentering(mode) {
    const offset = new THREE.Vector3(0, 0, 0);
    if (mode === "height") {
      offset.y = -ownCenter.y;
    } else if (mode === "xyz") {
      offset.copy(ownCenter).negate();
    }
    object.position.copy(offset);
  }
  recomputeOwnCenter();
  applyOwnCentering(centerMode);

  carModelGroup = new THREE.Group();
  carModelGroup.add(object);
  carModelGroup.position.set(0, 0, 0); // always the collision's own origin
  scene.add(carModelGroup);
  updateLegendFilesText(filename);

  const row = document.createElement("div");
  row.className = "legend-row";
  const swatch = document.createElement("span");
  swatch.className = "legend-swatch";
  swatch.style.background = "#4a5568";
  swatch.title = "Click to show/hide";
  const nameSpan = document.createElement("span");
  nameSpan.className = "legend-name";
  nameSpan.textContent = "Reference: " + filename;
  nameSpan.style.textDecoration = "underline dotted";
  nameSpan.style.cursor = "pointer";
  nameSpan.title = "Click to show/hide individual meshes";
  row.appendChild(swatch);
  row.appendChild(nameSpan);
  swatch.addEventListener("click", (e) => {
    e.stopPropagation();
    carModelGroup.visible = !carModelGroup.visible;
    row.classList.toggle("off", !carModelGroup.visible);
  });
  nameSpan.addEventListener("click", () => openModelMeshPanel(filename, carModelMeshes));
  legendRows.appendChild(row);
  carModelLegendRow = row;
  positionModeToggle();  // the legend grew by one row

  // Bounding-box recentering cannot detect orientation, so the manual per-axis rotation nudges live
  // in the Pivot box (keeps the legend height stable).
  const rotatePanel = document.getElementById("model-rotate-panel");
  rotatePanel.innerHTML = "";

  function addCheckbox(labelText, checked, onChange) {
    // Native checkbox.
    const label = document.createElement("label");
    label.className = "mr-checkbox-row";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = checked;
    input.addEventListener("pointerdown", (e) => e.stopPropagation());
    input.addEventListener("change", (e) => {
      e.stopPropagation();
      onChange(input.checked);
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(labelText));
    rotatePanel.appendChild(label);
    return input;
  }
  function addRadio(groupName, labelText, value, checkedValue, onChange) {
    // Radio variant of addCheckbox with a shared name; the panel is rebuilt on every import, so
    // reusing the group name is safe.
    const label = document.createElement("label");
    label.className = "mr-checkbox-row";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = groupName;
    input.value = value;
    input.checked = value === checkedValue;
    input.addEventListener("pointerdown", (e) => e.stopPropagation());
    input.addEventListener("change", (e) => {
      e.stopPropagation();
      if (input.checked) onChange(value);
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(labelText));
    rotatePanel.appendChild(label);
    return input;
  }
  const axisGroupTitle = document.createElement("div");
  axisGroupTitle.className = "mr-title";
  axisGroupTitle.textContent = "Model axis";
  axisGroupTitle.style.marginBottom = "6px";
  rotatePanel.appendChild(axisGroupTitle);
  addRadio("center-mode", "Original - Model's original axes", "normal", centerMode, (mode) => {
    centerMode = mode;
    applyOwnCentering(centerMode);
  });
  addRadio("center-mode", "Center Vertically - Center model vertically", "height", centerMode, (mode) => {
    centerMode = mode;
    applyOwnCentering(centerMode);
  });
  addRadio("center-mode", "Center at Origin - Align model center to XYZ = 0", "xyz", centerMode, (mode) => {
    centerMode = mode;
    applyOwnCentering(centerMode);
  });
  const titleRow = document.createElement("div");
  titleRow.className = "mr-title";
  titleRow.textContent = "Rotate reference model";
  const axisLabelSpan = document.createElement("span");
  axisLabelSpan.className = "mr-axis-readout";
  titleRow.appendChild(axisLabelSpan);
  rotatePanel.appendChild(titleRow);

  let selectedAxis = "y";  // default axis: yaw
  const axisNames = { x: "X", y: "Y", z: "Z" };
  function updateAxisReadout() {
    axisLabelSpan.textContent = "(" + axisNames[selectedAxis] + ")";
    axisLabelSpan.className = "mr-axis-readout mr-axis-readout-" + selectedAxis;
  }

  const axisRow = document.createElement("div");
  axisRow.className = "mr-row mr-axis-row";
  const axisBtns = {};
  [["x", "X"], ["y", "Y"], ["z", "Z"]].forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.className = "mr-axis-btn mr-axis-btn-" + key;
    btn.title = "Rotate around " + label;
    btn.addEventListener("pointerdown", (e) => e.stopPropagation());
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      selectedAxis = key;
      Object.entries(axisBtns).forEach(([k, b]) => b.classList.toggle("mr-active", k === key));
      updateAxisReadout();
    });
    axisRow.appendChild(btn);
    axisBtns[key] = btn;
  });
  axisBtns[selectedAxis].classList.add("mr-active");
  updateAxisReadout();
  rotatePanel.appendChild(axisRow);

  const stepRow = document.createElement("div");
  stepRow.className = "mr-row";
  [[-90, "\u2b6f 90\u00b0"], [90, "90\u00b0 \u2b6e"]].forEach(([deg, text]) => {
    const btn = document.createElement("button");
    btn.textContent = text;
    btn.title = "Rotate the reference model " + deg + "\u00b0 around the selected axis";
    btn.addEventListener("pointerdown", (e) => e.stopPropagation());
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      carModelGroup.rotation[selectedAxis] += deg * Math.PI / 180;
    });
    stepRow.appendChild(btn);
  });
  const resetBtn = document.createElement("button");
  resetBtn.textContent = "Reset";
  resetBtn.title = "Undo all manual rotation on the reference model";
  resetBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
  resetBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    carModelGroup.rotation.set(0, 0, 0);
  });
  stepRow.appendChild(resetBtn);
  rotatePanel.appendChild(stepRow);
  rotatePanel.style.display = "block";

  showModelToast("Loaded reference model: " + filename + " (" + meshCount + " mesh" + (meshCount === 1 ? "" : "es") + ")\nUse the rotation buttons below if it's not facing the right way.", "info");
}
loadCarModelIfPresent();

// --------------------------------------------------------------
// setCarModel bridge
// --------------------------------------------------------------
// The C# host swaps the reference model on an open page (navigating would drop unsaved edits).
// Reruns only the model loading; BOUNDS/shapes are untouched. No-op outside WebView2.
if (window.chrome && window.chrome.webview) {
  window.chrome.webview.addEventListener("message", (event) => {
    const data = event.data;
    if (data && data.type === "setCarModel" && typeof data.base64 === "string") {
      loadCarModelIfPresent(data.base64, data.filename || "", data.ext || "");
    }
  });
}

document.querySelectorAll('input[name="pivot-mode"]').forEach((radio) => {
  radio.addEventListener("change", (e) => {
    if (!e.target.checked) return;
    pivotMode = e.target.id === "mode-radio-model" ? "model" : "body";
    Object.values(shapes).forEach(updateShapeGeometry);
    Object.keys(pins).forEach((k) => refreshPinsForShape(pins[k].marker.userData.shapeName));
    if (openInfoShape) openInfoPanel(openInfoShape);
  });
});

function isShapeDirty(shape) {
  const cloudDirty = shape.cloudLocal
    ? !shape.originalCloudLocal || shape.cloudLocal.length !== shape.originalCloudLocal.length
      || shape.cloudLocal.some((v, i) => v.some((c, axis) => Math.abs(c - shape.originalCloudLocal[i][axis]) > 1e-9))
    : false;
  return (shape.byteOffset === null && !shape.savedToFile)
      || shape.halfDim.some((v,i) => Math.abs(v - shape.originalHalfDim[i]) > 1e-9)
      || shape.position.some((v,i) => Math.abs(v - shape.originalPosition[i]) > 1e-9)
      || shape.pivot.some((v,i) => Math.abs(v - shape.originalPivot[i]) > 1e-9)
      || shape.quat.some((v,i) => Math.abs(v - shape.originalQuat[i]) > 1e-9)
      || shape.boundType !== shape.originalBoundType
      || shape.childrenIndex !== shape.originalChildrenIndex
      || shape.numberOfChildren !== shape.originalNumberOfChildren
      || shape.collisionCloudIndex !== shape.originalCollisionCloudIndex
      || shape.radiusRaw !== shape.originalRadiusRaw
      || shape.surfaceNameHash !== shape.originalSurfaceNameHash
      || shape.nameHash !== shape.originalNameHash
      || cloudDirty;
}

function rebaseShapeBaseline(shape) {
  shape.originalHalfDim = shape.halfDim.slice();
  shape.originalPosition = shape.position.slice();
  shape.originalPivot = shape.pivot.slice();
  shape.originalQuat = shape.quat.slice();
  shape.originalBoundType = shape.boundType;
  shape.originalChildrenIndex = shape.childrenIndex;
  shape.originalNumberOfChildren = shape.numberOfChildren;
  shape.originalCollisionCloudIndex = shape.collisionCloudIndex;
  shape.originalRadiusRaw = shape.radiusRaw;
  shape.originalSurfaceNameHash = shape.surfaceNameHash;
  shape.originalNameHash = shape.nameHash;
  if (shape.cloudLocal) shape.originalCloudLocal = shape.cloudLocal.map((v) => v.slice());
  shape.savedToFile = true;
}

function markDirty(shape, isDirty) {
  shape.dirty = isDirty;
  shape.legendRow.classList.toggle("dirty", isDirty);
  updateSaveStatus();
}

// --------------------------------------------------------------
// Bound field panel
// --------------------------------------------------------------
// Direct single-field assignments, committed on Enter or focus loss. ChildrenIndex,
// NumberOfChildren, CollisionCloudIndex, Radius and the hashes stay locked until "Edit advanced
// fields" is checked.
const infoPanelEl = document.getElementById("info-panel");
const btMenuEl = document.getElementById("boundtype-menu");
let boundTypeMenuOpen = null;
let boundTypeMenuScrollTop = 0;
const sfMenuEl = document.getElementById("surface-menu");
let surfaceMenuOpen = null;
let surfaceMenuScrollTop = 0;
let openInfoShape = null;
gameUiReady = true;

function setOpenInfoShape(shape) {
  if (!shape || shape.name !== boundTypeMenuOpen) closeBoundTypeMenu();
  if (!shape || shape.name !== surfaceMenuOpen) closeSurfaceMenu();
  if (!shape || shape.name !== cloudPanelShapeName) closeCloudPanel();
  if (openInfoShape && openInfoShape !== shape) {
    openInfoShape.infoOpen = false;
    openInfoShape.legendRow.classList.remove("editing");
  }
  openInfoShape = shape;
  if (shape) {
    shape.infoOpen = true;
    shape.legendRow.classList.add("editing");
  }
}

// Mesh list panel for the imported model, opened from the "Reference: <file>" legend row. Show/hide
// only, no fields.
function meshDisplayName(mesh, originalIndex) {
  return mesh.name && mesh.name.length ? mesh.name : ("Mesh " + (originalIndex + 1));
}

// Drag-paint: null when idle, otherwise the visibility being applied to each row the pointer
// enters.
let meshDragPaintState = null;
document.addEventListener("pointerup", () => { meshDragPaintState = null; });

function openModelMeshPanel(filename, meshes) {
  boundTypeMenuOpen = null;
  setOpenInfoShape(null);  // no bound selected
  modelMeshPanelOpen = true;
  meshDragPaintState = null;

  infoPanelEl.innerHTML = `
    <div class="i-title"><span>Reference: ${filename}</span><span class="i-close">&#10005;</span></div>
    <div class="i-note" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
      <span>Click, or click-drag, to show/hide meshes.</span>
      <button id="mesh-toggle-all-btn">Hide all</button>
    </div>
    <div id="mesh-panel-rows"></div>
  `;
  infoPanelEl.style.display = "block";

  // "_"-named meshes first. "Mesh N" uses the original index, so sorting never renumbers.
  const orderedMeshes = meshes
    .map((mesh, originalIndex) => ({ mesh, originalIndex }))
    .sort((a, b) => {
      const aFirst = isUnderscoreNamedMesh(a.mesh) ? 0 : 1;
      const bFirst = isUnderscoreNamedMesh(b.mesh) ? 0 : 1;
      return aFirst !== bFirst ? aFirst - bFirst : a.originalIndex - b.originalIndex;
    });

  const rowsHolder = infoPanelEl.querySelector("#mesh-panel-rows");
  const toggleAllBtn = infoPanelEl.querySelector("#mesh-toggle-all-btn");
  function updateToggleAllLabel() {
    const anyVisible = meshes.some((m) => m.visible);
    toggleAllBtn.textContent = anyVisible ? "Hide all" : "Show all";
  }
  function setMeshVisible(row, mesh, visible) {
    mesh.visible = visible;
    row.classList.toggle("off", !visible);
  }

  orderedMeshes.forEach(({ mesh, originalIndex }) => {
    const row = document.createElement("div");
    row.className = "legend-row" + (mesh.visible ? "" : " off");
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = isGlassName(mesh.name) ? "#1c2429" : (isUnderscoreNamedMesh(mesh) ? "#6fa8ff" : "#4a5568");
    swatch.title = "Click to show/hide";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = meshDisplayName(mesh, originalIndex);
    row.appendChild(swatch);
    row.appendChild(nameSpan);

    // pointerdown toggles this row and paints that state onto the rows entered next; a click is a
    // one-row drag.
    row.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      meshDragPaintState = !mesh.visible;
      setMeshVisible(row, mesh, meshDragPaintState);
      updateToggleAllLabel();
    });
    row.addEventListener("pointerenter", () => {
      if (meshDragPaintState === null) return;
      setMeshVisible(row, mesh, meshDragPaintState);
      updateToggleAllLabel();
    });

    rowsHolder.appendChild(row);
  });
  updateToggleAllLabel();

  toggleAllBtn.addEventListener("click", () => {
    const anyVisible = meshes.some((m) => m.visible);
    const newVisible = !anyVisible;
    Array.from(rowsHolder.children).forEach((row, i) => {
      setMeshVisible(row, orderedMeshes[i].mesh, newVisible);
    });
    updateToggleAllLabel();
  });

  infoPanelEl.querySelector(".i-close").addEventListener("click", () => {
    infoPanelEl.style.display = "none";
    modelMeshPanelOpen = false;
    meshDragPaintState = null;
  });
}

// int16 limits at each field's scale. Out-of-range edits are clamped with a warning when typed,
// not silently at export.
const MAX_STORABLE_UNIT = 32767 / 1000; // Position/HalfDimension/Pivot: 32.767
const MAX_STORABLE_QUAT = 1; // Orientation quaternion component: raw int16/32767, so |value|<=1

function applyDirectEdit(shape, kind, axis, value) {
  if (Number.isNaN(value)) return;
  setFieldWarn(kind, "");
  if (kind === "position") {
    if (Math.abs(value) > MAX_STORABLE_UNIT) {
      setFieldWarn(kind, `PositionX/Y/Z can only store up to \u00b1${MAX_STORABLE_UNIT} - clamped from ${fmt(value)}.`);
      value = Math.sign(value) * MAX_STORABLE_UNIT;
    }
    shape.position[axis] = value;
  } else if (kind === "halfDim") {
    if (shape.type === "sphere" && RADIUS_FORMAT === "float") {
      // Most Wanted spheres: HalfDimension is never edited directly because the engine reads only
      // Radius. Carbon+ falls through to the generic path.
      setFieldWarn(kind, "Locked - spheres use Radius instead.");
      return;
    }
    if (value <= 1e-5) { setFieldWarn(kind, "HalfDimension must be greater than 0 - edit ignored."); return; }
    if (value > MAX_STORABLE_UNIT) {
      setFieldWarn(kind, `HalfDimension can only store up to ${MAX_STORABLE_UNIT} - clamped from ${fmt(value)}.`);
      value = MAX_STORABLE_UNIT;
    }
    shape.halfDim[axis] = value;
    if (shape.type === "sphere") {
      // Carbon+ ("hash"): the slot is an AttributeName, so radiusRaw is never touched.
      // radiusDecoded is only the render-scale baseline and tracks max(HalfDimension).
      shape.radiusDecoded = Math.max(shape.halfDim[0], shape.halfDim[1], shape.halfDim[2]);
    } else if (!shape.radiusManual && RADIUS_FORMAT === "float") {
      // fRadius follows max(HalfDimension) for Box/MeshVsGround bounds until it is edited manually
      // (see the "radius" case and the "Edit advanced fields" handler).
      const maxDim = Math.max(shape.halfDim[0], shape.halfDim[1], shape.halfDim[2]);
      shape.radiusDecoded = maxDim;
      shape.radiusRaw = floatToRawUint32(maxDim);
    }
  } else if (kind === "pivot") {
    if (Math.abs(value) > MAX_STORABLE_UNIT) {
      setFieldWarn(kind, `PivotX/Y/Z can only store up to \u00b1${MAX_STORABLE_UNIT} - clamped from ${fmt(value)}.`);
      value = Math.sign(value) * MAX_STORABLE_UNIT;
    }
    shape.pivot[axis] = value;
  } else if (kind === "orientAxis" || kind === "orientAngle") {
    // "orientAxis" = X/Y/Z, "orientAngle" = W quaternion component.
    let clamped = false;
    if (Math.abs(value) > MAX_STORABLE_QUAT) {
      const label = kind === "orientAxis" ? "OrientationX/Y/Z" : "OrientationW";
      setFieldWarn(kind, `${label} can only store up to \u00b1${MAX_STORABLE_QUAT} - clamped from ${fmt(value)}.`);
      value = Math.sign(value) * MAX_STORABLE_QUAT;
      clamped = true;
    }
    if (kind === "orientAxis") shape.quat[axis] = value; else shape.quat[3] = value;
    shape.R = quatToRotMat(shape.quat[0], shape.quat[1], shape.quat[2], shape.quat[3]);
    // #orient-warn is shared with the unit-length check; a clamp message from this edit takes
    // priority.
    if (!clamped) setFieldWarn(kind, orientWarningText(shape));
  } else if (kind === "radius") {
    if (value <= 1e-5) { setFieldWarn(kind, "Radius must be greater than 0 - edit ignored."); return; }
    shape.radiusDecoded = value;
    shape.radiusRaw = floatToRawUint32(value);
    if (shape.type === "sphere") {
      // Sphere HalfDimension mirrors Radius, the only size the engine reads.
      shape.halfDim = [value, value, value];
      // originalRadiusDecoded stays fixed at load time, like the other original* values, so the
      // dirty check and render scale are relative to the opened file.
    } else {
      // Box/MeshVsGround radius (needs "Edit advanced fields"). A manual edit keeps the typed value
      // and stops the max(HalfDimension) sync for this bound for good. Undo restores automatic mode.
      shape.radiusManual = true;
    }
  }
  refreshShapeAndDescendants(shape);
  markDirty(shape, isShapeDirty(shape));
  if (openInfoShape === shape) refreshInfoPanelReadouts(shape);
}

function applyIntFieldEdit(shape, field, rawText) {
  const value = parseInt(rawText, 10);
  if (Number.isNaN(value)) return;
  const limits = {
    childrenIndex: [-32768, 32767],
    numberOfChildren: [0, 255],
    collisionCloudIndex: [-128, 127],
  };
  const [min, max] = limits[field];
  if (value < min || value > max) return; // refuse out-of-range for that field's storage type
  shape[field] = value;
  markDirty(shape, isShapeDirty(shape));
  // ChildrenIndex/NumberOfChildren change which bounds are descendants, so every shape is
  // refreshed.
  if (field === "childrenIndex" || field === "numberOfChildren") {
    rebuildLegendTree();
    Object.values(shapes).forEach((s) => { updateShapeGeometry(s); refreshPinsForShape(s.name); });
  } else if (field === "collisionCloudIndex") {
    syncUnresolved();
  }
  refreshGameState(); // flags, cloud and child range decide what the game adds
}

function parseHashText(rawText) {
  let text = rawText.trim();
  if (/^0x/i.test(text)) text = text.slice(2);
  if (!/^[0-9a-fA-F]{1,8}$/.test(text)) return null;
  return parseInt(text, 16) >>> 0; // unsigned 32-bit
}

function applyHashFieldEdit(shape, field, rawText) {
  const value = parseHashText(rawText);
  if (value === null) return; // must be a valid hex value
  shape[field] = value;
  markDirty(shape, isShapeDirty(shape));
}

function refreshInfoPanelReadouts(shape) {
  infoPanelEl.querySelectorAll("input[data-kind]").forEach((input) => {
    if (document.activeElement === input) return;
    const kind = input.dataset.kind, axis = parseInt(input.dataset.axis, 10);
    if (kind === "orientAxis") { input.value = fmt(shape.quat[axis]); return; }
    if (kind === "orientAngle") { input.value = fmt(shape.quat[3]); return; }
    if (kind === "radius") { input.value = fmt(shape.radiusDecoded); return; }
    if (kind === "halfDim" && shape.type === "sphere" && RADIUS_FORMAT === "float") { input.value = fmt(shape.radiusDecoded); return; }
    const src = kind === "position" ? shape.position : kind === "pivot" ? shape.pivot : shape.halfDim;
    input.value = fmt(src[axis]);
  });
  refreshShapeHints(shape);
}

function refreshShapeHints(shape) {
  if (shape !== openInfoShape) return; // the notes belong to the bound whose panel is open
  const setHint = (id, text) => {
    const el = infoPanelEl.querySelector("#" + id);
    if (el) el.textContent = text;
  };
  const boxOnlyOffset = shape.boundType === KBOUNDS_BOX_ONLY && shape.position.some((v) => Math.abs(v) > 1e-9);
  setHint("position-hint", boxOnlyOffset ? "Usually (0, 0, 0) for this BoundType." : "");
  const meshWithoutCloud = (shape.boundType & KBOUNDS_MESH_VS_GROUND) !== 0 && !shape.cloudLocal && shape.collisionCloudIndex < 0;
  setHint("inactive-hint", shape.inactive ? "No collision flags." : "");
  setHint("game-hint", gameHintText(shape));
  setHint("boundtype-hint", meshWithoutCloud ? "MeshVsGround is normally only set on bounds with a cloud - consider turning it off." : "");
  keepMenusAnchored();
}

// A note appearing or disappearing changes the panel height and can shift its scroll position. An
// open menu follows its field instead of being closed by the scroll handler.
function keepMenusAnchored() {
  if (boundTypeMenuOpen !== null) {
    boundTypeMenuScrollTop = infoPanelEl.scrollTop;
    positionBoundTypeMenu();
  }
  if (surfaceMenuOpen !== null) {
    surfaceMenuScrollTop = infoPanelEl.scrollTop;
    positionSurfaceMenu();
  }
}

function orientWarningText(shape) {
  const mag = Math.hypot(shape.quat[0], shape.quat[1], shape.quat[2], shape.quat[3]);
  if (mag < 1e-9) return "Orientation is all zero - not a valid quaternion, treated as identity (no rotation).";
  if (Math.abs(mag - 1) > 0.02) return "Quaternion is not unit-length (|q| = " + mag.toFixed(3) + ") - the game expects a normalized rotation quaternion.";
  return "";
}

// Commits on Enter or when focus leaves the field, never per keystroke.
function wireCommit(input, commitFn) {
  input.addEventListener("keydown", (e) => {
    // Enter only blurs; the resulting change event runs commitFn. Calling it here would run it
    // twice, and the second run (on the reformatted value) clears the warning set by the first.
    if (e.key === "Enter") { input.blur(); }
  });
  input.addEventListener("change", () => {
    commitFn();
    // An emptied number field changes nothing; show the value it had again instead of a blank.
    if (input.type === "number" && input.value.trim() === "" && input.dataset.focusValue !== undefined) {
      input.value = input.dataset.focusValue;
    }
  });
  input.addEventListener("pointerdown", (e) => e.stopPropagation());
}

function openInfoPanel(shape) {
  if (boundTypeMenuOpen !== shape.name) boundTypeMenuOpen = null;
  setOpenInfoShape(shape);
  modelMeshPanelOpen = false;  // the panel now shows bound fields
  const axisLabel = ["X", "Y", "Z"];
  const posRows = axisLabel.map((L, i) => `
    <div class="i-row"><label>Position${L}</label>
      <input type="number" step="any" data-kind="position" data-axis="${i}" value="${fmt(shape.position[i])}"></div>
  `).join("");
  // MW spheres: HalfDimension inputs are locked and show Radius on all axes (the exported value).
  // Carbon+ has no real Radius, so HalfDimension stays editable.
  const halfDimLocked = shape.type === "sphere" && RADIUS_FORMAT === "float";
  const halfRows = axisLabel.map((L, i) => `
    <div class="i-row"><label>HalfDimension${L}</label>
      <input type="number" step="any" data-kind="halfDim" data-axis="${i}" ${halfDimLocked ? "disabled" : ""} value="${fmt(halfDimLocked ? shape.radiusDecoded : shape.halfDim[i])}"></div>
  `).join("");
  const pivotRows = axisLabel.map((L, i) => `
    <div class="i-row"><label>Pivot${L}</label>
      <input type="number" step="any" data-kind="pivot" data-axis="${i}" value="${fmt(shape.pivot[i])}"></div>
  `).join("");
  const orientAxisRows = axisLabel.map((L, i) => `
    <div class="i-row"><label>Orientation${L}</label>
      <input type="number" step="any" data-kind="orientAxis" data-axis="${i}" value="${fmt(shape.quat[i])}"></div>
  `).join("");

  infoPanelEl.innerHTML = `
    <div class="i-title"><span>${shapeLabel(shape)}</span><span class="i-close">&#10005;</span></div>
    <div class="i-note">Press Enter to apply.</div>
    <div class="i-note" id="inactive-hint">${shape.inactive ? "No collision flags." : ""}</div>
    <div class="i-note" id="game-hint">${gameHintText(shape)}</div>

    <div class="i-section">Position</div>
    ${posRows}
    <div class="i-note i-field-warn" id="position-warn" style="color:#e6b450;"></div>
    <div class="i-note i-field-warn" id="position-hint" style="color:#e6b450;"></div>

    <div class="i-section">Half Dimension</div>
    ${halfDimLocked ? '<div class="i-note">Locked - mirrors Radius (see Advanced fields below).</div>' : ''}
    ${(shape.type === "sphere" && !halfDimLocked) ? '<div class="i-note">Editing resizes this Sphere directly (AttributeName here isn\'t a size).</div>' : ''}
    ${halfRows}
    <div class="i-note i-field-warn" id="halfdim-warn" style="color:#e6b450;"></div>

    <div class="i-section">Pivot</div>
    ${pivotRows}
    <div class="i-note i-field-warn" id="pivot-warn" style="color:#e6b450;"></div>

    <div class="i-section">Orientation (quaternion X, Y, Z, W)</div>
    ${orientAxisRows}
    <div class="i-row"><label>OrientationW</label>
      <input type="number" step="any" data-kind="orientAngle" value="${fmt(shape.quat[3])}"></div>
    <div class="i-note i-field-warn" id="orient-warn" style="color:#e6b450;"></div>

    <div class="i-section">
      <label style="display:flex; align-items:center; gap:6px; cursor:pointer; text-transform:none; font-size:11px; color:#9fb3d1;">
        <input type="checkbox" id="unlock-other"> Edit advanced fields (ChildrenIndex, hashes, ...)
      </label>
    </div>
    <div class="i-row i-row-advanced"><label>BoundType</label><button type="button" class="i-bt-box" id="boundtype-box" disabled aria-haspopup="true" aria-expanded="false" title="Click to edit the BoundType flags"><span id="boundtype-hex">${toHex32(shape.boundType)}</span><span class="i-bt-caret">&#9662;</span></button></div>
    <div class="i-bt-names i-row-advanced" id="boundtype-names">${boundTypeNamesText(shape.boundType)}</div>
    <div class="i-note i-field-warn" id="boundtype-hint" style="color:#e6b450;"></div>
    <div class="i-row i-row-advanced"><label>ChildrenIndex</label><input type="number" step="1" disabled data-int="childrenIndex" value="${shape.childrenIndex}"></div>
    <div class="i-row i-row-advanced"><label>NumberOfChildren</label><input type="number" step="1" min="0" max="255" disabled data-int="numberOfChildren" value="${shape.numberOfChildren}"></div>
    <div class="i-row i-row-advanced"><label>CollisionCloudIndex</label><input type="number" step="1" disabled data-int="collisionCloudIndex" value="${shape.collisionCloudIndex}"></div>
    ${RADIUS_FORMAT === "hash"
      ? `<div class="i-row i-row-advanced"><label>AttributeName</label><span class="i-readonly">${toHex32(shape.radiusRaw)}</span></div>`
      : `<div class="i-row i-row-advanced" title="Sphere: the real collision radius. Box: follows max(HalfDimension) unless edited here."><label>Radius (fRadius)</label><input type="number" step="any" disabled data-kind="radius" value="${fmt(shape.radiusDecoded)}"></div>
    <div class="i-note i-field-warn i-row-advanced" id="radius-warn" style="color:#e6b450;"></div>`}
    <div class="i-row i-row-advanced"><label>SurfaceName</label><button type="button" class="i-bt-box" id="surface-box" disabled aria-haspopup="true" aria-expanded="false"><span class="i-bt-label" id="surface-label"></span><span class="i-bt-caret">&#9662;</span></button></div>
    <div class="i-row i-row-advanced"><label>NameHash</label><input type="text" disabled data-hash="nameHash" value="${toHex32(shape.nameHash)}"></div>
    <div class="i-section">Collision cloud</div>
    <div class="i-row"><label>${shape.cloudLocal ? "Cloud" : "No cloud"}</label>${shape.cloudLocal
      ? `<button type="button" class="i-bt-box" id="cloud-open" title="Edit this bound's collision cloud"><span>${shape.cloudLocal.length} ${shape.cloudLocal.length === 1 ? "vertex" : "vertices"}</span><span class="i-bt-caret">&#9656;</span></button>`
      : '<button type="button" class="i-bt-box" id="cloud-add" title="Add a collision cloud to this bound"><span>+ Cloud</span></button>'}</div>
  `;
  infoPanelEl.style.display = "block";
  refreshShapeHints(shape);

  const warnEl = infoPanelEl.querySelector("#orient-warn");
  function refreshWarn() { warnEl.textContent = orientWarningText(shape); }
  refreshWarn();

  infoPanelEl.querySelectorAll("input[data-kind]").forEach((input) => {
    wireCommit(input, () => {
      const kind = input.dataset.kind;
      const axis = input.dataset.axis !== undefined ? parseInt(input.dataset.axis, 10) : null;
      applyDirectEdit(shape, kind, axis, parseFloat(input.value));
      // applyDirectEdit() sets each field's own warning (including #orient-warn); calling
      // refreshWarn() here would overwrite a clamp warning.
    });
  });
  infoPanelEl.querySelectorAll("input[data-int]").forEach((input) => {
    wireCommit(input, () => applyIntFieldEdit(shape, input.dataset.int, input.value));
  });
  infoPanelEl.querySelectorAll("input[data-hash]").forEach((input) => {
    wireCommit(input, () => {
      applyHashFieldEdit(shape, input.dataset.hash, input.value);
      input.value = toHex32(shape[input.dataset.hash]); // also resets an invalid entry
    });
  });
  const cloudOpen = infoPanelEl.querySelector("#cloud-open");
  if (cloudOpen) {
    cloudOpen.classList.toggle("open", cloudPanelShapeName === shape.name);
    cloudOpen.addEventListener("click", () => {
      if (cloudPanelShapeName === shape.name) closeCloudPanel(); else openCloudPanel(shape);
      cloudOpen.classList.toggle("open", cloudPanelShapeName === shape.name);
    });
    cloudOpen.addEventListener("pointerdown", (e) => e.stopPropagation());
  }
  const cloudAdd = infoPanelEl.querySelector("#cloud-add");
  if (cloudAdd) {
    cloudAdd.addEventListener("click", () => {
      if (addCloud(shape)) openCloudPanel(shape);
    });
    cloudAdd.addEventListener("pointerdown", (e) => e.stopPropagation());
  }
  if (cloudPanelShapeName === shape.name) positionCloudPanel();
  const btBox = infoPanelEl.querySelector("#boundtype-box");
  btBox.addEventListener("click", () => {
    if (advancedUnlocked[shape.name]) setBoundTypeMenu(shape, boundTypeMenuOpen !== shape.name);
  });
  btBox.addEventListener("pointerdown", (e) => e.stopPropagation());
  const sfBox = infoPanelEl.querySelector("#surface-box");
  sfBox.addEventListener("click", () => {
    if (advancedUnlocked[shape.name]) setSurfaceMenu(shape, surfaceMenuOpen !== shape.name);
  });
  sfBox.addEventListener("pointerdown", (e) => e.stopPropagation());
  syncSurfaceUi(shape);
  const unlockBox = infoPanelEl.querySelector("#unlock-other");
  unlockBox.checked = !!advancedUnlocked[shape.name];
  syncAdvancedRows(unlockBox.checked);
  setBoundTypeMenu(shape, unlockBox.checked && boundTypeMenuOpen === shape.name);
  setSurfaceMenu(shape, unlockBox.checked && surfaceMenuOpen === shape.name);
  unlockBox.addEventListener("change", (e) => {
    advancedUnlocked[shape.name] = e.target.checked;
    syncAdvancedRows(e.target.checked);
    if (!e.target.checked) {
      setBoundTypeMenu(shape, false);
      setSurfaceMenu(shape, false);
    }
  });
  infoPanelEl.querySelector("#unlock-other").addEventListener("pointerdown", (e) => e.stopPropagation());
  infoPanelEl.querySelector(".i-close").addEventListener("click", () => {
    closeBoundTypeMenu();
    closeSurfaceMenu();
    infoPanelEl.style.display = "none";
    setOpenInfoShape(null);
  });
}

// --------------------------------------------------------------
// Edits
// --------------------------------------------------------------
// BoundType 64 (Box only): corner edits only resize HalfDimension; Position is left unchanged.
const KBOUNDS_BOX_ONLY = 64;

// Position and HalfDimension are int16 / 1000 in the file. Pin edits clamp like applyDirectEdit, so
// no shape holds a value the export would saturate.
function clampStorablePosition(shape) {
  const clamped = shape.position.map((v) => Math.max(-MAX_STORABLE_UNIT, Math.min(MAX_STORABLE_UNIT, v)));
  const changed = clamped.some((v, i) => v !== shape.position[i]);
  shape.position = clamped;
  return changed;
}

// Box corner edit: resize one side, the opposite side stays fixed (position += R @ s*(newHalf -
// oldHalf)). Skipped for KBOUNDS_BOX_ONLY.
function applyBoxCornerEdit(shape, pointIndex, axis, newLocalValue) {
  const s = BOX_SIGNS[pointIndex][axis];
  const oldHalf = shape.halfDim[axis];
  let newHalf = s * newLocalValue;
  if (newHalf <= 1e-5) return; // refuse to collapse/invert the box
  let clamped = false;
  if (newHalf > MAX_STORABLE_UNIT) {
    newHalf = MAX_STORABLE_UNIT;
    clamped = true;
  }

  // A root that is the only shape sits at the origin in the game: leave Position untouched.
  if (shape.boundType !== KBOUNDS_BOX_ONLY && !gameRootAlone(shape)) {
    const shiftVec = [0,0,0];
    shiftVec[axis] = s * (newHalf - oldHalf);
    shape.position = vadd(shape.position, matVec(shape.R, shiftVec));
    if (clampStorablePosition(shape)) clamped = true;
  }
  if (clamped) structureWarn(`Values past \u00b1${MAX_STORABLE_UNIT} can't be stored - clamped.`);
  shape.halfDim[axis] = newHalf;
  if (!shape.radiusManual && RADIUS_FORMAT === "float") {
    const maxDim = Math.max(shape.halfDim[0], shape.halfDim[1], shape.halfDim[2]);
    shape.radiusDecoded = maxDim;
    shape.radiusRaw = floatToRawUint32(maxDim);
  }

  updateShapeGeometry(shape);
  const changed = isShapeDirty(shape);
  markDirty(shape, changed);
  refreshPinsForShape(shape.name);
  if (shape.boundType !== KBOUNDS_BOX_ONLY) {
    // Position changed, so descendants move too.
    descendantsOf(shape).forEach((d) => { updateShapeGeometry(d); refreshPinsForShape(d.name); });
  }
  if (openInfoShape === shape) refreshInfoPanelReadouts(shape);
}

// Sphere center edit: translation only.
function applySphereCenterEdit(shape, axis, newWorldValue) {
  if (gameRootAlone(shape)) {
    structureWarn("The game places this sphere at the origin (its Position is ignored as the only collision shape).");
    return;
  }
  // world center = worldPoint(shape, [0,0,0], mode)
  // Solve for shape.position holding the OTHER two WORLD axes constant.
  const currentWorld = worldPoint(shape, [0,0,0], pivotMode);
  const delta = newWorldValue - currentWorld[axis];
  const deltaVec = [0,0,0]; deltaVec[axis] = delta;
  // Position lives in the parent frame: rotate the world delta back through the inverse combined
  // ancestor rotation (identity without a parent).
  const ancR = ancestorRotationProduct(shape);
  const deltaPos = matTVec(ancR, deltaVec);
  shape.position = vadd(shape.position, deltaPos);
  if (clampStorablePosition(shape)) structureWarn(`Values past \u00b1${MAX_STORABLE_UNIT} can't be stored - clamped.`);

  refreshShapeAndDescendants(shape); // position changed, so descendants move too
  const changed = isShapeDirty(shape);
  markDirty(shape, changed);
  if (openInfoShape === shape) refreshInfoPanelReadouts(shape);
}

function currentLocalCornerValue(shape, pointIndex, axis) {
  return BOX_SIGNS[pointIndex][axis] * shape.halfDim[axis];
}
function currentWorldPoint(shape, pointIndex) {
  if (shape.type === "sphere") return worldPoint(shape, [0,0,0], pivotMode);
  const signs = BOX_SIGNS[pointIndex];
  const local = [signs[0]*shape.halfDim[0], signs[1]*shape.halfDim[1], signs[2]*shape.halfDim[2]];
  return worldPoint(shape, local, pivotMode);
}
function currentCloudWorldPoint(shape, index) {
  return worldPoint(shape, shape.cloudLocal[index], pivotMode);
}

// --------------------------------------------------------------
// Pin panels
// --------------------------------------------------------------
const pins = {};
function pinKey(shapeName, kind, pointIndex) { return shapeName + "#" + kind + "#" + pointIndex; }
// Shared numeric formatter: 7 decimals (drops float32 -> float64 noise), trailing zeros stripped.
// Position/HalfDimension/Pivot only hold 3 decimals (int16 / 1000).
function fmt(n) {
  if (!Number.isFinite(n)) return "0";
  if (Math.abs(n) < 1e-9) return "0";
  return parseFloat(n.toFixed(7)).toString();
}
// Message line for refused or altered edits (zero size, BoundType 64 position lock, int16
// overflow), so the input never disagrees with the shape or the export.
const FIELD_WARN_EL_ID = {
  position: "position-warn", halfDim: "halfdim-warn", pivot: "pivot-warn",
  radius: "radius-warn", orientAxis: "orient-warn", orientAngle: "orient-warn",
};
function setFieldWarn(kind, msg) {
  const id = FIELD_WARN_EL_ID[kind];
  const el = id && document.getElementById(id);
  if (el) el.textContent = msg || "";
}

function applyCloudPointEdit(shape, index, axis, value) {
  if (Number.isNaN(value)) return;
  shape.cloudLocal[index][axis] = value;
  updateShapeGeometry(shape);
  markDirty(shape, isShapeDirty(shape));
  refreshPinsForShape(shape.name);
}

function boundTypeNamesText(v) {
  return `${v} \u00b7 ${decodeBoundType(v)}`;
}

function setBoundTypeWarn(msg) {
  const el = document.getElementById("boundtype-warn");
  if (el) el.textContent = msg || "";
  if (boundTypeMenuOpen !== null) positionBoundTypeMenu();
}

function boundFlagLocked(bit) {
  return (bit & BOUNDTYPE_LOCKED_MASK) !== 0;
}

function boundFlagTitle(bit) {
  if (!boundFlagLocked(bit)) return toHex32(bit);
  return bit === KBOUNDS_PRIM_VS_OWN_PARTS ? "Unused in Most Wanted" : "Locked (Box/Sphere)";
}

function boundTypeLockMessage(oldType, newType) {
  const changed = oldType ^ newType;
  if (changed & (KBOUNDS_BOX_FLAG | KBOUNDS_SPHERE_FLAG)) return "Box/Sphere type is locked.";
  return changed & BOUNDTYPE_LOCKED_MASK ? "PrimVsOwnParts is unused in Most Wanted." : "";
}

function closeBoundTypeMenu() {
  boundTypeMenuOpen = null;
  btMenuEl.classList.remove("open");
  const box = infoPanelEl.querySelector("#boundtype-box");
  if (box) {
    box.classList.remove("open");
    box.setAttribute("aria-expanded", "false");
  }
}

function renderBoundTypeMenu(shape) {
  btMenuEl.innerHTML = `<div class="bt-flags">${BOUND_FLAGS.map(([bit, name]) => {
    const locked = boundFlagLocked(bit);
    return `<label class="${locked ? "locked" : ""}" title="${boundFlagTitle(bit)}"><input type="checkbox" data-flag="${bit}" ${locked ? "disabled" : ""} ${shape.boundType & bit ? "checked" : ""}> ${name}</label>`;
  }).join("")}</div><div class="bt-warn" id="boundtype-warn"></div>`;
}

function positionAnchoredMenu(menuEl, anchorEl, minLeft) {
  if (!anchorEl) return;
  const anchor = anchorEl.getBoundingClientRect();
  const panel = infoPanelEl.getBoundingClientRect();
  const leftEdge = cloudPanelShapeName !== null ? cloudPanelEl.getBoundingClientRect().left : panel.left;
  const w = menuEl.offsetWidth, h = menuEl.offsetHeight;
  if (leftEdge - w - 6 >= minLeft) {
    menuEl.style.left = (leftEdge - w - 6) + "px";
    menuEl.style.top = Math.max(8, Math.min(anchor.top + anchor.height / 2 - h / 2, window.innerHeight - h - 8)) + "px";
    return;
  }
  let top = anchor.bottom + 6;
  if (top + h > window.innerHeight - 8) top = Math.max(8, anchor.top - h - 6);
  menuEl.style.left = Math.max(8, Math.min(anchor.right - w, window.innerWidth - w - 8)) + "px";
  menuEl.style.top = top + "px";
}

function positionBoundTypeMenu() {
  positionAnchoredMenu(btMenuEl, infoPanelEl.querySelector("#boundtype-box"), 8);
}

// Keeps clear of the legend and the Pivot box when there is room to the left of the panel.
function positionSurfaceMenu() {
  const legendRight = Math.max(
    document.getElementById("legend").getBoundingClientRect().right,
    document.getElementById("mode-toggle-wrap").getBoundingClientRect().right
  );
  positionAnchoredMenu(sfMenuEl, infoPanelEl.querySelector("#surface-box"), Math.max(8, legendRight + 6));
}

function setBoundTypeMenu(shape, open) {
  if (!open) {
    closeBoundTypeMenu();
    return;
  }
  closeSurfaceMenu();
  boundTypeMenuOpen = shape.name;
  const box = infoPanelEl.querySelector("#boundtype-box");
  if (box) {
    box.classList.add("open");
    box.setAttribute("aria-expanded", "true");
  }
  renderBoundTypeMenu(shape);
  btMenuEl.classList.add("open");
  positionBoundTypeMenu();
  boundTypeMenuScrollTop = infoPanelEl.scrollTop;
}

function closeSurfaceMenu() {
  surfaceMenuOpen = null;
  sfMenuEl.classList.remove("open");
  const box = infoPanelEl.querySelector("#surface-box");
  if (box) {
    box.classList.remove("open");
    box.setAttribute("aria-expanded", "false");
  }
}

function surfaceItem(className, nameText, hexText) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sf-item " + className;
  const name = document.createElement("span");
  name.className = "sf-name";
  name.textContent = nameText;
  btn.appendChild(name);
  if (hexText) {
    const hex = document.createElement("span");
    hex.className = "sf-hex";
    hex.textContent = hexText;
    btn.appendChild(hex);
  }
  return btn;
}

function renderSurfaceMenu(shape) {
  sfMenuEl.textContent = "";
  if (SURFACE_NAMES.length > SURFACE_SEARCH_MIN_ITEMS) {
    const search = document.createElement("input");
    search.type = "text";
    search.className = "sf-search";
    search.placeholder = "Search...";
    search.spellcheck = false;
    sfMenuEl.appendChild(search);
  }
  const list = document.createElement("div");
  list.className = "sf-list";
  if (!SURFACE_NAMES.length) {
    const empty = document.createElement("div");
    empty.className = "sf-empty";
    empty.textContent = "No names loaded. Put SurfaceNames.txt in the Engine folder next to core.py.";
    list.appendChild(empty);
  }
  SURFACE_NAMES.forEach(([name, hash]) => {
    const item = surfaceItem("sf-entry", name, toHex32(hash));
    item.dataset.hash = String(hash >>> 0);
    item.dataset.search = (name + " " + toHex32(hash)).toLowerCase();
    list.appendChild(item);
  });
  const none = document.createElement("div");
  none.className = "sf-empty sf-nomatch";
  none.textContent = "No match.";
  none.style.display = "none";
  list.appendChild(none);
  sfMenuEl.appendChild(list);

  const sep = document.createElement("div");
  sep.className = "sf-sep";
  sfMenuEl.appendChild(sep);
  sfMenuEl.appendChild(surfaceItem("sf-custom", "Custom hash...", ""));
  const row = document.createElement("div");
  row.className = "sf-custom-row";
  row.style.display = "none";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "sf-custom-input";
  input.placeholder = "0x00000000";
  input.spellcheck = false;
  const set = document.createElement("button");
  set.type = "button";
  set.className = "sf-set";
  set.textContent = "Set";
  row.appendChild(input);
  row.appendChild(set);
  sfMenuEl.appendChild(row);
  const warn = document.createElement("div");
  warn.className = "sf-warn";
  sfMenuEl.appendChild(warn);
  markSurfaceActive(shape);
}

function markSurfaceActive(shape) {
  const current = shape.surfaceNameHash >>> 0;
  sfMenuEl.querySelectorAll(".sf-entry").forEach((item) => {
    item.classList.toggle("active", parseInt(item.dataset.hash, 10) === current);
  });
  const custom = sfMenuEl.querySelector(".sf-custom");
  if (custom) custom.classList.toggle("active", !SURFACE_NAME_BY_HASH.has(current));
}

function syncSurfaceUi(shape) {
  const hash = shape.surfaceNameHash >>> 0;
  const label = infoPanelEl.querySelector("#surface-label");
  if (label) label.textContent = surfaceLabel(hash);
  const box = infoPanelEl.querySelector("#surface-box");
  if (box) box.title = SURFACE_NAME_BY_HASH.has(hash) ? SURFACE_NAME_BY_HASH.get(hash) + " - " + toHex32(hash) : "Click to choose the SurfaceName";
  if (surfaceMenuOpen === shape.name) markSurfaceActive(shape);
}

function setSurfaceMenu(shape, open) {
  if (!open) {
    closeSurfaceMenu();
    return;
  }
  closeBoundTypeMenu();
  surfaceMenuOpen = shape.name;
  const box = infoPanelEl.querySelector("#surface-box");
  if (box) {
    box.classList.add("open");
    box.setAttribute("aria-expanded", "true");
  }
  renderSurfaceMenu(shape);
  sfMenuEl.classList.add("open");
  positionSurfaceMenu();
  surfaceMenuScrollTop = infoPanelEl.scrollTop;
  const list = sfMenuEl.querySelector(".sf-list");
  const active = list.querySelector(".sf-entry.active");
  if (active) list.scrollTop = Math.max(0, active.offsetTop - (list.clientHeight - active.offsetHeight) / 2);
}

function commitSurfaceHash(hash) {
  const shape = surfaceMenuOpen !== null ? shapes[surfaceMenuOpen] : null;
  if (!shape) return;
  applyHashFieldEdit(shape, "surfaceNameHash", toHex32(hash));
  syncSurfaceUi(shape);
  closeSurfaceMenu();
}

function openSurfaceCustomRow(shape) {
  const row = sfMenuEl.querySelector(".sf-custom-row");
  const input = sfMenuEl.querySelector(".sf-custom-input");
  const warn = sfMenuEl.querySelector(".sf-warn");
  const show = row.style.display === "none";
  row.style.display = show ? "flex" : "none";
  warn.textContent = "";
  if (show) {
    input.value = SURFACE_NAME_BY_HASH.has(shape.surfaceNameHash >>> 0) ? "" : toHex32(shape.surfaceNameHash);
    input.focus();
    input.select();
  }
  positionSurfaceMenu();
}

function commitSurfaceCustom() {
  const input = sfMenuEl.querySelector(".sf-custom-input");
  const hash = parseHashText(input.value);
  if (hash === null) {
    sfMenuEl.querySelector(".sf-warn").textContent = "Enter a hex value of up to 8 digits, e.g. 0x6CA26F9B.";
    positionSurfaceMenu();
    return;
  }
  commitSurfaceHash(hash);
}

function filterSurfaceList(text) {
  const q = text.trim().toLowerCase();
  let shown = 0;
  sfMenuEl.querySelectorAll(".sf-entry").forEach((item) => {
    const match = !q || item.dataset.search.includes(q);
    item.style.display = match ? "" : "none";
    if (match) shown += 1;
  });
  const none = sfMenuEl.querySelector(".sf-nomatch");
  if (none) none.style.display = shown || !SURFACE_NAMES.length ? "none" : "";
}

function syncBoundTypeUi(shape) {
  btMenuEl.querySelectorAll("input[data-flag]").forEach((input) => {
    const bit = parseInt(input.dataset.flag, 10);
    const locked = boundFlagLocked(bit);
    input.checked = !!(shape.boundType & bit);
    input.disabled = locked;
    if (input.parentElement) {
      input.parentElement.classList.toggle("locked", locked);
      input.parentElement.title = boundFlagTitle(bit);
    }
  });
  const hex = infoPanelEl.querySelector("#boundtype-hex");
  if (hex) hex.textContent = toHex32(shape.boundType);
  const names = infoPanelEl.querySelector("#boundtype-names");
  if (names) names.textContent = boundTypeNamesText(shape.boundType);
  refreshShapeHints(shape);
}

function refreshInactiveState(shape) {
  const inactive = !(shape.boundType & KBOUNDS_ACTIVE_MASK);
  if (inactive === shape.inactive) return;
  shape.inactive = inactive;
  if (shape.edges) {
    shape.edges.material.transparent = inactive;
    shape.edges.material.opacity = inactive ? 0.35 : 1;
    shape.edges.material.needsUpdate = true;
  }
  const row = shape.legendRow;
  if (!row) return;
  const nameSpan = row.querySelector(".legend-name");
  const tag = row.querySelector(".legend-tag:not(.warn):not(.alone)");
  if (nameSpan) nameSpan.title = "Click to see/edit all fields" + (inactive ? " - helper bound" : "");
  if (inactive && !tag && nameSpan) {
    nameSpan.after(makeLegendTag("helper"));
  } else if (!inactive && tag) {
    tag.remove();
  }
}

function syncBoxOnlyPinNotes(shape) {
  if (shape.type !== "box") return;
  const boxOnly = shape.boundType === KBOUNDS_BOX_ONLY;
  Object.values(pins).forEach((pin) => {
    if (pin.shapeName !== shape.name || pin.kind === "cloud") return;
    const note = pin.el.querySelector(".p-note");
    if (boxOnly && !note) {
      const label = pin.el.querySelector(".p-section-label");
      if (!label) return;
      const newNote = document.createElement("div");
      newNote.className = "p-note";
      newNote.textContent = "Editing resizes Half-Dimension only.";
      label.after(newNote);
    } else if (!boxOnly && note) {
      note.remove();
    }
  });
}

function applyBoundTypeEdit(shape, newType) {
  if (!Number.isInteger(newType) || newType < 0 || newType > 0xFFFF) return;
  if (newType === shape.boundType) return;
  const lockMessage = boundTypeLockMessage(shape.boundType, newType);
  if (lockMessage) {
    setBoundTypeWarn(lockMessage);
    syncBoundTypeUi(shape);
    return;
  }
  shape.boundType = newType;
  refreshInactiveState(shape);
  refreshGameState();
  markDirty(shape, isShapeDirty(shape));
  syncBoxOnlyPinNotes(shape);
  if (openInfoShape === shape) {
    syncBoundTypeUi(shape);
    setBoundTypeWarn("");
  }
}

const undoStack = [];
const redoStack = [];
const HISTORY_LIMIT = 300;
let historyCoalesceKey = null;
const advancedUnlocked = {};

function snapshotShape(shape) {
  return {
    position: shape.position.slice(), halfDim: shape.halfDim.slice(), pivot: shape.pivot.slice(), quat: shape.quat.slice(),
    boundType: shape.boundType,
    childrenIndex: shape.childrenIndex, numberOfChildren: shape.numberOfChildren, collisionCloudIndex: shape.collisionCloudIndex,
    cloudSlot: shape.cloudSlot,
    radiusRaw: shape.radiusRaw, radiusDecoded: shape.radiusDecoded, radiusManual: shape.radiusManual,
    surfaceNameHash: shape.surfaceNameHash, nameHash: shape.nameHash,
    cloudLocal: shape.cloudLocal ? shape.cloudLocal.map((v) => v.slice()) : null,
  };
}

function recordShapeEdit(shape, before, key) {
  if (JSON.stringify(before) === JSON.stringify(snapshotShape(shape))) return;
  if (key && key === historyCoalesceKey) return;
  historyCoalesceKey = key;
  undoStack.push({ name: shape.name, state: before });
  if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
  redoStack.length = 0;
}

// One history step per focused input (typing in a pin field); focusing any field starts a new step.
window.addEventListener("focusin", () => { historyCoalesceKey = null; });

function withHistory(fn) {
  return function (shape, ...rest) {
    const before = snapshotShape(shape);
    const result = fn.call(this, shape, ...rest);
    const active = document.activeElement;
    recordShapeEdit(shape, before, active && active.tagName === "INPUT" && pinsHolder.contains(active) ? active : null);
    return result;
  };
}

applyDirectEdit = withHistory(applyDirectEdit);
applyIntFieldEdit = withHistory(applyIntFieldEdit);
applyHashFieldEdit = withHistory(applyHashFieldEdit);
applyBoxCornerEdit = withHistory(applyBoxCornerEdit);
applySphereCenterEdit = withHistory(applySphereCenterEdit);
applyCloudPointEdit = withHistory(applyCloudPointEdit);
applyBoundTypeEdit = withHistory(applyBoundTypeEdit);

function syncAdvancedRows(on) {
  infoPanelEl.querySelectorAll("input[data-int], input[data-hash], #boundtype-box, #surface-box, input[data-kind=\"radius\"]").forEach((input) => {
    input.disabled = !on;
  });
  infoPanelEl.querySelectorAll(".i-row-advanced").forEach((row) => {
    row.classList.toggle("unlocked", on);
  });
}

function refreshInfoPanelAll(shape) {
  refreshInfoPanelReadouts(shape);
  infoPanelEl.querySelectorAll("input[data-int]").forEach((input) => { input.value = shape[input.dataset.int]; });
  infoPanelEl.querySelectorAll("input[data-hash]").forEach((input) => { input.value = toHex32(shape[input.dataset.hash]); });
  syncSurfaceUi(shape);
  infoPanelEl.querySelectorAll(".i-field-warn").forEach((el) => { el.textContent = ""; });
  setBoundTypeWarn("");
  syncBoundTypeUi(shape);
  const orientWarn = infoPanelEl.querySelector("#orient-warn");
  if (orientWarn) orientWarn.textContent = orientWarningText(shape);
}

function assignShapeState(shape, state) {
  shape.boundType = state.boundType;
  shape.position = state.position.slice();
  shape.halfDim = state.halfDim.slice();
  shape.pivot = state.pivot.slice();
  shape.quat = state.quat.slice();
  shape.R = quatToRotMat(shape.quat[0], shape.quat[1], shape.quat[2], shape.quat[3]);
  shape.childrenIndex = state.childrenIndex;
  shape.numberOfChildren = state.numberOfChildren;
  shape.collisionCloudIndex = state.collisionCloudIndex;
  shape.cloudSlot = state.cloudSlot;
  shape.radiusRaw = state.radiusRaw;
  shape.radiusDecoded = state.radiusDecoded;
  shape.radiusManual = state.radiusManual;
  shape.surfaceNameHash = state.surfaceNameHash;
  shape.nameHash = state.nameHash;
  if (state.cloudLocal && shape.cloudLocal && state.cloudLocal.length === shape.cloudLocal.length) {
    state.cloudLocal.forEach((v, i) => v.forEach((c, axis) => { shape.cloudLocal[i][axis] = c; }));
  }
  if (shape.radiusManual) advancedUnlocked[shape.name] = true;
}

function restoreShape(shape, state) {
  const hierarchyChanged = shape.childrenIndex !== state.childrenIndex || shape.numberOfChildren !== state.numberOfChildren;
  const boundTypeChanged = shape.boundType !== state.boundType;
  assignShapeState(shape, state);
  refreshInactiveState(shape);
  refreshGameState();
  markDirty(shape, isShapeDirty(shape));
  if (hierarchyChanged) {
    rebuildLegendTree();
    Object.values(shapes).forEach((s) => { updateShapeGeometry(s); refreshPinsForShape(s.name); });
  } else {
    refreshShapeAndDescendants(shape);
  }
  if (boundTypeChanged) syncBoxOnlyPinNotes(shape);
  syncUnresolved();
  if (openInfoShape === shape) {
    const box = infoPanelEl.querySelector("#unlock-other");
    if (box) { box.checked = !!advancedUnlocked[shape.name]; syncAdvancedRows(box.checked); }
    refreshInfoPanelAll(shape);
  }
}

// Every step toasts "Undo: <bound or topic>" / "Redo: ...", whatever the kind of edit.
function stepHistory(from, to, label) {
  let item = from.pop();
  // A per-bound entry whose bound no longer exists cannot be applied; skip to the next one.
  while (item && !item.world && !shapes[item.name]) item = from.pop();
  if (!item) return;
  historyCoalesceKey = null;
  if (item.world) {
    to.push({ world: true, state: snapshotWorld(), names: item.names, text: item.text });
    restoreWorld(item.state);
    const present = (item.names || []).map((n) => shapes[n]).find(Boolean);
    showModelToast(label + ": " + (present ? shapeLabel(present) : item.text || "structure"), "info");
    return;
  }
  const shape = shapes[item.name];
  to.push({ name: item.name, state: snapshotShape(shape) });
  restoreShape(shape, item.state);
  showModelToast(label + ": " + shapeLabel(shape), "info");
}

document.addEventListener("pointerdown", (e) => {
  if (boundTypeMenuOpen === null) return;
  if (e.target instanceof Element && e.target.closest("#boundtype-box, #boundtype-menu")) return;
  closeBoundTypeMenu();
}, true);
window.addEventListener("keydown", (e) => {
  if (boundTypeMenuOpen === null || (e.key !== "Escape" && e.key !== "Enter")) return;
  if (e.key === "Enter" && e.target instanceof Element && e.target.closest("#boundtype-box, #boundtype-menu")) {
    e.preventDefault();
    e.stopPropagation();
  }
  closeBoundTypeMenu();
}, true);
window.addEventListener("resize", closeBoundTypeMenu);
infoPanelEl.addEventListener("scroll", () => {
  if (infoPanelEl.scrollTop !== boundTypeMenuScrollTop) closeBoundTypeMenu();
});
document.addEventListener("pointerdown", (e) => {
  if (surfaceMenuOpen === null) return;
  if (e.target instanceof Element && e.target.closest("#surface-box, #surface-menu")) return;
  closeSurfaceMenu();
}, true);
window.addEventListener("keydown", (e) => {
  if (surfaceMenuOpen !== null && e.key === "Escape") closeSurfaceMenu();
}, true);
window.addEventListener("resize", closeSurfaceMenu);
infoPanelEl.addEventListener("scroll", () => {
  if (surfaceMenuOpen !== null && infoPanelEl.scrollTop !== surfaceMenuScrollTop) closeSurfaceMenu();
});
sfMenuEl.addEventListener("pointerdown", (e) => e.stopPropagation());
sfMenuEl.addEventListener("click", (e) => {
  const shape = surfaceMenuOpen !== null ? shapes[surfaceMenuOpen] : null;
  if (!shape || !(e.target instanceof Element)) return;
  const entry = e.target.closest(".sf-entry");
  if (entry) { commitSurfaceHash(parseInt(entry.dataset.hash, 10)); return; }
  if (e.target.closest(".sf-custom")) { openSurfaceCustomRow(shape); return; }
  if (e.target.closest(".sf-set")) commitSurfaceCustom();
});
sfMenuEl.addEventListener("input", (e) => {
  if (e.target.classList && e.target.classList.contains("sf-search")) filterSurfaceList(e.target.value);
  else if (e.target.classList && e.target.classList.contains("sf-custom-input")) sfMenuEl.querySelector(".sf-warn").textContent = "";
});
sfMenuEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.classList && e.target.classList.contains("sf-custom-input")) {
    e.preventDefault();
    commitSurfaceCustom();
  }
});
btMenuEl.addEventListener("pointerdown", (e) => e.stopPropagation());
btMenuEl.addEventListener("change", (e) => {
  const input = e.target;
  if (!input.dataset || !input.dataset.flag || !openInfoShape) return;
  const bit = parseInt(input.dataset.flag, 10);
  applyBoundTypeEdit(openInfoShape, input.checked ? (openInfoShape.boundType | bit) : (openInfoShape.boundType & ~bit & 0xFFFF));
});

document.addEventListener("focusin", (e) => {
  historyCoalesceKey = null;
  if (e.target.tagName === "INPUT") e.target.dataset.focusValue = e.target.value;
});
document.addEventListener("focusout", () => { historyCoalesceKey = null; });

// Only text-entry controls keep the native Ctrl+Z; a focused radio/checkbox/button (e.g. after
// choosing a Pivot mode) must not swallow it.
const TEXT_INPUT_TYPES = new Set(["text", "number", "search", "tel", "url", "email", "password", ""]);
function isTextEntry(el) {
  return !!el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && TEXT_INPUT_TYPES.has(el.type)));
}

// The canvas handlers cancel the focus change on a press, which leaves a typed value uncommitted.
// Blur the focused field on any press outside it.
document.addEventListener("pointerdown", (e) => {
  const active = document.activeElement;
  if (active && active !== document.body && e.target !== active && isTextEntry(active)) active.blur();
}, true);

window.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const isRedo = (e.code === "KeyZ" && e.shiftKey) || e.code === "KeyY";
  const isUndo = e.code === "KeyZ" && !e.shiftKey;
  if (!isUndo && !isRedo) return;
  const active = document.activeElement;
  if (active && active !== document.body && !isTextEntry(active)) active.blur();
  if (isTextEntry(active)) {
    const inPins = pinsHolder.contains(active);
    if (!inPins && !infoPanelEl.contains(active) && !btMenuEl.contains(active) && !cloudPanelEl.contains(active)) return;
    if (!inPins && active.value !== active.dataset.focusValue) return;
    active.blur();
  }
  e.preventDefault();
  if (isRedo) stepHistory(redoStack, undoStack, "Redo"); else stepHistory(undoStack, redoStack, "Undo");
});

// --------------------------------------------------------------
// Adding / deleting bounds and clouds
// --------------------------------------------------------------
// A new bound is the last child of the selected bound (end of its child block, or appended to the
// file for a first child). Delete removes the bound and its descendants. Both renumber
// ChildrenIndex/NumberOfChildren/CollisionCloudIndex, validate before mutating, and are one undo
// step (full-layout snapshot).
let nextNewBoundId = 1;
const MAX_BOUNDS = 32767;
const MAX_CHILDREN = 255;
const MAX_CLOUDS = 127;
const KBOUNDS_MESH_VS_GROUND = 0x10;

function shapeLabel(shape) { return "Bound_" + shape.index; }

function boundsInOrder() { return Object.values(shapes).sort((a, b) => a.index - b.index); }

function colorForIndex(i) {
  return "#" + new THREE.Color().setHSL((i * 0.6180339887498949) % 1, 0.65, 0.55).getHexString().toUpperCase();
}

function detachShape(shape) {
  scene.remove(shape.group);
  delete shapes[shape.name];
  const drop = new Set(shape.markers.concat(shape.cloudPoints || []));
  for (let i = markerMeshes.length - 1; i >= 0; i--) {
    if (drop.has(markerMeshes[i])) markerMeshes.splice(i, 1);
  }
}

function attachShape(shape) {
  shapes[shape.name] = shape;
  scene.add(shape.group);
  shape.markers.forEach((m) => markerMeshes.push(m));
  (shape.cloudPoints || []).forEach((m) => markerMeshes.push(m));
}

function unpinAll() {
  Object.values(pins).forEach((pin) => unpin(pin.shapeName, pin.kind, pin.pointIndex));
}

function refreshAfterStructureChange() {
  unpinAll();
  closeStructureMenu();
  const list = boundsInOrder();
  list.forEach(refreshInactiveState);
  rebuildLegendTree();
  list.forEach((s) => {
    updateShapeGeometry(s);
    markDirty(s, isShapeDirty(s));
  });
  updateToggleAllLabel();
  if (openInfoShape && shapes[openInfoShape.name] !== openInfoShape) {
    setOpenInfoShape(null);
    infoPanelEl.style.display = "none";
  } else if (openInfoShape) {
    openInfoPanel(openInfoShape);
  }
  syncCloudPanel();
  updateSaveStatus();
}

function snapshotWorld() {
  return {
    shapes: Object.values(shapes).map((s) => ({
      shape: s,
      index: s.index,
      state: snapshotShape(s),
      cloudByteOffset: s.cloudByteOffset ? s.cloudByteOffset.slice() : null,
    })),
    clouds: cloudTable.map((e) => ({ orphan: e.orphan })),
  };
}

function restoreWorld(snap) {
  const keep = new Set(snap.shapes.map((x) => x.shape));
  Object.values(shapes).forEach((s) => { if (!keep.has(s)) detachShape(s); });
  snap.shapes.forEach(({ shape }) => { if (shapes[shape.name] !== shape) attachShape(shape); });
  snap.shapes.forEach(({ shape, index, state, cloudByteOffset }) => {
    shape.index = index;
    assignShapeState(shape, state);
    disposeCloudPoints(shape);
    if (state.cloudLocal) {
      shape.cloudLocal = state.cloudLocal.map((v) => v.slice());
      shape.cloudByteOffset = cloudByteOffset.slice();
      buildCloudPoints(shape);
    } else {
      shape.cloudLocal = null;
      shape.cloudByteOffset = null;
    }
  });
  cloudTable.length = 0;
  snap.clouds.forEach((e) => cloudTable.push({ orphan: e.orphan }));
  refreshAfterStructureChange();
}

// `who` labels the Undo/Redo toast: a bound (shown as its current Bound_n) or a short text.
function historyLabel(who) {
  if (!who) return { names: [], text: "structure" };
  if (typeof who === "string") return { names: [], text: who };
  return { names: [who.name], text: shapeLabel(who) };
}

function labelLastEdit(who) {
  Object.assign(undoStack[undoStack.length - 1], historyLabel(who));
}

function runStructuralEdit(apply, who) {
  const before = snapshotWorld();
  if (apply() === false) return false;
  undoStack.push(Object.assign({ world: true, state: before }, historyLabel(who)));
  if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
  redoStack.length = 0;
  historyCoalesceKey = null;
  return true;
}

function structureWarn(message) {
  showModelToast(message, "warn");
  return false;
}

function newBoundData(parent, kind, index) {
  const radius = 0.25;
  return {
    name: "Bound_n" + nextNewBoundId++,
    color: colorForIndex(index + BOUNDS.length),
    type: kind,
    inactive: false,
    byteOffset: null,
    halfDim: [radius, radius, radius],
    quat: [0, 0, 0, 1],
    pivot: [0, 0, 0],
    position: [0, 0, 0],
    radius,
    boundType: kind === "sphere" ? 0x82 : 0x46,
    childrenIndex: -1,
    numberOfChildren: 0,
    collisionCloudIndex: -1,
    radiusRaw: RADIUS_FORMAT === "float" ? floatToRawUint32(radius) : 0,
    surfaceNameHash: 0,
    nameHash: 0,
    cloudVertices: null,
  };
}

function addBound(parent, kind) {
  let created = null;
  const done = runStructuralEdit(() => {
    const all = boundsInOrder();
    if (all.length >= MAX_BOUNDS) return structureWarn("Bound limit reached.");
    if (parent.numberOfChildren >= MAX_CHILDREN) return structureWarn(`${shapeLabel(parent)} already has ${MAX_CHILDREN} children.`);
    const blockEnd = parent.childrenIndex + parent.numberOfChildren;
    if (parent.numberOfChildren > 0 && (parent.childrenIndex <= parent.index || blockEnd > all.length)) {
      return structureWarn(`${shapeLabel(parent)} has an invalid child range - see Unresolved items, or fix ChildrenIndex/NumberOfChildren first.`);
    }
    const at = parent.numberOfChildren > 0 ? blockEnd : all.length;
    all.forEach((s) => {
      if (s.index >= at) s.index += 1;
      if (s.numberOfChildren > 0 && s.childrenIndex >= at) s.childrenIndex += 1;
    });
    if (parent.numberOfChildren > 0) {
      parent.numberOfChildren += 1;
    } else {
      parent.childrenIndex = at;
      parent.numberOfChildren = 1;
    }
    created = createShape(newBoundData(parent, kind, at), at);
    return true;
  });
  if (!done) return null;
  labelLastEdit(created);
  refreshAfterStructureChange();
  openInfoPanel(created);
  return created;
}

// Removes cloud k from the table: its holder loses the points, record references to it become -1,
// and references to later clouds shift down.
function removeCloudEntry(k) {
  cloudTable.splice(k, 1);
  Object.values(shapes).forEach((s) => {
    if (s.cloudSlot === k) {
      disposeCloudPoints(s);
      s.cloudLocal = null;
      s.cloudByteOffset = null;
      s.cloudSlot = -1;
    } else if (s.cloudSlot > k) {
      s.cloudSlot -= 1;
    }
    if (s.collisionCloudIndex === k) s.collisionCloudIndex = -1;
    else if (s.collisionCloudIndex > k) s.collisionCloudIndex -= 1;
  });
}

function deleteBoundCore(target) {
  if (target.index === 0) return structureWarn("The root bound can't be deleted.");
  const all = boundsInOrder();
  const byIndex = new Map(all.map((s) => [s.index, s]));
  const removed = new Set([target].concat(descendantsOf(target)));
  const remaining = all.filter((s) => !removed.has(s));
  const newIndex = new Map(remaining.map((s, i) => [s, i]));
  const kidsOf = new Map();
  for (const s of remaining) {
    if (s.numberOfChildren <= 0) continue;
    const kids = [];
    for (let j = s.childrenIndex; j < s.childrenIndex + s.numberOfChildren; j++) {
      const kid = byIndex.get(j);
      if (!kid) return structureWarn(`${shapeLabel(s)} lists a child outside the file - fix its ChildrenIndex first.`);
      if (!removed.has(kid)) kids.push(kid);
    }
    for (let i = 1; i < kids.length; i++) {
      if (newIndex.get(kids[i]) !== newIndex.get(kids[i - 1]) + 1) return structureWarn(`${shapeLabel(s)} has a non-contiguous child range - fix it first.`);
    }
    kidsOf.set(s, kids);
  }
  const removedClouds = new Set();
  removed.forEach((s) => { if (s.cloudSlot >= 0) removedClouds.add(s.cloudSlot); });
  removed.forEach(detachShape);
  Array.from(removedClouds).sort((a, b) => b - a).forEach((k) => {
    if (k < cloudTable.length && !cloudTable[k].orphan) removeCloudEntry(k);
  });
  remaining.forEach((s) => {
    s.index = newIndex.get(s);
    if (kidsOf.has(s)) {
      const kids = kidsOf.get(s);
      s.numberOfChildren = kids.length;
      s.childrenIndex = kids.length ? newIndex.get(kids[0]) : -1;
    }
  });
  return true;
}

function deleteBound(target) {
  if (!runStructuralEdit(() => deleteBoundCore(target), target)) return false;
  refreshAfterStructureChange();
  return true;
}

// --------------------------------------------------------------
// Unresolved items
// --------------------------------------------------------------
// Records appended by other tools, or manual edits of the advanced fields, can leave entries the
// hierarchy and cloud table do not cover:
//   - child ranges: NumberOfChildren runs past the last bound, or ChildrenIndex is negative
//   - unassigned bounds: no bound lists them as a child
//   - unassigned clouds: no record references them (empty clouds are the usual case)
//   - mismatched cloud references: CollisionCloudIndex names a cloud another bound holds (zero-filled
//     records all carry index 0), a cloud nobody holds, a cloud that does not exist, or a different
//     cloud than the one whose points the bound holds
// CollisionCloudIndex is written as it stands; which bound holds a cloud's points is tracked
// separately (cloudSlot), so editing the field never moves or overwrites points.

function cloudHolderOf(k) {
  return boundsInOrder().find((s) => s.cloudSlot === k) || null;
}

// Coordinates of cloud k as stored in the file: read from the file for a cloud no bound holds,
// otherwise rebuilt from the holder's local offsets.
function cloudFilePoints(k) {
  const entry = cloudTable[k];
  if (entry.orphan) return entry.orphan.map((off) => [0, 4, 8].map((d) => fileView.getFloat32(off + d, true)));
  const holder = cloudHolderOf(k);
  return holder ? holder.cloudLocal.map((local) => localToParentFrame(holder, local)) : [];
}

function isEmptyBound(s) {
  return s.halfDim.every((v) => v === 0) && !(RADIUS_FORMAT === "float" && s.radiusDecoded > 0);
}

function childRangeBroken(s, total) {
  return s.numberOfChildren > 0 && (s.childrenIndex < 0 || s.childrenIndex + s.numberOfChildren > total);
}

function childRangeTrimmable(s, total) {
  return s.childrenIndex > s.index && s.childrenIndex < total;
}

function findUnresolved() {
  const all = boundsInOrder();
  const referenced = new Set(all.map((s) => s.collisionCloudIndex));
  return {
    ranges: all.filter((s) => childRangeBroken(s, all.length)),
    bounds: buildHierarchy().roots.filter((s) => s.index !== 0),
    refs: all.filter((s) => s.collisionCloudIndex >= 0 && s.collisionCloudIndex !== s.cloudSlot),
    clouds: cloudTable.map((_, k) => (referenced.has(k) ? -1 : k)).filter((k) => k >= 0),
  };
}

// Repair used by Fix all: match = record points at the cloud the bound holds; take = the bound
// holds the cloud it references (when no holder references it); clear = drop the reference.
function refFix(x) {
  const k = x.collisionCloudIndex;
  if (x.cloudSlot >= 0) return "match";
  const holder = k < cloudTable.length ? cloudHolderOf(k) : null;
  if (k < cloudTable.length && (!holder || holder.collisionCloudIndex !== k)) return "take";
  return "clear";
}

// Moves `x` and its subtree to the end of `target`'s child block (or to the end of the file when
// target has no children) and renumbers every ChildrenIndex. Validates before mutating.
function attachSubtreeCore(x, target) {
  const all = boundsInOrder();
  const byIndex = new Map(all.map((s) => [s.index, s]));
  const moved = new Set([x].concat(descendantsOf(x)));
  if (moved.has(target)) return structureWarn("A bound can't become a child of itself or of its own descendants.");
  if (Array.from(moved).some(inParentLoop)) return structureWarn(`${shapeLabel(x)} is part of a parent loop - fix its ChildrenIndex first.`);
  if (target.numberOfChildren >= MAX_CHILDREN) return structureWarn(`${shapeLabel(target)} already has ${MAX_CHILDREN} children.`);
  const kidsOf = new Map();
  for (const s of all) {
    if (s.numberOfChildren <= 0) continue;
    const kids = [];
    for (let j = s.childrenIndex; j < s.childrenIndex + s.numberOfChildren; j++) {
      const kid = byIndex.get(j);
      if (!kid) return structureWarn(`${shapeLabel(s)} lists a child outside the file - fix its ChildrenIndex first.`);
      kids.push(kid);
    }
    kidsOf.set(s, kids);
  }
  const rest = all.filter((s) => !moved.has(s));
  const block = kidsOf.get(target) || [];
  const last = block.length ? rest.indexOf(block[block.length - 1]) : -1;
  if (block.length && last < 0) return structureWarn(`${shapeLabel(target)} has an invalid child range - fix it first.`);
  const at = block.length ? last + 1 : rest.length;
  const order = rest.slice(0, at).concat([x], all.filter((s) => moved.has(s) && s !== x), rest.slice(at));
  const newIndex = new Map(order.map((s, i) => [s, i]));
  kidsOf.set(target, block.concat([x]));
  for (const [s, kids] of kidsOf) {
    for (let i = 1; i < kids.length; i++) {
      if (newIndex.get(kids[i]) !== newIndex.get(kids[i - 1]) + 1) return structureWarn(`${shapeLabel(s)} has a non-contiguous child range - fix it first.`);
    }
  }
  order.forEach((s, i) => { s.index = i; });
  for (const [s, kids] of kidsOf) {
    s.numberOfChildren = kids.length;
    s.childrenIndex = newIndex.get(kids[0]);
  }
  return true;
}

// Makes `shape` the holder of cloud k. The points keep their file coordinates and are read in the
// target's frame like any other cloud. `setFlag` also sets MeshVsGround, as addCloud() does.
function assignCloudCore(k, shape, setFlag) {
  const entry = cloudTable[k];
  if (!entry) return false;
  if (shape.cloudSlot >= 0) return structureWarn(`${shapeLabel(shape)} already has a collision cloud.`);
  if (shape.collisionCloudIndex !== -1 && shape.collisionCloudIndex !== k) return structureWarn(`Resolve ${shapeLabel(shape)} first.`);
  const previous = entry.orphan ? null : cloudHolderOf(k);
  if (!entry.orphan && !previous) return false;
  const points = cloudFilePoints(k);
  const offsets = entry.orphan ? entry.orphan.slice() : previous.cloudByteOffset.slice();
  if (previous) {
    disposeCloudPoints(previous);
    previous.cloudLocal = null;
    previous.cloudByteOffset = null;
    previous.cloudSlot = -1;
  }
  shape.collisionCloudIndex = k;
  shape.cloudSlot = k;
  shape.cloudLocal = points.map((p) => parentFrameToLocal(shape, p));
  shape.cloudByteOffset = offsets;
  if (setFlag) shape.boundType |= KBOUNDS_MESH_VS_GROUND;
  buildCloudPoints(shape);
  entry.orphan = null;
  return true;
}

// Fix all: repair or clear cloud references, delete empty clouds and empty bounds, attach the other
// unassigned bounds to the root. Clouds with vertices are left alone.
function applyRefFix(x) {
  const fix = refFix(x);
  if (fix === "match") x.collisionCloudIndex = x.cloudSlot;
  else if (fix === "take") return assignCloudCore(x.collisionCloudIndex, x, false);
  else x.collisionCloudIndex = -1;
  return true;
}

function trimChildRangeCore(shape) {
  const total = Object.keys(shapes).length;
  if (!childRangeBroken(shape, total) || !childRangeTrimmable(shape, total)) return false;
  shape.numberOfChildren = total - shape.childrenIndex;
  return true;
}

function resolveAllCore() {
  const u = findUnresolved();
  u.ranges.forEach(trimChildRangeCore);
  for (const x of u.refs) if (!applyRefFix(x)) return false;
  findUnresolved().clouds
    .filter((k) => cloudFilePoints(k).length === 0)
    .sort((a, b) => b - a)
    .forEach((k) => removeCloudEntry(k));
  const root = boundsInOrder().find((s) => s.index === 0);
  for (const x of u.bounds) {
    if (!shapes[x.name] || inParentLoop(x)) continue;
    const ok = isEmptyBound(x) && descendantsOf(x).length === 0 ? deleteBoundCore(x) : attachSubtreeCore(x, root);
    if (!ok) return false;
  }
  return true;
}

function runResolve(apply, who) {
  const before = snapshotWorld();
  if (!runStructuralEdit(apply, who)) {
    restoreWorld(before);
    return false;
  }
  refreshAfterStructureChange();
  return true;
}

function resolveAll() { return runResolve(resolveAllCore, "unresolved items"); }
function trimChildRange(shape) { return runResolve(() => trimChildRangeCore(shape), shape); }
function clearChildRange(shape) { return runResolve(() => { shape.numberOfChildren = 0; return true; }, shape); }
function attachUnassignedBound(x, target) { return runResolve(() => attachSubtreeCore(x, target), x); }
function assignUnassignedCloud(k, shape) { return runResolve(() => assignCloudCore(k, shape, true), shape); }
function clearCloudReference(shape) { return runResolve(() => { shape.collisionCloudIndex = -1; return true; }, shape); }
function repairCloudReference(shape) { return runResolve(() => applyRefFix(shape), shape); }
function deleteUnassignedCloud(k) {
  return runResolve(() => {
    if (!cloudTable[k]) return false;
    removeCloudEntry(k);
    return true;
  }, "unassigned cloud");
}

function positionResolvePanel() {
  const legendRect = document.getElementById("legend").getBoundingClientRect();
  const top = Math.max(8, legendRect.top);
  resolvePanelEl.style.left = (legendRect.right + 8) + "px";
  resolvePanelEl.style.top = top + "px";
  resolvePanelEl.style.maxHeight = (window.innerHeight - top - 14) + "px";
}

function closeResolvePanel() {
  resolvePanelOpen = false;
  resolvePanelEl.classList.remove("open");
  resolvePanelEl.innerHTML = "";
  unresolvedBannerEl.querySelector(".ub-open").classList.remove("open");
}

function describeResolveAll(u) {
  const parts = [];
  const total = Object.keys(shapes).length;
  const trim = u.ranges.filter((x) => childRangeTrimmable(x, total)).length;
  const fixable = u.bounds.filter((x) => !inParentLoop(x));
  const emptyBounds = fixable.filter((x) => isEmptyBound(x) && descendantsOf(x).length === 0);
  const attach = fixable.length - emptyBounds.length;
  const clear = u.refs.filter((x) => refFix(x) === "clear").length;
  const repair = u.refs.length - clear;
  const emptyClouds = u.clouds.filter((k) => cloudFilePoints(k).length === 0).length;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (trim) parts.push(`trim ${plural(trim, "child range")}`);
  if (attach) parts.push(`attach ${plural(attach, "bound")} to ${shapeLabel(boundsInOrder()[0])}`);
  if (emptyBounds.length) parts.push(`delete ${plural(emptyBounds.length, "empty bound")}`);
  if (clear) parts.push(`clear ${plural(clear, "cloud reference")}`);
  if (repair) parts.push(`repair ${plural(repair, "cloud reference")}`);
  if (emptyClouds) parts.push(`delete ${plural(emptyClouds, "empty cloud")}`);
  return parts;
}

function renderResolvePanel(u) {
  const all = boundsInOrder();
  const previous = resolvePanelEl.querySelector(".r-body");
  const scroll = previous ? previous.scrollTop : 0;
  const plan = describeResolveAll(u);
  const noCloud = all.filter((s) => s.cloudSlot === -1 && s.collisionCloudIndex === -1);
  let html = `
    <div class="r-title"><span>Unresolved items</span><span class="r-close">&#10005;</span></div>
    <div class="r-note">Entries the bound hierarchy, child ranges or the cloud table do not account for. Resolve each one, or fix them all at once.</div>
    <button type="button" class="r-btn r-fix" data-act="fix-all"${plan.length ? "" : " disabled"}>Fix all recommended</button>
    <div class="r-note">${plan.length ? "Will " + plan.join(", ") + "." : "Nothing to fix automatically."}${u.clouds.some((k) => cloudFilePoints(k).length) ? " Clouds with vertices are left for you to assign or delete." : ""}</div>
    <div class="r-body">`;

  if (u.ranges.length) {
    const total = all.length;
    html += `<div class="r-sec">Child ranges (${u.ranges.length})</div>`;
    u.ranges.forEach((x) => {
      const why = x.childrenIndex < 0 ? "has a negative ChildrenIndex"
        : `lists ${x.numberOfChildren} child${x.numberOfChildren === 1 ? "" : "ren"} from index ${x.childrenIndex}, but the file has ${total} bound${total === 1 ? "" : "s"}`;
      html += `<div class="r-item" data-index="${x.index}">
        <div class="r-line"><span class="r-name">${shapeLabel(x)}</span>
          <span class="r-meta">${why}</span></div>
        <div class="r-line">${childRangeTrimmable(x, total) ? `<button type="button" class="r-btn" data-act="trim-range">Trim to ${total - x.childrenIndex}</button>` : ""}
          <button type="button" class="r-btn" data-act="clear-range">Clear children</button></div>
      </div>`;
    });
  }

  if (u.bounds.length) {
    html += `<div class="r-sec">Unassigned bounds (${u.bounds.length})</div>`;
    u.bounds.forEach((x) => {
      const subtree = new Set([x].concat(descendantsOf(x)));
      const kids = subtree.size - 1;
      const empty = isEmptyBound(x);
      const loop = inParentLoop(x);
      const options = all.filter((t) => !subtree.has(t))
        .map((t) => `<option value="${t.index}">${shapeLabel(t)}</option>`).join("");
      html += `<div class="r-item" data-index="${x.index}">
        <div class="r-line"><span class="r-name">${shapeLabel(x)}</span>
          <span class="r-meta">${loop ? "part of a parent loop" : "not a child of any bound"}${empty ? ", zero size" : ""}${kids && !loop ? `, ${kids} descendant${kids === 1 ? "" : "s"}` : ""}</span></div>
        <div class="r-line"><select class="r-sel"${loop ? " disabled" : ""}>${options}</select>
          <button type="button" class="r-btn" data-act="attach"${loop ? " disabled" : ""}>Attach</button>
          <button type="button" class="r-btn danger" data-act="delete-bound">Delete</button></div>
      </div>`;
    });
  }

  if (u.refs.length) {
    html += `<div class="r-sec">Cloud references (${u.refs.length})</div>`;
    u.refs.forEach((x) => {
      const k = x.collisionCloudIndex;
      const holder = k < cloudTable.length ? cloudHolderOf(k) : null;
      const fix = refFix(x);
      const why = k >= cloudTable.length ? `cloud ${k}, which does not exist`
        : x.cloudSlot >= 0 ? `cloud ${k}, but holds the points of cloud ${x.cloudSlot}`
        : holder ? `cloud ${k}, which ${shapeLabel(holder)} holds` : `cloud ${k}, which no bound holds`;
      html += `<div class="r-item" data-index="${x.index}">
        <div class="r-line"><span class="r-name">${shapeLabel(x)}</span>
          <span class="r-meta">references ${why}</span></div>
        <div class="r-line">${fix === "match" ? `<button type="button" class="r-btn" data-act="repair-ref">Use cloud ${x.cloudSlot}</button>` : ""}${fix === "take" ? `<button type="button" class="r-btn" data-act="repair-ref">Take cloud ${k}</button>` : ""}
          <button type="button" class="r-btn" data-act="clear-ref">Clear reference</button></div>
      </div>`;
    });
  }

  if (u.clouds.length) {
    html += `<div class="r-sec">Unassigned clouds (${u.clouds.length})</div>`;
    u.clouds.forEach((k) => {
      const pts = cloudFilePoints(k);
      const sample = pts.slice(0, 4).map((pt) => "(" + pt.map((v) => fmt(v)).join(", ") + ")").join(" ");
      const options = noCloud.length
        ? noCloud.map((t) => `<option value="${t.index}">${shapeLabel(t)}</option>`).join("")
        : `<option value="">No bound without a cloud</option>`;
      html += `<div class="r-item" data-cloud="${k}">
        <div class="r-line"><span class="r-name">Cloud ${k}</span>
          <span class="r-meta">${pts.length ? `${pts.length} vert${pts.length === 1 ? "ex" : "ices"}` : "empty"}, referenced by no bound</span></div>
        ${pts.length ? `<div class="r-coords">${sample}${pts.length > 4 ? " ..." : ""}</div>` : ""}
        <div class="r-line">${pts.length ? `<select class="r-sel"${noCloud.length ? "" : " disabled"}>${options}</select>
          <button type="button" class="r-btn" data-act="assign-cloud"${noCloud.length ? "" : " disabled"}>Assign</button>` : ""}
          <button type="button" class="r-btn danger" data-act="delete-cloud">Delete</button></div>
      </div>`;
    });
  }
  html += "</div>";
  resolvePanelEl.innerHTML = html;
  resolvePanelEl.classList.add("open");
  resolvePanelEl.querySelector(".r-body").scrollTop = scroll;
  unresolvedBannerEl.querySelector(".ub-open").classList.add("open");
}

function syncUnresolved() {
  const u = findUnresolved();
  const n = u.ranges.length + u.bounds.length + u.refs.length + u.clouds.length;
  unresolvedBannerEl.classList.toggle("show", n > 0);
  unresolvedBannerEl.querySelector(".ub-text").textContent = `${n} unresolved item${n === 1 ? "" : "s"}`;
  unresolvedBannerEl.title = [
    u.ranges.length ? `${u.ranges.length} invalid child range${u.ranges.length === 1 ? "" : "s"}` : "",
    u.bounds.length ? `${u.bounds.length} unassigned bound${u.bounds.length === 1 ? "" : "s"}` : "",
    u.refs.length ? `${u.refs.length} invalid cloud reference${u.refs.length === 1 ? "" : "s"}` : "",
    u.clouds.length ? `${u.clouds.length} unassigned cloud${u.clouds.length === 1 ? "" : "s"}` : "",
  ].filter(Boolean).join(", ");
  if (n === 0) {
    closeResolvePanel();
  } else if (resolvePanelOpen) {
    renderResolvePanel(u);
    positionResolvePanel();
  }
  positionModeToggle();
}

unresolvedBannerEl.addEventListener("click", () => {
  if (resolvePanelOpen) {
    closeResolvePanel();
    return;
  }
  resolvePanelOpen = true;
  renderResolvePanel(findUnresolved());
  positionResolvePanel();
});

resolvePanelEl.addEventListener("click", (e) => {
  if (e.target.closest(".r-close")) { closeResolvePanel(); return; }
  const button = e.target.closest("[data-act]");
  if (!button || button.disabled) return;
  const act = button.dataset.act;
  const item = button.closest(".r-item");
  const byIndex = (i) => boundsInOrder().find((s) => s.index === i);
  if (act === "fix-all") { resolveAll(); return; }
  if (act === "delete-bound" || act === "delete-cloud") {
    if (!button.classList.contains("armed")) {
      const label = button.textContent;
      button.classList.add("armed");
      button.textContent = "Sure?";
      setTimeout(() => {
        button.classList.remove("armed");
        button.textContent = label;
      }, 4000);
      return;
    }
    if (act === "delete-bound") deleteBound(byIndex(parseInt(item.dataset.index, 10)));
    else deleteUnassignedCloud(parseInt(item.dataset.cloud, 10));
    return;
  }
  if (act === "attach") {
    const x = byIndex(parseInt(item.dataset.index, 10));
    const target = byIndex(parseInt(item.querySelector(".r-sel").value, 10));
    if (x && target) attachUnassignedBound(x, target);
  } else if (act === "trim-range" || act === "clear-range") {
    const x = byIndex(parseInt(item.dataset.index, 10));
    if (x) (act === "trim-range" ? trimChildRange : clearChildRange)(x);
  } else if (act === "clear-ref") {
    const x = byIndex(parseInt(item.dataset.index, 10));
    if (x) clearCloudReference(x);
  } else if (act === "repair-ref") {
    const x = byIndex(parseInt(item.dataset.index, 10));
    if (x) repairCloudReference(x);
  } else if (act === "assign-cloud") {
    const target = byIndex(parseInt(item.querySelector(".r-sel").value, 10));
    if (target) assignUnassignedCloud(parseInt(item.dataset.cloud, 10), target);
  }
});

window.addEventListener("resize", () => { if (resolvePanelOpen) positionResolvePanel(); });

function addCloud(shape) {
  if (shape.cloudSlot >= 0) return structureWarn(`${shapeLabel(shape)} already has a collision cloud.`);
  if (shape.collisionCloudIndex >= 0) return structureWarn(`Resolve ${shapeLabel(shape)} first.`);
  if (cloudTable.length >= MAX_CLOUDS) return structureWarn("Collision cloud limit reached.");
  runStructuralEdit(() => {
    shape.collisionCloudIndex = cloudTable.length;
    shape.cloudSlot = cloudTable.length;
    cloudTable.push({ orphan: null });
    shape.cloudLocal = [[0, 0, 0]];
    shape.cloudByteOffset = shape.cloudLocal.map(() => null);
    shape.boundType |= KBOUNDS_MESH_VS_GROUND;
    buildCloudPoints(shape);
    return true;
  }, shape);
  refreshAfterStructureChange();
  return true;
}

function deleteCloud(shape) {
  if (shape.cloudSlot < 0 || shape.cloudSlot >= cloudTable.length) return false;
  runStructuralEdit(() => {
    removeCloudEntry(shape.cloudSlot);
    return true;
  }, shape);
  refreshAfterStructureChange();
  return true;
}

function rebuildCloud(shape) {
  disposeCloudPoints(shape);
  buildCloudPoints(shape);
}

function addCloudVertex(shape) {
  if (!shape.cloudLocal) return null;
  runStructuralEdit(() => {
    shape.cloudLocal.push([0, 0, 0]);
    shape.cloudByteOffset.push(null);
    rebuildCloud(shape);
    return true;
  }, shape);
  refreshAfterStructureChange();
  if (cloudPanelShapeName === shape.name) {
    const rows = cloudPanelEl.querySelector(".c-rows");
    rows.scrollTop = rows.scrollHeight;
    const first = rows.querySelector(".c-row:last-child input");
    if (first) first.focus();
  }
  return shape.cloudPoints[shape.cloudPoints.length - 1];
}

function removeCloudVertex(shape, pointIndex) {
  if (!shape.cloudLocal || pointIndex < 0 || pointIndex >= shape.cloudLocal.length) return false;
  runStructuralEdit(() => {
    shape.cloudLocal.splice(pointIndex, 1);
    shape.cloudByteOffset.splice(pointIndex, 1);
    rebuildCloud(shape);
    return true;
  }, shape);
  refreshAfterStructureChange();
  return true;
}

// --------------------------------------------------------------
// Row menu and cloud panel
// --------------------------------------------------------------
// Row menu ("..." or right-click), delete confirmation, cloud panel (docked left of the bound
// panel, follows its bound).
function closeStructureMenu() {
  structureMenuTarget = null;
  structureMenuEl.classList.remove("open");
  structureMenuEl.innerHTML = "";
  document.querySelectorAll(".legend-row.menu-target").forEach((row) => row.classList.remove("menu-target"));
}

function renderStructureMenu(shape) {
  const root = shape.index === 0;
  structureMenuEl.innerHTML = `
    <div class="sm-title">${shapeLabel(shape)}</div>
    <button type="button" class="sm-item" data-sm="add-box" title="Add a Box bound as the last child of this bound">Add Box child</button>
    <button type="button" class="sm-item" data-sm="add-sphere" title="Add a Sphere bound as the last child of this bound">Add Sphere child</button>
    <div class="sm-sep"></div>
    <button type="button" class="sm-item danger" data-sm="delete" ${root ? "disabled" : ""} title="${root ? "The root bound can't be deleted" : "Delete this bound and everything under it"}">Delete bound...</button>`;
}

function renderDeleteConfirm(shape) {
  const below = descendantsOf(shape).length;
  structureMenuEl.innerHTML = `
    <div class="sm-title">${shapeLabel(shape)}</div>
    <div class="sm-text">Delete ${shapeLabel(shape)}${below ? ` and its ${below} descendant${below === 1 ? "" : "s"}` : ""}?</div>
    <div class="sm-row"><button type="button" class="sm-item" data-sm="cancel">Cancel</button><button type="button" class="sm-item danger" data-sm="confirm">Delete</button></div>`;
}

function openStructureMenu(shape, row) {
  closeBoundTypeMenu();
  closeSurfaceMenu();
  closeStructureMenu();
  structureMenuTarget = shape.name;
  row.classList.add("menu-target");
  renderStructureMenu(shape);
  structureMenuEl.classList.add("open");
  const legend = document.getElementById("legend").getBoundingClientRect();
  const anchor = row.getBoundingClientRect();
  structureMenuEl.style.left = (legend.right + 6) + "px";
  structureMenuEl.style.top = Math.max(8, Math.min(anchor.top - 6, window.innerHeight - structureMenuEl.offsetHeight - 8)) + "px";
}

function closeCloudPanel() {
  cloudPanelShapeName = null;
  cloudPanelEl.classList.remove("open");
  cloudPanelEl.innerHTML = "";
  const opener = infoPanelEl.querySelector("#cloud-open");
  if (opener) opener.classList.remove("open");
}

function positionCloudPanel() {
  const info = infoPanelEl.getBoundingClientRect();
  const top = Math.max(8, info.top);
  cloudPanelEl.style.left = Math.max(8, info.left - cloudPanelEl.offsetWidth - 8) + "px";
  cloudPanelEl.style.top = top + "px";
  cloudPanelEl.style.maxHeight = (window.innerHeight - top - 14) + "px";
}

function renderCloudPanel(shape) {
  const previous = cloudPanelEl.querySelector(".c-rows");
  const scroll = previous ? previous.scrollTop : 0;
  const rows = shape.cloudLocal.map((v, i) => `<div class="c-row"><span class="c-idx">${i}</span>${
    [0, 1, 2].map((axis) => `<input type="text" data-i="${i}" data-axis="${axis}" value="${fmt(v[axis])}">`).join("")
  }<button type="button" class="c-del" data-i="${i}" title="Remove this vertex">&times;</button></div>`).join("");
  cloudPanelEl.innerHTML = `
    <div class="c-title"><span>${shapeLabel(shape)} - Collision cloud</span><span class="c-close">&#10005;</span></div>
    <div class="c-note">${shape.cloudLocal.length} ${shape.cloudLocal.length === 1 ? "vertex" : "vertices"}, cloud ${shape.cloudSlot}. Local coordinates. Press Enter to apply.</div>
    <div class="c-actions">
      <button type="button" class="c-btn" data-cl="add-vertex">+ Vertex</button>
      <button type="button" class="c-btn danger" data-cl="delete-cloud">Delete cloud</button>
    </div>
    <div class="c-head"><span>#</span><span>X</span><span>Y</span><span>Z</span><span></span></div>
    <div class="c-rows">${rows}</div>`;
  cloudPanelEl.classList.add("open");
  cloudPanelEl.querySelector(".c-rows").scrollTop = scroll;
  cloudPanelEl.querySelector(".c-close").addEventListener("click", closeCloudPanel);
  cloudPanelEl.querySelectorAll("input").forEach((input) => {
    wireCommit(input, () => {
      const i = parseInt(input.dataset.i, 10), axis = parseInt(input.dataset.axis, 10);
      const value = parseFloat(input.value);
      if (!Number.isNaN(value)) applyCloudPointEdit(shape, i, axis, value);
      input.value = fmt(shape.cloudLocal[i][axis]);
    });
  });
  cloudPanelEl.querySelectorAll(".c-del").forEach((button) => {
    button.addEventListener("click", () => removeCloudVertex(shape, parseInt(button.dataset.i, 10)));
  });
  cloudPanelEl.querySelector('[data-cl="add-vertex"]').addEventListener("click", () => addCloudVertex(shape));
  const deleteButton = cloudPanelEl.querySelector('[data-cl="delete-cloud"]');
  deleteButton.addEventListener("click", () => {
    if (!deleteButton.classList.contains("armed")) {
      deleteButton.classList.add("armed");
      deleteButton.textContent = "Sure?";
      setTimeout(() => {
        deleteButton.classList.remove("armed");
        deleteButton.textContent = "Delete cloud";
      }, 4000);
      return;
    }
    deleteCloud(shape);
  });
}

function openCloudPanel(shape) {
  closeBoundTypeMenu();
  closeSurfaceMenu();
  cloudPanelShapeName = shape.name;
  renderCloudPanel(shape);
  positionCloudPanel();
  const opener = infoPanelEl.querySelector("#cloud-open");
  if (opener) opener.classList.add("open");
}

function syncCloudPanel() {
  if (cloudPanelShapeName === null) return;
  const shape = shapes[cloudPanelShapeName];
  if (!shape || !shape.cloudLocal || shape !== openInfoShape) {
    closeCloudPanel();
    return;
  }
  renderCloudPanel(shape);
  positionCloudPanel();
}

function syncCloudPanelValues(shapeName) {
  if (cloudPanelShapeName !== shapeName) return;
  const shape = shapes[shapeName];
  if (!shape || !shape.cloudLocal) return;
  cloudPanelEl.querySelectorAll("input").forEach((input) => {
    if (document.activeElement === input) return;
    const v = shape.cloudLocal[parseInt(input.dataset.i, 10)];
    if (v) input.value = fmt(v[parseInt(input.dataset.axis, 10)]);
  });
}

structureMenuEl.addEventListener("click", (e) => {
  const button = e.target.closest("[data-sm]");
  const shape = structureMenuTarget === null ? null : shapes[structureMenuTarget];
  if (!button || button.disabled) return;
  if (!shape) {
    closeStructureMenu();
    return;
  }
  const action = button.dataset.sm;
  if (action === "add-box" || action === "add-sphere") {
    closeStructureMenu();
    addBound(shape, action === "add-box" ? "box" : "sphere");
  } else if (action === "delete") {
    renderDeleteConfirm(shape);
  } else if (action === "cancel") {
    renderStructureMenu(shape);
  } else if (action === "confirm") {
    closeStructureMenu();
    deleteBound(shape);
  }
});
structureMenuEl.addEventListener("pointerdown", (e) => e.stopPropagation());
cloudPanelEl.addEventListener("pointerdown", (e) => e.stopPropagation());
document.addEventListener("pointerdown", (e) => {
  if (structureMenuTarget === null) return;
  if (e.target instanceof Element && e.target.closest("#structure-menu, .legend-more")) return;
  closeStructureMenu();
}, true);
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && structureMenuTarget !== null) closeStructureMenu();
});
window.addEventListener("resize", () => {
  closeStructureMenu();
  if (cloudPanelShapeName !== null) positionCloudPanel();
});
legendRows.addEventListener("scroll", closeStructureMenu);

function createPin(marker) {
  const shapeName = marker.userData.shapeName;
  const pointIndex = marker.userData.pointIndex;
  const isCloud = !!marker.userData.isCloud;
  const kind = isCloud ? "cloud" : "corner";
  const shape = shapes[shapeName];
  const key = pinKey(shapeName, kind, pointIndex);
  if (pins[key]) return;

  const el = document.createElement("div");
  el.className = "pin-panel";

  if (isCloud) {
    const localVals = shape.cloudLocal[pointIndex];
    const worldVals = currentCloudWorldPoint(shape, pointIndex);
    el.innerHTML = `
      <div class="p-name"><span>${shapeLabel(shape)} - Collision Vertex ${marker.userData.pointIndex} of ${marker.userData.cloudVertexCount}</span><span class="p-close">&#10005;</span></div>
      <div class="p-section-label">Local</div>
      <div class="p-row"><label>X</label><input type="number" step="any" data-axis="0" value="${fmt(localVals[0])}"></div>
      <div class="p-row"><label>Y</label><input type="number" step="any" data-axis="1" value="${fmt(localVals[1])}"></div>
      <div class="p-row"><label>Z</label><input type="number" step="any" data-axis="2" value="${fmt(localVals[2])}"></div>
      <div class="p-section-label">World</div>
      <div class="p-row"><label>X</label><span class="p-readonly" data-world="0">${fmt(worldVals[0])}</span></div>
      <div class="p-row"><label>Y</label><span class="p-readonly" data-world="1">${fmt(worldVals[1])}</span></div>
      <div class="p-row"><label>Z</label><span class="p-readonly" data-world="2">${fmt(worldVals[2])}</span></div>
      <button type="button" class="p-del" title="Remove this vertex from the collision cloud">Remove vertex</button>
    `;
    pinsHolder.appendChild(el);
    const inputs = Array.from(el.querySelectorAll("input"));
    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        const axis = parseInt(input.dataset.axis, 10);
        applyCloudPointEdit(shape, pointIndex, axis, parseFloat(input.value));
      });
      input.addEventListener("pointerdown", (e) => e.stopPropagation());
    });
    const removeButton = el.querySelector(".p-del");
    removeButton.addEventListener("click", () => removeCloudVertex(shape, pointIndex));
    removeButton.addEventListener("pointerdown", (e) => e.stopPropagation());
    pins[key] = { el, inputs, worldEls: Array.from(el.querySelectorAll(".p-readonly")), marker, shapeName, pointIndex, kind };
  } else if (shape.type === "box") {
    const localVals = [0,1,2].map(axis => currentLocalCornerValue(shape, pointIndex, axis));
    const worldVals = currentWorldPoint(shape, pointIndex);
    const isBoxOnly = shape.boundType === KBOUNDS_BOX_ONLY;
    el.innerHTML = `
      <div class="p-name"><span>${shapeLabel(shape)}</span><span class="p-close">&#10005;</span></div>
      <div class="p-section-label">Local</div>
      ${isBoxOnly ? '<div class="p-note">Editing resizes Half-Dimension only.</div>' : ''}
      <div class="p-row"><label>X</label><input type="number" step="any" data-axis="0" value="${fmt(localVals[0])}"></div>
      <div class="p-row"><label>Y</label><input type="number" step="any" data-axis="1" value="${fmt(localVals[1])}"></div>
      <div class="p-row"><label>Z</label><input type="number" step="any" data-axis="2" value="${fmt(localVals[2])}"></div>
      <div class="p-section-label">World</div>
      <div class="p-row"><label>X</label><span class="p-readonly" data-world="0">${fmt(worldVals[0])}</span></div>
      <div class="p-row"><label>Y</label><span class="p-readonly" data-world="1">${fmt(worldVals[1])}</span></div>
      <div class="p-row"><label>Z</label><span class="p-readonly" data-world="2">${fmt(worldVals[2])}</span></div>
    `;
    pinsHolder.appendChild(el);
    const inputs = Array.from(el.querySelectorAll("input"));
    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        const axis = parseInt(input.dataset.axis, 10);
        const val = parseFloat(input.value);
        if (Number.isNaN(val)) return;
        applyBoxCornerEdit(shape, pointIndex, axis, val);
      });
      input.addEventListener("pointerdown", (e) => e.stopPropagation());
    });
    pins[key] = { el, inputs, worldEls: Array.from(el.querySelectorAll(".p-readonly")), marker, shapeName, pointIndex, kind };
  } else {
    const worldVals = currentWorldPoint(shape, pointIndex);
    el.innerHTML = `
      <div class="p-name"><span>${shapeLabel(shape)}</span><span class="p-close">&#10005;</span></div>
      <div class="p-section-label">World</div>
      <div class="p-note">Editing moves the entire sphere.</div>
      <div class="p-row"><label>X</label><input type="number" step="any" data-axis="0" value="${fmt(worldVals[0])}"></div>
      <div class="p-row"><label>Y</label><input type="number" step="any" data-axis="1" value="${fmt(worldVals[1])}"></div>
      <div class="p-row"><label>Z</label><input type="number" step="any" data-axis="2" value="${fmt(worldVals[2])}"></div>
    `;
    pinsHolder.appendChild(el);
    const inputs = Array.from(el.querySelectorAll("input"));
    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        const axis = parseInt(input.dataset.axis, 10);
        const val = parseFloat(input.value);
        if (Number.isNaN(val)) return;
        applySphereCenterEdit(shape, axis, val);
      });
      input.addEventListener("pointerdown", (e) => e.stopPropagation());
    });
    pins[key] = { el, inputs, worldEls: [], marker, shapeName, pointIndex, kind };
  }

  el.querySelector(".p-close").addEventListener("click", () => unpin(shapeName, kind, pointIndex));
  el.addEventListener("pointerdown", (e) => e.stopPropagation());

  marker.userData.pinned = true;
  marker.userData.scaleMult = 1.8;
  applyMarkerScale(marker);
}

function unpin(shapeName, kind, pointIndex) {
  const key = pinKey(shapeName, kind, pointIndex);
  const pin = pins[key];
  if (!pin) return;
  pin.el.remove();
  pin.marker.userData.pinned = false;
  pin.marker.userData.scaleMult = 1;
  applyMarkerScale(pin.marker);
  delete pins[key];
}

function togglePin(marker) {
  const kind = marker.userData.isCloud ? "cloud" : "corner";
  const key = pinKey(marker.userData.shapeName, kind, marker.userData.pointIndex);
  if (pins[key]) unpin(marker.userData.shapeName, kind, marker.userData.pointIndex);
  else createPin(marker);
}

// Pin fields apply while typing; one left empty shows the current value again after losing focus
// (refreshPinsForShape skips the focused field).
pinsHolder.addEventListener("change", (e) => {
  if (e.target.tagName !== "INPUT" || e.target.value.trim() !== "") return;
  const pin = Object.values(pins).find((p) => p.inputs.includes(e.target));
  if (pin) requestAnimationFrame(() => refreshPinsForShape(pin.shapeName));
});

function refreshPinsForShape(shapeName) {
  syncCloudPanelValues(shapeName);
  Object.values(pins).forEach((pin) => {
    if (pin.shapeName !== shapeName) return;
    const shape = shapes[shapeName];
    if (pin.kind === "cloud") {
      const localVals = shape.cloudLocal[pin.pointIndex];
      const world = currentCloudWorldPoint(shape, pin.pointIndex);
      pin.inputs.forEach((input) => {
        if (document.activeElement === input) return;
        const axis = parseInt(input.dataset.axis, 10);
        input.value = fmt(localVals[axis]);
      });
      pin.worldEls.forEach((el) => {
        const axis = parseInt(el.dataset.world, 10);
        el.textContent = fmt(world[axis]);
      });
      return;
    }
    const world = currentWorldPoint(shape, pin.pointIndex);
    if (shape.type === "box") {
      const localVals = [0,1,2].map(axis => currentLocalCornerValue(shape, pin.pointIndex, axis));
      pin.inputs.forEach((input) => {
        if (document.activeElement === input) return;
        const axis = parseInt(input.dataset.axis, 10);
        input.value = fmt(localVals[axis]);
      });
      pin.worldEls.forEach((el) => {
        const axis = parseInt(el.dataset.world, 10);
        el.textContent = fmt(world[axis]);
      });
    } else {
      pin.inputs.forEach((input) => {
        if (document.activeElement === input) return;
        const axis = parseInt(input.dataset.axis, 10);
        input.value = fmt(world[axis]);
      });
    }
  });
}

// Raycaster ignores Object3D.visible, so markers of hidden bounds stay pickable.
// isEffectivelyVisible() walks the ancestors (a marker lives in its bound's group);
// pickMarkerHits() drops hits that are not effectively visible.
function isEffectivelyVisible(obj) {
  for (let o = obj; o; o = o.parent) {
    if (!o.visible) return false;
  }
  return true;
}
function pickMarkerHits() {
  return raycaster.intersectObjects(markerMeshes).filter((h) => isEffectivelyVisible(h.object));
}

function updatePinPositions() {
  Object.values(pins).forEach((pin) => {
    const worldPos = new THREE.Vector3();
    pin.marker.getWorldPosition(worldPos);
    const screen = worldPos.clone().project(camera);
    const x = (screen.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-screen.y * 0.5 + 0.5) * window.innerHeight;
    pin.el.style.left = x + "px";
    pin.el.style.top = y + "px";
    // A pinned point's panel follows its bound's visibility.
    pin.el.style.display = (screen.z > 1 || !isEffectivelyVisible(pin.marker)) ? "none" : "block";
  });
}

// --------------------------------------------------------------
// Hover tooltip + click to pin
// --------------------------------------------------------------
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let hovered = null;

function onPointerMove(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = pickMarkerHits();

  if (hits.length > 0) {
    const obj = hits[0].object;
    if (hovered !== obj) {
      if (hovered && !hovered.userData.pinned) { hovered.userData.scaleMult = 1; applyMarkerScale(hovered); }
      hovered = obj;
      if (!hovered.userData.pinned) { hovered.userData.scaleMult = 1.8; applyMarkerScale(hovered); }
    }
    const shape = shapes[obj.userData.shapeName];
    const isCloud = !!obj.userData.isCloud;
    const p = isCloud ? currentCloudWorldPoint(shape, obj.userData.pointIndex) : currentWorldPoint(shape, obj.userData.pointIndex);
    const hoverShape = shapeLabel(shapes[obj.userData.shapeName]);
    const label = isCloud ? `${hoverShape} - Collision Vertex ${obj.userData.pointIndex} of ${obj.userData.cloudVertexCount}` : hoverShape;
    tooltip.innerHTML = `<span class="t-name">${label}</span>World X: ${fmt(p[0])}\nWorld Y: ${fmt(p[1])}\nWorld Z: ${fmt(p[2])}`;
    tooltip.style.display = "block";
    tooltip.style.left = (event.clientX + 14) + "px";
    tooltip.style.top = (event.clientY + 14) + "px";
    renderer.domElement.style.cursor = "pointer";
  } else {
    if (hovered && !hovered.userData.pinned) { hovered.userData.scaleMult = 1; applyMarkerScale(hovered); }
    hovered = null;
    tooltip.style.display = "none";
    renderer.domElement.style.cursor = "default";
  }
}

function onClick(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = pickMarkerHits();
  if (hits.length > 0) togglePin(hits[0].object);
}

renderer.domElement.addEventListener("mousemove", onPointerMove);
renderer.domElement.addEventListener("mouseleave", () => {
  if (hovered && !hovered.userData.pinned) { hovered.userData.scaleMult = 1; applyMarkerScale(hovered); }
  hovered = null;
  tooltip.style.display = "none";
});
renderer.domElement.addEventListener("click", onClick);

// --------------------------------------------------------------
// Saving
// --------------------------------------------------------------
const saveStatus = document.getElementById("save-status");
const saveBtn = document.getElementById("save-btn");

function anyDirty() { return Object.values(shapes).some(s => s.dirty); }

function updateSaveStatus() {
  const dirtyCount = Object.values(shapes).filter(s => s.dirty).length;
  const structureEdited = structureUnsaved();
  // Not `disabled`: the click that blurs a field with a typed value must still reach the button.
  // "idle" is only a look; saveDirtyShapes() returns early when nothing changed.
  const idle = dirtyCount === 0 && !structureEdited;
  saveBtn.classList.toggle("idle", idle);
  saveBtn.setAttribute("aria-disabled", String(idle));
  if (idle) {
    saveStatus.textContent = "No unsaved changes.";
  } else {
    saveStatus.textContent = `${dirtyCount} bound(s) changed${structureEdited ? " (structure edited)" : ""} - click Export Collision to save.`;
  }
}
updateSaveStatus();

// Patch one 48-byte CollisionBound record in place (all editable fields) plus this bound's cloud
// vertices; nothing else. Field offsets within the record:
const FIELD_SUBOFFSET = {
  orientationX: 0, orientationY: 2, orientationZ: 4, orientationW: 6,
  positionX: 8, positionY: 10, positionZ: 12,
  boundType: 14,
  halfDimensionX: 16, halfDimensionY: 18, halfDimensionZ: 20,
  numberOfChildren: 22, collisionCloudIndex: 23,
  pivotX: 24, pivotY: 26, pivotZ: 28,
  childrenIndex: 30,
  radius: 32, surfaceName: 36, nameHash: 40,
};
function toRawInt16(value) {
  // Position/HalfDimension/Pivot scale (COLLISION_GEOM_VECTOR_PRESSICION = 1000).
  const raw = Math.round(value * 1000.0);
  return Math.max(-32768, Math.min(32767, raw)); // clamp to int16 range
}
function toRawInt16Quat(value) {
  // Orientation scale (COLLISION_GEOM_QUAT_PRECISION = 32767).
  const raw = Math.round(value * 32767.0);
  return Math.max(-32768, Math.min(32767, raw));
}
function patchShapeRecord(dv, base, shape) {
  dv.setInt16(base + FIELD_SUBOFFSET.orientationX, toRawInt16Quat(shape.quat[0]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.orientationY, toRawInt16Quat(shape.quat[1]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.orientationZ, toRawInt16Quat(shape.quat[2]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.orientationW, toRawInt16Quat(shape.quat[3]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.positionX, toRawInt16(shape.position[0]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.positionY, toRawInt16(shape.position[1]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.positionZ, toRawInt16(shape.position[2]), true);
  dv.setUint16(base + FIELD_SUBOFFSET.boundType, shape.boundType & 0xFFFF, true);
  // MW spheres: after a Radius edit HalfDimension is written as Radius on all axes (as in real
  // files and the locked inputs); before that it is written as read, so unrelated edits (e.g.
  // BoundType) leave those bytes alone. Carbon+ ("hash") writes shape.halfDim.
  const half = (shape.type === "sphere" && RADIUS_FORMAT === "float" && shape.radiusRaw !== shape.originalRadiusRaw)
    ? [shape.radiusDecoded, shape.radiusDecoded, shape.radiusDecoded]
    : shape.halfDim;
  dv.setInt16(base + FIELD_SUBOFFSET.halfDimensionX, toRawInt16(half[0]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.halfDimensionY, toRawInt16(half[1]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.halfDimensionZ, toRawInt16(half[2]), true);
  dv.setUint8(base + FIELD_SUBOFFSET.numberOfChildren, shape.numberOfChildren & 0xFF);
  dv.setInt8(base + FIELD_SUBOFFSET.collisionCloudIndex, shape.collisionCloudIndex);
  dv.setInt16(base + FIELD_SUBOFFSET.pivotX, toRawInt16(shape.pivot[0]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.pivotY, toRawInt16(shape.pivot[1]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.pivotZ, toRawInt16(shape.pivot[2]), true);
  dv.setInt16(base + FIELD_SUBOFFSET.childrenIndex, shape.childrenIndex, true);
  dv.setUint32(base + FIELD_SUBOFFSET.radius, shape.radiusRaw >>> 0, true);
  dv.setUint32(base + FIELD_SUBOFFSET.surfaceName, shape.surfaceNameHash >>> 0, true);
  dv.setUint32(base + FIELD_SUBOFFSET.nameHash, shape.nameHash >>> 0, true);
}

function patchShapeIntoBytes(bytes, shape) {
  const dv = new DataView(bytes.buffer);
  patchShapeRecord(dv, shape.byteOffset, shape);
  if (shape.cloudPoints) {
    // Cloud vertices are stored as parent-frame floats (localToParentFrame).
    shape.cloudLocal.forEach((local, i) => {
      const world = localToParentFrame(shape, local);
      const off = shape.cloudByteOffset[i];
      dv.setFloat32(off, world[0], true);
      dv.setFloat32(off + 4, world[1], true);
      dv.setFloat32(off + 8, world[2], true);
    });
  }
}

function cloudVerticesForExport(k) {
  const entry = cloudTable[k];
  if (entry.orphan) {
    return entry.orphan.map((off) => [fileView.getFloat32(off, true), fileView.getFloat32(off + 4, true), fileView.getFloat32(off + 8, true), fileView.getFloat32(off + 12, true)]);
  }
  const owner = cloudHolderOf(k);
  if (!owner) return [];
  return owner.cloudLocal.map((local, i) => {
    const world = localToParentFrame(owner, local);
    const off = owner.cloudByteOffset ? owner.cloudByteOffset[i] : null;
    if (off === null || off === undefined) return world.concat(0);
    const original = [0, 1, 2, 3].map((axis) => fileView.getFloat32(off + axis * 4, true));
    const unchanged = world.every((c, axis) => Math.abs(c - original[axis]) <= 1e-6 * Math.max(1, Math.abs(original[axis])));
    return unchanged ? original : world.concat(original[3]);
  });
}

// Re-serialise the chunk after bounds/clouds were added or removed: header (counts, size words +=
// delta), 48-byte records (existing ones copied then patched, new ones zeroed), cloud section,
// trailing bytes.
function buildStructuralBytes() {
  const order = boundsInOrder();
  const boundsStart = BOUNDS[0].byteOffset;
  const header = fileBytes.subarray(0, boundsStart);
  const tail = fileBytes.subarray(CLOUD_META.consumed);
  const clouds = cloudTable.map((_, k) => cloudVerticesForExport(k));
  const cloudHeader = IS_BINARY_EXPORT ? 4 : 16;
  const cloudSize = (IS_BINARY_EXPORT ? 0 : 16) + clouds.reduce((sum, verts) => sum + cloudHeader + 16 * verts.length, 0);
  const total = header.length + order.length * 48 + cloudSize + tail.length;
  const out = new Uint8Array(total);
  const dv = new DataView(out.buffer);
  out.set(header, 0);
  const delta = total - fileBytes.length;
  (IS_BINARY_EXPORT ? [4, 16, 28, 32] : [4]).forEach((at) => dv.setUint32(at, fileView.getUint32(at, true) + delta, true));
  dv.setUint32(NUM_BOUNDS_OFFSET, order.length, true);
  if (IS_BINARY_EXPORT) dv.setUint32(NUM_BOUNDS_OFFSET + 4, clouds.length, true);
  order.forEach((shape, i) => {
    const base = boundsStart + i * 48;
    if (shape.byteOffset !== null) out.set(fileBytes.subarray(shape.byteOffset, shape.byteOffset + 48), base);
    patchShapeRecord(dv, base, shape);
  });
  let at = boundsStart + order.length * 48;
  if (!IS_BINARY_EXPORT) {
    dv.setUint32(at, clouds.length, true);
    at += 16;
  }
  clouds.forEach((verts) => {
    dv.setUint32(at, verts.length, true);
    at += cloudHeader;
    verts.forEach((v) => {
      v.forEach((c, axis) => dv.setFloat32(at + axis * 4, c, true));
      at += 16;
    });
  });
  out.set(tail, at);
  return out;
}

function verifyStructuralBytes(out) {
  const dv = new DataView(out.buffer);
  const boundCount = dv.getUint32(NUM_BOUNDS_OFFSET, true);
  if (boundCount !== Object.keys(shapes).length) return false;
  let at = BOUNDS[0].byteOffset + boundCount * 48;
  let cloudCount;
  if (IS_BINARY_EXPORT) {
    cloudCount = dv.getUint32(NUM_BOUNDS_OFFSET + 4, true);
  } else {
    cloudCount = dv.getUint32(at, true);
    at += 16;
  }
  if (cloudCount !== cloudTable.length) return false;
  for (let k = 0; k < cloudCount; k++) {
    at += (IS_BINARY_EXPORT ? 4 : 16) + dv.getUint32(at, true) * 16;
    if (at > out.length) return false;
  }
  return at + (fileBytes.length - CLOUD_META.consumed) === out.length;
}

function downloadBytes(filename, bytes) {
  const blob = new Blob([bytes], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// The info panel (and the cloud panel docked to it) sits below the save bar, whose height follows
// the status text; otherwise it covers the Export button.
function positionInfoPanel() {
  const top = Math.ceil(document.getElementById("save-bar").getBoundingClientRect().bottom) + 8;
  infoPanelEl.style.top = top + "px";
  infoPanelEl.style.maxHeight = (window.innerHeight - top - 14) + "px";
  if (cloudPanelShapeName) positionCloudPanel();
  if (boundTypeMenuOpen !== null) {
    boundTypeMenuScrollTop = infoPanelEl.scrollTop;
    positionBoundTypeMenu();
  }
  if (surfaceMenuOpen !== null) {
    surfaceMenuScrollTop = infoPanelEl.scrollTop;
    positionSurfaceMenu();
  }
}
new ResizeObserver(positionInfoPanel).observe(document.getElementById("save-bar"));
window.addEventListener("resize", positionInfoPanel);
positionInfoPanel();

// Commit a typed but uncommitted value (blur fires change) so a save never misses what the field
// shows.
function commitPendingField() {
  const active = document.activeElement;
  if (active && active !== document.body && isTextEntry(active)) active.blur();
}

async function saveDirtyShapes() {
  commitPendingField();
  const structural = structureDiffersFromFile();
  const dirtyShapes = Object.values(shapes).filter(s => s.dirty);
  if (dirtyShapes.length === 0 && !structureUnsaved()) return;
  const touched = structural ? Object.values(shapes) : dirtyShapes;

  let outBytes;
  if (structural) {
    // Counts changed: rebuild the whole chunk (fileBytes stays as loaded).
    outBytes = buildStructuralBytes();
    if (!verifyStructuralBytes(outBytes)) {
      saveStatus.textContent = "SAFETY ABORT: the rebuilt chunk failed its layout check - refusing to save. This should never happen; please report it.";
      console.error("Structural export self-check failed");
      return;
    }
  } else {
    // Patch the in-memory copy: it is both the saved data and the base for later edits.
    dirtyShapes.forEach((s) => patchShapeIntoBytes(fileBytes, s));

    // Patching never changes NumberOfBounds; verify that and refuse to save otherwise.
    const checkView = new DataView(fileBytes.buffer);
    const currentNumBounds = checkView.getInt32(NUM_BOUNDS_OFFSET, true);
    if (currentNumBounds !== ORIGINAL_NUM_BOUNDS) {
      saveStatus.textContent = `SAFETY ABORT: bound count changed (${ORIGINAL_NUM_BOUNDS} -> ${currentNumBounds}) - refusing to save. This should never happen; please report it.`;
      console.error("Bound-count safety check failed", ORIGINAL_NUM_BOUNDS, currentNumBounds);
      return;
    }
    outBytes = fileBytes;
  }

  if ("showSaveFilePicker" in window) {
    // Native Save dialog, so the file can go straight into the game folder.
    try {
      const suggestedName = ORIGINAL_FILENAME.replace(/\.bin$/i, "") + "_edited.bin";
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: "Collision bin", accept: { "application/octet-stream": [".bin"] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(outBytes);
      await writable.close();
      touched.forEach((s) => markDirty(s, false));
      lastSavedSignature = structureSignature();
      saveStatus.textContent = `Saved as ${handle.name}.`;
      touched.forEach(rebaseShapeBaseline);
    } catch (err) {
      if (err && err.name !== "AbortError") console.error("Save picker failed", err);
      return;
    }
  } else {
    downloadBytes(ORIGINAL_FILENAME.replace(/\.bin$/i, "") + "_edited.bin", outBytes);
    touched.forEach((s) => markDirty(s, false));
    lastSavedSignature = structureSignature();
    saveStatus.textContent = "Downloaded a patched .bin - move it into the game folder yourself.";
    touched.forEach(rebaseShapeBaseline);
  }
  updateSaveStatus();
}

saveBtn.addEventListener("click", saveDirtyShapes);

// Ctrl+S (capture phase). Browsers may still open their own Save dialog; the Export button is the
// reliable path.
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    e.stopPropagation();
    saveDirtyShapes();
  }
}, { capture: true });

// --------------------------------------------------------------
// Resize / render loop
// --------------------------------------------------------------
function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}
window.addEventListener("resize", onResize);

// Block the browser's default file-drop navigation.
window.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "none"; // shows the "not allowed" cursor
});
window.addEventListener("drop", (e) => e.preventDefault());


function animate() {
  requestAnimationFrame(animate);
  tickGizAnim();
  controls.update();
  updatePinPositions();
  renderer.render(scene, camera);
  updateGizmo();
}
animate();
</script>
</body>
</html>
"""


DEPENDENCIES_DIRNAME = "Dependencies"
ENGINE_DIRNAME = "Engine"
SURFACE_NAMES_FILENAME = "SurfaceNames.txt"
SURFACE_NAMES_ENV = "COLLISIONTOOL_SURFACE_NAMES"


def _find_local_lib_path(filename):
    candidates = [
        os.path.join(SCRIPT_DIR, DEPENDENCIES_DIRNAME, filename),
        os.path.join(os.getcwd(), DEPENDENCIES_DIRNAME, filename),
        os.path.join(SCRIPT_DIR, filename),
        os.path.join(os.getcwd(), filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def read_local_lib(filename):
    path = _find_local_lib_path(filename)
    if path is None:
        raise FileNotFoundError(
            f"Could not find '{filename}'.\n"
            f"Put it in a 'Dependencies' folder next to this script "
            f"(Dependencies/{filename}), or directly next to the script.\n"
            f"See the header comment for download links."
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_local_lib_optional(filename):
    """Like read_local_lib, but returns "" when the file is missing (optional libraries)."""
    path = _find_local_lib_path(filename)
    if path is None:
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _find_engine_file(filename):
    candidates = [
        os.path.join(SCRIPT_DIR, ENGINE_DIRNAME, filename),
        os.path.join(os.getcwd(), ENGINE_DIRNAME, filename),
        os.path.join(SCRIPT_DIR, filename),
        os.path.join(os.getcwd(), filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


_SURFACE_LINE_RE = re.compile(
    r"^(?P<name>[^=:#;]+?)\s*[=:]\s*(?:0[xX])?(?P<hash>[0-9A-Fa-f]{1,8})\s*(?:[#;].*)?$"
)


def parse_surface_names(text):
    """'name = 0xHASH' lines -> [[name, hash_u32], ...] in file order. Malformed lines are skipped;
    a repeated name keeps its first hash."""
    entries, seen = [], set()
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith(("#", ";", "//")):
            continue
        m = _SURFACE_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append([name, int(m.group("hash"), 16)])
    return entries


def load_surface_names():
    path = os.environ.get(SURFACE_NAMES_ENV)
    if not (path and os.path.isfile(path)):
        path = _find_engine_file(SURFACE_NAMES_FILENAME)
    if path is None:
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return parse_surface_names(f.read())
    except OSError:
        return []


def build_cloud_meta(parsed):
    referenced = {b["collisionCloudIndex"] for b in parsed["bounds"] if b["collisionCloudIndex"] >= 0}
    orphans = [
        {"index": k, "offsets": [v["offset"] for v in cloud]}
        for k, cloud in enumerate(parsed["clouds"]) if k not in referenced
    ]
    return {"count": len(parsed["clouds"]), "consumed": parsed["consumed_bytes"], "orphans": orphans}


def write_html(display_bounds, original_bytes, original_filename, num_bounds, out_path,
               model_bytes=b"", model_filename="", model_ext="", radius_is_float=True,
               num_bounds_offset=20, cloud_meta=None):
    three_js_code = read_local_lib(THREE_JS_FILENAME)
    orbit_js_code = read_local_lib(ORBIT_JS_FILENAME)

    # OBJLoader.js is optional; embed its resolved path (or None) so the page can report
    # why model import is unavailable.
    model_lib_filenames = (OBJ_LOADER_FILENAME,)
    model_lib_paths = {name: _find_local_lib_path(name) for name in model_lib_filenames}
    model_loader_code = ";\n".join(
        read_local_lib_optional(name) for name in model_lib_filenames if model_lib_paths[name]
    )

    data_json = json.dumps(display_bounds)
    bin_b64 = base64.b64encode(original_bytes).decode("ascii")
    model_b64 = base64.b64encode(model_bytes).decode("ascii") if model_bytes else ""
    model_lib_status_json = json.dumps({name: path for name, path in model_lib_paths.items()})
    radius_format_json = json.dumps("float" if radius_is_float else "hash")
    cloud_meta_json = json.dumps(cloud_meta or {"count": 0, "consumed": len(original_bytes), "orphans": []})

    html = HTML_TEMPLATE
    html = html.replace("__THREE_JS_CODE__", three_js_code)
    html = html.replace("__ORBIT_CONTROLS_CODE__", orbit_js_code)
    html = html.replace("__MODEL_LOADER_CODE__", model_loader_code)
    html = html.replace("__DATA_JSON__", data_json)
    html = html.replace("__ORIGINAL_BIN_B64__", bin_b64)
    html = html.replace("__ORIGINAL_FILENAME__", original_filename)
    html = html.replace("__ORIGINAL_NUM_BOUNDS__", str(num_bounds))
    html = html.replace("__NUM_BOUNDS_OFFSET__", str(num_bounds_offset))
    html = html.replace("__MODEL_B64__", model_b64)
    html = html.replace("__MODEL_FILENAME__", model_filename)
    html = html.replace("__MODEL_EXT__", model_ext)
    html = html.replace("__MODEL_LIB_STATUS_JSON__", model_lib_status_json)
    html = html.replace("__RADIUS_FORMAT_JSON__", radius_format_json)
    html = html.replace("__CLOUD_META_JSON__", cloud_meta_json)
    surface_names_json = json.dumps(load_surface_names()).replace("</", "<\\/")
    html = html.replace("__SURFACE_NAMES_JSON__", surface_names_json)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ----------------------------------------------------------------------
# File discovery / main
# ----------------------------------------------------------------------

def find_bin_file(args):
    if args:
        return args[0]
    candidates = sorted(glob.glob("*.bin"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise SystemExit(
            "Multiple .bin files found in this folder: " + ", ".join(candidates) +
            "\nPass the one you want explicitly: python core.py <file.bin>"
        )
    return None


def main():
    args = sys.argv[1:]
    bin_path = find_bin_file(args)

    if not bin_path:
        print("No .bin file found.")
        print("Pass one explicitly: python core.py path/to/Collision.bin")
        print("or place exactly one .bin file next to this script.")
        return

    if not os.path.isfile(bin_path):
        print(f"ERROR: '{bin_path}' does not exist.")
        return

    with open(bin_path, "rb") as f:
        original_bytes = f.read()

    try:
        parsed = parse_collision_bin(original_bytes)
    except ValueError as e:
        print(f"ERROR: {e}")
        return

    print(f"Read: {bin_path} ({len(original_bytes)} bytes)")
    print(f"  {len(load_surface_names())} surface name(s) from {ENGINE_DIRNAME}/{SURFACE_NAMES_FILENAME}")
    print(f"  {parsed['num_bounds']} collision bound(s), {len(parsed['clouds'])} cloud(s) "
          f"({', '.join(str(len(c)) + ' verts' for c in parsed['clouds']) or 'none'})")
    if parsed["consumed_bytes"] != len(original_bytes):
        print(f"  NOTE: parser consumed {parsed['consumed_bytes']} bytes but the file "
              f"has {len(original_bytes)} - there may be trailing data this tool doesn't "
              f"understand. It will still be preserved byte-for-byte on save, but double "
              f"check this really is a single extracted Collision chunk.")

    display_bounds = []
    for idx, bound in enumerate(parsed["bounds"]):
        color = color_for_index(idx)
        display_bounds.append(build_bound_json(bound, idx, color, parsed["clouds"], parsed["radius_is_float"]))
        b = bound
        kind = "sphere" if bound_is_sphere(b["boundType"]) else "box"
        print(f"  Bound_{idx}: {kind:6s} halfDim={tuple(round(v,4) for v in b['halfDim'])} "
              f"pos={tuple(round(v,4) for v in b['position'])} "
              f"childrenIndex={b['childrenIndex']} numChildren={b['numberOfChildren']}")

    bin_dir = os.path.dirname(os.path.abspath(bin_path))
    out_file = args[1] if len(args) > 1 and args[1] else os.path.join(bin_dir, "collision_bounds_3d.html")

    # Optional 3rd argument: reference .obj model (visual only).
    model_path = args[2] if len(args) > 2 and args[2] else None
    model_bytes, model_filename, model_ext = b"", "", ""
    if model_path:
        if not os.path.isfile(model_path):
            print(f"WARNING: car model file not found, skipping: {model_path}")
        else:
            with open(model_path, "rb") as mf:
                model_bytes = mf.read()
            model_filename = os.path.basename(model_path)
            model_ext = os.path.splitext(model_path)[1].lower().lstrip(".")
            if model_ext != "obj":
                print(f"WARNING: unsupported car model type '.{model_ext}' (expected .obj), skipping.")
                model_bytes, model_filename, model_ext = b"", "", ""

    try:
        write_html(display_bounds, original_bytes, os.path.basename(bin_path), parsed["num_bounds"], out_file,
                   model_bytes=model_bytes, model_filename=model_filename, model_ext=model_ext,
                   radius_is_float=parsed["radius_is_float"],
                   num_bounds_offset=parsed["num_bounds_offset"],
                   cloud_meta=build_cloud_meta(parsed))
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        return

    print(f"\nSaved: {out_file}")
    print("Fully offline. Click a marker dot to pin/resize a corner, or click a")
    print("bound's NAME in the legend to see & edit every raw field - everything")
    print("is editable there (Position, HalfDimension, Pivot, Orientation, BoundType")
    print("flags, ChildrenIndex, NumberOfChildren, CollisionCloudIndex, hashes);")
    print("the same panel adds/deletes bounds and collision clouds.")
    print("Click 'Export Collision' (top-right, or Ctrl+S) to save your changes -")
    print("it uses your browser's native Save dialog, or downloads a patched")
    print("copy if that's not available.")


if __name__ == "__main__":
    main()
