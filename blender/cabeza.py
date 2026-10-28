"""Cabeza 3D girando con mandíbula sincronizada a audio.

/Applications/Blender.app/Contents/MacOS/Blender --background --python cabeza.py
"""
import glob
import math
import os
import time
import wave

import bpy
import numpy as np

# ---------- parámetros (todos ajustables por variable de entorno) ----------
def par(name, default):
    return type(default)(os.environ.get(name, default))


N = par("N", 60)          # cuadros de la vuelta completa
FPS = par("FPS", 12)
RES = par("RES", 800)     # píxeles, cuadrado
TARGET_FACES = par("TARGET_FACES", 60000)
# alturas como fracción del busto completo (0 = base de los hombros, 1 = coronilla)
JAW_Z = par("JAW_Z", 0.525)     # corte a la altura de la boca
CHIN_Z = par("CHIN_Z", 0.39)    # barbilla: por debajo el peso vuelve a 0
HINGE_Y = par("HINGE_Y", 0.45)  # bisagra hacia atrás (0 = nariz, 1 = espalda)
# apertura máxima en radianes. 0.15 (≈8,6°) es lo que eligió Diego comparando
# 0.22 / 0.15 / 0.11 con el mismo audio: con 0.22 la mandíbula se descolgaba.
MAX_ANG = par("MAX_ANG", 0.15)
LIP_BAND = par("LIP_BAND", 0.02)    # degradado bajo el corte
NECK_BAND = par("NECK_BAND", 0.04)  # degradado bajo la barbilla

MUTE = os.environ.get("MUTE") == "1"    # ignora el audio: la boca no se mueve
# CALIB=1: solo renderiza frente y perfil con boca cerrada y abierta
CALIB = os.environ.get("CALIB") == "1"

HOME = os.path.expanduser("~")
AUDIO = os.environ.get("AUDIO") or os.path.join(HOME, "Desktop", "voz.wav")
OUT = os.environ.get("OUT") or os.path.join(
    HOME, "Desktop",
    "cabeza_calib" if CALIB else ("cabeza_frames_mudo" if MUTE else "cabeza_frames"),
)
LOG = os.environ.get("LOG") or os.path.join(HOME, "Desktop", "log.txt")

T0 = time.time()
open(LOG, "w").close()


def log(msg):
    line = f"[{time.time() - T0:6.1f}s] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


# ---------- 1. modelo: el indicado en GLB, o el más reciente de ~/Downloads ----------
src = os.environ.get("GLB")
if not src:
    glbs = sorted(glob.glob(os.path.join(HOME, "Downloads", "*.glb")), key=os.path.getmtime)
    if not glbs:
        log("ERROR: no hay .glb en ~/Downloads")
        raise SystemExit(1)
    src = glbs[-1]
log(f"GLB: {src}")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=src)

# ---------- 2. unir mallas, limpiar jerarquía y transformaciones ----------
meshes = [o for o in scene.objects if o.type == "MESH"]
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
for o in [o for o in scene.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)

# textura original, antes de tocar materiales
tex = None
for o in meshes:
    for slot in o.material_slots:
        if not slot.material or not slot.material.use_nodes:
            continue
        for node in slot.material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            linked_to_base = any(l.to_socket.name == "Base Color" for l in node.outputs[0].links)
            if tex is None or linked_to_base:
                tex = node.image
            if linked_to_base:
                break
log(f"textura: {tex.name if tex else 'NINGUNA'}")

if len(meshes) > 1:
    bpy.ops.object.join()
head = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
log(f"unidas {len(meshes)} mallas, caras: {len(head.data.polygons)}")

# ---------- 3. decimar ----------
faces = len(head.data.polygons)
if faces > TARGET_FACES:
    mod = head.modifiers.new("dec", "DECIMATE")
    mod.ratio = TARGET_FACES / faces
    bpy.ops.object.modifier_apply(modifier=mod.name)
log(f"decimado: {len(head.data.polygons)} caras")

# ---------- 4. origen al centro de la geometría ----------
bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
head.location = (0, 0, 0)
head.rotation_mode = "XYZ"   # el importador glTF deja QUATERNION y rotation_euler se ignora

# ---------- 5. material de emisión ----------
mat = bpy.data.materials.new("emision")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial")
emi = nt.nodes.new("ShaderNodeEmission")
emi.inputs["Strength"].default_value = 1.0
nt.links.new(emi.outputs[0], out.inputs["Surface"])
if tex:
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = tex
    nt.links.new(img.outputs["Color"], emi.inputs["Color"])
head.data.materials.clear()
head.data.materials.append(mat)
log("material de emisión aplicado, sin luces")

