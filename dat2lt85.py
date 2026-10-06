import os
import sys
import struct
import math
from PIL import Image
import glob
  


def get_parent_dir():
    if getattr(sys, 'frozen', False):
        # если exe
        base_dir = os.path.dirname(sys.executable)
    else:
        # если обычный скрипт
        base_dir = os.path.dirname(os.path.abspath(__file__))
    # спускаемся на один каталог выше
    parent_dir = os.path.dirname(base_dir)
    return parent_dir
    
current_dir = get_parent_dir()

# === Utilities ===
def read_lithtech_string(f):
    (length,) = struct.unpack("<H", f.read(2))  # uint16
    if length == 0:
        return ""
    return f.read(length).decode("utf-8", errors="ignore")
    
class SectionInfo:
    def __init__(self, texture, triangle_count):
        self.texture = texture
        self.triangle_count = triangle_count

def st_gethash_ic(s: str) -> int:
    """
    Implementation of st_GetHashCode_ic from LithTech.
    Returns a uint32 hash of the name.
    """
    n = 0
    for ch in s:
        c = ch.upper()
        val = ord(c) - ord('A') 
        n = (n * 29 + (val & 0xFFFFFFFF)) & 0xFFFFFFFF
    return n

# === Basic Types ===
class Vec3:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    @classmethod
    def read(cls, f):
        return cls(*struct.unpack("<3f", f.read(12)))

    def __repr__(self):
        return f"({self.x:.4f}, {self.y:.4f}, {self.z:.4f})"

    def __sub__(self, other):
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def inverse(self):
        def safe(v): return 1 / v if v != 0 else 0
        return Vec3(safe(self.x), safe(self.y), safe(self.z))

class Vec3u:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    @classmethod
    def read(cls, f):
        return cls(*struct.unpack("<3I", f.read(12)))

    def __repr__(self):
        return f"({self.x}, {self.y}, {self.z})"


class Vec2:
    def __init__(self, x=0, y=0):
        self.x, self.y = x, y

    @classmethod
    def read(cls, f):
        return cls(*struct.unpack("<2f", f.read(8)))

    def __repr__(self):
        return f"({self.x:.4f}, {self.y:.4f})"


class Color:
    @classmethod
    def read(cls, f):
        return Vec3.read(f)

    def __repr__(self):
        return super().__repr__()


class Quaternion:
    def __init__(self, x, y, z, w):
        self.x, self.y, self.z, self.w = x, y, z, w

    @classmethod
    def read(cls, f):
        return cls(*struct.unpack("<4f", f.read(16)))

    def __repr__(self):
        return f"({self.x:.3f}, {self.y:.3f}, {self.z:.3f}, {self.w:.3f})"


# === Header ===
class LithtechHeader:
    def read(self, f):
        unpacked = struct.unpack("<15I", f.read(60))
        (
            self.version,
            self.object_data_pos,
            self.blind_object_data_pos,
            self.lightgrid_pos,
            self.collision_data_pos,
            self.particle_blocker_data_pos,
            self.render_data_pos,
            self.packer_type,
            self.packer_version,
            *self.future
        ) = unpacked

    def print_info(self, out):
        print("Header Information:", file=out)
        print(f"  Version: {self.version}", file=out)
        print(f"  ObjectDataPos:          0x{self.object_data_pos:08X}", file=out)
        print(f"  BlindObjectDataPos:     0x{self.blind_object_data_pos:08X}", file=out)
        print(f"  LightgridPos:           0x{self.lightgrid_pos:08X}", file=out)
        print(f"  CollisionDataPos:       0x{self.collision_data_pos:08X}", file=out)
        print(f"  ParticleBlockerDataPos: 0x{self.particle_blocker_data_pos:08X}", file=out)
        print(f"  RenderDataPos:          0x{self.render_data_pos:08X}", file=out)


# === World Information ===
info_string = ""

class LithtechWorldInfo:
    def read(self, f):
        global info_string
        (strlen,) = struct.unpack("<I", f.read(4))
        info_string = f.read(strlen).decode("utf-8", errors="ignore")
        self.extents_min = Vec3.read(f)
        self.extents_max = Vec3.read(f)
        self.offset = Vec3.read(f)
        # self.extents_diff_inv = (self.extents_max - self.extents_min).inverse()

    def print_info(self, out):
        print("\nWorld Info:", file=out)
        print(f"  Info String:      {info_string}", file=out)
        print(f"  Extents Min:      {self.extents_min}", file=out)
        print(f"  Extents Max:      {self.extents_max}", file=out)
        print(f"  Offset:           {self.offset}", file=out)
        # print(f"  Extents Inverse:  {self.extents_diff_inv}", file=out)


class Vec3:
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z

    @staticmethod
    def read(f):
        return Vec3(*struct.unpack('<3f', f.read(12)))

    def __str__(self):
        return f"({self.x:.6f}, {self.y:.6f}, {self.z:.6f})"

# Surface flags definitions
SURFACE_FLAGS = {
    1 << 0: "SOLID",
    1 << 1: "NONEXISTENT",
    1 << 2: "INVISIBLE",
    1 << 4: "SKY",
    1 << 6: "FLATSHADE",
    1 << 7: "LIGHTMAP",
    1 << 8: "NOSUBDIV",
    1 << 10: "PARTICLEBLOCKER",
    1 << 12: "GOURAUDSHADE",
    1 << 17: "PHYSICSBLOCKER",
    1 << 19: "RBSPLITTER",
    1 << 21: "VISBLOCKER",
    1 << 22: "NOTASTEP",
    1 << 24: "RECEIVELIGHT",
    1 << 25: "RECEIVESHADOWS",
    1 << 26: "RECEIVESUNLIGHT",
    1 << 28: "SHADOWMESH",
    1 << 29: "CASTSHADOWMESH",
    1 << 30: "CLIPLIGHT",
}

def decode_surface_flags(flags):
    return [name for bit, name in SURFACE_FLAGS.items() if flags & bit]

def parse_and_dump_worldtree(data: bytes):
    out = ["Parsed WorldLayout Tree:\n"]

    def read_node(reader, prefix="", is_last=True):
        bit = (reader['data'][reader['byte']] >> reader['bit']) & 1
        reader['bit'] += 1
        if reader['bit'] == 8:
            reader['bit'] = 0
            reader['byte'] += 1

        connector = "└── " if is_last else "├── "
        out.append(prefix + connector + ("[Node]\n" if bit else "[Leaf]\n"))
        new_prefix = prefix + ("    " if is_last else "│   ")
        if bit:
            for i in range(4):
                read_node(reader, new_prefix, i == 3)

    reader = {'data': data, 'byte': 0, 'bit': 0}
    read_node(reader)
    return out


class WorldModel:
    def __init__(self):
        self.dummy = 0
        self.world_info_flags = 0
        self.world_name = ""
        self.texture_names = []  # Added to store the list of textures
        self.points_len = 0
        self.planes_len = 0
        self.surfaces_len = 0
        self.portals = 0
        self.polies_len = 0
        self.leaves_len = 0
        self.polies_vertices_len = 0
        self.visible_list_len = 0
        self.leaf_list = 0
        self.nodes_len = 0
        self.world_bbox_min = Vec3()
        self.world_bbox_max = Vec3()
        self.world_translation = Vec3()

    def read(self, f):

        self.dummy, = struct.unpack('<I', f.read(4))
        self.world_info_flags, = struct.unpack('<I', f.read(4))
        name_len, = struct.unpack('<H', f.read(2))

        self.world_name = f.read(name_len).decode('utf-8')

        self.points_len, = struct.unpack('<I', f.read(4))
        self.planes_len, = struct.unpack('<I', f.read(4))
        self.surfaces_len, = struct.unpack('<I', f.read(4))
        self.portals, = struct.unpack('<I', f.read(4))
        self.polies_len, = struct.unpack('<I', f.read(4))
        self.leaves_len, = struct.unpack('<I', f.read(4))
        self.polies_vertices_len, = struct.unpack('<I', f.read(4))
        self.visible_list_len, = struct.unpack('<I', f.read(4))
        self.leaf_list, = struct.unpack('<I', f.read(4))
        self.nodes_len, = struct.unpack('<I', f.read(4))

        self.world_bbox_min = Vec3.read(f)
        self.world_bbox_max = Vec3.read(f)
        self.world_translation = Vec3.read(f)

        # # Loading the texture name section
        texture_names_size, = struct.unpack('<I', f.read(4))
        texture_names_len, = struct.unpack('<I', f.read(4))
        raw_texture_data = f.read(texture_names_size)

        self.texture_names = self.parse_texture_names(raw_texture_data)        # # Number of vertices in each polygon

        self.vertices_len = list(f.read(self.polies_len))

        # Planes (Vec3 + float)
        self.planes = [(Vec3.read(f), struct.unpack("<f", f.read(4))[0]) for _ in range(self.planes_len)]

        # Surfaces (Flags uint32, TextureIndex uint16, TextureFlags uint16)
        self.surfaces = []
        for _ in range(self.surfaces_len):
            flags, tex_idx, tex_flags = struct.unpack("<IHH", f.read(8))
            self.surfaces.append({
                'Flags': flags,
                'TextureIndex': tex_idx,
                'TextureFlags': tex_flags
            })

        # Polies: surface_index (4) + plane_index (4) + vertex_indices[]
        self.polies = []
        for vert_count in self.vertices_len:
            surface_idx = struct.unpack("<I", f.read(4))[0]
            plane_idx = struct.unpack("<I", f.read(4))[0]
            indices = list(struct.unpack(f"<{vert_count}I", f.read(4 * vert_count)))
            self.polies.append((surface_idx, plane_idx, indices))

        # Nodes: poly_index + zero + [child1, child2]
        self.nodes = []
        for _ in range(self.nodes_len):
            poly_idx = struct.unpack("<I", f.read(4))[0]
            zero = struct.unpack("<H", f.read(2))[0]
            children = struct.unpack("<2i", f.read(8))
            self.nodes.append((poly_idx, zero, children))

        # Points
        self.points = [Vec3.read(f) for _ in range(self.points_len)]

        # Root node index
        self.root_node_index = struct.unpack("<i", f.read(4))[0]

        # Sections (always 0)
        self.sections = struct.unpack("<I", f.read(4))[0]

    def parse_texture_names(self, raw_bytes):
        textures = raw_bytes.split(b'\x00')
        result = []
        for t in textures:
            if not t:
                continue
            # Decode and normalize the path
            name = t.decode('utf-8').replace('\\', '/')
            result.append(name)
        return result


    def print_info(self, out):
        print("\nWorldModel Info:", file=out)
        print(f"  Dummy:               {self.dummy}", file=out)
        print(f"  World Info Flags:    {self.world_info_flags}", file=out)
        print(f"  Name:                {self.world_name}", file=out)
        print(f"  Points:              {self.points_len}", file=out)
        print(f"  Planes:              {self.planes_len}", file=out)
        print(f"  Surfaces:            {self.surfaces_len}", file=out)
        print(f"  Portals:             {self.portals}", file=out)
        print(f"  Polies:              {self.polies_len}", file=out)
        print(f"  Leaves:              {self.leaves_len}", file=out)
        print(f"  Poly Vertices:       {self.polies_vertices_len}", file=out)
        print(f"  Visible List:        {self.visible_list_len}", file=out)
        print(f"  Leaf List:           {self.leaf_list}", file=out)
        print(f"  Nodes:               {self.nodes_len}", file=out)
        # print("\n--- Points ---", file=out)
        # for i, pt in enumerate(self.points):
            # print(f"  [{i}] ({pt.x:.4f}, {pt.y:.4f}, {pt.z:.4f})", file=out)

        # print("\n--- Polygons grouped by Surface ---", file=out)
        # from collections import defaultdict
        # surface_to_polies = defaultdict(list)
        # for poly_idx, (surface_idx, plane_idx, indices) in enumerate(self.polies):
            # surface_to_polies[surface_idx].append((poly_idx, plane_idx, indices))

        # for s_idx in sorted(surface_to_polies.keys()):
            # poly_list = surface_to_polies[s_idx]
            # print(f"  Surface {s_idx}: {len(poly_list)} polygons", file=out)
            # for poly_idx, plane_idx, indices in poly_list:
                # print(f"    [Polygon {poly_idx}] Surface: {s_idx}, Plane: {plane_idx}, PointIndices: {indices}", file=out)


        print(f"  World BBox Min:      {self.world_bbox_min}", file=out)
        print(f"  World BBox Max:      {self.world_bbox_max}", file=out)
        print(f"  World Translation:   {self.world_translation}", file=out)

        print(f"  RootNodeIndex:       {self.root_node_index}", file=out)
        print(f"  Sections (raw):      {self.sections}", file=out)

        print("\n--- Surfaces ---", file=out)
        for i, s in enumerate(self.surfaces):
            flags = s['Flags']
            texture_index = s['TextureIndex']
            texture_flags = s['TextureFlags']
            flag_names = decode_surface_flags(flags)
            flag_str = ', '.join(flag_names) if flag_names else 'None'

            # Get the texture name by index
            if 0 <= texture_index < len(self.texture_names):
                texture_name = self.texture_names[texture_index]
            else:
                texture_name = "<INVALID INDEX>"

            print(f"  [{i}] Flags: 0x{flags:08X} ({flag_str}), "
                  f"TextureIndex: {texture_index} ({texture_name}), "
                  f"TextureFlags: 0x{texture_flags:04X}", file=out)

class WorldTree:
    def __init__(self):
        self.root_bbox_min = Vec3()
        self.root_bbox_max = Vec3()
        self.sub_nodes_len = 0
        self.terrain_depth = 0
        self.world_layout = b""
        self.layout_tree_strs = []
        self.world_models_len = 0
        self.world_models = []

    def read(self, f):
        self.root_bbox_min = Vec3.read(f)
        self.root_bbox_max = Vec3.read(f)
        self.sub_nodes_len, = struct.unpack('<I', f.read(4))
        self.terrain_depth, = struct.unpack('<I', f.read(4))

        layout_len_bytes = (self.sub_nodes_len + 7) // 8
        self.world_layout = f.read(layout_len_bytes)

        self.layout_tree_strs = parse_and_dump_worldtree(self.world_layout)

        self.world_models_len, = struct.unpack('<I', f.read(4))
        self.world_models = []
        for _ in range(self.world_models_len):
            wm = WorldModel()
            wm.read(f)
            self.world_models.append(wm)

    def print_info(self, out):
        print("\nWorldTree Info:", file=out)
        print(f"  Root BBox Min:    {self.root_bbox_min}", file=out)
        print(f"  Root BBox Max:    {self.root_bbox_max}", file=out)
        print(f"  Sub Nodes Len:    {self.sub_nodes_len}", file=out)
        print(f"  Terrain Depth:    {self.terrain_depth}", file=out)
        print(f"  Layout Size:      {len(self.world_layout)} bytes", file=out)

       # out.writelines(self.layout_tree_strs)

        print(f"  WorldModels:      {self.world_models_len} total", file=out)
        for i, wm in enumerate(self.world_models):
            print(f"\n  [WorldModel {i}]", file=out)
            wm.print_info(out)

