# Harakiri ad factory

I co-wrote and star in *Harakiri, Me Haces Falta*, and we had no money for marketing. So I built a small pipeline to make our vertical ads. In each one, a 3D bust of a character turns slowly on a white background and talks in the actor's own voice, with a ring of text spinning around it. Then the trailer cuts in around that character, and the ad closes on where to watch the film.

The code here is the 3D part: from a `.glb` model and an audio file to a transparent video you can drop into any editor.

## How an ad gets made

1. **The bust.** I upload a photo of the actor to [Meshy](https://www.meshy.ai) and download the textured `.glb` it generates.
2. **The voice.** I transcribe the whole film with WhisperX, find the lines I want, and cut clean voice references with FFmpeg. New lines come from [Voicebox](https://github.com/jamiepine/voicebox), which clones a voice locally.
3. **The animation.** `blender/cabeza.py` runs inside Blender with no window. It imports the bust, cuts it at the mouth, rigs a jaw on a hinge and moves it with the loudness of the audio, frame by frame. Loudness can't tell two syllables apart, so it can also read a [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) curve. It renders transparent PNGs with Eevee.
4. **The export.** `blender/girar.py` wraps all of that in one command. Each job gets its own folder with the audio, the frames, a ProRes 4444 file with alpha for the editor, and a preview on white with sound.
5. **The edit.** I put the bust, the trailer cut and the character's song together by hand. I tried automating this step too, but the result felt mechanical.

## Run it

You need [Blender](https://www.blender.org/download/) and FFmpeg (`brew install ffmpeg` on a Mac). On macOS the script finds Blender in `/Applications`. Anywhere else, set `BLENDER` to its path.

```bash
# a test: front and profile, mouth closed and open
python3 blender/girar.py prueba --modelo busto.glb --audio voz.wav --calibrar

# the real render, with a strip of text (a PNG with transparency) turning around the head
python3 blender/girar.py taxista --modelo busto.glb --audio voz.m4a --rotulo anillo.png

# other options: jaw opening, cut height, turn speed, text size...
python3 blender/girar.py --help
```

Results go to `~/Movies/cabeza3d/<job name>/`. If you leave out `--modelo`, it uses the newest `.glb` in `~/Downloads`.

The jaw opens up to 0.15 radians. I chose that by comparing 0.11, 0.15 and 0.22 on the same audio; at 0.22 the jaw looked like it was falling off. Change it with `--apertura`.

The code comments are in Spanish.
