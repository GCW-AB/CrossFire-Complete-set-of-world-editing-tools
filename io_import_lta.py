# SPDX-License-Identifier: GPL-2.0-or-later
"""
LithTech LTA / DTX Importer + Exporter for Blender
=================================================

导入 / 导出 LithTech / Jupiter 引擎的 LTA 关卡文件，并识别、解码 DTX 纹理。

导入支持:
  * LTA S-表达式解析 (world / nodehierarchy / globalproplist)
  * Polyhedron 笔刷几何体 (顶点 / 三角形 / 四边形 / 任意多边形 / 法线)
  * O/P/Q 纹理坐标向量 -> Blender UV
  * WorldModel 等物体的 Pos / Rotation (父子层级)
  * DTX 纹理: BPP_32 (BGRA), BPP_16 (RGB565), BPP_8 (RGB332),
              BPP_8P / BPP_32P (调色板), S3TC DXT1 / DXT3 / DXT5
  * 基础灯光对象导入 (可选)
  * 记录原始类名 / 纹理路径 / infostring, 便于无损回写

导出支持:
  * 把网格对象写回 world / polyhedronlist / nodehierarchy / globalproplist
  * 由 Blender UV 反算 O/P/Q 纹理坐标向量 (与导入完全互逆)
  * 对象层级 (type object) 与笔刷节点 (type brush) 重建
  * 灯光等点实体对象导出 (Pos / Rotation)
  * 可选: 烘焙对象变换到世界坐标、按连通块拆分笔刷、导出选中项

安装: 编辑 -> 偏好设置 -> 插件 -> 安装... -> 选择本文件 -> 勾选启用
使用: 文件 -> 导入 -> LithTech LTA (.lta)
      文件 -> 导出 -> LithTech LTA (.lta)

已知限制:
  * 面的法线导出时按顶点绕序重算 (Newell), 不保留 LTA 里存储的原始法线 ——
    Blender 网格本身不保存 LTA 法线, 因此源文件与 Blender 的法线差异无法回写。
  * 极少数非平面四边形无法用单一平面 O/P/Q 精确表示, 贴图坐标会有轻微偏差。
"""

bl_info = {
    "name": "LithTech LTA (.lta) and DTX textures (Import / Export)",
    "author": "LTA Import",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "File > Import/Export > LithTech LTA (.lta)",
    "description": "Import/export LithTech LTA level files and decode DTX textures",
    "category": "Import-Export",
}

import math
import os
import struct

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatProperty,
    EnumProperty,
)
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.types import Operator


# =============================================================================
# S-表达式解析器
# =============================================================================

class LTAParseError(Exception):
    pass


def _is_space(ch):
    return ch in " \t\r\n"


def parse_sexpr(text):
    """把 LTA 文本解析为嵌套 list。

    数字 -> float, 引号 -> str, 裸 token -> str。
    返回顶层表达式组成的 list。
    """
    n = len(text)
    pos = 0

    def skip_ws(i):
        while i < n and _is_space(text[i]):
            i += 1
        return i

    def parse_expr(i):
        i = skip_ws(i)
        ch = text[i]
        if ch == '(':
            return parse_list(i + 1)
        if ch == '"':
            return parse_string(i + 1)
        return parse_atom(i)

    def parse_list(i):
        items = []
        while True:
            i = skip_ws(i)
            if i >= n:
                raise LTAParseError("未闭合的括号")
            ch = text[i]
            if ch == ')':
                return items, i + 1
            value, i = parse_expr(i)
            items.append(value)

    def parse_string(i):
        chars = []
        while i < n:
            ch = text[i]
            if ch == '"':
                return "".join(chars), i + 1
            if ch == '\\' and i + 1 < n:
                nxt = text[i + 1]
                # LTA 字符串主要用于 Windows 路径，反斜杠是字面量
                # (如 textures\new、map7\Transportship)，不能当作转义符吃掉。
                # 仅处理 \" 与 \\ 两种真正的转义。
                if nxt == '"' or nxt == '\\':
                    chars.append(nxt)
                else:
                    chars.append('\\')
                    chars.append(nxt)
                i += 2
                continue
            chars.append(ch)
            i += 1
        raise LTAParseError("未闭合的字符串")

    def parse_atom(i):
        start = i
        while i < n and not _is_space(text[i]) and text[i] not in "()":
            i += 1
        token = text[start:i]
        return _atom_value(token), i

    roots = []
    pos = skip_ws(pos)
    while pos < n:
        value, pos = parse_expr(pos)
        roots.append(value)
        pos = skip_ws(pos)
    return roots


def _atom_value(token):
    # 尝试解析为数字
    try:
        return float(token)
    except ValueError:
        return token


# =============================================================================
# 嵌套节点辅助
# 节点约定: ["名字", child1, child2, ...]
# =============================================================================

def node_children(node):
    return node[1:]


def find_all(node, name):
    """返回直接子节点中 head == name 的所有节点。"""
    return [c for c in node[1:]
            if isinstance(c, list) and len(c) > 0 and c[0] == name]


def find_first(node, name):
    for c in node[1:]:
        if isinstance(c, list) and len(c) > 0 and c[0] == name:
            return c
    return None


def direct_or_wrapped(node, name):
    """收集直接 children 中 head==name 的节点。

    LTA 中 '( name ( ... ) )' 形式会多产生一个无名 wrapper 节点；
    若直接 children 没有匹配，则进入一层 wrapper 查找。
    """
    result = [c for c in node[1:]
              if isinstance(c, list) and len(c) > 0 and c[0] == name]
    if result:
        return result
    # 进入无名 wrapper: wrapper 没有 head 标签，其实际内容从索引 0 开始
    for c in node[1:]:
        if isinstance(c, list):
            for cc in c:
                if isinstance(cc, list) and len(cc) > 0 and cc[0] == name:
                    result.append(cc)
    return result


def first_direct_or_wrapped(node, name):
    found = direct_or_wrapped(node, name)
    return found[0] if found else None


def as_float(value, default=0.0):
    if isinstance(value, (int, float)):
        return float(value)
    return default


# =============================================================================
# LTA 场景数据结构
# =============================================================================

class Poly:
    __slots__ = ("indices", "normal", "O", "P", "Q", "texname")

    def __init__(self):
        # 面顶点索引, 支持三角形 / 四边形 / 任意多边形
        self.indices = []
        self.normal = (0.0, 0.0, 0.0)
        self.O = (0.0, 0.0, 0.0)
        self.P = (0.0, 0.0, 0.0)
        self.Q = (0.0, 0.0, 0.0)
        self.texname = ""


class Polyhedron:
    __slots__ = ("points", "polys")

    def __init__(self):
        # points: list of (x, y, z)
        self.points = []
        # polys: list of Poly
        self.polys = []


class ObjectInfo:
    __slots__ = ("nodeid", "classname", "name", "pos", "rot_deg", "brush_ids")

    def __init__(self, nodeid, classname):
        self.nodeid = nodeid
        self.classname = classname
        self.name = classname
        self.pos = (0.0, 0.0, 0.0)
        self.rot_deg = (0.0, 0.0, 0.0)
        self.brush_ids = []


# =============================================================================
# 从解析树提取场景
# =============================================================================

def _extract_polyhedron(ph_node):
    ph = Polyhedron()

    # polyhedron 自身带 wrapper: '( polyhedron ( color/pointlist/polylist ) )'
    pointlist = first_direct_or_wrapped(ph_node, "pointlist")
    if pointlist is not None:
        # pointlist 无 wrapper, 直接 children 即顶点行
        for row in pointlist[1:]:
            if isinstance(row, list) and len(row) >= 3:
                ph.points.append((
                    as_float(row[0]),
                    as_float(row[1]),
                    as_float(row[2]),
                ))

    polylist = first_direct_or_wrapped(ph_node, "polylist")
    if polylist is not None:
        # polylist 带 wrapper
        for ep in direct_or_wrapped(polylist, "editpoly"):
            ph.polys.append(_extract_poly(ep))

    return ph


def _extract_poly(ep):
    poly = Poly()

    fnode = find_first(ep, "f")
    if fnode is not None and len(fnode) >= 4:
        # f 后跟任意数量顶点索引 (常见 3 或 4, 也可能是多边形)
        poly.indices = [int(as_float(v)) for v in fnode[1:]]

    nnode = find_first(ep, "n")
    if nnode is not None and len(nnode) >= 4:
        poly.normal = (
            as_float(nnode[1]),
            as_float(nnode[2]),
            as_float(nnode[3]),
        )

    ti = find_first(ep, "textureinfo")
    if ti is not None and len(ti) >= 4:
        # 前三个无名子节点即 O / P / Q
        o_node = ti[1]
        p_node = ti[2]
        q_node = ti[3]
        if isinstance(o_node, list) and len(o_node) >= 3:
            poly.O = (as_float(o_node[0]),
                      as_float(o_node[1]),
                      as_float(o_node[2]))
        if isinstance(p_node, list) and len(p_node) >= 3:
            poly.P = (as_float(p_node[0]),
                      as_float(p_node[1]),
                      as_float(p_node[2]))
        if isinstance(q_node, list) and len(q_node) >= 3:
            poly.Q = (as_float(q_node[0]),
                      as_float(q_node[1]),
                      as_float(q_node[2]))

        name_node = find_first(ti, "name")
        if name_node is not None and len(name_node) >= 2:
            val = name_node[1]
            if isinstance(val, str):
                poly.texname = val

    return poly