# === World objects ===
def read_world_objects(f, header, out):
    f.seek(header.object_data_pos)
    (count,) = struct.unpack("<I", f.read(4))
    print(f"\nWorldObjects count: {count}", file=out)

    keyframer_basekeynames = []   # list for KeyFramer BaseKeyName
    scattervolume_names = []      # list for ScatterVolume Name
    occluder_names = {}           # dictionary: {name: hash}

    for i in range(count):
        (object_size,) = struct.unpack("<H", f.read(2))
        obj_type = read_lithtech_string(f)
        (prop_count,) = struct.unpack("<I", f.read(4))
        print(f"\n[Object #{i}] Type: {obj_type}, Properties: {prop_count}", file=out)

        for j in range(prop_count):
            name = read_lithtech_string(f)
            data_type = struct.unpack("<B", f.read(1))[0]
            flags = struct.unpack("<I", f.read(4))[0]
            data_size = struct.unpack("<H", f.read(2))[0]

            value = None
            if name == "RenderGroup" and data_type == 6:
                value = struct.unpack("<f", f.read(4))[0]
            elif data_type == 0:
                value = read_lithtech_string(f)
            elif data_type == 1:
                value = Vec3.read(f)
            elif data_type == 2:
                value = Color.read(f)
            elif data_type == 3:
                value = struct.unpack("<f", f.read(4))[0]
            elif data_type == 5:
                value = struct.unpack("<B", f.read(1))[0] != 0
            elif data_type == 6:
                value = struct.unpack("<f", f.read(4))[0]
            elif data_type == 7:
                value = Quaternion.read(f)
            else:
                f.seek(data_size, 1)
                value = f"<Unknown type {data_type}, skipped {data_size} bytes>"

            print(f"  - {name} = {value}", file=out)

            # Save for KeyFramer → BaseKeyName
            if obj_type == "KeyFramer" and name == "BaseKeyName" and isinstance(value, str):
                keyframer_basekeynames.append(value)

            # Save for ScatterVolume → Name
            if obj_type == "ScatterVolume" and name == "Name" and isinstance(value, str):
                scattervolume_names.append(value)

            # Save for DynamicOccluderVolume → OccluderName1..10
            if obj_type == "DynamicOccluderVolume" and name.startswith("OccluderName") and isinstance(value, str) and value != "":
                if value not in occluder_names:  # save only unique
                    occluder_names[value] = st_gethash_ic(value)

    # You can print the result for debugging
    # print("\n[DEBUG] DynamicOccluderVolume OccluderNames:")
    # for nm, hsh in occluder_names.items():
    #     print(f"  {nm} -> 0x{hsh:08X}")


    return keyframer_basekeynames, scattervolume_names, occluder_names

def read_blind_objects(f, header, keyframer_basekeynames, scattervolume_names, out):
    f.seek(header.blind_object_data_pos)
    (object_count,) = struct.unpack("<I", f.read(4))
    print(f"Blind Objects: {object_count}\n", file=out)

    keyframer_idx = 0
    scatter_idx = 0

    keyframer_data_map = {}

    for obj_idx in range(object_count):
        (engine_size,) = struct.unpack("<I", f.read(4))
        (obj_id,) = struct.unpack("<I", f.read(4))

        print(f"Blind Object {obj_idx + 1}:", file=out)
        print(f"  - ID = {obj_id} (0x{obj_id:08X})", file=out)

        if obj_id == 1789855876:
            if keyframer_idx < len(keyframer_basekeynames):
                key_name = keyframer_basekeynames[keyframer_idx]
            else:
                key_name = "<Unknown KeyFramer Name>"
            keyframer_idx += 1

            keyframer_data_map[key_name] = []

            (key_count,) = struct.unpack("<I", f.read(4))
            print(f"  - KF Name: {key_name}", file=out)
            print(f"  - NumKeys = {key_count}", file=out)

            for key_idx in range(key_count):
                if key_idx == 0:
                    full_key_name = f"{key_name}{key_idx}"
                else:
                    full_key_name = f"{key_name}{key_idx:02d}"

                (key_type,) = struct.unpack("<H", f.read(2))
                (name_len,) = struct.unpack("<B", f.read(1))
                (cmd_len,) = struct.unpack("<B", f.read(1))

                pos = Vec3.read(f)
                rot_deg = Vec3.read(f)

                (timestamp,) = struct.unpack("<f", f.read(4))
                (sound_radius,) = struct.unpack("<f", f.read(4))

                sound_name = f.read(name_len).decode("ascii", errors="ignore")
                command = f.read(cmd_len).decode("ascii", errors="ignore")

                bez_prev = None
                bez_next = None
                if key_type == 0x0000:
                    pass
                elif key_type == 0x0001:
                    bez_prev = Vec3.read(f)
                elif key_type == 0x0002:
                    bez_next = Vec3.read(f)
                elif key_type == 0x0003:
                    bez_prev = Vec3.read(f)
                    bez_next = Vec3.read(f)
                else:
                    raise ValueError(f"Unknown key_type: {key_type:#06x} at file position: 0x{f.tell():08X}")

                # Logging
                print(f"    [Key #{key_idx}] - {full_key_name}:", file=out)
                print(f"    - SoundNameLen = {name_len}", file=out)
                print(f"    - CommandLen = {cmd_len}", file=out)
                print(f"    - Pos = {pos}", file=out)
                print(f"    - Rotation = {rot_deg}", file=out)
                print(f"    - TimeStamp = {timestamp:.6f}", file=out)
                print(f"    - SoundRadius = {sound_radius:.6f}", file=out)
                print(f"    - SoundName = '{sound_name}'", file=out)
                print(f"    - Command = '{command}'", file=out)
                if bez_prev:
                    print(f"    - BezierPrev = {bez_prev}", file=out)
                if bez_next:
                    print(f"    - BezierNext = {bez_next}", file=out)

                keyframer_data_map[key_name].append({
                    "full_name": full_key_name,
                    "pos": pos,
                    "rot_deg": rot_deg,
                    "timestamp": timestamp,
                    "sound_radius": sound_radius,
                    "sound_name": sound_name,
                    "command": command,
                    "bez_prev": bez_prev,
                    "bez_next": bez_next
                })

            print("", file=out)

        elif obj_id == 1945451140:  # ScatterVolume
            if scatter_idx < len(scattervolume_names):
                scatter_name = scattervolume_names[scatter_idx]
            else:
                scatter_name = "<Unknown ScatterVolume Name>"
            scatter_idx += 1

            (num_volumes,) = struct.unpack("<I", f.read(4))
            print(f"  - ScatterVolume name: {scatter_name}", file=out)
            print(f"  - NumVolumes = {num_volumes}", file=out)

            for vi in range(num_volumes):
                pos = Vec3.read(f)
                dims = Vec3.read(f)
                (num_particles,) = struct.unpack("<I", f.read(4))

                print(f"    [Volume #{vi}]: pos={pos}, dims={dims}, particles={num_particles}", file=out)

                for pi in range(num_particles):
                    part_pos = Vec3.read(f)
                    (color,) = struct.unpack("<I", f.read(4))
                    (scale,) = struct.unpack("<f", f.read(4))
                    (waveRot,) = struct.unpack("<B", f.read(1))
                    (waveStart,) = struct.unpack("<B", f.read(1))

                    print(f"      Particle {pi}: pos={part_pos}, color=0x{color:08X}, scale={scale:.6f}, "
                          f"waveRot={waveRot}, waveStart={waveStart}", file=out)
                print("", file=out)

        else:
            f.seek(engine_size, 1)

        print("", file=out)

    return keyframer_data_map


          
def read_particle_blockers(f, header, out):
    f.seek(header.particle_blocker_data_pos)
    (count,) = struct.unpack("<I", f.read(4))
    print(f"\nParticle Blockers: {count}", file=out)

    for i in range(count):
        (vcount,) = struct.unpack("<B", f.read(1))
        verts = [Vec3.read(f) for _ in range(vcount)]
        normal = Vec3.read(f)
        (radius,) = struct.unpack("<f", f.read(4))

        print(f"  [Blocker #{i}] Verts: {vcount}, Radius: {radius:.2f}, Normal: {normal}", file=out)
        for v in verts:
            print(f"    - {v}", file=out)

EPCShaderType = {
    0: "None",                      # No shading
    1: "Gouraud",                   # Textured and vertex-lit
    2: "Lightmap",                  # Base lightmap
    4: "Lightmap",                  # Texturing pass of lightmapping                   Lightmap_Texture!!!
    5: "Skypan",                    # Skypan
    6: "SkyPortal",
    7: "Occluder",
    8: "Gouraud",                   # Gouraud shaded dual texture                      DualTexture!!!
    9: "Lightmap",                  # Texture stage of lightmap shaded dual texture    Lightmap_DualTexture!!!
    10: "Splitter",                 # Renderblock splitter
    11: "Unknown"                   # Error fallback
}

EPCShaderTypeInfoDbg = {
    0: "None",                      # No shading
    1: "Gouraud",                   # Textured and vertex-lit
    2: "Lightmap",                  # Base lightmap
    4: "Lightmap_Texture",          # Texturing pass of lightmapping                   Lightmap_Texture!!!
    5: "Skypan",                    # Skypan
    6: "SkyPortal",
    7: "Occluder",
    8: "DualTexture",               # Gouraud shaded dual texture                      DualTexture!!!
    9: "Lightmap_DualTexture",      # Texture stage of lightmap shaded dual texture    Lightmap_DualTexture!!!
    10: "Splitter",                 # Renderblock splitter
    11: "Unknown"                   # Error fallback
}

# === RenderData ===
def read_render_data(f, header, out, version_flag):
    f.seek(header.render_data_pos)
    (render_node_count,) = struct.unpack("<I", f.read(4))
    print(f"\nRenderData - RENDERNODE count: {render_node_count}", file=out)

    for i in range(render_node_count):
        center = Vec3.read(f)
        half_dims = Vec3.read(f)
        (section_count,) = struct.unpack("<I", f.read(4))

        print(f"\n[RenderNode #{i}]", file=out)
        print(f"  Center:    {center}", file=out)
        print(f"  HalfDims:  {half_dims}", file=out)
        print(f"  Sections:  {section_count}", file=out)

        for s in range(section_count):
            tex0 = read_lithtech_string(f)
            tex1 = read_lithtech_string(f)
            shader_code = struct.unpack("<B", f.read(1))[0]
            tri_count = struct.unpack("<I", f.read(4))[0]
            tex_effect = read_lithtech_string(f)
            w, h, size = struct.unpack("<3I", f.read(12))
            f.read(size)  # lightmap data (compressed)
            shader_name = EPCShaderTypeInfoDbg.get(shader_code, f"Unknown({shader_code})")
            print(f"      [Section {s}] Texture0: {tex0}, Tris: {tri_count}, Shadercode: {shader_name}", file=out)
            if tex1 != "":
                print(f"      [Section {s}] Texture1: {tex1}", file=out)
            if tex_effect != "":
                print(f"        [Section {s}] TextureEffect: {tex_effect}", file=out)

        (vertex_count,) = struct.unpack("<I", f.read(4))
        print(f"  Vertices: {vertex_count}", file=out)
        if version_flag == "-v1":
            f.seek(vertex_count * (12 + 8 + 8 + 4 + 12 + 12 + 12), 1)  # Skip all VERTEX
        else:
            f.seek(vertex_count * (12 + 8 + 8 + 4 + 12), 1)  # Skip all VERTEX

        (tri_count,) = struct.unpack("<I", f.read(4))
        print(f"  Triangles: {tri_count}", file=out)
        f.seek(tri_count * (12 + 4), 1)  # 3*uint32 + poly index

        # Next: sky portals, occluders, lightgroups (can skip for now)
        skip_blocks = struct.unpack("<I", f.read(4))[0]
        if skip_blocks > 0:
            print(f"SkyPortals: {skip_blocks}", file=out)
        for _ in range(skip_blocks):
            vert_count = struct.unpack("<B", f.read(1))[0]
            f.seek(12 * vert_count + 12 + 4, 1)

        skip_occluders = struct.unpack("<I", f.read(4))[0]
        if skip_occluders > 0:
            print(f"Occluders: {skip_occluders}", file=out)
        for _ in range(skip_occluders):
            vert_count = struct.unpack("<B", f.read(1))[0]
            f.seek(12 * vert_count + 12 + 4, 1)
            m_nID = struct.unpack("<I", f.read(4))[0]
            print(f"    Occluders Hashcode: {m_nID}", file=out)

        lightgroups = struct.unpack("<I", f.read(4))[0]
        if lightgroups > 0:
            print(f"LightGroups: {lightgroups}", file=out)
        for lg_index in range(lightgroups):

            lg_name = read_lithtech_string(f)
            print(f"LightGroup{lg_index} name: {lg_name}", file=out)
            f.seek(12, 1)              # skip Vec3 (3 floats = 12 bytes)

            (intensity_data_len,) = struct.unpack("<I", f.read(4))
            f.seek(intensity_data_len, 1)  # skip zero compressed intensity data

            (section_lm_len,) = struct.unpack("<I", f.read(4))
            if section_lm_len > 0:
                for __ in range(section_lm_len):
                    (sublm_len,) = struct.unpack("<I", f.read(4))
                    if sublm_len > 0:
                        for __ in range(sublm_len):
                            f.seek(16, 1)       # skip Left, Top, Width, Height, DataLen (5*4 bytes)
                            (datalen,) = struct.unpack("<I", f.read(4))
                            f.seek(datalen, 1)  # skip actual lightmap data
                    else:
                        # If sublm_len == 0, the loop is skipped; can add log or do nothing
                        pass
            else:
                # If section_lm_len == 0, the loop is skipped; can add log or do nothing
                pass
        child_flags = struct.unpack("<B", f.read(1))[0]
        child_indices = struct.unpack("<2I", f.read(8))
        print(f"  ChildFlags: {child_flags}", file=out)
        print(f"  ChildIndices: {child_indices[0]}, {child_indices[1]}", file=out)
        
    # === WorldModels (WMRENDERNODE) ===
    (wm_node_count,) = struct.unpack("<I", f.read(4))
    print(f"\nWorldModelNodes count: {wm_node_count}", file=out)

    for wm_index in range(wm_node_count):
        name = read_lithtech_string(f)
        print(f"\n[WMRenderNode #{wm_index}] Name: {name}", file=out)
        (subnode_count,) = struct.unpack("<I", f.read(4))
        for subnode_index in range(subnode_count):
            print(f"\n  [SubRenderNode #{subnode_index}]", file=out)

            center = Vec3.read(f)
            half_dims = Vec3.read(f)
            (section_count,) = struct.unpack("<I", f.read(4))
            print(f"    Center: {center}", file=out)
            print(f"    HalfDims: {half_dims}", file=out)
            print(f"    Sections: {section_count}", file=out)

            for s in range(section_count):
                tex0 = read_lithtech_string(f)
                tex1 = read_lithtech_string(f)
                shader_code = struct.unpack("<B", f.read(1))[0]
                tri_count = struct.unpack("<I", f.read(4))[0]
                tex_effect = read_lithtech_string(f)
                w, h, size = struct.unpack("<3I", f.read(12))
                f.read(size)
                shader_name = EPCShaderTypeInfoDbg.get(shader_code, f"Unknown({shader_code})")
                print(f"      [Section {s}] Texture0: {tex0}, Tris: {tri_count}, Shadercode: {shader_name}", file=out)  
                if tex1 != "":
                    print(f"      [Section {s}] Texture1: {tex1}", file=out)
                if tex_effect != "":
                    print(f"        [Section {s}] TextureEffect: {tex_effect}", file=out)

            (vertex_count,) = struct.unpack("<I", f.read(4))
            print(f"    Vertices: {vertex_count}", file=out)
            if version_flag == "-v1":
                f.seek(vertex_count * (12 + 8 + 8 + 4 + 12 + 12 + 12), 1)  # Skip all VERTEX
            else:
                f.seek(vertex_count * (12 + 8 + 8 + 4 + 12), 1)  # Skip all VERTEX

            (tri_count,) = struct.unpack("<I", f.read(4))
            print(f"    Triangles: {tri_count}", file=out)
            f.seek(tri_count * (12 + 4), 1)

            # Next: sky portals, occluders, lightgroups (can skip for now)
            skip_blocks = struct.unpack("<I", f.read(4))[0]
            if skip_blocks > 0:
                print(f"SkyPortals: {skip_blocks}", file=out)
            for _ in range(skip_blocks):
                vert_count = struct.unpack("<B", f.read(1))[0]
                f.seek(12 * vert_count + 12 + 4, 1)

            skip_occluders = struct.unpack("<I", f.read(4))[0]
            if skip_occluders > 0:
                print(f"Occluders: {skip_occluders}", file=out)
            for _ in range(skip_occluders):
                vert_count = struct.unpack("<B", f.read(1))[0]
                f.seek(12 * vert_count + 12 + 4, 1)
                m_nID = struct.unpack("<I", f.read(4))[0]
                print(f"    Occluders Hashcode: {m_nID}", file=out)

            lightgroups = struct.unpack("<I", f.read(4))[0]
            if lightgroups > 0:
                print(f"LightGroups: {lightgroups}", file=out)
            for lg_index in range(lightgroups):

                lg_name = read_lithtech_string(f)
                print(f"LightGroup{lg_index} name: {lg_name}", file=out)
                f.seek(12, 1)              # skip Vec3 (3 floats = 12 bytes)

                (intensity_data_len,) = struct.unpack("<I", f.read(4))
                f.seek(intensity_data_len, 1)  # skip zero compressed intensity data

                (section_lm_len,) = struct.unpack("<I", f.read(4))
                if section_lm_len > 0:
                    for __ in range(section_lm_len):
                        (sublm_len,) = struct.unpack("<I", f.read(4))
                        if sublm_len > 0:
                            for __ in range(sublm_len):
                                f.seek(16, 1)       # skip Left, Top, Width, Height, DataLen (5*4 bytes)
                                (datalen,) = struct.unpack("<I", f.read(4))
                                f.seek(datalen, 1)  # skip actual lightmap data
                        else:
                            # If sublm_len == 0, the loop is skipped; can add log or do nothing
                            pass
                else:
                    # If section_lm_len == 0, the loop is skipped; can add log or do nothing
                    pass
            child_flags = struct.unpack("<B", f.read(1))[0]
            child_indices = struct.unpack("<2I", f.read(8))
            print(f"  ChildFlags: {child_flags}", file=out)
            print(f"  ChildIndices: {child_indices[0]}, {child_indices[1]}", file=out)

        (no_child_flag,) = struct.unpack("<I", f.read(4))
        print(f"  NoChildFlag: {no_child_flag}", file=out)
        
    (lightgroups_len,) = struct.unpack("<I", f.read(4))
    print(f"\n[WorldLightGroups] Count: {lightgroups_len}", file=out)
    for i in range(lightgroups_len):
        name = read_lithtech_string(f)
        color = Vec3.read(f)
        offset = Vec3u.read(f)
        size = Vec3u.read(f)

        total_len = size.x * size.y * size.z
        data = f.read(total_len)

        print(f"  - [{i}] {name}", file=out)
        print(f"      Color: {color}", file=out)
        print(f"      Offset: {offset}", file=out)
        print(f"      Size: {size}", file=out)
        print(f"      DataLen: {total_len}", file=out)


