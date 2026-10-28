#!/usr/bin/env python3
"""Cabeza 3D girando, de un modelo y un audio a un vídeo con transparencia.

Cada trabajo vive en su propia carpeta dentro de ~/Movies/cabeza3d/, así que
dos renders distintos nunca mezclan cuadros.

    python3 girar.py estreno --audio ~/Downloads/clip.m4a --dur 17
    python3 girar.py mudo --sin-audio --dur 16
    python3 girar.py prueba --audio voz.wav --calibrar

Dentro de la carpeta del trabajo quedan:
    audio.wav      el audio convertido (16 bits, mono)
    cuadros/       los PNG con fondo transparente
    salida.mov     ProRes 4444 con canal alfa, el que va al editor
    revisar.mp4    previsualización con fondo blanco y sonido
    log.txt        el diario del render
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cabeza.py")
BASE = os.path.expanduser("~/Movies/cabeza3d")


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit(f"\nFalló: {' '.join(str(c) for c in cmd[:3])}...")
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("nombre", help="nombre del trabajo; es la carpeta donde queda todo")
    p.add_argument("--audio", help="audio que mueve la boca (m4a, wav, mp3, mov...)")
    p.add_argument("--sin-audio", action="store_true", dest="mudo", help="boca quieta")
    p.add_argument("--dur", type=float, help="segundos de la vuelta completa; por defecto, lo que dure el audio")
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--res", type=int, default=800, help="píxeles de lado (800)")
    p.add_argument("--modelo", help="archivo .glb; por defecto el más reciente de ~/Downloads")
    p.add_argument("--calibrar", action="store_true", help="solo 4 imágenes de frente y perfil, en 5 segundos")
    # ajuste fino de la mandíbula
    p.add_argument("--corte", type=float, help="altura de la boca, fracción del busto (0.525)")
    p.add_argument("--barbilla", type=float, help="altura de la barbilla (0.39)")
    p.add_argument("--bisagra", type=float, help="profundidad de la bisagra (0.45)")
    p.add_argument("--apertura", type=float, help="apertura máxima en radianes (0.22)")
    p.add_argument("--rotulo", help="PNG con alfa: tira de texto que gira al revés alrededor")
    p.add_argument("--rotulo-alto", type=float, dest="rotulo_alto", help="altura del rótulo, fracción del busto (0.42)")
    p.add_argument("--rotulo-radio", type=float, dest="rotulo_radio", help="radio del rótulo, veces el ancho de la cabeza (1.45)")
    p.add_argument("--rotulo-veces", type=int, dest="rotulo_veces", help="veces que la tira da la vuelta; más veces, letra más chica (2)")
    p.add_argument("--rotulo-doble", action="store_true", dest="rotulo_doble", help="muestra también el texto del lado de atrás, reflejado")
    p.add_argument("--ladeo", type=float, help="grados de cabeza ladeada (-18)")
    p.add_argument("--giro", type=float, help="grados de cabeza girada; por defecto se mide sola")
    a = p.parse_args()

    if not a.audio and not a.mudo:
        sys.exit("Falta --audio, o --sin-audio si la boca no se mueve.")
    if not os.path.exists(BLENDER):
        sys.exit(f"No encuentro Blender en {BLENDER}")

    job = os.path.join(BASE, a.nombre)
    frames = os.path.join(job, "cuadros")
    os.makedirs(frames, exist_ok=True)
    # los cuadros viejos se borran: si el render nuevo es más corto, si no quedarían mezclados
    viejos = glob.glob(os.path.join(frames, "f_*.png"))
    for f in viejos:
        os.remove(f)
    if viejos:
        print(f"borrados {len(viejos)} cuadros del render anterior")

    env = dict(os.environ)
    env["FPS"], env["RES"] = str(a.fps), str(a.res)
    env["OUT"], env["LOG"] = frames, os.path.join(job, "log.txt")
    if a.modelo:
        env["GLB"] = os.path.abspath(os.path.expanduser(a.modelo))
    if a.calibrar:
        env["CALIB"] = "1"
    for clave, valor in (("JAW_Z", a.corte), ("CHIN_Z", a.barbilla), ("HINGE_Y", a.bisagra),
                         ("MAX_ANG", a.apertura), ("ROLL", a.ladeo), ("YAW", a.giro),
                         ("RING_Z", a.rotulo_alto), ("RING_R", a.rotulo_radio),
                         ("RING_REP", a.rotulo_veces)):
        if valor is not None:
            env[clave] = str(valor)
    if a.rotulo:
        rot = os.path.abspath(os.path.expanduser(a.rotulo))
        if not os.path.exists(rot):
            sys.exit(f"No existe el rótulo: {rot}")
        env["RING"] = rot
        if a.rotulo_doble:
            env["RING_DOBLE"] = "1"

    audio = None
    if a.mudo:
        env["MUTE"] = "1"
    else:
        origen = os.path.expanduser(a.audio)
        if not os.path.exists(origen):
            sys.exit(f"No existe el audio: {origen}")
        audio = os.path.join(job, "audio.wav")
        print(f"convirtiendo {os.path.basename(origen)} a 16 bits mono...")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", origen,
             "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", audio])
        env["AUDIO"] = audio
        if a.dur is None:   # la vuelta cierra justo cuando acaba el clip
            dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", audio], capture_output=True, text=True)
            a.dur = round(float(dur.stdout.strip()), 2)
            print(f"la vuelta durará lo que el audio: {a.dur}s")

    if a.dur is None:
        a.dur = 17
    env["N"] = str(round(a.dur * a.fps))

    t0 = time.time()
    print(f"renderizando {env['N']} cuadros a {a.res}px...")
    run([BLENDER, "--background", "--python", SCRIPT], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(env["LOG"]) as f:
        diario = f.read()
    for linea in diario.splitlines():
        if any(k in linea for k in ("giro de", "mandíbula", "rótulo", "audio:", "abierta", "VERIFICACIÓN", "ERROR")):
            print("  " + linea.split("] ", 1)[-1])

    if a.calibrar:
        print(f"\ncalibración en {frames}")
        return

    mov = os.path.join(job, "salida.mov")
    prev = os.path.join(job, "revisar.mp4")
    patron = os.path.join(frames, "f_%03d.png")
    print("exportando ProRes 4444 con alfa...")
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", patron,
         "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", mov])
    # previsualización: fondo blanco, porque el MP4 no admite transparencia
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", patron]
    if audio:
        cmd += ["-i", audio]
    cmd += ["-filter_complex", "[0]split[a][b];[a]drawbox=c=white:t=fill[bg];[bg][b]overlay,format=yuv420p[v]",
            "-map", "[v]"]
    if audio:
        cmd += ["-map", "1:a", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", prev]
    run(cmd)

    mb = os.path.getsize(mov) / 1e6
    print(f"\nlisto en {time.time() - t0:.0f}s")
    print(f"  {mov}  ({mb:.0f} MB, ProRes 4444 con alfa, {a.dur:g}s)")
    print(f"  {prev}  (para revisar; el fondo blanco es solo de esta copia)")


if __name__ == "__main__":
    main()