# ---------- 6. envolvente RMS por cuadro ----------
env = np.zeros(N)
if MUTE:
    log("MUTE=1: no se lee voz.wav, la boca se queda quieta")
elif os.path.exists(AUDIO):
    with wave.open(AUDIO, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if sw != 2:
            log(f"AVISO: {AUDIO} no es de 16 bits ({sw * 8}), boca quieta")
        else:
            data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
            data = data.reshape(-1, ch).mean(axis=1) / 32768.0
            spf = sr / FPS
            for i in range(N):
                chunk = data[int(i * spf):int((i + 1) * spf)]
                if chunk.size:
                    env[i] = math.sqrt(float(np.mean(chunk ** 2)))
            # suelo = ruido de ambiente (percentil 15); por debajo, boca cerrada
            floor = np.percentile(env, 15)
            if env.max() > floor:
                env = np.clip((env - floor) / (env.max() - floor), 0, 1)
            env[env < 0.08] = 0.0
            log(f"audio: {n / sr:.2f}s, {sr}Hz, {ch}ch; envolvente media {env.mean():.2f}")
            log("envolvente: " + " ".join(f"{v:.1f}" for v in env))
else:
    log("sin voz.wav: la boca no se mueve")

# ---------- 6b. curva de Rhubarb (opcional, CURVE=<ruta>) ----------
# El RMS sabe CUÁNTO suena pero no QUÉ se dice: dos sílabas seguidas al mismo
# volumen le salen como una sola boca abierta. Rhubarb reconoce los visemas y
# da el timing real. Si HARAKIRI_ADS ha dejado una curva, manda sobre la
# envolvente; si no, todo sigue como antes.
CURVE = os.environ.get("CURVE")
if CURVE:
    if os.path.exists(CURVE):
        import json as _json

        with open(CURVE) as _f:
            _c = _json.load(_f)
        _fr = _c.get("frames") or []
        if _fr:
            env = np.array([_fr[min(i, len(_fr) - 1)] for i in range(N)],
                           dtype=np.float32)
            log(f"curva de sincronía labial: {_c.get('method')}, "
                f"{len(_fr)} cuadros, media {env.mean():.2f}")
        else:
            log(f"AVISO: {CURVE} no trae cuadros; sigo con la envolvente de volumen")
    else:
        log(f"AVISO: no existe {CURVE}; sigo con la envolvente de volumen")

# ---------- 7. mandíbula por deformación de vértices ----------
me = head.data
nv = len(me.vertices)
base = np.empty(nv * 3, dtype=np.float32)
me.vertices.foreach_get("co", base)
base = base.reshape(-1, 3)
zmin, zmax = base[:, 2].min(), base[:, 2].max()
height = zmax - zmin
z_cut = zmin + JAW_Z * height
z_chin = zmin + CHIN_Z * height

# giro de la cabeza: el modelo no mira exactamente a -Y, así que la bisagra
# se calcula en el eje propio de la cara. La punta de la nariz da la dirección.
slab = (base[:, 2] > z_cut) & (base[:, 2] < z_cut + 0.10 * height)
c_xy = base[slab][:, :2].mean(axis=0)
d = base[slab][:, :2] - c_xy
nose = d[np.argmax(np.hypot(d[:, 0], d[:, 1]))]
YAW = float(os.environ["YAW"]) * math.pi / 180 if "YAW" in os.environ else math.atan2(nose[0], -nose[1])
log(f"giro de la cabeza: {YAW * 180 / math.pi:.1f}°")

# ROLL: cabeza ladeada (grados, positivo = corona hacia +X)
ROLL = par("ROLL", -18.0) * math.pi / 180
cy, sy = math.cos(YAW), math.sin(YAW)
cr, sr = math.cos(ROLL), math.sin(ROLL)
M = np.array([[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]]) @ np.array(
    [[cy, sy, 0], [-sy, cy, 0], [0, 0, 1]])     # mundo -> cara
base = (base @ M.T).astype(np.float32)
ymin, ymax = base[:, 1].min(), base[:, 1].max()   # la cara mira a -Y
y_hinge = ymin + HINGE_Y * (ymax - ymin)
# peso: sube bajo el corte, vale 1 hasta la barbilla, cae a 0 por debajo (cuello, pecho);
# se apaga detrás de la bisagra (nuca)
z = base[:, 2]
w_lip = np.clip((z_cut - z) / (LIP_BAND * height), 0, 1)
w_neck = np.clip((z - (z_chin - NECK_BAND * height)) / (NECK_BAND * height), 0, 1)
w_y = np.clip((y_hinge - base[:, 1]) / (0.25 * (ymax - ymin)), 0, 1)
weight = (w_lip * w_neck * w_y).astype(np.float32)
log(f"mandíbula: z_cut={z_cut:.3f} z_chin={z_chin:.3f} y_hinge={y_hinge:.3f}, "
    f"vértices con peso: {(weight > 0).sum()}/{nv}")


def set_jaw(angle):
    a = angle * weight
    c, s = np.cos(a), np.sin(a)
    dy = base[:, 1] - y_hinge
    dz = base[:, 2] - z_cut
    co = base.copy()
    co[:, 1] = y_hinge + dy * c - dz * s
    co[:, 2] = z_cut + dy * s + dz * c
    world = co @ M                            # de vuelta al eje del mundo
    me.vertices.foreach_set("co", world.ravel())
    me.update()


# ---------- 8. rótulo: anillo de texto que gira al revés ----------
RING = os.environ.get("RING")          # PNG con alfa, tira larga de texto
RING_Z = par("RING_Z", 0.42)           # altura del centro del ocho, fracción del busto
RING_R = par("RING_R", 1.45)           # radio, veces el ancho de la cabeza
RING_REP = par("RING_REP", 1)          # veces que la tira da la vuelta: más veces, letra más chica
RING_INF = par("RING_INF", 0.18)       # vaivén en ocho: altura del sube y baja, fracción del busto
r_xy = float(np.sqrt(base[:, 0] ** 2 + base[:, 1] ** 2).max())
ring = None

if RING:
    img = bpy.data.images.load(RING)
    iw, ih = img.size
    radio = r_xy * RING_R
    alto = 2 * math.pi * radio * ih / iw / RING_REP   # mantiene la proporción de la tira
    zc = zmin + RING_Z * height
    S = 256
    amp = RING_INF * height            # sube y baja dos veces por vuelta: visto de frente, un ocho
    verts, faces, uvs = [], [], []

    def onda(a):
        return zc + amp * math.sin(2 * a)

    for i in range(S):
        a0, a1 = 2 * math.pi * i / S, 2 * math.pi * (i + 1) / S
        z0, z1 = onda(a0), onda(a1)
        base_i = len(verts)
        verts += [(radio * math.sin(a0), -radio * math.cos(a0), z0 + alto / 2),
                  (radio * math.sin(a1), -radio * math.cos(a1), z1 + alto / 2),
                  (radio * math.sin(a1), -radio * math.cos(a1), z1 - alto / 2),
                  (radio * math.sin(a0), -radio * math.cos(a0), z0 - alto / 2)]
        # orden invertido: así la cara de fuera mira hacia fuera y el texto no sale espejado
        faces.append((base_i + 3, base_i + 2, base_i + 1, base_i))
        u0, u1 = i / S * RING_REP, (i + 1) / S * RING_REP
        uvs += [(u0, 0), (u1, 0), (u1, 1), (u0, 1)]

    rm = bpy.data.meshes.new("rotulo")
    rm.from_pydata(verts, [], faces)
    uv = rm.uv_layers.new(name="UVMap")
    for j, co in enumerate(uvs):
        uv.data[j].uv = co
    ring = bpy.data.objects.new("rotulo", rm)
    scene.collection.objects.link(ring)
    ring.rotation_mode = "XYZ"

    rmat = bpy.data.materials.new("rotulo")
    rmat.use_nodes = True
    rnt = rmat.node_tree
    rnt.nodes.clear()
    rout = rnt.nodes.new("ShaderNodeOutputMaterial")
    rmix = rnt.nodes.new("ShaderNodeMixShader")       # alfa del PNG: texto sí, fondo no
    rtrans = rnt.nodes.new("ShaderNodeBsdfTransparent")
    remi = rnt.nodes.new("ShaderNodeEmission")
    remi.inputs["Strength"].default_value = 1.0
    rtex = rnt.nodes.new("ShaderNodeTexImage")
    rtex.image = img
    rnt.links.new(rtex.outputs["Color"], remi.inputs["Color"])
    rnt.links.new(rtex.outputs["Alpha"], rmix.inputs["Fac"])
    rnt.links.new(rtrans.outputs[0], rmix.inputs[1])
    rnt.links.new(remi.outputs[0], rmix.inputs[2])
    rnt.links.new(rmix.outputs[0], rout.inputs["Surface"])
    # sin esto se ve el texto del lado de atrás, reflejado, y ensucia la lectura
    rmat.use_backface_culling = os.environ.get("RING_DOBLE") != "1"
    for prop, valor in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED")):
        try:                                   # el nombre cambió entre versiones de Blender
            setattr(rmat, prop, valor)
        except (AttributeError, TypeError):
            pass
    rm.materials.append(rmat)
    ring_half = abs(zc) + amp + alto / 2       # para que el ocho no se salga del cuadro
    log(f"rótulo: {os.path.basename(RING)} {iw}x{ih}, radio {radio:.2f}, "
        f"alto {alto:.2f}, ocho {amp:.2f}")

# ---------- 9. cámara y render ----------
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 85
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
r = max(r_xy * (RING_R if RING else 1.0), height / 2, ring_half if RING else 0)
fov = 2 * math.atan(18 / cam_data.lens)
dist = r / math.tan(fov / 2) * (1.2 if RING else 1.12)   # el rótulo necesita más aire
cam.location = (0, -dist, 0)
cam.rotation_euler = (math.pi / 2, 0, 0)

for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        scene.render.engine = eng
        break
    except TypeError:
        pass
scene.eevee.taa_render_samples = 64 if RING else 16   # el alfa del rótulo pide más muestras
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.fps = FPS
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"   # colores de la foto, sin AgX
log(f"motor: {scene.render.engine}, {RES}px, {N} cuadros")

os.makedirs(OUT, exist_ok=True)


def still(name, rot, angle):
    head.rotation_euler = (0, 0, rot)
    if ring:
        ring.rotation_euler = (0, 0, -rot)
    set_jaw(angle)
    bpy.context.view_layer.update()
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)