# Directories to search for textures.  The DAT stores texture paths relative to
# the map's texture root (e.g. "map41\\nano30_void\\foo.dtx"), so the search
# roots must include the directory that holds those relative paths.  That
# directory is normally the DAT's own folder (or its "Textures" subfolder, or a
# sibling map folder under "dedit").  It is filled in once we know the DAT path
# (see _init_texture_search_dirs), then reused by every texture lookup.
#
# If a texture dimension is never resolved, the size comes back 0 and
# generate_opq_exact falls back to a degenerate UV basis, smearing ("拉丝")
# every texture across the polyhedron — this module keeps that from happening.
_TEXTURE_SEARCH_DIRS = [current_dir]

# Map of textures the converted map actually uses: {texture_rel_path (lower) :
# absolute source file path}.  Populated as get_dtx_texture_size resolves each
# texture, then used by _export_textures() to stage every referenced .dtx into
# the dedit project's Textures folder so the editor can actually show them.
_REQUIRED_TEXTURES = {}


def _init_texture_search_dirs(dat_path):
    """Seed the texture search roots from the .dat being converted.

    The relative texture paths in a .dat resolve against the folder holding the
    game textures.  That folder is the DAT's own directory plus a handful of
    well-known layout variants (an explicit "Textures" subfolder, and the
    per-map folders under "dedit").  Populate the global list once.
    """
    global _TEXTURE_SEARCH_DIRS
    roots = []
    dat_dir = os.path.dirname(os.path.abspath(dat_path))

    def add(p):
        if p and os.path.isdir(p) and p not in roots:
            roots.append(os.path.normpath(p))

    # The DAT's own directory first (covers "textures right next to the .dat").
    add(dat_dir)
    # An explicit Textures subfolder, e.g. <dat/>Textures/map41/...
    add(os.path.join(dat_dir, "Textures"))
    # Per-map folders alongside the DAT, e.g. <dat/>dedit/<map>/[Textures].
    dedit_dir = os.path.join(dat_dir, "dedit")
    add(dedit_dir)
    if os.path.isdir(dedit_dir):
        try:
            for child in os.listdir(dedit_dir):
                full = os.path.join(dedit_dir, child)
                if os.path.isdir(full):
                    add(full)
                    add(os.path.join(full, "Textures"))
        except OSError:
            pass

    # Keep the original default directory as a last resort.
    add(current_dir)

    # De-duplicate while preserving order.
    seen = set()
    _TEXTURE_SEARCH_DIRS = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            _TEXTURE_SEARCH_DIRS.append(r)


def get_dtx_texture_size(tex_path, search_dirs=None):
    if search_dirs is None:
        search_dirs = _TEXTURE_SEARCH_DIRS

    if tex_path.lower().startswith("lightanim") | tex_path.lower().startswith("default"):
        return 0, 0

    tex_rel = tex_path.replace("\\", "/").lower()

    # Build the ordered search list: explicit roots first, then the seeded ones.
    ordered = []
    for r in search_dirs:
        if r not in ordered:
            ordered.append(r)
    for r in _TEXTURE_SEARCH_DIRS:
        if r not in ordered:
            ordered.append(r)

    found = False
    for root in ordered:
        full_path = os.path.join(root, tex_rel)

        if not os.path.exists(full_path):
            continue

        found = True
        try:
            # --- STEP 1: If .spr — extract the path to .dtx ---
            if full_path.lower().endswith(".spr"):
                with open(full_path, "rb") as f:
                    f.seek(20)
                    dtx_rel_path = read_lithtech_string(f).replace("\\", "/").lower()
                    full_path = os.path.join(root, dtx_rel_path)
                    if not os.path.exists(full_path):
                        print(f"[MISSING] DTX inside SPR not found: {full_path}")
                        continue

            # Record the resolved texture so the export step can stage it into
            # the project's Textures folder (keyed by the original .dtx relative
            # path so unmodified texture names are preserved for the editor).
            _REQUIRED_TEXTURES[tex_rel] = os.path.abspath(full_path)

            # --- STEP 2: Reading DTX dimensions ---
            with open(full_path, "rb") as f:
                f.seek(8)
                w = struct.unpack("<H", f.read(2))[0]
                h = struct.unpack("<H", f.read(2))[0]
                return w, h

        except Exception as e:
            print(f"[WARN] Can't read texture: {full_path} ({e})")

    if not found:
        print(f"[MISSING] Texture not found: {tex_rel}")

    return 0, 0


def _detect_dedit_project(dat_path):
    """Return the dedit project directory that owns this map, if one exists.

    dedit organises each map into its own project folder — a directory that
    contains a "Worlds" subfolder (for the .lta) and a "Textures" subfolder
    (for the .dtx files).  Look for such a folder near the .dat so the exported
    textures and the converted .lta land in the right place for the editor.
    """
    dat_dir = os.path.abspath(os.path.dirname(dat_path))
    map_name = os.path.splitext(os.path.basename(dat_path))[0]

    # Allow an explicit override: point DSH_TEXTURE_OUT at the project folder
    # whose "Textures" subfolder should receive the staged .dtx files.
    override = os.environ.get("DSH_TEXTURE_OUT")
    if override and os.path.isdir(override):
        return os.path.abspath(override)

    candidates = []
    # The DAT's own folder may itself be a project (has Worlds/Textures).
    candidates.append(dat_dir)
    # A "dedit" sibling holding per-map projects: <parent>/dedit/<project>.
    for parent in (os.path.dirname(dat_dir), dat_dir):
        base = os.path.join(parent, "dedit")
        if os.path.isdir(base):
            try:
                for child in os.listdir(base):
                    full = os.path.join(base, child)
                    if os.path.isdir(full):
                        candidates.append(full)
            except OSError:
                pass

    # Prefer a project that already contains this map in its Worlds folder;
    # otherwise the first candidate that looks like a project directory.
    def looks_like_project(p):
        return os.path.isdir(os.path.join(p, "Worlds")) or os.path.isdir(os.path.join(p, "Textures"))

    best = None
    for c in candidates:
        if os.path.isdir(os.path.join(c, "Worlds", f"{map_name}.lta")):
            return c
        if best is None and looks_like_project(c):
            best = c
    return best


def _export_textures(dest_root):
    """Copy every texture the map used into <dest_root>/Textures/.

    dedit resolves texture names like "map41\\nano30_void\\x.dtx" against the
    project's "Textures" folder, so the .dtx files must be staged there keeping
    their relative folder structure.  Only files that are not already present
    are copied; the original case is preserved from the on-disk file.
    """
    if not _REQUIRED_TEXTURES:
        print("  (no textures were referenced, nothing to export)")
        return 0

    tex_root = os.path.join(dest_root, "Textures")
    copied = 0
    skipped = 0
    missing = []

    for rel_lower, src_abs in sorted(_REQUIRED_TEXTURES.items()):
        if not os.path.isfile(src_abs):
            missing.append(rel_lower)
            continue
        # Keep the relative path structure; preserve the on-disk filename case.
        rel_path = rel_lower.replace("/", os.sep)
        dst = os.path.join(tex_root, rel_path)
        # Path name is a relative path; key lookup was lower-cased, but the
        # folder names map to the same tree regardless of case on Windows.
        if os.path.exists(dst):
            skipped += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            import shutil
            shutil.copy2(src_abs, dst)
            copied += 1
        except Exception as e:
            missing.append(f"{rel_lower} ({e})")

    print(f"[textures] staged to {tex_root}: copied={copied} already_present={skipped} missing={len(missing)}")
    for m in missing:
        print(f"[textures] missing source: {m}")
    return copied


import numpy as np


def generate_opq_exact(v0, v1, v2, uv0, uv1, uv2, width, height):
    if width == 0 or height == 0:
        return Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 0, 1)
    
    def barycentric(p0, p1, p2, p):
        area = lambda a, b, c: (b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1])
        n = area(p0, p1, p2)
        if abs(n) < 1e-10:
            return np.array([1.0, 0.0, 0.0])
        u = area(p1, p2, p) / n
        v = area(p2, p0, p) / n
        w = 1.0 - u - v
        return np.array([u, v, w])

    # --- Step 1: invert Y in UV
    t0 = np.array([uv0.x, -uv0.y])
    t1 = np.array([uv1.x, -uv1.y])
    t2 = np.array([uv2.x, -uv2.y])

    # --- Step 2: barycentric for O, P, Q
    bc_o = barycentric(t0, t1, t2, np.array([0.0, 0.0]))
    bc_p = barycentric(t0, t1, t2, np.array([1.0, 0.0]))
    bc_q = barycentric(t0, t1, t2, np.array([0.0, 1.0]))

    # --- Step 3: to world space
    p0 = np.array([v0.x, v0.y, v0.z])
    p1 = np.array([v1.x, v1.y, v1.z])
    p2 = np.array([v2.x, v2.y, v2.z])

    O = bc_o[0]*p0 + bc_o[1]*p1 + bc_o[2]*p2
    P = bc_p[0]*p0 + bc_p[1]*p1 + bc_p[2]*p2 - O
    Q = bc_q[0]*p0 + bc_q[1]*p1 + bc_q[2]*p2 - O

    # --- Step 4: scale factors
    tp = np.linalg.norm(P)
    tq = np.linalg.norm(Q)
    tp = 1.0 / (tp / width) if tp > 1e-8 else 1.0
    tq = 1.0 / (tq / height) if tq > 1e-8 else 1.0

    P = P / np.linalg.norm(P) if np.linalg.norm(P) > 1e-8 else np.array([1.0, 0.0, 0.0])
    Q = Q / np.linalg.norm(Q) if np.linalg.norm(Q) > 1e-8 else np.array([0.0, 1.0, 0.0])

    # --- Step 5: orthogonalize
    R = np.cross(Q, P)
    Pn = np.cross(R, Q)
    Qn = np.cross(P, R)

    Pn = Pn / np.linalg.norm(Pn)
    Qn = Qn / np.linalg.norm(Qn)

    pscale = 1.0 / np.dot(P, Pn)
    qscale = 1.0 / np.dot(Q, Qn)

    P_final = Pn * tp * pscale
    Q_final = Qn * tq * qscale * -1

    return Vec3(*O), Vec3(*P_final), Vec3(*Q_final)


from collections import namedtuple

Vertex = namedtuple("Vertex", ["pos", "normal", "uv", "uv1", "color", "tangent", "binormal"])

def read_vertex_data(f, count, version_flag):
    vertices = []
    for _ in range(count):
        pos = Vec3.read(f)
        uv0 = Vec2.read(f)
        uv1 = Vec2.read(f)
        color = f.read(4)
        normal = Vec3.read(f)
        tangent = binormal = None
        if version_flag == "-v1":
            tangent = Vec3.read(f)
            binormal = Vec3.read(f)
        vertices.append(Vertex(pos, normal, uv0, uv1, color, tangent, binormal))
    return vertices


def skip_lightanim_triangles(f, animbase_tri_count):
    lightanim_indices = []
    for _ in range(animbase_tri_count):
        i0, i1, i2 = struct.unpack("<3I", f.read(12))
        f.read(4)
        lightanim_indices.append((i0, i1, i2))
    if not lightanim_indices:
        return 0
    min_idx = min(min(i0, i1, i2) for (i0, i1, i2) in lightanim_indices)
    max_idx = max(max(i0, i1, i2) for (i0, i1, i2) in lightanim_indices)
    return max_idx - min_idx + 1


def split_triangles_by_sections(triangles, section_infos):
    result = []
    cursor = 0
    for tex0, tex_w, tex_h, tex1, tex_w1, tex_h1, tri_count, shader_str, texture_effect in section_infos:
        tris = triangles[cursor:cursor + tri_count]
        result.append((
            tex0, tex_w, tex_h,
            tex1, tex_w1, tex_h1,
            tris,
            shader_str,
            texture_effect
        ))
        cursor += tri_count
    return result

# === ±inf / NaN UV 兜底（原 DAT 打包阶段缺纹理宽高，dot/0 产生 inf，约半数面受影响）===
# 用顶点自带切空间轴（tangent=纹理P方向, binormal=Q方向）按 LithTech 默认
# 1 texel / 1 world unit 重建平面贴图坐标；切空间退化时按法线方向取同节点
# 有效面投票出的轴向模板；零面积退化面直接给单位基。
_UV_TEMPLATE_VOTES = {}