def _build_property_map(plist_node):
    """把一个 proplist 节点转为 {属性名: 值}。"""
    result = {}
    # ( proplist ( props... ) )  -> 属性在 plist_node[1].children
    containers = []
    for child in plist_node[1:]:
        if isinstance(child, list):
            containers.append(child)
    # 多数情况下只有一个包裹容器
    if not containers:
        return result

    for prop in containers[0] if len(containers) == 1 else _flat(containers):
        if not (isinstance(prop, list) and len(prop) >= 2):
            continue
        ptype = prop[0]
        pname = prop[1]
        if not isinstance(pname, str):
            continue

        data_node = None
        for c in prop[2:]:
            if isinstance(c, list) and len(c) > 0 and c[0] == "data":
                data_node = c
                break
        if data_node is None:
            result[pname] = None
            continue

        result[pname] = _read_prop_value(ptype, data_node)

    return result


def _flat(lists):
    for lst in lists:
        for item in lst:
            yield item


def _read_prop_value(ptype, data_node):
    # data_node: ["data", ...]
    if len(data_node) < 2:
        return None

    if ptype in ("vector", "color"):
        # ( data ( vector (x y z) ) )
        inner = data_node[1]
        if isinstance(inner, list) and len(inner) >= 2:
            vec = inner[1]
            if isinstance(vec, list) and len(vec) >= 3:
                return (as_float(vec[0]),
                        as_float(vec[1]),
                        as_float(vec[2]))
        return (0.0, 0.0, 0.0)

    if ptype == "rotation":
        # ( data ( eulerangles (x y z) ) )
        inner = data_node[1]
        if isinstance(inner, list) and len(inner) >= 2:
            ang = inner[1]
            if isinstance(ang, list) and len(ang) >= 3:
                return (as_float(ang[0]),
                        as_float(ang[1]),
                        as_float(ang[2]))
        return (0.0, 0.0, 0.0)

    if ptype == "string":
        val = data_node[1]
        return val if isinstance(val, str) else ""

    if ptype in ("real", "longint"):
        return as_float(data_node[1])

    if ptype == "bool":
        return int(as_float(data_node[1])) != 0

    val = data_node[1]
    return val


class LTAScene:
    def __init__(self):
        self.polyhedra = []       # list of Polyhedron
        self.objects = {}         # nodeid -> ObjectInfo
        # brush 全局索引 -> (object nodeid or None for main world)
        self.brush_owner = {}
        self.world_brush_ids = []
        self.info_string = ""


def build_scene(roots):
    scene = LTAScene()

    world = None
    for r in roots:
        if isinstance(r, list) and r and r[0] == "world":
            world = r
            break

    # nodehierarchy / globalproplist 是 world 的直接子节点（LTA 不严格缩进）
    hierarchy = None
    globalprops = None
    if world is not None:
        hierarchy = find_first(world, "nodehierarchy")
        globalprops = find_first(world, "globalproplist")

    # --- 世界几何 ---
    if world is not None:
        header = find_first(world, "header")
        if header is not None:
            info = first_direct_or_wrapped(header, "infostring")
            if info is not None and len(info) >= 2:
                scene.info_string = info[1] if isinstance(info[1], str) else ""

        plist = find_first(world, "polyhedronlist")
        if plist is not None:
            for ph_node in direct_or_wrapped(plist, "polyhedron"):
                scene.polyhedra.append(_extract_polyhedron(ph_node))

    # --- 属性表 ---
    prop_maps = []
    if globalprops is not None:
        # ( globalproplist ( (proplist) (proplist) ... ) )
        # 内层是无名 wrapper, proplist 节点从索引 0 开始
        wrapper = None
        for c in globalprops[1:]:
            if isinstance(c, list):
                wrapper = c
                break
        if wrapper is not None:
            for plist_node in wrapper:
                if isinstance(plist_node, list) and plist_node and \
                        plist_node[0] == "proplist":
                    prop_maps.append(_build_property_map(plist_node))

    def get_props(propid):
        idx = int(propid)
        if 0 <= idx < len(prop_maps):
            return prop_maps[idx]
        return {}

    # --- 节点层级 ---
    if hierarchy is not None:
        rootnode = find_first(hierarchy, "worldnode")
        if rootnode is not None:
            _walk_hierarchy(rootnode, None, get_props, scene)

    return scene


def _walk_hierarchy(wn, current_owner, get_props, scene):
    ntype_node = find_first(wn, "type")
    ntype = ntype_node[1] if ntype_node is not None and len(ntype_node) >= 2 else "null"

    nodeid = 0
    idnode = find_first(wn, "nodeid")
    if idnode is not None and len(idnode) >= 2:
        nodeid = int(as_float(idnode[1]))

    owner = current_owner

    if ntype == "object":
        label = ""
        lnode = find_first(wn, "label")
        if lnode is not None and len(lnode) >= 2 and isinstance(lnode[1], str):
            label = lnode[1]

        props_node = find_first(wn, "properties")
        classname = label or "Object"
        props = {}
        if props_node is not None:
            # properties 直接 child 'name' 是权威引擎类名，不受用户改名影响
            cls_node = find_first(props_node, "name")
            if (cls_node is not None and len(cls_node) >= 2
                    and isinstance(cls_node[1], str) and cls_node[1]):
                classname = cls_node[1]
            propid_node = find_first(props_node, "propid")
            if propid_node is not None and len(propid_node) >= 2:
                props = get_props(int(as_float(propid_node[1])))

        info = ObjectInfo(nodeid, classname)
        info.name = label or classname
        # 实例属性表中的 Name 是用户/系统给的实例名（非空时采用）
        if (isinstance(props.get("Name"), str) and props["Name"]):
            info.name = props["Name"]
        if props.get("Pos") is not None:
            info.pos = props["Pos"]
        if props.get("Rotation") is not None:
            info.rot_deg = props["Rotation"]

        scene.objects[nodeid] = info
        owner = nodeid

    elif ntype == "brush":
        bidx = 0
        bnode = find_first(wn, "brushindex")
        if bnode is not None and len(bnode) >= 2:
            bidx = int(as_float(bnode[1]))

        if owner is None:
            scene.world_brush_ids.append(bidx)
            scene.brush_owner[bidx] = None
        else:
            if owner not in scene.objects:
                # 异常情况下补一个
                scene.objects[owner] = ObjectInfo(owner, "Object")
            scene.objects[owner].brush_ids.append(bidx)
            scene.brush_owner[bidx] = owner

    childlist = find_first(wn, "childlist")
    if childlist is not None:
        for child in direct_or_wrapped(childlist, "worldnode"):
            _walk_hierarchy(child, owner, get_props, scene)


# =============================================================================
# DTX 纹理解码
# =============================================================================

# BPPIdent
_BPP_8P = 0
_BPP_8 = 1
_BPP_16 = 2
_BPP_32 = 3
_BPP_DXT1 = 4
_BPP_DXT3 = 5
_BPP_DXT5 = 6
_BPP_32P = 7

_DTX_SECTIONSFIXED = 1 << 3


class DTXError(Exception):
    pass


class DTXImage:
    __slots__ = ("width", "height", "rgba")

    def __init__(self, width, height, rgba):
        self.width = width
        self.height = height
        # rgba: bytes, 每像素 4 字节 R,G,B,A, 行序 top -> bottom
        self.rgba = rgba


def _decode_565(c):
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    r = (r5 << 3) | (r5 >> 2)
    g = (g6 << 2) | (g6 >> 4)
    b = (b5 << 3) | (b5 >> 2)
    return r, g, b