if CALIB:
    for view, rot in (("frente", -YAW), ("perfil", -YAW + math.pi / 2)):
        still(f"{view}_cerrada.png", rot, 0.0)
        still(f"{view}_abierta.png", rot, MAX_ANG)
    log(f"calibración en {OUT}")
    raise SystemExit(0)

if env.any():
    log(f"cuadros con boca abierta: {(env > 0).sum()}/{N}, audio usado: {N / FPS:.1f}s")
# Vueltas por segundo. Sin VUELTAS_S se comporta como siempre: una vuelta
# en todo el clip, que con una línea de 12 s deja al personaje de espaldas la
# mitad del tiempo. El v7 giraba rápido acelerando el vídeo (HEAD_SPEED=6),
# pero eso descuadra la boca; girando aquí, boca y giro van cada uno a lo suyo.
VUELTAS_S = float(os.environ.get("VUELTAS_S", "0")) or None
VUELTAS = VUELTAS_S * N / FPS if VUELTAS_S else 1.0
log(f"giro: {VUELTAS:.2f} vueltas en {N / FPS:.1f}s"
    + (f" ({VUELTAS_S} vueltas/s)" if VUELTAS_S else " (una vuelta por clip)"))

ROT_CURVE = os.environ.get("ROT_CURVE")    # json con un angulo (radianes) por cuadro: giro libre
_rot = None
if ROT_CURVE:
    import json as _json2
    _rot = _json2.load(open(ROT_CURVE))
    log(f"curva de giro: {len(_rot)} cuadros")