def _unit_axis(a):
    if a is None:
        return None
    try:
        if not (math.isfinite(a.x) and math.isfinite(a.y) and math.isfinite(a.z)):
            return None
    except AttributeError:
        return None
    ln = math.sqrt(a.x*a.x + a.y*a.y + a.z*a.z)
    if ln < 1e-8:
        return None
    return Vec3(a.x/ln, a.y/ln, a.z/ln)


def _cross3(a, b):
    return Vec3(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)


def _dominant_key(n):
    vals = (n.x, n.y, n.z)
    ax = max(range(3), key=lambda i: abs(vals[i]))
    t = [0, 0, 0]
    t[ax] = 1 if vals[ax] > 0 else -1
    return tuple(t)


def _axes_frame_ok(T, B, n):
    if T is None or B is None or n is None:
        return False
    return (abs(T.x*B.x + T.y*B.y + T.z*B.z) <= 0.05 and
            abs(T.x*n.x + T.y*n.y + T.z*n.z) <= 0.05 and
            abs(B.x*n.x + B.y*n.y + B.z*n.z) <= 0.05)


def _vec2_finite(uv):
    return math.isfinite(uv.x) and math.isfinite(uv.y)


def accumulate_uv_templates(vertices):
    """从 UV 正常的顶点投票统计各法线方向的默认贴图轴（T=P方向, B=Q方向）。"""
    for v in vertices:
        if not (math.isfinite(v.uv.x) and math.isfinite(v.uv.y)):
            continue
        n, T, B = _unit_axis(v.normal), _unit_axis(v.tangent), _unit_axis(v.binormal)
        if not _axes_frame_ok(T, B, n):
            continue
        key = _dominant_key(n)
        bucket = _UV_TEMPLATE_VOTES.setdefault(key, {})
        tpl = ((round(T.x), round(T.y), round(T.z)),
               (round(B.x), round(B.y), round(B.z)))
        bucket[tpl] = bucket.get(tpl, 0) + 1


def _template_axes(n):
    bucket = _UV_TEMPLATE_VOTES.get(_dominant_key(n))
    if not bucket:
        return None, None
    t, b = max(bucket.items(), key=lambda kv: kv[1])[0]
    return Vec3(*t), Vec3(*b)


def _tri_degenerate(p0, p1, p2):
    e1 = Vec3(p1.x-p0.x, p1.y-p0.y, p1.z-p0.z)
    e2 = Vec3(p2.x-p0.x, p2.y-p0.y, p2.z-p0.z)
    cr = _cross3(e1, e2)
    l1 = e1.x*e1.x + e1.y*e1.y + e1.z*e1.z
    l2 = e2.x*e2.x + e2.y*e2.y + e2.z*e2.z
    if l1 <= 1e-12 or l2 <= 1e-12:
        return True
    return (cr.x*cr.x + cr.y*cr.y + cr.z*cr.z) / (l1*l2) < 1e-10


def synth_planar_uv(p0, p1, p2, v0, v1, v2, width, height):
    """给 UV 非有限的三角面生成默认平面贴图坐标，v0/v1/v2 为 Vertex（取法线与切空间轴），
    返回合成的 (uv0,uv1,uv2)。"""
    n = _unit_axis(v0.normal)
    T, B = _unit_axis(v0.tangent), _unit_axis(v0.binormal)
    if not _axes_frame_ok(T, B, n):
        if n is not None:
            tT, tB = _template_axes(n)
            if tT is not None:
                T, B = tT, tB
        if not _axes_frame_ok(T, B, n):
            n = n or Vec3(0, 0, 1)
            ref = Vec3(0, 0, 1) if abs(n.z) < 0.9 else Vec3(1, 0, 0)
            d = n.x*ref.x + n.y*ref.y + n.z*ref.z
            T = _unit_axis(Vec3(ref.x-n.x*d, ref.y-n.y*d, ref.z-n.z*d)) or Vec3(1, 0, 0)
            B = _cross3(n, T)

    def one(p):
        return Vec2((T.x*p.x + T.y*p.y + T.z*p.z) / width,
                    (B.x*p.x + B.y*p.y + B.z*p.z) / height)
    return one(p0), one(p1), one(p2)


_UNIT_UV_BASIS = (Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 0, 1))


def safe_texture_basis(p0, p1, p2, v0, v1, v2, uv_attr, width, height):
    """生成贴图 O/P/Q。v0/v1/v2 为 Vertex；uv_attr='uv'/'uv1' 指定贴图通道。
    UV 正常走原反推；UV 非有限或面退化时走兜底，保证输出恒有限、不产生 NaN。"""
    u0, u1, u2 = getattr(v0, uv_attr), getattr(v1, uv_attr), getattr(v2, uv_attr)
    if (width and height and
            _vec2_finite(u0) and _vec2_finite(u1) and _vec2_finite(u2)):
        return generate_opq_exact(p0, p1, p2, u0, u1, u2, width, height)
    if not width or not height or _tri_degenerate(p0, p1, p2):
        return _UNIT_UV_BASIS
    su0, su1, su2 = synth_planar_uv(p0, p1, p2, v0, v1, v2, width, height)
    O, P, Q = generate_opq_exact(p0, p1, p2, su0, su1, su2, width, height)
    vals = (O.x, O.y, O.z, P.x, P.y, P.z, Q.x, Q.y, Q.z)
    if all(math.isfinite(x) for x in vals):
        return O, P, Q
    return _UNIT_UV_BASIS


def write_polyhedron(out_file, vertices, section_triangles):

    out_file.write("\t\t( polyhedron (\n")
    out_file.write("\t\t\t( color 255 255 255 )\n")
    out_file.write("\t\t\t( pointlist \n")
    for v in vertices:
        adjusted_v = apply_world_offset(v.pos)
        out_file.write(f"\t\t\t\t( {write_vec3(adjusted_v)} 255 255 255 255 )\n")
    out_file.write("\t\t\t)\n\t\t\t( polylist (\n")

    for tex_name, tex_w, tex_h, tex1_name, tex1_w, tex1_h, tris, shader_str, texture_effect in section_triangles:
        for tri in tris:
            v0, v1, v2 = [vertices[i] for i in tri]

            # Apply world offset to positions
            p0 = apply_world_offset(v0.pos)
            p1 = apply_world_offset(v1.pos)
            p2 = apply_world_offset(v2.pos)

            n = v0.normal
            # 源数据法线损坏（非有限/未单位化）时用几何法线兜底
            finite_n = (n is not None and
                        math.isfinite(n.x) and math.isfinite(n.y) and math.isfinite(n.z))
            if not finite_n or _unit_axis(n) is None:
                geon = _cross3(Vec3(p1.x-p0.x, p1.y-p0.y, p1.z-p0.z),
                               Vec3(p2.x-p0.x, p2.y-p0.y, p2.z-p0.z))
                n = _unit_axis(geon) or Vec3(0, 0, 1)

            # Recalculate dist using the offset positions
            dist = p0.x * n.x + p0.y * n.y + p0.z * n.z

            # Generate origin/U/V taking WORLD_OFFSET into account
            origin, U, V = safe_texture_basis(p0, p1, p2, v0, v1, v2, "uv", tex_w, tex_h)
            origin1, U1, V1 = safe_texture_basis(p0, p1, p2, v0, v1, v2, "uv1", tex1_w, tex1_h)
            out_file.write("\t\t\t\t( editpoly \n")
            out_file.write(f"\t\t\t\t\t( f {tri[0]} {tri[1]} {tri[2]} )\n")
            out_file.write(f"\t\t\t\t\t( n {write_vec3(n)} )\n")
            out_file.write(f"\t\t\t\t\t( dist {dist:.6f} )\n")
            out_file.write("\t\t\t\t\t( textureinfo \n")
            out_file.write(f"\t\t\t\t\t\t( {write_vec3(origin)} )\n")
            out_file.write(f"\t\t\t\t\t\t( {write_vec3(U)} )\n")
            out_file.write(f"\t\t\t\t\t\t( {write_vec3(V)} )\n")
            out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
            out_file.write(f'\t\t\t\t\t\t( name "{tex_name}" )\n')
            out_file.write("\t\t\t\t\t)\n")
            out_file.write("\t\t\t\t\t( flags )\n")
            out_file.write("\t\t\t\t\t( shade 0 0 0 )\n")
            out_file.write('\t\t\t\t\t( physicsmaterial "Default" )\n')
            out_file.write('\t\t\t\t\t( surfacekey "" )\n')
            out_file.write("\t\t\t\t\t( textures ( \n")
            out_file.write("\t\t\t\t\t\t( 1 ( textureinfo \n")
            out_file.write(f"\t\t\t\t\t\t\t( {write_vec3(origin1)} )\n")
            out_file.write(f"\t\t\t\t\t\t\t( {write_vec3(U1)} )\n")
            out_file.write(f"\t\t\t\t\t\t\t( {write_vec3(V1)} )\n")
            out_file.write(f'\t\t\t\t\t\t\t( sticktopoly 1 )\n')
            out_file.write(f'\t\t\t\t\t\t\t( name "{tex1_name}" )\n')
            out_file.write("\t\t\t\t\t\t) )\n")
            out_file.write("\t\t\t\t\t) )\n")
            out_file.write("\t\t\t\t)\n")

    out_file.write("\t\t\t) )\n\t\t) )\n")

def read_world_objects_lta(f, header):
    f.seek(header.object_data_pos)
    (count,) = struct.unpack("<I", f.read(4))
    objects = []
    metas = []
    for i in range(count):
        (object_size,) = struct.unpack("<H", f.read(2))
        obj_type = read_lithtech_string(f)
        (prop_count,) = struct.unpack("<I", f.read(4))
        props = {"__Type": obj_type}
        meta = {}
        for _ in range(prop_count):
            name = read_lithtech_string(f)
            data_type = struct.unpack("<B", f.read(1))[0]
            flags = struct.unpack("<I", f.read(4))[0]
            data_size = struct.unpack("<H", f.read(2))[0]

            if data_type == 0:
                value = read_lithtech_string(f)
                meta_type = "string"
            elif data_type == 1:
                value = Vec3.read(f)
                meta_type = "vector"
            elif data_type == 2:
                value = Vec3.read(f)
                meta_type = "color"
            elif data_type == 3:
                value = struct.unpack("<f", f.read(4))[0]
                meta_type = "real"
            elif data_type == 5:
                value = struct.unpack("<B", f.read(1))[0] != 0
                meta_type = "bool"
            elif data_type == 6:
                value = struct.unpack("<f", f.read(4))[0]
                meta_type = "longint"
            elif data_type == 7:
                value = Quaternion.read(f)
                meta_type = "rotation"
            else:
                f.seek(data_size, 1)
                value = None
                meta_type = "string"

            props[name] = value
            # Keep the raw PF_* property flags (ltserverobj.h) so the LTA writer
            # can restore the exact editor tokens (distance/radius/group1/
            # staticlist/hidden/...).  Dropping them corrupts composite groups
            # such as the Light attenuation controls.
            meta[name] = {"type": meta_type, "flags": flags}

        objects.append(props)
        metas.append(meta)

    return objects, metas

WORLD_OFFSET = None

def read_world_info(f):
    global WORLD_OFFSET
    world_info = LithtechWorldInfo()
    world_info.read(f)
    WORLD_OFFSET = world_info.offset  # Now available throughout the script
    return world_info

def apply_world_offset(vec):
    if WORLD_OFFSET is None:
        return vec  # offset is not set yet
    return Vec3(
        vec.x + WORLD_OFFSET.x,
        vec.y + WORLD_OFFSET.y,
        vec.z + WORLD_OFFSET.z)

def write_vec3(vec):
    return f"{vec.x:.6f} {vec.y:.6f} {vec.z:.6f}"

# --- LithTech property flags -> LTA flag tokens (ltserverobj.h PF_* enum) ---
# Bits 6..11 (NUM_GROUP_BITS=6, FIRST_GROUP_BIT=6) encode the group number:
# groupN token iff N>0, emitted right after "groupowner".  The remaining tokens
# are listed in the same order DEdit's own converter emits them; token order is
# irrelevant to the loader (EditRegion.cpp ORs each bit), but matching it keeps
# diffs against known-good LTA files readable.
def prop_flag_tokens(flags):
    tokens = []
    if flags & (1 << 5):          # PF_GROUPOWNER
        tokens.append("groupowner")
    group_num = (flags >> 6) & 0x3F
    if group_num:
        tokens.append(f"group{group_num}")
    for bit, token in (
        (1 << 1,  "radius"),             # PF_RADIUS
        (1 << 20, "distance"),           # PF_DISTANCE
        (1 << 2,  "dims"),               # PF_DIMS
        (1 << 4,  "localdims"),          # PF_LOCALDIMS
        (1 << 0,  "hidden"),             # PF_HIDDEN
        (1 << 13, "objectlink"),         # PF_OBJECTLINK
        (1 << 14, "filename"),           # PF_FILENAME
        (1 << 15, "bezierprevtangent"),  # PF_BEZIERPREVTANGENT
        (1 << 16, "beziernexttangent"),  # PF_BEZIERNEXTTANGENT
        (1 << 17, "staticlist"),         # PF_STATICLIST
        (1 << 18, "dynamiclist"),        # PF_DYNAMICLIST
        (1 << 19, "compositetype"),      # PF_COMPOSITETYPE
        (1 << 3,  "fieldofview"),        # PF_FIELDOFVIEW
        (1 << 12, "fovradius"),          # PF_FOVRADIUS
        (1 << 21, "model"),              # PF_MODEL
        (1 << 22, "orthofrustum"),       # PF_ORTHOFRUSTUM
        (1 << 23, "notifychange"),       # PF_NOTIFYCHANGE
        (1 << 24, "event"),              # PF_EVENT
        (1 << 25, "textureeffect"),      # PF_TEXTUREEFFECT
    ):
        if flags & bit:
            tokens.append(token)
    return " ".join(tokens)

def write_physics_polygons(f, header, out_file):
    f.seek(header.collision_data_pos)
    (poly_count,) = struct.unpack("<I", f.read(4))

    for i in range(poly_count):
        # Read the plane
        normal = Vec3.read(f)
        (dist,) = struct.unpack("<f", f.read(4))

        # Read the number of vertices
        (vcount,) = struct.unpack("<I", f.read(4))

        verts = [Vec3.read(f) for _ in range(vcount)]
        out_file.write("\t\t( polyhedron (\n")
        out_file.write("\t\t\t( color 255 255 255 )\n")
        out_file.write("\t\t\t( pointlist \n")
        for v in verts:
            adjusted_v = apply_world_offset(v)
            out_file.write(f"\t\t\t\t( {write_vec3(adjusted_v)} 255 255 255 255 )\n")
        out_file.write("\t\t\t)\n\t\t\t( polylist (\n")
        out_file.write("\t\t\t\t( editpoly \n")
        out_file.write(f"\t\t\t\t\t( f {' '.join(str(j) for j in range(vcount))} )\n")
        out_file.write(f"\t\t\t\t\t( n {write_vec3(normal)} )\n")
        out_file.write(f"\t\t\t\t\t( dist {dist:.6f} )\n")
        out_file.write("\t\t\t\t\t( textureinfo \n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write(f'\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t)\n")
        out_file.write("\t\t\t\t\t( flags )\n")
        out_file.write("\t\t\t\t\t( shade 0 0 0 )\n")
        out_file.write("\t\t\t\t\t( physicsmaterial \"Default\" )\n")
        out_file.write("\t\t\t\t\t( surfacekey \"\" )\n")
        out_file.write("\t\t\t\t\t( textures ( \n")
        out_file.write("\t\t\t\t\t\t( 1 ( textureinfo \n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write(f'\t\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t)\n")
        out_file.write("\t\t\t) )\n\t\t) )\n")
    return poly_count