def _dxt_color_block(data, off, force_4color):
    c0, c1 = struct.unpack_from("<HH", data, off)
    bits = struct.unpack_from("<I", data, off + 4)[0]
    r0, g0, b0 = _decode_565(c0)
    r1, g1, b1 = _decode_565(c1)

    colors = [(r0, g0, b0, 255), (r1, g1, b1, 255)]
    if force_4color or c0 > c1:
        colors.append(((2 * r0 + r1) // 3,
                       (2 * g0 + g1) // 3,
                       (2 * b0 + b1) // 3, 255))
        colors.append(((r0 + 2 * r1) // 3,
                       (g0 + 2 * g1) // 3,
                       (b0 + 2 * b1) // 3, 255))
    else:
        colors.append(((r0 + r1) // 2,
                       (g0 + g1) // 2,
                       (b0 + b1) // 2, 255))
        colors.append((0, 0, 0, 0))

    out = bytearray(16 * 4)
    for i in range(16):
        idx = (bits >> (i * 2)) & 0x3
        r, g, b, a = colors[idx]
        base = i * 4
        out[base] = r
        out[base + 1] = g
        out[base + 2] = b
        out[base + 3] = a
    return out


def _dxt_alpha_dxt3(data, off):
    out = bytearray(16)
    for i in range(4):
        v = struct.unpack_from("<H", data, off + i * 2)[0]
        out[i * 4 + 0] = (v & 0xF) * 17
        out[i * 4 + 1] = ((v >> 4) & 0xF) * 17
        out[i * 4 + 2] = ((v >> 8) & 0xF) * 17
        out[i * 4 + 3] = ((v >> 12) & 0xF) * 17
    return out


def _dxt_alpha_dxt5(data, off):
    a0 = data[off]
    a1 = data[off + 1]
    alphas = [a0, a1]
    if a0 > a1:
        for i in range(1, 7):
            alphas.append(((7 - i) * a0 + i * a1) // 7)
    else:
        for i in range(1, 5):
            alphas.append(((5 - i) * a0 + i * a1) // 5)
        alphas.append(0)
        alphas.append(255)

    bits = data[off + 2:off + 8]
    packed = 0
    for i in range(6):
        packed |= bits[i] << (8 * i)

    out = bytearray(16)
    for i in range(16):
        idx = (packed >> (i * 3)) & 0x7
        out[i] = alphas[idx]
    return out


def _mip_data_size(bpp, w, h):
    if bpp == _BPP_DXT1:
        bx = max(1, (w + 3) // 4)
        by = max(1, (h + 3) // 4)
        return bx * by * 8
    if bpp in (_BPP_DXT3, _BPP_DXT5):
        bx = max(1, (w + 3) // 4)
        by = max(1, (h + 3) // 4)
        return bx * by * 16
    if bpp == _BPP_32:
        return w * h * 4
    if bpp in (_BPP_8, _BPP_8P, _BPP_32P):
        return w * h
    if bpp == _BPP_16:
        return w * h * 2
    return w * h


def decode_dtx(path):
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 32:
        raise DTXError("文件过小")

    res_type, version = struct.unpack_from("<Ii", data, 0)
    base_w, base_h, nmips, nsections = struct.unpack_from("<HHHH", data, 8)
    iflags, userflags = struct.unpack_from("<ii", data, 16)
    extra = data[24:36]
    bpp = extra[2] if extra[2] != 0 else _BPP_32

    if res_type != 0:
        raise DTXError("不是 DTX 资源 (ResType=%d)" % res_type)
    if nmips == 0 or nmips > 15:
        raise DTXError("Mipmap 数量非法: %d" % nmips)

    # 跳过所有 mip 数据，只解码 mip0
    # sizeof(DtxHeader):
    # 4(res)+4(ver)+2+2+2+2+4+4+12(extra)+128(cmd) = 164
    header_size = 164

    mip0_size = _mip_data_size(bpp, base_w, base_h)
    mip0 = data[header_size:header_size + mip0_size]

    # 计算所有 mip 总大小，定位 sections
    w, h = base_w, base_h
    total_pix = 0
    for _ in range(nmips):
        total_pix += _mip_data_size(bpp, w, h)
        w = max(1, w >> 1)
        h = max(1, h >> 1)

    sections_start = header_size + total_pix

    palette = None
    if iflags & _DTX_SECTIONSFIXED:
        palette = _read_palette_section(data, sections_start, nsections)

    rgba = _decode_pixels(bpp, base_w, base_h, mip0, palette)
    return DTXImage(base_w, base_h, rgba)


def _read_palette_section(data, start, nsections):
    pos = start
    for _ in range(nsections):
        if pos + 29 > len(data):
            return None
        stype = bytes(data[pos:pos + 15]).split(b"\x00", 1)[0]
        # sname = data[pos+15:pos+25]
        (dlen,) = struct.unpack_from("<I", data, pos + 25)
        body_start = pos + 29
        body_end = body_start + dlen
        if stype == b"PALLETE32":
            # 256 * RPaletteColor, 每色 a,r,g,b
            return data[body_start:body_end]
        pos = body_end
    return None


def _decode_pixels(bpp, w, h, raw, palette):
    total = w * h
    out = bytearray(total * 4)

    if bpp == _BPP_32:
        # 文件内存字节序 B,G,R,A
        for i in range(total):
            s = i * 4
            d = i * 4
            out[d] = raw[s + 2]
            out[d + 1] = raw[s + 1]
            out[d + 2] = raw[s]
            out[d + 3] = raw[s + 3]

    elif bpp == _BPP_16:
        for i in range(total):
            c = struct.unpack_from("<H", raw, i * 2)[0]
            r, g, b = _decode_565(c)
            d = i * 4
            out[d] = r
            out[d + 1] = g
            out[d + 2] = b
            out[d + 3] = 255

    elif bpp == _BPP_8:
        # RGB332: RR R GG G BB
        for i in range(total):
            v = raw[i]
            r3 = (v >> 5) & 0x7
            g3 = (v >> 2) & 0x7
            b2 = v & 0x3
            d = i * 4
            out[d] = (r3 << 5) | (r3 << 2) | (r3 >> 1)
            out[d + 1] = (g3 << 5) | (g3 << 2) | (g3 >> 1)
            out[d + 2] = (b2 << 6) | (b2 << 4) | (b2 << 2) | b2
            out[d + 3] = 255

    elif bpp == _BPP_32P:
        if palette is None:
            # 无调色板，按索引灰度兜底
            for i in range(total):
                d = i * 4
                v = raw[i]
                out[d] = out[d + 1] = out[d + 2] = v
                out[d + 3] = 255
        else:
            for i in range(total):
                ps = raw[i] * 4
                d = i * 4
                # palette 字节 a,r,g,b
                out[d] = palette[ps + 1]
                out[d + 1] = palette[ps + 2]
                out[d + 2] = palette[ps + 3]
                out[d + 3] = palette[ps]

    elif bpp == _BPP_8P:
        if palette is not None:
            for i in range(total):
                ps = raw[i] * 4
                d = i * 4
                out[d] = palette[ps + 1]
                out[d + 1] = palette[ps + 2]
                out[d + 2] = palette[ps + 3]
                out[d + 3] = palette[ps]
        else:
            for i in range(total):
                d = i * 4
                v = raw[i]
                out[d] = out[d + 1] = out[d + 2] = v
                out[d + 3] = 255

    elif bpp == _BPP_DXT1:
        _decode_s3tc(w, h, raw, out, "DXT1")
    elif bpp == _BPP_DXT3:
        _decode_s3tc(w, h, raw, out, "DXT3")
    elif bpp == _BPP_DXT5:
        _decode_s3tc(w, h, raw, out, "DXT5")
    else:
        # 未知格式: 不透明黑兜底
        for i in range(total):
            out[i * 4 + 3] = 255

    return bytes(out)


def _decode_s3tc(w, h, raw, out, mode):
    blocks_x = max(1, (w + 3) // 4)
    blocks_y = max(1, (h + 3) // 4)

    block_pix = 16 * 4
    if mode == "DXT1":
        block_bytes = 8
    else:
        block_bytes = 16

    for by_i in range(blocks_y):
        for bx_i in range(blocks_x):
            boff = (by_i * blocks_x + bx_i) * block_bytes

            if mode == "DXT1":
                color = _dxt_color_block(raw, boff, False)
                alpha = None
            elif mode == "DXT3":
                alpha = _dxt_alpha_dxt3(raw, boff)
                color = _dxt_color_block(raw, boff + 8, True)
            else:
                alpha = _dxt_alpha_dxt5(raw, boff)
                color = _dxt_color_block(raw, boff + 8, True)

            for py in range(4):
                for px in range(4):
                    x = bx_i * 4 + px
                    y = by_i * 4 + py
                    if x >= w or y >= h:
                        continue
                    ci = (py * 4 + px) * 4
                    di = (y * w + x) * 4
                    out[di] = color[ci]
                    out[di + 1] = color[ci + 1]
                    out[di + 2] = color[ci + 2]
                    out[di + 3] = alpha[py * 4 + px] if alpha is not None else color[ci + 3]


# =============================================================================
# Blender 导入
# =============================================================================

def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _calc_uv(poly, px_py_pz, tex_w, tex_h, flip_v):
    """从 O/P/Q 与原始局部坐标计算 Blender UV。"""
    rel = (px_py_pz[0] - poly.O[0],
           px_py_pz[1] - poly.O[1],
           px_py_pz[2] - poly.O[2])
    u = _dot(poly.P, rel)
    v = -_dot(poly.Q, rel)
    if tex_w:
        u /= tex_w
    if tex_h:
        v /= tex_h
    if flip_v:
        v = -v
    return u, v


class TextureResolver:
    def __init__(self, lta_path, extra_dir):
        import os
        self.os = os
        lta_dir = os.path.dirname(os.path.abspath(lta_path))
        roots = [lta_dir]
        for sub in ("Textures", "textures"):
            roots.append(os.path.join(lta_dir, sub))
        parent = os.path.dirname(lta_dir)
        if parent and parent != lta_dir:
            roots.append(os.path.join(parent, "Textures"))
            roots.append(parent)
        if extra_dir:
            roots.append(extra_dir)
        self.roots = roots
        self.cache = {}
        self.missing = set()

    def resolve(self, name):
        key = name.replace("\\", "/").lower()
        if key in self.cache:
            return self.cache[key]
        if key in self.missing:
            return None

        rel = name.replace("\\", "/")
        candidates = []
        for root in self.roots:
            candidates.append(self.os.path.join(root, rel))
        # 也尝试 basename
        base = self.os.path.basename(rel)
        for root in self.roots:
            candidates.append(self.os.path.join(root, base))

        for cand in candidates:
            if self.os.path.isfile(cand):
                self.cache[key] = cand
                return cand

        self.missing.add(key)
        return None


def _image_to_blender(name, dtx_img, images_cache, pack=True):
    if name in images_cache:
        return images_cache[name]

    w = dtx_img.width
    h = dtx_img.height
    img = bpy.data.images.new(name, w, h, alpha=True)

    rgba = dtx_img.rgba
    # Blender pixels: bottom-up, flat RGBA float
    pixels = [0.0] * (w * h * 4)
    row_bytes = w * 4
    for row in range(h):
        src_row = h - 1 - row  # top-first -> bottom-up
        src_off = src_row * row_bytes
        dst_off = row * w * 4
        for x in range(w):
            s = src_off + x * 4
            d = dst_off + x * 4
            pixels[d] = rgba[s] / 255.0
            pixels[d + 1] = rgba[s + 1] / 255.0
            pixels[d + 2] = rgba[s + 2] / 255.0
            pixels[d + 3] = rgba[s + 3] / 255.0

    img.pixels[:] = pixels
    if pack:
        img.pack()
    images_cache[name] = img
    return img


def _save_image_as_png(img, dtx_path):
    """把解码后的图像存成 DTX 旁边的 PNG 文件，并让图像引用该文件。

    失败（如目录只读）时保持内存图像不变。
    """
    png_path = os.path.splitext(dtx_path)[0] + ".png"
    img.filepath_raw = png_path
    img.file_format = 'PNG'
    img.save()
    # 从磁盘回读，确保显示的是文件内容且解除内存占用
    img.reload()


def _get_or_create_material(texname, resolver, import_textures,
                            materials_cache, images_cache,
                            convert_dtx_to_png=False):
    if texname in materials_cache:
        return materials_cache[texname]

    base = texname.replace("\\", "/")
    base = base.rsplit("/", 1)[-1]
    if base.lower().endswith(".dtx"):
        base = base[:-4]
    if not base:
        base = "Material"

    mat = bpy.data.materials.new(name=base)
    mat.use_nodes = True
    mat.use_backface_culling = False
    # 记录原始纹理路径，供导出 LTA 时还原 name
    mat["lta_texture"] = texname
    # 不透明是新建材质的默认值，无需显式设置。
    # 注意: Blender 4.1+ 移除了 blend_method, 改用 surface_render_method。

    if import_textures:
        resolved = resolver.resolve(texname)
        if resolved:
            try:
                dtx_img = decode_dtx(resolved)
                img = _image_to_blender(base, dtx_img, images_cache,
                                        pack=not convert_dtx_to_png)
                if convert_dtx_to_png:
                    try:
                        _save_image_as_png(img, resolved)
                    except Exception:
                        # 写盘失败则退回内存图像
                        if not img.packed_file:
                            img.pack()
                ntree = mat.node_tree
                tex_node = ntree.nodes.new("ShaderNodeTexImage")
                tex_node.image = img
                tex_node.location = (-300, 300)
                # 用 type 查找，避免界面语言本地化节点名（中文为“原理化 BSDF”）
                bsdf = next((n for n in ntree.nodes
                             if n.type == 'BSDF_PRINCIPLED'), None)
                if bsdf is not None:
                    ntree.links.new(tex_node.outputs["Color"],
                                    bsdf.inputs["Base Color"])
                    # socket identifier 跨语言固定
                    alpha_in = bsdf.inputs.get("Alpha")
                    if alpha_in is not None:
                        ntree.links.new(tex_node.outputs["Alpha"], alpha_in)
                # 含透明则启用混合（跨 3.x / 4.x）
                if _image_has_alpha(dtx_img):
                    if hasattr(mat, "surface_render_method"):
                        mat.surface_render_method = 'BLENDED'
                    elif hasattr(mat, "blend_method"):
                        mat.blend_method = 'BLEND'
            except Exception:
                pass

    materials_cache[texname] = mat
    return mat


def _image_has_alpha(dtx_img):
    rgba = dtx_img.rgba
    for i in range(3, len(rgba), 4):
        if rgba[i] < 255:
            return True
    return False


class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.face_uvs = []      # 每面 3 个 (u,v)
        self.face_tex = []      # 每面纹理名
        self.face_mat = []      # 每面材质索引
        self.materials = []     # 材质对象列表
        self._mat_index = {}

    def add_polyhedron(self, ph, scale, resolver, import_textures,
                       materials_cache, images_cache, tex_dim_cache, flip_v,
                       convert_dtx_to_png=False):
        base = len(self.verts)

        # 顶点
        for p in ph.points:
            self.verts.append((p[0] * scale, p[1] * scale, p[2] * scale))

        # 面
        for poly in ph.polys:
            idx = poly.indices
            if len(idx) < 3:
                continue
            if any(i < 0 or i >= len(ph.points) for i in idx):
                continue

            texname = poly.texname
            tw, th = _texture_dimensions(
                poly, texname, resolver, import_textures, tex_dim_cache)

            uvs = tuple(
                _calc_uv(poly, ph.points[i], tw, th, flip_v) for i in idx)

            self.faces.append(tuple(base + i for i in idx))
            self.face_uvs.append(uvs)
            self.face_tex.append(texname)

            mat = _get_or_create_material(
                texname, resolver, import_textures,
                materials_cache, images_cache, convert_dtx_to_png)
            if mat.name not in self._mat_index:
                self._mat_index[mat.name] = len(self.materials)
                self.materials.append(mat)
            self.face_mat.append(self._mat_index[mat.name])

    def build(self, name):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.update()

        for mat in self.materials:
            mesh.materials.append(mat)

        if self.face_uvs:
            uvlayer = mesh.uv_layers.new(name="UVMap")
        else:
            uvlayer = None

        for poly in mesh.polygons:
            fi = poly.index
            if fi < len(self.face_mat):
                poly.material_index = self.face_mat[fi]
                uvs = self.face_uvs[fi]
                loops = poly.loop_indices
                for k in range(min(len(loops), len(uvs))):
                    uvlayer.data[loops[k]].uv = uvs[k]
            poly.use_smooth = False

        return mesh


def _texture_dimensions(poly, texname, resolver, import_textures, cache):
    """UV 归一化所需的纹理宽高。优先从 DTX 头读取。"""
    key = texname.replace("\\", "/").lower()
    if key in cache:
        return cache[key]

    w, h = 0, 0
    # 从 P/Q 模长无法可靠反推尺寸，尝试直接读 DTX 头
    if import_textures and texname:
        resolved = resolver.resolve(texname)
        if resolved:
            try:
                with open(resolved, "rb") as f:
                    head = f.read(16)
                if len(head) >= 16:
                    w, h = struct.unpack_from("<HH", head, 8)
            except Exception:
                w, h = 0, 0

    cache[key] = (w, h)
    return w, h


def import_lta(context, filepath, *, scale, import_textures, texture_dir,
               merge_world, flip_v, import_lights, convert_dtx_to_png=False):
    import os
    import time

    t0 = time.time()
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    roots = parse_sexpr(text)
    del text
    scene = build_scene(roots)
    del roots

    resolver = TextureResolver(filepath, texture_dir)
    materials_cache = {}
    images_cache = {}
    tex_dim_cache = {}

    # 主 Collection
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    root_col = bpy.data.collections.new(base_name)
    context.collection.children.link(root_col)
    # 记录源信息, 供导出时无损还原
    root_col["lta_infostring"] = scene.info_string
    root_col["lta_scale"] = scale
    root_col["lta_source"] = os.path.basename(filepath)

    stats = {"brushes": 0, "textures": 0, "lights": 0, "objects": 0}

    def link_object(obj):
        root_col.objects.link(obj)

    # --- 主世界笔刷 ---
    world_builder = MeshBuilder()
    for bidx in scene.world_brush_ids:
        if 0 <= bidx < len(scene.polyhedra):
            world_builder.add_polyhedron(
                scene.polyhedra[bidx], scale, resolver, import_textures,
                materials_cache, images_cache, tex_dim_cache, flip_v,
                convert_dtx_to_png)
            stats["brushes"] += 1

    if world_builder.faces:
        if merge_world:
            mesh = world_builder.build("World")
            link_world = bpy.data.objects.new("World", mesh)
            link_object(link_world)
        else:
            # 每笔刷单独
            _build_split_brushes(
                scene, scene.world_brush_ids, scale, resolver,
                import_textures, materials_cache, images_cache,
                tex_dim_cache, flip_v, root_col, None, stats,
                convert_dtx_to_png)

    # --- 对象 (WorldModel 等) ---
    for nodeid, info in scene.objects.items():
        if not info.brush_ids:
            continue
        stats["objects"] += 1

        builder = MeshBuilder()
        for bidx in info.brush_ids:
            if 0 <= bidx < len(scene.polyhedra):
                builder.add_polyhedron(
                    scene.polyhedra[bidx], scale, resolver, import_textures,
                    materials_cache, images_cache, tex_dim_cache, flip_v,
                    convert_dtx_to_png)
                stats["brushes"] += 1

        if not builder.faces:
            continue

        mesh = builder.build(_safe_name(info.name))
        mesh_obj = bpy.data.objects.new(_safe_name(info.name), mesh)
        # 记录引擎类名 / 实例名, 供导出时重建 object 节点
        mesh_obj["lta_classname"] = info.classname
        mesh_obj["lta_name"] = info.name

        # 父 Empty 承载 Pos / Rotation
        empty = bpy.data.objects.new(_safe_name(info.name) + "_Transform", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty["lta_classname"] = info.classname
        empty["lta_name"] = info.name
        empty.location = (info.pos[0] * scale,
                          info.pos[1] * scale,
                          info.pos[2] * scale)
        import math
        empty.rotation_mode = 'XYZ'
        empty.rotation_euler = (
            math.radians(info.rot_deg[0]),
            math.radians(info.rot_deg[1]),
            math.radians(info.rot_deg[2]),
        )
        link_object(empty)
        mesh_obj.parent = empty
        link_object(mesh_obj)

    # --- 灯光 ---
    if import_lights:
        _import_lights(scene, scale, root_col, stats)

    stats["textures"] = len(images_cache)
    elapsed = time.time() - t0
    print(
        "[LTA] 完成: 笔刷 %d, 对象 %d, 纹理 %d, 灯光 %d, 用时 %.1f 秒"
        % (stats["brushes"], stats["objects"], stats["textures"],
           stats["lights"], elapsed)
    )
    if resolver.missing:
        print("[LTA] 未找到 %d 个纹理: %s"
              % (len(resolver.missing),
                 ", ".join(sorted(resolver.missing)[:20])))

    return stats


def _build_split_brushes(scene, brush_ids, scale, resolver, import_textures,
                         materials_cache, images_cache, tex_dim_cache, flip_v,
                         root_col, parent, stats, convert_dtx_to_png=False):
    for n, bidx in enumerate(brush_ids):
        if not (0 <= bidx < len(scene.polyhedra)):
            continue
        builder = MeshBuilder()
        builder.add_polyhedron(
            scene.polyhedra[bidx], scale, resolver, import_textures,
            materials_cache, images_cache, tex_dim_cache, flip_v,
            convert_dtx_to_png)
        if builder.faces:
            mesh = builder.build("Brush_%d" % n)
            obj = bpy.data.objects.new("Brush_%d" % n, mesh)
            root_col.objects.link(obj)
            if parent is not None:
                obj.parent = parent


def _import_lights(scene, scale, root_col, stats):
    light_classes = {
        "Light": 'POINT',
        "ObjectLight": 'POINT',
        "PointLight": 'POINT',
        "DirLight": 'SUN',
        "DirectionalLight": 'SUN',
        "SpotLight": 'SPOT',
    }
    for nodeid, info in scene.objects.items():
        kind = light_classes.get(info.classname)
        if kind is None:
            continue

        light_data = bpy.data.lights.new(
            name=_safe_name(info.name), type=kind)
        light_data.energy = 100.0 if kind == 'SUN' else 500.0
        obj = bpy.data.objects.new(_safe_name(info.name), light_data)
        obj.location = (info.pos[0] * scale,
                        info.pos[1] * scale,
                        info.pos[2] * scale)
        import math
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = (math.radians(info.rot_deg[0]),
                              math.radians(info.rot_deg[1]),
                              math.radians(info.rot_deg[2]))
        obj["lta_classname"] = info.classname
        obj["lta_name"] = info.name
        root_col.objects.link(obj)
        stats["lights"] += 1


def _safe_name(name):
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name else "Object"


# =============================================================================
# LTA 导出: Blender 场景 -> LTA 文本
# =============================================================================

# ---- S-表达式序列化 --------------------------------------------------------

class _Str(str):
    """序列化标记: 输出时用双引号包裹的字符串字面量。

    普通 str 视为 S-表达式符号 (不加引号), _Str 视为字符串 (加引号)。
    """


def _atom_to_text(value):
    if isinstance(value, _Str):
        return '"' + str(value).replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "%.6f" % value
    if isinstance(value, str):
        return value
    return str(value)


def _sexpr_render(node, indent, lines):
    pad = "\t" * indent
    if isinstance(node, list) and not node:
        lines.append(pad + "( )")
        return
    if not isinstance(node, list):
        lines.append(pad + _atom_to_text(node))
        return

    # 匿名 wrapper: 首元素本身是列表 (如 ( ( a ) ( b ) ) ), 无 head 原子
    if isinstance(node[0], list):
        lines.append(pad + "(")
        for c in node:
            if isinstance(c, list):
                _sexpr_render(c, indent + 1, lines)
            else:
                lines.append("\t" * (indent + 1) + _atom_to_text(c))
        lines.append(pad + ")")
        return

    head = node[0]
    children = node[1:]
    # 无子列表 -> 单行
    if not any(isinstance(c, list) for c in children):
        parts = [_atom_to_text(head)] + [_atom_to_text(c) for c in children]
        lines.append(pad + "( " + " ".join(parts) + " )")
        return

    # 多行: head 与其后的前置原子同行, 其余子节点缩进
    head_line = pad + "( " + _atom_to_text(head)
    idx = 0
    while idx < len(children) and not isinstance(children[idx], list):
        head_line += " " + _atom_to_text(children[idx])
        idx += 1
    lines.append(head_line)
    for c in children[idx:]:
        if isinstance(c, list):
            _sexpr_render(c, indent + 1, lines)
        else:
            lines.append("\t" * (indent + 1) + _atom_to_text(c))
    lines.append(pad + ")")


def serialize_lta(roots):
    """把嵌套 list 树渲染为 LTA 文本。"""
    lines = []
    for r in roots:
        _sexpr_render(r, 0, lines)
    return "\n".join(lines) + "\n"


# ---- 向量与纹理坐标反算 ----------------------------------------------------

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _newell_normal(verts):
    """Newell 法: 对任意多边形稳健地求法线 (遵循顶点绕序)。"""
    nx = ny = nz = 0.0
    m = len(verts)
    for i in range(m):
        a = verts[i]
        b = verts[(i + 1) % m]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-12:
        return (0.0, 0.0, 0.0)
    return (nx / ln, ny / ln, nz / ln)


def _solve_in_plane(e1, e2, a1, a2):
    """求 (近似) 平面内向量 w, 使 w·e1 = a1, w·e2 = a2。

    因拖掉法线方向分量不影响在平面上的投影, 这里只取 e1/e2 张成的分量。
    退化 (e1 ∥ e2) 时返回零向量。
    """
    d11 = _dot(e1, e1)
    d12 = _dot(e1, e2)
    d22 = _dot(e2, e2)
    det = d11 * d22 - d12 * d12
    if abs(det) < 1e-12:
        return (0.0, 0.0, 0.0)
    alpha = (a1 * d22 - a2 * d12) / det
    beta = (a2 * d11 - a1 * d12) / det
    return (alpha * e1[0] + beta * e2[0],
            alpha * e1[1] + beta * e2[1],
            alpha * e1[2] + beta * e2[2])


def _best_triple(verts):
    """在多边形中挑一组最不退化 (面积最大) 的三个顶点, 用于拟合纹理平面。"""
    n = len(verts)
    if n == 3:
        return 0, 1, 2
    idxs = list(range(n)) if n <= 10 else list(range(0, n, max(1, n // 8)))
    best = (0, 1, 2)
    best_area = -1.0
    for a in range(len(idxs)):
        ia = idxs[a]
        for b in range(a + 1, len(idxs)):
            ib = idxs[b]
            e1 = _vsub(verts[ib], verts[ia])
            for c in range(b + 1, len(idxs)):
                ic = idxs[c]
                cr = _vcross(e1, _vsub(verts[ic], verts[ia]))
                area = cr[0] * cr[0] + cr[1] * cr[1] + cr[2] * cr[2]
                if area > best_area:
                    best_area = area
                    best = (ia, ib, ic)
    return best


def _compute_textureinfo(verts, uvs, tw, th, flip_v):
    """由多边形顶点与 UV 反算 LTA 的 O / P / Q 纹理向量。

    与导入侧完全互逆:
        u = dot(P, p - O) / tw
        v = -dot(Q, p - O) / th        (随后按 flip_v 再取反)
    返回 (O, P, Q); 无法精确表示时回退为轴对齐投影。
    """
    if tw <= 0:
        tw = 1.0
    if th <= 0:
        th = 1.0

    # UV 完全退化为一个点 (无 UV 层 / 所有点 UV 相同) -> 精确复现该常值
    if all(uv == uvs[0] for uv in uvs):
        return _constant_uv_textureinfo(verts, uvs[0], tw, th, flip_v)

    i0, i1, i2 = _best_triple(verts)
    p0, p1, p2 = verts[i0], verts[i1], verts[i2]
    uv0, uv1, uv2 = uvs[i0], uvs[i1], uvs[i2]
    e1 = _vsub(p1, p0)
    e2 = _vsub(p2, p0)

    du1, du2 = uv1[0] - uv0[0], uv2[0] - uv0[0]
    dv1, dv2 = uv1[1] - uv0[1], uv2[1] - uv0[1]
    # 抵消导入时的 flip_v
    if flip_v:
        dv1, dv2 = -dv1, -dv2
        v0 = -uv0[1]
    else:
        v0 = uv0[1]

    normal = _newell_normal(verts)
    P0 = _solve_in_plane(e1, e2, tw * du1, tw * du2)
    Q0 = _solve_in_plane(e1, e2, -th * dv1, -th * dv2)

    def candidate(P, Q):
        O = _solve_origin(P, Q, p0, uv0[0], v0, tw, th)
        if O is None:
            return None
        return O, P, Q

    def residual(cand):
        O, P, Q = cand
        err = 0.0
        for p, uv in zip(verts, uvs):
            rel = _vsub(p, O)
            u = _dot(P, rel) / tw
            v = -_dot(Q, rel) / th
            if flip_v:
                v = -v
            err = max(err, abs(u - uv[0]), abs(v - uv[1]))
        return err

    # 候选向量对。平面上投影只取决于向量的面内分量; 面外 (法线) 分量仅贡献
    # 一个常数偏移 (由 O 吸收)。因此当某条 UV 轴在面上退化为常值时, 可以给
    # 它叠加一个法线分量来承载该偏移, 而完全不改变面上的 UV。
    # 这里列出"纯净解"及其法线修正版, 逐个验证 UV 残差。
    nP = _vadd(P0, normal)
    nQ = _vadd(Q0, normal)
    exact = []     # (|O|, -( |P|²+|Q|² ), cand)
    best = None
    best_err = float("inf")
    for P in (P0, nP):
        for Q in (Q0, nQ):
            if _dot(P, P) < 1e-12 and _dot(Q, Q) < 1e-12:
                continue
            cand = candidate(P, Q)
            if cand is None:
                continue
            err = residual(cand)
            if err < 1e-9:
                O = cand[0]
                exact.append((_dot(O, O), -(_dot(P, P) + _dot(Q, Q)), cand))
            if err < best_err:
                best_err = err
                best = cand
    if exact:
        # 多个解都精确复现 UV 时, 选最数值稳定的一组:
        # |O| 最小 (避免微小向量配巨大原点被 %.6f 截断), 其次向量模长最大。
        exact.sort(key=lambda t: (t[0], t[1]))
        return exact[0][2]
    if best is not None:
        return best
    return _axis_projection(normal)


def _solve_origin(P, Q, p0, u0, v0, tw, th):
    """求 O, 使 dot(P,O)=dot(P,p0)-u0*tw 且 dot(Q,O)=dot(Q,p0)+v0*th。

    取最小范数解 (在 P/Q 张成方向); P、Q 近退化时返回 None。
    """
    b1 = _dot(P, p0) - u0 * tw
    b2 = _dot(Q, p0) + v0 * th
    d11 = _dot(P, P)
    d12 = _dot(P, Q)
    d22 = _dot(Q, Q)
    det = d11 * d22 - d12 * d12
    if abs(det) < 1e-12 * max(d11 * d22, 1.0):
        return None
    x = (b1 * d22 - b2 * d12) / det
    y = (b2 * d11 - b1 * d12) / det
    return (x * P[0] + y * Q[0],
            x * P[1] + y * Q[1],
            x * P[2] + y * Q[2])


def _axis_projection(normal):
    """按主轴把纹理投影到平整面上 (无 UV 时的默认映射)。"""
    ax = max(range(3), key=lambda i: abs(normal[i]))
    if ax == 0:
        P, Q = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    elif ax == 1:
        P, Q = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    else:
        P, Q = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    return (0.0, 0.0, 0.0), P, Q


def _constant_uv_textureinfo(verts, uv, tw, th, flip_v):
    """整面 UV 为同一常值时, 构造精确复现该常值的 O/P/Q。

    令 P、Q 平行于面法线, 则面上各点的 dot(P,rel) 恒定, 从而 u、v 恒定;
    O 取沿法线下移一个单位, 使命中值等于目标常数。
    """
    n = _newell_normal(verts)
    if n == (0.0, 0.0, 0.0):
        return _axis_projection(n)
    u0 = uv[0]
    v0 = -uv[1] if flip_v else uv[1]
    p0 = verts[0]
    O = (p0[0] - n[0], p0[1] - n[1], p0[2] - n[2])
    P = _vmul(n, u0 * tw)
    Q = _vmul(n, -v0 * th)
    return O, P, Q


# ---- 材质 -> 纹理名 / 尺寸 -------------------------------------------------

def _material_texture(mat):
    """返回 (texname, tw, th)。

    texname 优先取导入时记录在材质上的原始 LTA 路径 (mat["lta_texture"])。
    """
    texname = ""
    if mat is not None:
        raw = mat.get("lta_texture")
        if isinstance(raw, str) and raw:
            texname = raw

    img = None
    if (mat is not None and getattr(mat, "use_nodes", False)
            and mat.node_tree is not None):
        for n in mat.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image is not None:
                img = n.image
                break

    tw = th = 0
    if img is not None:
        try:
            tw, th = int(img.size[0]), int(img.size[1])
        except Exception:
            tw = th = 0

    if not texname:
        if img is not None:
            nm = img.name
            texname = nm if nm.lower().endswith(".dtx") else nm + ".dtx"
        else:
            texname = "Default"

    if tw <= 0 or th <= 0:
        tw = th = 1
    return texname, tw, th


# ---- 网格对象 -> polyhedron ------------------------------------------------

def _mesh_find(mesh):
    """顶点并查集, 用于按连通块拆分笔刷。"""
    parent = list(range(len(mesh.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for e in mesh.edges:
        union(e.vertices[0], e.vertices[1])
    return find


def _object_polyhedra(obj, *, scale, bake, use_uv, flip_v, split_islands):
    """把网格对象转为 1..N 个 polyhedron 字典。

    bake=True: 顶点/位置烘焙到世界坐标; False: 保留局部坐标 (对象变换另存)。
    """
    mesh = obj.data
    mw = obj.matrix_world
    mirror = mw.to_3x3().determinant() < 0.0
    uv_layer = mesh.uv_layers.active

    if bake:
        engine_co = [(_vmul(tuple(mw @ v.co), scale)) for v in mesh.vertices]
    else:
        engine_co = [(_vmul((v.co[0], v.co[1], v.co[2]), scale))
                     for v in mesh.vertices]

    faces = []
    for poly in mesh.polygons:
        vids = list(poly.vertices)
        if len(vids) < 3:
            continue
        if mirror:
            vids = vids[::-1]
        verts = [engine_co[i] for i in vids]
        if use_uv and uv_layer is not None:
            uvs = [tuple(uv_layer.data[li].uv) for li in poly.loop_indices]
            if mirror:
                uvs = uvs[::-1]
        else:
            uvs = [(0.0, 0.0)] * len(vids)
        faces.append((vids, verts, uvs, poly.material_index))

    if not faces:
        return []

    if split_islands:
        find = _mesh_find(mesh)
        groups = {}
        for f in faces:
            groups.setdefault(find(f[0][0]), []).append(f)
        face_groups = list(groups.values())
    else:
        face_groups = [faces]

    result = []
    for group in face_groups:
        ph = _build_polyhedron(group, mesh, use_uv, flip_v)
        if ph["polys"]:
            result.append(ph)
    return result


def _build_polyhedron(face_list, mesh, use_uv, flip_v):
    points = []
    vmap = {}
    polys = []

    for (vids, verts, uvs, mi) in face_list:
        out_idx = []
        for k in range(len(vids)):
            p = verts[k]
            key = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
            idx = vmap.get(key)
            if idx is None:
                idx = len(points)
                vmap[key] = idx
                points.append(p)
            out_idx.append(idx)
        if len(out_idx) < 3:
            continue

        normal = _newell_normal(verts)
        if normal == (0.0, 0.0, 0.0):
            continue
        dist = _dot(normal, verts[0])

        mat = mesh.materials[mi] if 0 <= mi < len(mesh.materials) else None
        texname, tw, th = _material_texture(mat)
        if use_uv:
            O, P, Q = _compute_textureinfo(verts, uvs, tw, th, flip_v)
        else:
            O, P, Q = _axis_projection(normal)

        polys.append({
            "indices": out_idx,
            "normal": normal,
            "dist": dist,
            "O": O, "P": P, "Q": Q,
            "tex": texname,
        })

    return {"points": points, "polys": polys}


# ---- 节点 / 属性节点构造 ---------------------------------------------------

_LIGHT_CLASS = {
    'POINT': "Light",
    'SUN': "StaticSunLight",
    'SPOT': "SpotLight",
    'AREA': "Light",
}


def _wn(ntype, nodeid, propid, *, label=None, name=None, brushindex=None,
        flags=None, childlist=None):
    """构造一个 worldnode。"""
    node = ["worldnode", ["type", ntype]]
    if label is not None:
        node.append(["label", _Str(label)])
    if brushindex is not None:
        node.append(["brushindex", int(brushindex)])
    node.append(["nodeid", int(nodeid)])
    # DEdit 要求 flags 的值包在匿名列表里: ( flags ( worldroot expanded ) )
    node.append(["flags", list(flags) if flags else []])
    props = ["properties"]
    if name is not None:
        props.append(["name", _Str(name)])
    props.append(["propid", int(propid)])
    node.append(props)
    if childlist:
        node.append(["childlist", childlist])
    return node


def _object_proplist(name, pos, rot):
    return ["proplist", [
        ["string", _Str("Name"), [], ["data", _Str(name)]],
        ["vector", _Str("Pos"), ["distance"],
         ["data", ["vector", [pos[0], pos[1], pos[2]]]]],
        ["rotation", _Str("Rotation"), [],
         ["data", ["eulerangles", [rot[0], rot[1], rot[2]]]]],
    ]]


def _brush_proplist():
    z = [0.0, 0.0, 0.0]
    return ["proplist", [
        ["string", _Str("Name"), [], ["data", _Str("Brush")]],
        ["vector", _Str("Pos"), ["distance"], ["data", ["vector", list(z)]]],
        ["rotation", _Str("Rotation"), [],
         ["data", ["eulerangles", list(z)]]],
        ["longint", _Str("RenderGroup"), [], ["data", 0]],
        ["string", _Str("Type"), ["staticlist"], ["data", _Str("Normal")]],
        ["string", _Str("Lighting"), ["staticlist"],
         ["data", _Str("Gouraud")]],
        ["bool", _Str("NotAStep"), [], ["data", 0]],
        ["bool", _Str("Detail"), [], ["data", 0]],
        ["longint", _Str("LightControl"), ["groupowner", "group1"],
         ["data", 0]],
        ["string", _Str("TextureEffect"), ["textureeffect"]],
        ["color", _Str("AmbientLight"), ["group1"],
         ["data", ["vector", list(z)]]],
        ["longint", _Str("LMGridSize"), ["group1"], ["data", 0]],
        ["bool", _Str("ClipLight"), ["group1"], ["data", 1]],
        ["bool", _Str("CastShadowMesh"), ["group1"], ["data", 1]],
        ["bool", _Str("ReceiveLight"), ["group1"], ["data", 1]],
        ["bool", _Str("ReceiveShadows"), ["group1"], ["data", 1]],
        ["bool", _Str("ReceiveSunlight"), ["group1"], ["data", 1]],
        ["real", _Str("LightPenScale"), ["group1"], ["data", 0]],
        ["real", _Str("CreaseAngle"), ["group1"], ["data", 45.0]],
    ]]


# ---- polyhedron 节点 -------------------------------------------------------

def _textureinfo_node(poly, name):
    return ["textureinfo",
            [poly["O"][0], poly["O"][1], poly["O"][2]],
            [poly["P"][0], poly["P"][1], poly["P"][2]],
            [poly["Q"][0], poly["Q"][1], poly["Q"][2]],
            ["sticktopoly", 1],
            ["name", _Str(name)]]


def _polyhedron_node(ph):
    pts = ["pointlist"]
    for p in ph["points"]:
        pts.append([p[0], p[1], p[2], 255, 255, 255, 255])

    eps = []
    for poly in ph["polys"]:
        eps.append(["editpoly",
                    ["f"] + [int(i) for i in poly["indices"]],
                    ["n", poly["normal"][0], poly["normal"][1], poly["normal"][2]],
                    ["dist", poly["dist"]],
                    _textureinfo_node(poly, poly["tex"]),
                    ["flags"],
                    ["shade", 0, 0, 0],
                    ["physicsmaterial", _Str("Default")],
                    ["surfacekey", _Str("")],
                    ["textures", [[1, _textureinfo_node(poly, "Default")]]]])
    # polylist 同样要带 wrapper: "( polylist ( ( editpoly ... ) ... ) )"
    polylist = ["polylist", eps]

    # DEdit 的 CEditBrush::LoadLTA 用 GetElement(1) 取匿名 wrapper,
    # 因此 color/pointlist/polylist 必须包在 "( polyhedron ( ... ) )" 里。
    return ["polyhedron", [["color", 255, 255, 255], pts, polylist]]


# ---- 场景 -> 文档 ----------------------------------------------------------

def _collect_mesh_objects(context, use_selection):
    pool = context.selected_objects if use_selection else context.scene.objects
    objs = []
    for obj in pool:
        if obj.type == 'MESH' and obj.data is not None \
                and len(obj.data.polygons) > 0:
            objs.append(obj)
    return objs


def _object_transform(obj, scale):
    loc = obj.matrix_world.translation
    pos = (loc[0] * scale, loc[1] * scale, loc[2] * scale)
    eul = obj.matrix_world.to_euler('XYZ')
    rot = (math.degrees(eul[0]), math.degrees(eul[1]), math.degrees(eul[2]))
    return pos, rot


def build_lta_document(context, *, scale, use_selection, export_lights,
                       bake_transforms, use_uv, flip_v, split_islands,
                       world_name, infostring):
    """收集场景并构造 LTA 文档 (顶层表达式列表)。返回 (roots, stats)。"""
    mesh_objs = _collect_mesh_objects(context, use_selection)
    if export_lights:
        pool = context.selected_objects if use_selection \
            else context.scene.objects
        light_objs = [o for o in pool if o.type == 'LIGHT']
    else:
        light_objs = []

    polyhedra = []
    world_brushes = []
    object_nodes = []   # (obj, cls, name, [brush idx])

    # 主世界几何: 无 lta_classname 的网格 -> 世界笔刷
    for obj in mesh_objs:
        if obj.get("lta_classname"):
            continue
        for ph in _object_polyhedra(obj, scale=scale, bake=True,
                                    use_uv=use_uv, flip_v=flip_v,
                                    split_islands=split_islands):
            world_brushes.append(len(polyhedra))
            polyhedra.append(ph)

    # 对象几何: 带 lta_classname 的网格 -> object 节点 + 子笔刷
    for obj in mesh_objs:
        cls = obj.get("lta_classname")
        if not cls:
            continue
        brushes = []
        for ph in _object_polyhedra(obj, scale=scale,
                                    bake=bake_transforms, use_uv=use_uv,
                                    flip_v=flip_v,
                                    split_islands=split_islands):
            brushes.append(len(polyhedra))
            polyhedra.append(ph)
        name = obj.get("lta_name") or obj.name
        object_nodes.append((obj, cls, name, brushes))

    # 灯光 (点实体, 无几何)
    for obj in light_objs:
        cls = obj.get("lta_classname") or _LIGHT_CLASS.get(
            obj.data.type, "Light")
        name = obj.get("lta_name") or obj.name
        object_nodes.append((obj, cls, name, []))

    # --- proplist 表 ---
    prop_lists = [["proplist", []], _brush_proplist()]
    BRUSH_PID = 1

    counter = [0]

    def next_id():
        counter[0] += 1
        return counter[0]

    # --- 节点层级 ---
    root_id = next_id()
    rn_id = next_id()
    rn0_id = next_id()

    world_brush_nodes = [
        _wn("brush", next_id(), BRUSH_PID, name="Brush", brushindex=b)
        for b in world_brushes]

    rn0 = _wn("null", rn0_id, 0, label="RenderNode0",
              childlist=world_brush_nodes)
    rn = _wn("null", rn_id, 0, label="RenderNodes", childlist=[rn0])

    oaw_id = next_id()
    obj_child_nodes = []
    for obj, cls, name, brushes in object_nodes:
        pos, rot = _object_transform(obj, scale)
        if bake_transforms and brushes:
            # 几何已烘焙到世界坐标 -> 节点变换归零
            pos = (0.0, 0.0, 0.0)
            rot = (0.0, 0.0, 0.0)
        pid = len(prop_lists)
        prop_lists.append(_object_proplist(name, pos, rot))
        bnodes = [
            _wn("brush", next_id(), BRUSH_PID, name="Brush", brushindex=b)
            for b in brushes]
        obj_child_nodes.append(
            _wn("object", next_id(), pid, label=cls, name=cls,
                childlist=bnodes))

    oaw = _wn("null", oaw_id, 0, label="ObjectsAndWMs",
              childlist=obj_child_nodes)

    root = _wn("null", root_id, 0, label=world_name,
               flags=["worldroot", "expanded"], childlist=[rn, oaw])

    # --- 文档 ---
    # 注意: DEdit 的读取器要求 header / polyhedronlist / globalproplist 的
    # 子节点包在一层匿名列表里, 即 "( header ( ( versioncode 2 ) ... ) )"。
    # nodehierarchy 例外, worldnode 是它的直接子节点 (无 wrapper)。
    header = ["header", [["versioncode", 2],
                         ["infostring", _Str(infostring)]]]
    polyhedronlist = ["polyhedronlist",
                      [_polyhedron_node(ph) for ph in polyhedra]]
    nodehierarchy = ["nodehierarchy", root]
    globalproplist = ["globalproplist", prop_lists]

    world = ["world", header, polyhedronlist, nodehierarchy, globalproplist]
    roots = [world]

    stats = {
        "brushes": len(polyhedra),
        "world_brushes": len(world_brushes),
        "objects": len(object_nodes),
        "lights": len(light_objs),
    }
    return roots, stats


def _guess_infostring():
    for col in bpy.data.collections:
        v = col.get("lta_infostring")
        if isinstance(v, str) and v:
            return v
    return ""


def export_lta(context, filepath, *, scale=100.0, use_selection=False,
               export_lights=True, bake_transforms=True, use_uv=True,
               flip_v=False, split_islands=False, world_name="",
               infostring=""):
    """把当前场景导出为 LTA 文件。返回统计 dict。"""
    import time
    t0 = time.time()

    if not world_name:
        world_name = (context.scene.name if context.scene else "world")
    if not infostring:
        infostring = _guess_infostring()

    roots, stats = build_lta_document(
        context,
        scale=scale,
        use_selection=use_selection,
        export_lights=export_lights,
        bake_transforms=bake_transforms,
        use_uv=use_uv,
        flip_v=flip_v,
        split_islands=split_islands,
        world_name=world_name,
        infostring=infostring,
    )
    text = serialize_lta(roots)
    with open(filepath, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)

    stats["bytes"] = len(text)
    stats["elapsed"] = time.time() - t0
    print("[LTA] 导出完成: 笔刷 %d (世界 %d), 对象 %d, 灯光 %d, %.1f 秒 -> %s"
          % (stats["brushes"], stats["world_brushes"], stats["objects"],
             stats["lights"], stats["elapsed"], filepath))
    return stats


# =============================================================================
# Operator / 注册
# =============================================================================

class LTA_OT_import(Operator, ImportHelper):
    bl_idname = "import_scene.lta"
    bl_label = "Import LTA"
    bl_description = "Import a LithTech LTA level with DTX textures"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".lta"
    filter_glob: StringProperty(default="*.lta", options={'HIDDEN'})

    scale: FloatProperty(
        name="Scale",
        description="Scale applied to all geometry (LithTech units are ~cm, "
                    "0.01 converts to meters)",
        default=0.01,
        min=0.0001,
        max=1000.0,
    )

    import_textures: BoolProperty(
        name="Import DTX Textures",
        description="Find, decode and apply DTX textures",
        default=True,
    )

    texture_dir: StringProperty(
        name="Texture Root (optional)",
        description="Extra root folder searched for DTX files "
                    "(resolved relative to texture names)",
        default="",
        subtype='DIR_PATH',
    )

    convert_dtx_to_png: BoolProperty(
        name="Convert DTX to PNG",
        description="Save decoded textures as PNG files next to the DTX and "
                    "use the PNG files; off = decode DTX directly into "
                    "in-memory images (packed into the .blend)",
        default=True,
    )

    merge_world: BoolProperty(
        name="Merge Main World",
        description="Merge all main-world brushes into one mesh",
        default=True,
    )

    flip_v: BoolProperty(
        name="Flip V",
        description="Flip texture V coordinate if textures appear upside down",
        default=False,
    )

    import_lights: BoolProperty(
        name="Import Lights",
        description="Create basic Blender lights for light objects",
        default=False,
    )

    def execute(self, context):
        try:
            import_lta(
                context,
                self.filepath,
                scale=self.scale,
                import_textures=self.import_textures,
                texture_dir=self.texture_dir,
                merge_world=self.merge_world,
                flip_v=self.flip_v,
                import_lights=self.import_lights,
                convert_dtx_to_png=self.convert_dtx_to_png,
            )
        except Exception as exc:
            self.report({'ERROR'}, "LTA import failed: %s" % exc)
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "scale")
        layout.prop(self, "import_textures")
        if self.import_textures:
            layout.prop(self, "texture_dir")
            layout.prop(self, "convert_dtx_to_png")
            layout.prop(self, "flip_v")
        layout.prop(self, "merge_world")
        layout.prop(self, "import_lights")


def menu_func_import(self, context):
    self.layout.operator(LTA_OT_import.bl_idname,
                         text="LithTech LTA (.lta)")


class LTA_OT_export(Operator, ExportHelper):
    bl_idname = "export_scene.lta"
    bl_label = "Export LTA"
    bl_description = "Export the scene as a LithTech LTA level file"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".lta"
    filter_glob: StringProperty(default="*.lta", options={'HIDDEN'})

    scale: FloatProperty(
        name="Scale",
        description="Scale applied to exported geometry (inverse of import "
                    "scale; import default 0.01 -> export 100 converts meters "
                    "back to engine units)",
        default=100.0,
        min=0.0001,
        max=100000.0,
    )

    use_selection: BoolProperty(
        name="Selected Only",
        description="Export only selected objects",
        default=False,
    )

    world_name: StringProperty(
        name="World Name",
        description="Root node label (defaults to scene name)",
        default="",
    )

    bake_transforms: BoolProperty(
        name="Bake Object Transforms",
        description="Bake each object's world transform into the geometry and "
                    "write zero node transform; off = keep local geometry and "
                    "store the transform as the object node's Pos/Rotation",
        default=True,
    )

    split_islands: BoolProperty(
        name="Split Into Brushes",
        description="Split each mesh into separate polyhedra per connected "
                    "component (produces more, DEdit-friendly brushes)",
        default=False,
    )

    use_uv: BoolProperty(
        name="Export UV (O/P/Q)",
        description="Recompute per-face O/P/Q texture vectors from the mesh "
                    "UVs; off = use an axis-aligned projection",
        default=True,
    )

    flip_v: BoolProperty(
        name="Flip V",
        description="Invert V when converting UVs back to O/P/Q "
                    "(must match the import setting)",
        default=False,
    )

    export_lights: BoolProperty(
        name="Export Lights",
        description="Export light objects as LTA object nodes",
        default=True,
    )

    infostring: StringProperty(
        name="Info String",
        description="Value written to the world header infostring "
                    "(e.g. 'AmbientLight 85 85 85'); empty = auto (reuse the "
                    "last imported value if available)",
        default="",
    )

    def execute(self, context):
        try:
            export_lta(
                context,
                self.filepath,
                scale=self.scale,
                use_selection=self.use_selection,
                export_lights=self.export_lights,
                bake_transforms=self.bake_transforms,
                use_uv=self.use_uv,
                flip_v=self.flip_v,
                split_islands=self.split_islands,
                world_name=self.world_name,
                infostring=self.infostring,
            )
        except Exception as exc:
            self.report({'ERROR'}, "LTA export failed: %s" % exc)
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "scale")
        layout.prop(self, "world_name")
        layout.prop(self, "use_selection")
        layout.prop(self, "bake_transforms")
        layout.prop(self, "split_islands")
        layout.prop(self, "use_uv")
        if self.use_uv:
            layout.prop(self, "flip_v")
        layout.prop(self, "export_lights")
        layout.prop(self, "infostring")


def menu_func_export(self, context):
    self.layout.operator(LTA_OT_export.bl_idname,
                         text="LithTech LTA (.lta)")


_CLASSES = (LTA_OT_import, LTA_OT_export)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