for i in range(N):
    head.rotation_euler = (0, 0, _rot[min(i, len(_rot) - 1)] if _rot else 2 * math.pi * VUELTAS * i / N)
    if ring:
        ring.rotation_euler = (0, 0, -2 * math.pi * i / N)   # gira al revés
    set_jaw(MAX_ANG * env[i])
    bpy.context.view_layer.update()          # sin esto, cuadros idénticos
    scene.render.filepath = os.path.join(OUT, f"f_{i:03d}.png")
    bpy.ops.render.render(write_still=True)
    if i % 10 == 0:
        log(f"cuadro {i}/{N}")
log("render terminado")

# ---------- verificación: f_000 vs f_mitad ----------
def pixels(path):
    im = bpy.data.images.load(path)
    px = np.empty(im.size[0] * im.size[1] * 4, dtype=np.float32)
    im.pixels.foreach_get(px)
    return px.reshape(-1, 4)

mid = N // 2
a = pixels(os.path.join(OUT, "f_000.png"))
b = pixels(os.path.join(OUT, f"f_{mid:03d}.png"))
diff = float(np.abs(a - b).mean())
transp = float((a[:, 3] == 0).mean())
log(f"VERIFICACIÓN diff(f_000, f_{mid:03d}) = {diff:.4f} -> {'OK' if diff > 0.01 else 'FALLO: cuadros idénticos'}")
log(f"VERIFICACIÓN píxeles transparentes en f_000 = {transp:.0%} -> {'OK' if transp > 0.2 else 'FALLO: fondo no transparente'}")