def write_particleblockers_polygons(f, header, out_file):
    f.seek(header.particle_blocker_data_pos)
    (poly_count,) = struct.unpack("<I", f.read(4))

    for i in range(poly_count):
        # Read the plane
        normal = Vec3.read(f)
        (dist,) = struct.unpack("<f", f.read(4))

        # Read the number of vertices
        (vcount,) = struct.unpack("<I", f.read(4))

        verts = [Vec3.read(f) for _ in range(vcount)]

        out_file.write("\t\t( polyhedron (\n")
        out_file.write("\t\t\t( color 255 255 255 )\n")
        out_file.write("\t\t\t( pointlist \n")
        for v in verts:
            adjusted_v = apply_world_offset(v)
            out_file.write(f"\t\t\t\t( {write_vec3(adjusted_v)} 255 255 255 255 )\n")
        out_file.write("\t\t\t)\n\t\t\t( polylist (\n")
        out_file.write("\t\t\t\t( editpoly \n")
        out_file.write(f"\t\t\t\t\t( f {' '.join(str(j) for j in range(vcount))} )\n")
        out_file.write(f"\t\t\t\t\t( n {write_vec3(normal)} )\n")
        out_file.write(f"\t\t\t\t\t( dist {dist:.6f} )\n")
        out_file.write("\t\t\t\t\t( textureinfo \n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write(f'\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t)\n")
        out_file.write("\t\t\t\t\t( flags )\n")
        out_file.write("\t\t\t\t\t( shade 0 0 0 )\n")
        out_file.write("\t\t\t\t\t( physicsmaterial \"Default\" )\n")
        out_file.write("\t\t\t\t\t( surfacekey \"\" )\n")
        out_file.write("\t\t\t\t\t( textures ( \n")
        out_file.write("\t\t\t\t\t\t( 1 ( textureinfo \n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write(f'\t\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t)\n")
        out_file.write("\t\t\t) )\n\t\t) )\n")
    return poly_count

def write_occ(out_file, skyportals_all):

    for verts, normal, dist, occ_hashcode in skyportals_all:
        out_file.write("\t\t( polyhedron (\n")
        out_file.write("\t\t\t( color 255 255 255 )\n")
        out_file.write("\t\t\t( pointlist \n")

        for v in verts:
            adjusted_v = apply_world_offset(v)
            out_file.write(f"\t\t\t\t( {write_vec3(adjusted_v)} 255 255 255 255 )\n")
        out_file.write("\t\t\t)\n")
        out_file.write("\t\t\t( polylist (\n")
        out_file.write("\t\t\t\t( editpoly \n")
        out_file.write("\t\t\t\t\t( f 0 1 2 3 )\n")
        out_file.write(f"\t\t\t\t\t( n {write_vec3(normal)} )\n")
        out_file.write(f"\t\t\t\t\t( dist {dist:.6f} )\n")
        out_file.write("\t\t\t\t\t( textureinfo \n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write('\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t( flags )\n")
        out_file.write("\t\t\t\t\t( shade 0 0 0 )\n")
        out_file.write("\t\t\t\t\t( physicsmaterial \"Default\" )\n")
        out_file.write("\t\t\t\t\t( surfacekey \"\" )\n")
        out_file.write("\t\t\t\t\t( textures ( \n")
        out_file.write("\t\t\t\t\t\t( 1 ( textureinfo \n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write("\t\t\t\t\t\t\t( name \"Default\" )\n")
        out_file.write("\t\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t) )\n")
        
def write_skypo(out_file, skyportals_all):

    for verts, normal, dist in skyportals_all:
        out_file.write("\t\t( polyhedron (\n")
        out_file.write("\t\t\t( color 255 255 255 )\n")
        out_file.write("\t\t\t( pointlist \n")

        for v in verts:
            adjusted_v = apply_world_offset(v)
            out_file.write(f"\t\t\t\t( {write_vec3(adjusted_v)} 255 255 255 255 )\n")
        out_file.write("\t\t\t)\n")
        out_file.write("\t\t\t( polylist (\n")
        out_file.write("\t\t\t\t( editpoly \n")
        out_file.write("\t\t\t\t\t( f 0 1 2 3 )\n")
        out_file.write(f"\t\t\t\t\t( n {write_vec3(normal)} )\n")
        out_file.write(f"\t\t\t\t\t( dist {dist:.6f} )\n")
        out_file.write("\t\t\t\t\t( textureinfo \n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write(f"\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write('\t\t\t\t\t\t( name "Default" )\n')
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t( flags )\n")
        out_file.write("\t\t\t\t\t( shade 0 0 0 )\n")
        out_file.write("\t\t\t\t\t( physicsmaterial \"Default\" )\n")
        out_file.write("\t\t\t\t\t( surfacekey \"\" )\n")
        out_file.write("\t\t\t\t\t( textures ( \n")
        out_file.write("\t\t\t\t\t\t( 1 ( textureinfo \n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
        out_file.write("\t\t\t\t\t\t\t( sticktopoly 1 )\n")
        out_file.write("\t\t\t\t\t\t\t( name \"Default\" )\n")
        out_file.write("\t\t\t\t\t\t) )\n")
        out_file.write("\t\t\t\t\t) )\n")
        out_file.write("\t\t) )\n")

skyportals_all = []
occluders_all = []

def _lithtech_rle_decode(data):
    """LithTech TGA式RLE解码（光照贴图/灯光网格通用）：
    tag字节 0x80|(len-1)=run，后跟3字节颜色重复len次；(len-1)=raw span，后跟len*3字节。
    源码依据 tools/shared/engine/lightmap_compress.cpp DecompressLMData。"""
    out = bytearray()
    pos = 0
    n = len(data)
    while pos < n:
        tag = data[pos]; pos += 1
        ln = (tag & 0x7F) + 1
        if tag & 0x80:
            out += data[pos:pos + 3] * ln
            pos += 3
        else:
            nb = ln * 3
            out += data[pos:pos + nb]
            pos += nb
    return bytes(out)

def estimate_ambient_from_lightmaps(f, header, report=False):
    """从主世界光照贴图反推原版环境光。
    原理：LightMapMaker 用 m_AmbientLight 作光照贴图填充底色，零直射光区域的 texel
    精确等于环境光值——填充色是任何texel能达到的最低非零值，取占比>=1%的最暗色即为地板。
    report=True 时打印完整直方图复核信息（top颜色/暗色尾巴/亮度分布/地板值）。
    返回 (r,g,b)；无法估计（无光照贴图/数据异常）时返回 None。"""
    from collections import Counter
    back = f.tell()
    try:
        f.seek(header.render_data_pos)
        (rnc,) = struct.unpack("<I", f.read(4))
        if rnc == 0 or rnc > 100000:
            return None
        cnt = Counter()
        for _ in range(rnc):
            Vec3.read(f); Vec3.read(f)
            (sc,) = struct.unpack("<I", f.read(4))
            if sc > 100000:
                return None
            for _ in range(sc):
                read_lithtech_string(f); read_lithtech_string(f)
                f.read(1)  # shader
                f.read(4)  # tri count
                read_lithtech_string(f)
                w, h, size = struct.unpack("<3I", f.read(12))
                data = f.read(size)
                if size and 0 < w * h * 3 <= 16_000_000:
                    raw = _lithtech_rle_decode(data)
                    if len(raw) == w * h * 3:
                        cnt.update(zip(raw[0::3], raw[1::3], raw[2::3]))
            # 跳过节点尾部（顶点/三角形/天空门/遮挡体/灯光组/子节点标记）
            (vc,) = struct.unpack("<I", f.read(4))
            if vc > 50_000_000: return None
            f.seek(vc * 68, 1)
            (tc,) = struct.unpack("<I", f.read(4))
            if tc > 50_000_000: return None
            f.seek(tc * 16, 1)
            (sb,) = struct.unpack("<I", f.read(4))
            if sb > 10_000_000: return None
            for _ in range(sb):
                vcn = f.read(1)[0]; f.seek(12 * vcn + 16, 1)
            (so,) = struct.unpack("<I", f.read(4))
            if so > 10_000_000: return None
            for _ in range(so):
                vcn = f.read(1)[0]; f.seek(12 * vcn + 20, 1)
            (lg,) = struct.unpack("<I", f.read(4))
            if lg > 1_000_000: return None
            for _ in range(lg):
                read_lithtech_string(f); f.seek(12, 1)
                (idl,) = struct.unpack("<I", f.read(4)); f.seek(idl, 1)
                (sl,) = struct.unpack("<I", f.read(4))
                if sl > 1_000_000: return None
                for __ in range(sl):
                    (subl,) = struct.unpack("<I", f.read(4))
                    if subl > 1_000_000: return None
                    for ___ in range(subl):
                        f.seek(16, 1)
                        (dl,) = struct.unpack("<I", f.read(4)); f.seek(dl, 1)
            f.read(1); f.read(8)
        if not cnt:
            if report:
                print("[ambient] 主世界无可用光照贴图")
            return None
        total = sum(cnt.values())
        if report:
            print(f"[ambient] 光照贴图统计: {total} texels, {len(cnt)} 种颜色")
            print("[ambient] top 颜色 (rgb: 数量 占比):")
            for rgb0, c0 in cnt.most_common(10):
                print(f"    {rgb0}: {c0} ({100.0 * c0 / total:.2f}%)")
            dark = [(rgb0, c0) for rgb0, c0 in cnt.items()
                    if rgb0 != (0, 0, 0) and sum(rgb0) <= 384]
            dark.sort(key=lambda t: -t[1])
            if dark:
                print("[ambient] top 暗色(非黑, sum<=384):")
                for rgb0, c0 in dark[:8]:
                    print(f"    {rgb0}: {c0} ({100.0 * c0 / total:.2f}%)")
            buckets = [0] * 10
            for rgb0, c0 in cnt.items():
                buckets[min(9, (rgb0[0] + rgb0[1] + rgb0[2]) // 3 // 26)] += c0
            print(f"[ambient] 亮度分布 [0-25,26-51,...,234-255]: {buckets}")
        # 环境光=光照贴图的亮度地板：填充色是任何texel能达到的最低非零值（LightMapMaker
        # 用环境光作填充底，光照只在其上叠加），故取占比>=1%的非黑色中亮度最低者。
        # 实测：christmas→(85,85,85) 22.5%，Transportship_ren→(152,152,152) 16.6%
        cands = [(rgb, c) for rgb, c in cnt.items()
                 if rgb != (0, 0, 0) and c >= total * 0.01]
        if not cands:
            if report:
                print("[ambient] 无占比>=1%的非黑色，无法确定地板")
            return None
        rgb, c = min(cands, key=lambda t: (sum(t[0]), -t[1]))
        if report:
            print(f"[ambient] 地板值 = {rgb} ({100.0 * c / total:.2f}%)")
        return rgb
    except Exception:
        return None
    finally:
        f.seek(back)

def export_rendernodes_to_lta(f, header, out_file, map_name, worldtree, keyframer_keys_map, occluder_names, version_flag):
    from collections import namedtuple, defaultdict

    current_pos = f.tell()
    f.seek(header.object_data_pos)
    world_objects, world_objects_meta = read_world_objects_lta(f, header)

    f.seek(header.render_data_pos)
    (render_node_count,) = struct.unpack("<I", f.read(4))

    section_brushes = []
    section_brushes_by_node = defaultdict(list)
    _UV_TEMPLATE_VOTES.clear()

    # 环境光以烘焙光照贴图反推的地板值为准（烘焙值=原版观感的唯一真值）：
    # - infostring 为空 → 用反推值，失败回退默认
    # - infostring 已有 AmbientLight 但与烘焙地板不符（_ren 类改图常见：改了串没重烘焙）→ 覆盖并警告
    global info_string
    est = estimate_ambient_from_lightmaps(f, header, report=True)
    if not info_string.strip():
        if est:
            info_string = "AmbientLight %d %d %d" % est
            print(f"[ambient] 从原版光照贴图反推环境光: AmbientLight {est[0]} {est[1]} {est[2]}")
        else:
            info_string = "AmbientLight 85 85 85"
            print("[ambient] 光照贴图不可用，注入默认环境光: AmbientLight 85 85 85")
    elif est:
        import re
        mm = re.search(r"ambientlight\s+(\d+)\s+(\d+)\s+(\d+)", info_string, re.I)
        if mm:
            old = tuple(int(g) for g in mm.groups())
            if old != est:
                info_string = info_string[:mm.start()] + f"AmbientLight {est[0]} {est[1]} {est[2]}" + info_string[mm.end():]
                print(f"[ambient] 警告: DAT infostring 环境光 {old} 与烘焙光照贴图地板 {est} 不符，已按烘焙值覆盖")
        else:
            info_string = info_string.strip() + f" AmbientLight {est[0]} {est[1]} {est[2]}"
            print(f"[ambient] infostring 无 AmbientLight，追加烘焙地板值: AmbientLight {est[0]} {est[1]} {est[2]}")

    out_file.write(f"( world\n\t( header (\n\t\t( versioncode 2 )\n\t\t( infostring \"{info_string}\" )\n\t) )\n\t( polyhedronlist (\n")

    for node_index in range(render_node_count):
        center = Vec3.read(f)
        half_dims = Vec3.read(f)
        (section_count,) = struct.unpack("<I", f.read(4))

        # 1) Read all sections entirely (DO NOT skip lightanim), mark which ones to ignore
        sections = []
        for _ in range(section_count):
            tex0 = read_lithtech_string(f)
            tex1 = read_lithtech_string(f)

            shader_type_byte = f.read(1)[0]
            tri_count = struct.unpack("<I", f.read(4))[0]
            texture_effect = read_lithtech_string(f)
            w, h, size = struct.unpack("<3I", f.read(12))
            f.read(size)

            # normalize names
            t0 = tex0.strip()
            t1 = tex1.strip()
            if t0 == "":
                tex0 = "Default"
            if t1 == "":
                tex1 = "Default"

            is_lightanim = (t0.lower() == "lightanim_base")
            shader_str = EPCShaderType.get(shader_type_byte, "Unknown")
            tex_w,  tex_h  = get_dtx_texture_size(tex0, search_dirs=[current_dir])
            tex_w1, tex_h1 = get_dtx_texture_size(tex1, search_dirs=[current_dir])

            sections.append({
                "is_lightanim": is_lightanim,
                "tex0": tex0, "tex1": tex1,
                "tex_w": tex_w, "tex_h": tex_h,
                "tex_w1": tex_w1, "tex_h1": tex_h1,
                "tri_count": tri_count,
                "shader_str": shader_str,
                "texture_effect": texture_effect,
            })

        # 2) Read all vertices WITHOUT skips
        (vertex_count,) = struct.unpack("<I", f.read(4))
        vertices = read_vertex_data(f, vertex_count, version_flag)
        accumulate_uv_templates(vertices)

        # 3) Read all triangles WITHOUT skips
        (tri_count_total,) = struct.unpack("<I", f.read(4))
        all_tris = []
        for _ in range(tri_count_total):
            i0, i1, i2 = struct.unpack("<3I", f.read(12))
            f.read(4)  # poly index/flags — ignore
            all_tris.append((i0, i1, i2))

        # 4) Sanity-check — sum of tri_count across sections should match tri_count_total
        if sum(s["tri_count"] for s in sections) != len(all_tris):
            print(f"[WARN] RenderNode {node_index}: sum(section.tri_count) != total tris")

        # 5) Slice by sections in original order and FILTER out lightanim
        cursor = 0
        kept_sections = []  # list of tuples as for write_polyhedron
        for s in sections:
            tris = all_tris[cursor:cursor + s["tri_count"]]
            cursor += s["tri_count"]
            if s["is_lightanim"]:
                # completely ignore lightanim_base section
                continue

            kept_sections.append((
                s["tex0"], s["tex_w"], s["tex_h"],
                s["tex1"], s["tex_w1"], s["tex_h1"],
                tris, s["shader_str"], s["texture_effect"]
            ))

        # 6) Local repacking of vertices/indices and write polyhedron per section
        for section_idx, (tex0, tex_w, tex_h, tex1, tex_w1, tex_h1, tris, shader_str, texture_effect) in enumerate(kept_sections):
            # gather local vertices to avoid dependency on global indices
            local_verts = []
            index_map = {}
            for i0, i1, i2 in tris:
                for i in (i0, i1, i2):
                    if i not in index_map:
                        index_map[i] = len(local_verts)
                        local_verts.append(vertices[i])

            local_tris = [(index_map[i0], index_map[i1], index_map[i2]) for (i0, i1, i2) in tris]

            write_polyhedron(
                out_file,
                local_verts,
                [(tex0, tex_w, tex_h, tex1, tex_w1, tex_h1, local_tris, shader_str, texture_effect)]
            )

            label = f"Brush_RN{node_index}_S{section_idx}"
            section_brushes_by_node[node_index].append((label, len(section_brushes), shader_str, texture_effect))
            section_brushes.append((label, len(section_brushes)))

        # 7) Sky portals from RN
        (skip_blocks,) = struct.unpack("<I", f.read(4))
        for _ in range(skip_blocks):
            vert_count = struct.unpack("<B", f.read(1))[0]
            verts = [Vec3.read(f) for _ in range(vert_count)]
            plane_normal = Vec3.read(f)
            plane_dist = struct.unpack("<f", f.read(4))[0]
            skyportals_all.append((verts, plane_normal, plane_dist))

        # 8) Occluders from RN
        (skip_occluders,) = struct.unpack("<I", f.read(4))
        for _ in range(skip_occluders):
            vert_count = struct.unpack("<B", f.read(1))[0]
            verts = [Vec3.read(f) for _ in range(vert_count)]
            plane_normal = Vec3.read(f)
            plane_dist = struct.unpack("<f", f.read(4))[0]
            (occ_hashcode,) = struct.unpack("<I", f.read(4))
            occluders_all.append((verts, plane_normal, plane_dist, occ_hashcode))

        # 9) LightGroups from RN
        (lg_count,) = struct.unpack("<I", f.read(4))
        for lg_index in range(lg_count):
            name_len = struct.unpack("<H", f.read(2))[0]
            group_name = f.read(name_len).decode("utf-8", errors="ignore")
            center = Vec3.read(f)
            intensity_data_len = struct.unpack("<I", f.read(4))[0]
            zero_compressed_data = f.read(intensity_data_len)
            (section_lm_len,) = struct.unpack("<I", f.read(4))
            for s in range(section_lm_len):
                sub_lm_len = struct.unpack("<I", f.read(4))[0]
                for i in range(sub_lm_len):
                    left, top, width, height, datalen = struct.unpack("<5I", f.read(20))
                    compressed = f.read(datalen)

        f.read(1)
        f.read(8)

    # === WMRenderNodes (position-agnostic for lightanim_base) ===
    (wm_node_count,) = struct.unpack("<I", f.read(4))
    wm_names_list = {}
    wm_section_props = []
    all_wm_data = {}  # {wm_name: [(verts, section_tris), ...]}

    for wm_index in range(wm_node_count):
        wm_name = read_lithtech_string(f)
        wm_names_list[wm_index] = wm_name

        (subnode_count,) = struct.unpack("<I", f.read(4))
        wm_data = []  # Accumulate all polyhedrons of this WM (across all subnodes)

        for subnode_index in range(subnode_count):
            center = Vec3.read(f)
            half_dims = Vec3.read(f)
            (section_count,) = struct.unpack("<I", f.read(4))

            # 1) Read all sections (do not discard immediately), mark lightanim
            sections = []
            for _ in range(section_count):
                tex0 = read_lithtech_string(f)
                tex1 = read_lithtech_string(f)
                shader_type_byte = f.read(1)[0]
                tri_count = struct.unpack("<I", f.read(4))[0]
                texture_effect = read_lithtech_string(f)
                w, h, size = struct.unpack("<3I", f.read(12))
                f.read(size)

                t0 = tex0.strip()
                t1 = tex1.strip()
                if t0 == "":
                    tex0 = "Default"
                if t1 == "":
                    tex1 = "Default"

                is_lightanim = (t0.lower() == "lightanim_base")
                shader_str = EPCShaderType.get(shader_type_byte, "Unknown")
                tex_w,  tex_h  = get_dtx_texture_size(tex0, search_dirs=[current_dir])
                tex_w1, tex_h1 = get_dtx_texture_size(tex1, search_dirs=[current_dir])

                sections.append({
                    "is_lightanim": is_lightanim,
                    "tex0": tex0, "tex1": tex1,
                    "tex_w": tex_w, "tex_h": tex_h,
                    "tex_w1": tex_w1, "tex_h1": tex_h1,
                    "tri_count": tri_count,
                    "shader_str": shader_str,
                    "texture_effect": texture_effect,
                })

            # 2) Read all vertices (without skips)
            (vertex_count,) = struct.unpack("<I", f.read(4))
            vertices = read_vertex_data(f, vertex_count, version_flag)
            accumulate_uv_templates(vertices)

            # 3) Read all triangles (without skips)
            (tri_count_total,) = struct.unpack("<I", f.read(4))
            all_tris = []
            for _ in range(tri_count_total):
                i0, i1, i2 = struct.unpack("<3I", f.read(12))
                f.read(4)  # poly index/flags — ignore
                all_tris.append((i0, i1, i2))

            # 4) sanity-check
            expected = sum(s["tri_count"] for s in sections)
            if expected != len(all_tris):
                print(f"[WARN] WMRenderNode {wm_index}/{subnode_index}: "
                      f"sum(section.tri_count)={expected} != total_tris={len(all_tris)}")
                # Just in case — trim to the minimal possible to avoid crash
                tri_count_total = min(expected, len(all_tris))
            else:
                tri_count_total = len(all_tris)

            # 5) slice triangle stream by sections in original order
            cursor = 0
            kept_sections = []  # sections without lightanim, with triangles already sliced
            for s in sections:
                count = s["tri_count"]
                tris = all_tris[cursor:cursor + count]
                cursor += count
                if s["is_lightanim"]:
                    continue  # completely ignore lightanim
                kept_sections.append((
                    s["tex0"], s["tex_w"], s["tex_h"],
                    s["tex1"], s["tex_w1"], s["tex_h1"],
                    tris, s["shader_str"], s["texture_effect"]
                ))

            # 6) Local repacking of vertices/indices for each remaining section
            section_triangles = []
            for section_idx, (tex0, tex0_w, tex0_h,
                              tex1, tex_w1, tex_h1,
                              tris, shader_str, texture_effect) in enumerate(kept_sections):

                # gather local vertices
                local_verts = []
                index_map = {}
                for i0, i1, i2 in tris:
                    for i in (i0, i1, i2):
                        if i not in index_map:
                            index_map[i] = len(local_verts)
                            local_verts.append(vertices[i])

                # local triangle indices
                local_tris = [(index_map[i0], index_map[i1], index_map[i2]) for (i0, i1, i2) in tris]

                section_triangles.append((tex0, tex0_w, tex0_h,
                                          tex1, tex_w1, tex_h1,
                                          local_tris, shader_str, texture_effect))

                label = f"{wm_name}_{subnode_index}_S{section_idx}"
                wm_section_props.append({
                    "wm_index": wm_index,
                    "subnode_index": subnode_index,
                    "section_index": section_idx,
                    "label": label,
                    "shader_str": shader_str,
                    "texture_effect": texture_effect,
                })

                # Accumulate polyhedron (as before), but already without lightanim
                wm_data.append((local_verts, [(tex0, tex0_w, tex0_h,
                                               tex1, tex_w1, tex_h1,
                                               local_tris, shader_str, texture_effect)]))

            # 7) Skyportals
            (skip_blocks,) = struct.unpack("<I", f.read(4))
            for _ in range(skip_blocks):
                vert_count = struct.unpack("<B", f.read(1))[0]
                verts = [Vec3.read(f) for _ in range(vert_count)]
                plane_normal = Vec3.read(f)
                plane_dist = struct.unpack("<f", f.read(4))[0]
                skyportals_all.append((verts, plane_normal, plane_dist))

            # 8) Occluders
            (skip_occluders,) = struct.unpack("<I", f.read(4))
            for _ in range(skip_occluders):
                vert_count = struct.unpack("<B", f.read(1))[0]
                verts = [Vec3.read(f) for _ in range(vert_count)]
                plane_normal = Vec3.read(f)
                plane_dist = struct.unpack("<f", f.read(4))[0]
                (occ_hashcode,) = struct.unpack("<I", f.read(4))
                occluders_all.append((verts, plane_normal, plane_dist, occ_hashcode))

            # 9) LightGroups
            (lg_count,) = struct.unpack("<I", f.read(4))
            for lg_index in range(lg_count):
                name_len = struct.unpack("<H", f.read(2))[0]
                group_name = f.read(name_len).decode("utf-8", errors="ignore")
                center = Vec3.read(f)
                (intensity_data_len,) = struct.unpack("<I", f.read(4))
                f.read(intensity_data_len)
                (section_lm_len,) = struct.unpack("<I", f.read(4))
                for s in range(section_lm_len):
                    sub_lm_len = struct.unpack("<I", f.read(4))[0]
                    for i in range(sub_lm_len):
                        left, top, width, height, datalen = struct.unpack("<5I", f.read(20))
                        compressed = f.read(datalen)

            f.read(1)
            f.read(8)

        all_wm_data[wm_name] = wm_data
        (no_child_flag,) = struct.unpack("<I", f.read(4))

    # Write order according to world\_objects
    wm_ordered = []
    for obj in world_objects:
        obj_name = obj.get("Name")
        if obj_name and obj_name in all_wm_data:
            wm_ordered.append(obj_name)

    # Write polyhedron
    for wm_name in wm_ordered:
        wm_data = all_wm_data.get(wm_name, [])
        for verts, section_tris in wm_data:
            write_polyhedron(out_file, verts, section_tris)

    write_skypo(out_file, skyportals_all)
    write_occ(out_file, occluders_all)

    polyBlocks_count = write_physics_polygons(f, header, out_file)
    polypParticleblock_count = write_particleblockers_polygons(f, header, out_file)


    # === NODE HIERARCHY ===
    brushindex = 0
    base_nodeid = 1
    base_propid = 1
    out_file.write(") )\n")
    out_file.write("( nodehierarchy\n")
    out_file.write("\t( worldnode\n")
    out_file.write("\t\t( type null )\n")
    out_file.write(f'\t\t( label \"{map_name}\" )\n')
    out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
    out_file.write("\t\t( flags ( worldroot expanded ) )\n")
    out_file.write("\t\t( properties\n")
    out_file.write(f'\t\t\t( propid 0 )\n')
    out_file.write("\t\t)\n")
    out_file.write("\t\t( childlist (\n")
    base_nodeid += 1
    
    out_file.write("\t( worldnode\n")
    out_file.write("\t\t( type null )\n")
    out_file.write(f'\t\t( label "RenderNodes" )\n')
    out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
    out_file.write("\t\t( flags ( ) )\n")
    out_file.write("\t\t( properties\n")
    out_file.write(f'\t\t\t( propid 0 )\n')
    out_file.write("\t\t)\n")
    out_file.write("\t\t( childlist (\n")
    base_nodeid += 1
    for node_index, section_brushes in section_brushes_by_node.items():
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label \"RenderNode{node_index}\" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write("\t\t( flags ( ) )\n")
        out_file.write("\t\t( properties\n")
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write("\t\t)\n")
        out_file.write("\t\t( childlist (\n")
        base_nodeid += 1

        for label, _, _, _ in section_brushes:
            out_file.write("\t\t\t( worldnode\n")
            out_file.write("\t\t\t\t( type brush )\n")
            out_file.write(f'\t\t\t\t( brushindex {brushindex} )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write("\t\t\t\t( flags ( ) )\n")
            out_file.write("\t\t\t\t( properties\n")
            out_file.write(f'\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f'\t\t\t\t\t( propid {base_propid} )\n')
            out_file.write("\t\t\t\t)\n")
            out_file.write("\t\t\t)\n")
            base_propid += 1
            base_nodeid += 1
            brushindex += 1

        out_file.write("\t\t)\n")
        out_file.write("\t)\n)\n")
    out_file.write("\t)\n) )\n")
    # === OBJECT NODES ===

    matched_wm_to_obj = {}

    # ⚙️ 2. Find matches once (better in advance)
    for wm_id, wm_name in wm_names_list.items():
        for i, obj in enumerate(world_objects):
            name = obj.get("Name")
            if wm_name == name:
                matched_wm_to_obj[i] = wm_id  # link object to WM
                break

    if len(world_objects) > 0:
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label "ObjectsAndWMs" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write('\t\t( flags ( ) )\n')
        out_file.write('\t\t( properties\n')
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write('\t\t)\n')
        out_file.write('\t\t( childlist (\n')
        base_nodeid += 1

        for i, obj in enumerate(world_objects):
            name = obj.get("Name", f"Obj{i}")
            label = obj.get("__Type", "Object")

            out_file.write('\t\t\t( worldnode\n')
            out_file.write('\t\t\t\t( type object )\n')
            out_file.write(f'\t\t\t\t( label "{label}" )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write('\t\t\t\t( flags ( ) )\n')
            out_file.write('\t\t\t\t( properties\n')
            out_file.write(f'\t\t\t\t\t( name "{label}" )\n')
            out_file.write(f'\t\t\t\t\t( propid {base_propid} )\n')
            out_file.write('\t\t\t\t)\n')
            base_propid += 1
            object_nodeid = base_nodeid
            base_nodeid += 1

            if i in matched_wm_to_obj:
                wm_id = matched_wm_to_obj[i]
                section_index = 0
                out_file.write('\t\t\t\t( childlist (\n')

                for section in wm_section_props:
                    if section["wm_index"] == wm_id:
                        out_file.write('\t\t\t\t\t( worldnode\n')
                        out_file.write('\t\t\t\t\t\t( type brush )\n')
                        out_file.write(f'\t\t\t\t\t\t( brushindex {brushindex} )\n')
                        out_file.write(f'\t\t\t\t\t\t( nodeid {base_nodeid} )\n')
                        out_file.write('\t\t\t\t\t\t( flags ( ) )\n')
                        out_file.write('\t\t\t\t\t\t( properties\n')
                        out_file.write(f'\t\t\t\t\t\t\t( name "Brush" )\n')
                        out_file.write(f'\t\t\t\t\t\t\t( propid {base_propid} )\n')
                        out_file.write('\t\t\t\t\t\t)\n')
                        out_file.write('\t\t\t\t\t)\n')
                        base_nodeid += 1
                        base_propid += 1
                        brushindex += 1
                        section_index += 1

                out_file.write('\t\t\t\t) )\n')  # close childlist

            out_file.write(')\n')

        if len(keyframer_keys_map) > 0:
            for key_name in keyframer_keys_map:
                out_file.write("\t\t\t( worldnode\n")
                out_file.write("\t\t\t\t( type null )\n")
                out_file.write(f'\t\t\t\t( label "{key_name}" )\n')
                out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
                out_file.write('\t\t\t\t( flags ( path ) ) \n')
                out_file.write('\t\t\t\t( properties\n')
                out_file.write(f'\t\t\t\t\t( propid 0 )\n')
                out_file.write('\t\t\t\t)\n')
                out_file.write('\t\t\t\t( childlist (\n')
                base_nodeid += 1
                for entry in keyframer_keys_map[key_name]:
                    out_file.write('\t\t\t\t\t( worldnode\n')
                    out_file.write('\t\t\t\t\t\t( type object )\n')
                    out_file.write(f'\t\t\t\t\t\t( label "Key" )\n')
                    out_file.write(f'\t\t\t\t\t\t( nodeid {base_nodeid} )\n')
                    out_file.write('\t\t\t\t\t\t( flags ( ) )\n')
                    out_file.write('\t\t\t\t\t\t( properties\n')
                    out_file.write(f'\t\t\t\t\t\t\t( name "Key" )\n')
                    out_file.write(f'\t\t\t\t\t\t\t( propid {base_propid} )\n')
                    out_file.write('\t\t\t\t\t\t)\n')
                    out_file.write('\t\t\t\t\t)\n')
                    base_nodeid += 1
                    base_propid += 1

                out_file.write('\t\t)\n')
                out_file.write('\t\t) )\n')

        out_file.write('\t\t)\n')
        out_file.write('\t\t) )\n')

    
    if len(skyportals_all) > 0:
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label "SkyPortals" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write('\t\t( flags ( ) )\n')
        out_file.write('\t\t( properties\n')
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write('\t\t)\n')
        out_file.write('\t\t( childlist (\n')
        base_nodeid += 1
        for i in enumerate(skyportals_all):
            out_file.write('\t\t\t( worldnode\n')
            out_file.write('\t\t\t\t( type brush )\n')
            out_file.write(f'\t\t\t\t( brushindex {brushindex} )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write('\t\t\t\t( flags ( ) )\n')
            out_file.write('\t\t\t\t( properties\n')
            out_file.write('\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f'\t\t\t( propid {base_propid} )\n')
            out_file.write('\t\t\t\t)\n')
            out_file.write('\t\t\t)\n')
            brushindex += 1
            base_nodeid += 1
        base_propid += 1
        out_file.write('\t\t)\n')
        out_file.write('\t\t) )\n')
        
    if len(occluders_all) > 0:
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label "Occluders" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write('\t\t( flags ( ) )\n')
        out_file.write('\t\t( properties\n')
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write('\t\t)\n')
        out_file.write('\t\t( childlist (\n')
        base_nodeid += 1
        for i in enumerate(occluders_all):
            out_file.write('\t\t\t( worldnode\n')
            out_file.write('\t\t\t\t( type brush )\n')
            out_file.write(f'\t\t\t\t( brushindex {brushindex} )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write('\t\t\t\t( flags ( ) )\n')
            out_file.write('\t\t\t\t( properties\n')
            out_file.write('\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f'\t\t\t( propid {base_propid} )\n')
            out_file.write('\t\t\t\t)\n')
            out_file.write('\t\t\t)\n')
            brushindex += 1
            base_nodeid += 1
            base_propid += 1
        out_file.write('\t\t)\n')
        out_file.write('\t\t) )\n')
        
    if polyBlocks_count > 0:
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label "Blockers" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write('\t\t( flags ( ) )\n')
        out_file.write('\t\t( properties\n')
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write('\t\t)\n')
        out_file.write('\t\t( childlist (\n')
        base_nodeid += 1
        for i in range(polyBlocks_count):
            out_file.write('\t\t\t( worldnode\n')
            out_file.write('\t\t\t\t( type brush )\n')
            out_file.write(f'\t\t\t\t( brushindex {brushindex} )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write('\t\t\t\t( flags ( ) )\n')
            out_file.write('\t\t\t\t( properties\n')
            out_file.write('\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f'\t\t\t( propid {base_propid} )\n')
            out_file.write('\t\t\t\t)\n')
            out_file.write('\t\t\t)\n')
            brushindex += 1
            base_nodeid += 1
        base_propid += 1
        out_file.write('\t\t)\n')
        out_file.write('\t\t) )\n')
        
    if polypParticleblock_count > 0:
        out_file.write("\t( worldnode\n")
        out_file.write("\t\t( type null )\n")
        out_file.write(f'\t\t( label "ParticleBlockers" )\n')
        out_file.write(f'\t\t( nodeid {base_nodeid} )\n')
        out_file.write('\t\t( flags ( ) )\n')
        out_file.write('\t\t( properties\n')
        out_file.write(f'\t\t\t( propid 0 )\n')
        out_file.write('\t\t)\n')
        out_file.write('\t\t( childlist (\n')
        base_nodeid += 1
        for i in range(polypParticleblock_count):
            out_file.write('\t\t\t( worldnode\n')
            out_file.write('\t\t\t\t( type brush )\n')
            out_file.write(f'\t\t\t\t( brushindex {brushindex} )\n')
            out_file.write(f'\t\t\t\t( nodeid {base_nodeid} )\n')
            out_file.write('\t\t\t\t( flags ( ) )\n')
            out_file.write('\t\t\t\t( properties\n')
            out_file.write('\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f'\t\t\t( propid {base_propid} )\n')
            out_file.write('\t\t\t\t)\n')
            out_file.write('\t\t\t)\n')
            brushindex += 1
            base_nodeid += 1
        base_propid += 1
        out_file.write('\t\t)\n')
        out_file.write('\t\t) )\n')

        
    out_file.write('\t\t\t\t) ) ) )\n')
        
    out_file.write("( globalproplist (\n")
    out_file.write("    ( proplist ( \n")
    out_file.write("    ) )\n")
    for node_index in sorted(section_brushes_by_node.keys()):
        section_list = section_brushes_by_node[node_index]
        for section_index, (label, _, shader_str, texture_effect) in enumerate(section_list):
            out_file.write("    ( proplist ( \n")
            out_file.write(f'        ( string "Name" (  ) ( data "RN{node_index}_S{section_index}" ) )\n')
            out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
            out_file.write("        ( string \"Type\" ( staticlist ) ( data \"Normal\" ) )\n")
            out_file.write(f'        ( string "Lighting" ( staticlist ) ( data "{shader_str}" ) )\n')
            out_file.write("        ( bool \"NotAStep\" (  ) ( data 0 ) )\n")
            out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
            out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
            out_file.write(f'        ( string "TextureEffect" ( textureeffect ) ( data "{texture_effect}" ) )\n' if texture_effect else '        ( string "TextureEffect" ( textureeffect ) )\n')
            out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
            out_file.write("        ( bool \"ClipLight\" ( group1 ) ( data 1 ) )\n")
            out_file.write("        ( bool \"CastShadowMesh\" ( group1 ) ( data 1 ) )\n")
            out_file.write("        ( bool \"ReceiveLight\" ( group1 ) ( data 1 ) )\n")
            out_file.write("        ( bool \"ReceiveShadows\" ( group1 ) ( data 1 ) )\n")
            out_file.write("        ( bool \"ReceiveSunlight\" ( group1 ) ( data 1 ) )\n")
            out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
            out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
            out_file.write("    ) )\n")

    for i, props in enumerate(world_objects):
        meta = world_objects_meta[i]
        has_child = i in matched_wm_to_obj

        def format_vec3(v):
            return f"( vector ({v.x:.6f} {v.y:.6f} {v.z:.6f}) )"

        def format_rotation(q):
            return f"(eulerangles ({q.x:.6f} {q.y:.6f} {q.z:.6f}))"

        out_file.write("\t\t\t\t( proplist (\n")
        for key, value in props.items():
            if key == "__Type":
                continue

            field_meta = meta.get(key, {})
            field_type = field_meta.get("type")
            # Restore the exact PF_* flag tokens stored in the DAT instead of
            # hard-coding them (critical for Light: radius distance, the
            # groupowner/group1/compositetype attenuation group, ...).
            flag_tokens = prop_flag_tokens(field_meta.get("flags", 0))
            flag_part = f"( {flag_tokens} )" if flag_tokens else "(  )"

            if field_type == "string":
                # DEdit's CStringProp::SaveDataLTA omits the whole data clause
                # for empty strings (AttType/LightGroup/object links/...).
                if value:
                    out_file.write(f'\t\t\t\t\t(  string "{key}" {flag_part} ( data "{value}") )\n')
                else:
                    out_file.write(f'\t\t\t\t\t(  string "{key}" {flag_part})\n')

            elif field_type == "vector":
                if key == "Pos":
                    value = apply_world_offset(value)
                out_file.write(f'\t\t\t\t\t(  vector "{key}" {flag_part} ( data {format_vec3(value)} ) )\n')

            elif field_type == "color":
                out_file.write(f'\t\t\t\t\t(  color "{key}" {flag_part} ( data {format_vec3(value)} ) )\n')

            elif field_type == "rotation":
                out_file.write(f'\t\t\t\t\t(  rotation "{key}" {flag_part} ( data {format_rotation(value)} ) )\n')

            elif field_type == "bool":
                out_file.write(f'\t\t\t\t\t(  bool "{key}" {flag_part} ( data {1 if value else 0} ))\n')

            elif field_type == "real":
                out_file.write(f'\t\t\t\t\t(  real "{key}" {flag_part} ( data {value:.6f} ))\n')

            elif field_type == "longint":
                out_file.write(f'\t\t\t\t\t(  longint "{key}" {flag_part} ( data {float(value):.6f} ))\n')

            else:
                if isinstance(value, tuple) and len(value) == 3:
                    out_file.write(f'\t\t\t\t\t(  vector "{key}" {flag_part} ( data ( vector ({value[0]:.6f} {value[1]:.6f} {value[2]:.6f}) ) ) )\n')
                else:
                    out_file.write(f'\t\t\t\t\t(  string "{key}" ( hidden  ) )\n')

        out_file.write("\t\t\t\t)\t)\n")
        
        if i in matched_wm_to_obj:
            wm_id = matched_wm_to_obj[i]

            for section in wm_section_props:
                if section["wm_index"] == wm_id:
                    label = section["label"]
                    shader_str = section["shader_str"]
                    texture_effect = section["texture_effect"]
                    out_file.write("\t\t\t\t( proplist (\n")
                    out_file.write(f'\t\t\t\t\t( string "Name" (  ) ( data "{label}" ) )\n')
                    out_file.write("\t\t\t\t\t( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
                    out_file.write("\t\t\t\t\t( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
                    out_file.write("\t\t\t\t\t( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
                    out_file.write(f'\t\t\t\t\t( string "Type" ( staticlist ) ( data "Normal" ) )\n')
                    out_file.write(f'\t\t\t\t\t( string "Lighting" ( staticlist ) ( data "{shader_str}" ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "NotAStep" (  ) ( data 0 ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "Detail" (  ) ( data 0 ) )\n')
                    out_file.write(f'\t\t\t\t\t( longint "LightControl" ( groupowner group1 ) ( data 0.000000 ) )\n')

                    if texture_effect:
                        out_file.write(f'\t\t\t\t\t( string "TextureEffect" ( textureeffect ) ( data "{texture_effect}" ) )\n')
                    else:
                        out_file.write("\t\t\t\t\t( string \"TextureEffect\" ( textureeffect ) )\n")

                    out_file.write("\t\t\t\t\t( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
                    out_file.write("\t\t\t\t\t( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
                    out_file.write(f'\t\t\t\t\t( bool "ClipLight" ( group1 ) ( data 1 ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "CastShadowMesh" ( group1 ) ( data 1 ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "ReceiveLight" ( group1 ) ( data 1 ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "ReceiveShadows" ( group1 ) ( data 1 ) )\n')
                    out_file.write(f'\t\t\t\t\t( bool "ReceiveSunlight" ( group1 ) ( data 1 ) )\n')
                    out_file.write("\t\t\t\t\t( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
                    out_file.write("\t\t\t\t\t( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
                    out_file.write("\t\t\t\t) )\n")
                    
    if keyframer_keys_map:
        for key_name, key_list in keyframer_keys_map.items():
            for key_data in key_list:
                pos = key_data["pos"]
                if not isinstance(pos, Vec3):
                    pos = Vec3(*pos)
                
                rot_deg = key_data["rot_deg"]
                if not isinstance(rot_deg, Vec3):
                    rot_deg = Vec3(*rot_deg)
                
                bez_prev = key_data.get("bez_prev") or Vec3(0, 0, 0)
                bez_next = key_data.get("bez_next") or Vec3(0, 0, 0)
                sound_name = key_data.get("sound_name", "")
                command = key_data.get("command", "")

                out_file.write("        ( proplist ( \n")
                out_file.write(f'            ( string "Name" (  ) ( data "{key_data["full_name"]}") ) \n')
                pos = apply_world_offset(pos)
                out_file.write(f'            ( vector "Pos" ( distance ) ( data ( vector ( {write_vec3(pos)} ) ) ) ) \n')
                out_file.write(f'            ( rotation "Rotation" (  ) ( data ( eulerangles ({rot_deg.x:.6f} {rot_deg.y:.6f} {rot_deg.z:.6f}) ) ) ) \n')
                out_file.write(f'            ( longint "RenderGroup" (  ) ( data 0.000000 ) ) \n')
                out_file.write(f'            ( real "TimeStamp" (  ) ( data {key_data["timestamp"]:.6f} ) ) \n')

                if sound_name:
                    out_file.write(f'            ( string "SoundName" (  ) ( data "{sound_name}" ) ) \n')
                else:
                    out_file.write(f'            ( string "SoundName" (  ) ) \n')

                out_file.write(f'            ( real "SoundRadius" ( radius ) ( data {key_data["sound_radius"]:.6f} ) ) \n')

                if command:
                    out_file.write(f'            ( string "Command" ( notifychange ) ( data "{command}" ) ) \n')
                else:
                    out_file.write(f'            ( string "Command" ( notifychange ) ) \n')

                out_file.write(f'            ( vector "BezierPrev" ( bezierprevtangent ) ( data ( vector ({bez_prev.x:.6f} {bez_prev.y:.6f} {bez_prev.z:.6f}) ) ) ) \n')
                out_file.write(f'            ( vector "BezierNext" ( beziernexttangent ) ( data ( vector ({bez_next.x:.6f} {bez_next.y:.6f} {bez_next.z:.6f}) ) ) ) \n')
                out_file.write("        ) )\n\n")

    if len(skyportals_all) > 0:
        out_file.write("    ( proplist ( \n")
        out_file.write(f'        ( string "Name" (  ) ( data "SkyPortal" ) )\n')
        out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"Type\" ( staticlist ) ( data \"SkyPortal\" ) )\n")
        out_file.write("        ( string \"Lighting\" ( staticlist ) ( data \"Gouraud\" ) )\n")
        out_file.write("        ( bool \"NotAStep\" (  ) ( data 0 ) )\n")
        out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
        out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"TextureEffect\" ( textureeffect ) )\n")
        out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( bool \"ClipLight\" ( group1 ) ( data 1 ) )\n")
        out_file.write("        ( bool \"CastShadowMesh\" ( group1 ) ( data 1 ) )\n")
        out_file.write("        ( bool \"ReceiveLight\" ( group1 ) ( data 1 ) )\n")
        out_file.write("        ( bool \"ReceiveShadows\" ( group1 ) ( data 1 ) )\n")
        out_file.write("        ( bool \"ReceiveSunlight\" ( group1 ) ( data 1 ) )\n")
        out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
        out_file.write("    ) )\n")
    if len(occluders_all) > 0:
        for idx, (verts, plane_normal, plane_dist, occ_hashcode) in enumerate(occluders_all):
            # Find name by hash
            occ_name = "Occluder"
            for nm, hsh in occluder_names.items():
                if hsh == occ_hashcode:
                    occ_name = nm
                    break   # Match found, take this name

            out_file.write("    ( proplist ( \n")
            out_file.write(f'        ( string "Name" (  ) ( data "{occ_name}" ) )\n')
            out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
            out_file.write("        ( string \"Type\" ( staticlist ) ( data \"Occluder\" ) )\n")
            out_file.write("        ( string \"Lighting\" ( staticlist ) ( data \"Flat\" ) )\n")
            out_file.write("        ( bool \"NotAStep\" (  ) ( data 0 ) )\n")
            out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
            out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
            out_file.write("        ( string \"TextureEffect\" ( textureeffect ) )\n")
            out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
            out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
            out_file.write("        ( bool \"ClipLight\" ( group1 ) ( data 0 ) )\n")
            out_file.write("        ( bool \"CastShadowMesh\" ( group1 ) ( data 0 ) )\n")
            out_file.write("        ( bool \"ReceiveLight\" ( group1 ) ( data 0 ) )\n")
            out_file.write("        ( bool \"ReceiveShadows\" ( group1 ) ( data 0 ) )\n")
            out_file.write("        ( bool \"ReceiveSunlight\" ( group1 ) ( data 0 ) )\n")
            out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
            out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
            out_file.write("    ) )\n")

    if polyBlocks_count > 0:
        out_file.write("    ( proplist ( \n")
        out_file.write(f'        ( string "Name" (  ) ( data "Blocker" ) )\n')
        out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"Type\" ( staticlist ) ( data \"Blocker\" ) )\n")
        out_file.write("        ( string \"Lighting\" ( staticlist ) ( data \"Flat\" ) )\n")
        out_file.write("        ( bool \"NotAStep\" (  ) ( data 0 ) )\n")
        out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
        out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"TextureEffect\" ( textureeffect ) )\n")
        out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( bool \"ClipLight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"CastShadowMesh\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveLight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveShadows\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveSunlight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
        out_file.write("    ) )\n")
    if polypParticleblock_count > 0:
        out_file.write("    ( proplist ( \n")
        out_file.write(f'        ( string "Name" (  ) ( data "ParticleBlocker" ) )\n')
        out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"Type\" ( staticlist ) ( data \"ParticleBlocker\" ) )\n")
        out_file.write("        ( string \"Lighting\" ( staticlist ) ( data \"Flat\" ) )\n")
        out_file.write("        ( bool \"NotAStep\" (  ) ( data 0 ) )\n")
        out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
        out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"TextureEffect\" ( textureeffect ) )\n")
        out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( bool \"ClipLight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"CastShadowMesh\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveLight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveShadows\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( bool \"ReceiveSunlight\" ( group1 ) ( data 0 ) )\n")
        out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
        out_file.write("    ) )\n")
        
    out_file.write(") )\n")
    out_file.write(")\n")

def get_surface_type(flags: set[str]) -> str:
    if "NONEXISTENT" in flags:
        if "VISBLOCKER" in flags:
            return "Occluder"
        elif "RBSPLITTER" in flags:
            return "RBSplitter"
        else:
            return "RenderOnly"
    if "SOLID" not in flags:
        return "NonSolid"
    if "SKY" in flags:
        return "SkyPortal"
    return "Normal"

def get_lighting_type(flags: set[str]) -> str:
    if "SHADOWMESH" in flags and "GOURAUDSHADE" in flags:
        return "ShadowMesh"
    if "LIGHTMAP" in flags:
        return "Lightmap"
    if "GOURAUDSHADE" in flags:
        return "Gouraud"
    if "FLATSHADE" in flags:
        return "Flat"
    return "Gouraud"


def write_surfaces_to_lta(worldtree, out_file, map_name):
    from collections import defaultdict

    out_file.write("( world\n")
    out_file.write("\t( header (\n\t\t( versioncode 2 )\n\t) )\n")
    out_file.write("\t( polyhedronlist (\n")

    global_surface_data = []
    brushindex = 0

    for world_model in worldtree.world_models:
        surface_to_polies = defaultdict(list)
        for poly_idx, (surface_idx, plane_idx, indices) in enumerate(world_model.polies):
            surface_to_polies[surface_idx].append((poly_idx, plane_idx, indices))

        for surface_idx in sorted(surface_to_polies.keys()):
            global_surface_data.append((world_model, surface_idx))

            out_file.write("\t( polyhedron (\n")
            out_file.write("\t\t( color 255 255 255 )\n")

            point_map = {}
            local_points = []
            for _, _, indices in surface_to_polies[surface_idx]:
                for idx in indices:
                    if idx not in point_map:
                        point_map[idx] = len(local_points)
                        local_points.append(world_model.points[idx])

            out_file.write("\t\t( pointlist \n")
            for pt in local_points:
                adjusted = apply_world_offset(pt)
                out_file.write(f"\t\t\t( {adjusted.x:.6f} {adjusted.y:.6f} {adjusted.z:.6f} 255 255 255 255 )\n")
            out_file.write("\t\t)\n")

            out_file.write("\t\t( polylist (\n")
            for poly_idx, plane_idx, indices in surface_to_polies[surface_idx]:
                n, dist = world_model.planes[plane_idx]
                local_indices = [point_map[i] for i in indices]
                f_str = " ".join(str(i) for i in local_indices)

                tex_idx = world_model.surfaces[surface_idx]['TextureIndex']
                tex_name = world_model.texture_names[tex_idx] if 0 <= tex_idx < len(world_model.texture_names) else "Default"

                out_file.write("\t\t\t( editpoly \n")
                out_file.write(f"\t\t\t\t( f {f_str} )\n")
                out_file.write(f"\t\t\t\t( n {n.x:.6f} {n.y:.6f} {n.z:.6f} )\n")
                out_file.write(f"\t\t\t\t( dist {dist:.6f} )\n")
                out_file.write("\t\t\t\t( textureinfo \n")
                out_file.write("\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
                out_file.write("\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
                out_file.write("\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
                out_file.write("\t\t\t\t\t( sticktopoly 1 )\n")
                out_file.write(f'\t\t\t\t\t( name "{tex_name}" )\n')
                out_file.write("\t\t\t\t)\n")
                out_file.write("\t\t\t\t( flags )\n")
                out_file.write("\t\t\t\t( shade 0 0 0 )\n")
                out_file.write("\t\t\t\t( physicsmaterial \"Default\" )\n")
                out_file.write("\t\t\t\t( surfacekey \"\" )\n")
                out_file.write("\t\t\t\t( textures ( \n")
                out_file.write("\t\t\t\t\t( 1 ( textureinfo \n")
                out_file.write("\t\t\t\t\t\t( 0.000000 0.000000 0.000000 )\n")
                out_file.write("\t\t\t\t\t\t( 1.000000 0.000000 0.000000 )\n")
                out_file.write("\t\t\t\t\t\t( 0.000000 0.000000 1.000000 )\n")
                out_file.write("\t\t\t\t\t\t( sticktopoly 1 )\n")
                out_file.write(f'\t\t\t\t\t\t( name "Default" )\n')
                out_file.write("\t\t\t\t\t) )\n")
                out_file.write("\t\t\t\t) )\n")
                out_file.write("\t\t\t)\n")

            out_file.write("\t\t) )\n")
            out_file.write("\t) )\n")
            brushindex += 1

    brushindex = 0
    base_nodeid = 1
    base_propid = 1

    out_file.write(") )\n")
    out_file.write("( nodehierarchy\n")
    out_file.write("\t( worldnode\n")
    out_file.write("\t\t( type null )\n")
    out_file.write(f'\t\t( label "{map_name}_PhysicsDATA" )\n')
    out_file.write(f"\t\t( nodeid {base_nodeid} )\n")
    out_file.write("\t\t( flags ( worldroot expanded ) )\n")
    out_file.write("\t\t( properties\n")
    out_file.write(f"\t\t\t( propid 0 )\n")
    out_file.write("\t\t)\n")
    out_file.write("\t\t( childlist (\n")
    base_nodeid += 1

    for world_model in worldtree.world_models:
        surface_to_polies = defaultdict(list)
        for poly_idx, (surface_idx, plane_idx, indices) in enumerate(world_model.polies):
            surface_to_polies[surface_idx].append((poly_idx, plane_idx, indices))

        out_file.write("\t\t\t( worldnode\n")
        out_file.write("\t\t\t\t( type null )\n")
        out_file.write(f'\t\t\t\t( label "{world_model.world_name}" )\n')
        out_file.write(f"\t\t\t\t( nodeid {base_nodeid} )\n")
        out_file.write("\t\t\t\t( flags ( ) )\n")
        out_file.write("\t\t\t\t( properties\n")
        out_file.write(f"\t\t\t\t\t( propid 0 )\n")
        out_file.write("\t\t\t\t)\n")
        out_file.write("\t\t\t\t( childlist (\n")
        base_nodeid += 1

        for surface_idx in sorted(surface_to_polies.keys()):
            out_file.write("\t\t\t\t\t( worldnode\n")
            out_file.write("\t\t\t\t\t\t( type brush )\n")
            out_file.write(f"\t\t\t\t\t\t( brushindex {brushindex} )\n")
            out_file.write(f"\t\t\t\t\t\t( nodeid {base_nodeid} )\n")
            out_file.write("\t\t\t\t\t\t( flags ( ) )\n")
            out_file.write("\t\t\t\t\t\t( properties\n")
            out_file.write(f'\t\t\t\t\t\t\t( name "Brush" )\n')
            out_file.write(f"\t\t\t\t\t\t\t( propid {base_propid} )\n")
            out_file.write("\t\t\t\t\t\t)\n")
            out_file.write("\t\t\t\t\t)\n")
            base_propid += 1
            base_nodeid += 1
            brushindex += 1

        out_file.write("\t\t\t\t)\n")
        out_file.write("\t\t\t)\n")
        out_file.write("\t\t)\n")

    out_file.write("\t\t)\n")
    out_file.write("\t)\n")
    out_file.write(") )\n")
    out_file.write("( globalproplist (\n")
    out_file.write("    ( proplist ( \n")
    out_file.write("    ) )\n")
    
    surfaceinx = 0
    last_wm = None

    for wm, surface_idx in global_surface_data:
        if wm != last_wm:
            surfaceinx = 0
            last_wm = wm

        surface = wm.surfaces[surface_idx]
        flags = set(decode_surface_flags(surface.get("Flags", 0)))
        surf_type = get_surface_type(flags)
        lighting = get_lighting_type(flags)

        out_file.write("    ( proplist ( \n")
        out_file.write(f'        ( string "Name" (  ) ( data "Surface{surfaceinx}" ) )\n')
        out_file.write("        ( vector \"Pos\" ( distance ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( rotation \"Rotation\" (  ) ( data ( eulerangles (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"RenderGroup\" (  ) ( data 0.000000 ) )\n")
        out_file.write(f'        ( string "Type" ( staticlist ) ( data "{surf_type}" ) )\n')
        out_file.write(f'        ( string "Lighting" ( staticlist ) ( data "{lighting}" ) )\n')

        def bool_flag(name): return 1 if name in flags else 0

        out_file.write(f'        ( bool "NotAStep" (  ) ( data {bool_flag("NOTASTEP")} ) )\n')
        out_file.write("        ( bool \"Detail\" (  ) ( data 0 ) )\n")
        out_file.write("        ( longint \"LightControl\" ( groupowner group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( string \"TextureEffect\" ( textureeffect ) )\n")
        out_file.write("        ( color \"AmbientLight\" ( group1 ) ( data ( vector (0.000000 0.000000 0.000000) ) ) )\n")
        out_file.write("        ( longint \"LMGridSize\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write(f'        ( bool "ClipLight" ( group1 ) ( data {bool_flag("CLIPLIGHT")} ) )\n')
        out_file.write(f'        ( bool "CastShadowMesh" ( group1 ) ( data {bool_flag("CASTSHADOWMESH")} ) )\n')
        out_file.write(f'        ( bool "ReceiveLight" ( group1 ) ( data {bool_flag("RECEIVELIGHT")} ) )\n')
        out_file.write(f'        ( bool "ReceiveShadows" ( group1 ) ( data {bool_flag("RECEIVESHADOWS")} ) )\n')
        out_file.write(f'        ( bool "ReceiveSunlight" ( group1 ) ( data {bool_flag("RECEIVESUNLIGHT")} ) )\n')
        out_file.write("        ( real \"LightPenScale\" ( group1 ) ( data 0.000000 ) )\n")
        out_file.write("        ( real \"CreaseAngle\" ( group1 ) ( data 45.000000 ) )\n")
        out_file.write("    ) )\n")

        surfaceinx += 1
    out_file.write(") )\n")
    out_file.write(")\n")
    

def main(dat_path, version_flag):
    map_name = os.path.splitext(os.path.basename(dat_path))[0]
    info_txt = f"{map_name}.txt"
    output_lta_path = f"{map_name}.lta"
    output_path = f"{map_name}_PhysicsDATA.lta"

    # Resolve the texture search roots from the .dat location before reading any
    # texture dimensions, so the map's textures are found and UVs map correctly.
    _init_texture_search_dirs(dat_path)

    with open(info_txt, "w", encoding="utf-8") as out:
        with open(dat_path, "rb") as f:
            header = LithtechHeader()
            header.read(f)
            header.print_info(out)

            world_info = LithtechWorldInfo()
            world_info.read(f)
            world_info.print_info(out)

            world_tree = WorldTree()
            world_tree.read(f)
            world_tree.print_info(out)

            keyframer_basekeynames, scattervolume_names, occluder_names = read_world_objects(f, header, out)
            keyframer_keys_map = read_blind_objects(f, header, keyframer_basekeynames, scattervolume_names, out)
            read_render_data(f, header, out, version_flag)

    with open(dat_path, "rb") as f, open(output_lta_path, "w", encoding="utf-8") as out_lta:
        header = LithtechHeader()
        header.read(f)
        world_info = read_world_info(f)
        export_rendernodes_to_lta(f, header, out_lta, map_name, world_tree, keyframer_keys_map, occluder_names, version_flag)

        with open(output_path, "w", encoding="utf-8") as out_file:
            write_surfaces_to_lta(world_tree, out_file, map_name)
    print(f"{map_name} has been successfully converted.")

    # Stage the textures the map actually used into the owning dedit project's
    # Textures folder (auto-detected, or a folder given via DSH_TEXTURE_OUT).
    # This is what lets DEdit display the textures instead of colour blocks.
    project = _detect_dedit_project(dat_path)
    if project:
        try:
            _export_textures(project)
            print(f"[textures] exported to project: {project}")
        except Exception as e:
            print(f"[textures] export skipped ({e})")
    else:
        print("[textures] no dedit project detected — textures were not staged. "
              "Run with DSH_TEXTURE_OUT=<folder> to choose a Textures root.")



if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: dat2lta85 <mapname.dat> -v1 | -v2")
        sys.exit(1)

    dat_file_path = sys.argv[1]
    version_flag = sys.argv[2]

    if not os.path.isfile(dat_file_path):
        print(f"Error: File not found: {dat_file_path}")
        sys.exit(1)

    if version_flag not in ("-v1", "-v2"):
        print("Error: version flag must be -v1 or -v2")
        print("Usage: dat2lta85 <mapname.dat> -v1 | -v2")
        print()
        print("Flags description:")
        print("  -v1   For Lithtech Jupiter v85 maps that use tangents and binormals.")
        print("  -v2   For Lithtech Jupiter v85 maps where tangents and binormals are absent.")
        print("https://github.com/lokea2/DAT2LTA85")
        sys.exit(1)

    main(dat_file_path, version_flag)
