"""Optional demo authoring: synthesize narration and measure its actual duration.

Requires edge-tts and imageio-ffmpeg. Sends the public demo script to Microsoft's
online speech service; not an application runtime dependency. Never clones a voice.
"""
import asyncio
import json
import re
import subprocess
from pathlib import Path
import edge_tts
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/narration'
VOICE='en-US-AndrewMultilingualNeural'

async def main():
    OUT.mkdir(exist_ok=True,parents=True)
    scenes=json.loads((ROOT/'docs/narration.json').read_text(encoding='utf-8'))
    semaphore=asyncio.Semaphore(3)
    async def prepare(scene):
        async with semaphore:
            target=OUT/(scene['id']+'.mp3')
            wav=OUT/(scene['id']+'.wav')
            fingerprint=OUT/(scene['id']+'.txt')
            identity=VOICE+'\n'+scene['text']
            if not target.exists() or not fingerprint.exists() or fingerprint.read_text(encoding='utf-8')!=identity:
                communicate=edge_tts.Communicate(scene['text'],VOICE,rate='+3%')
                await communicate.save(str(target))
                fingerprint.write_text(identity,encoding='utf-8')
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-i',str(target),'-ar','48000','-ac','1',str(wav)],check=True)
            import wave
            with wave.open(str(wav)) as audio:
                scene['duration']=audio.getnframes()/audio.getframerate()
            scene['audio']=str(wav.relative_to(ROOT))
            scene['voice']=VOICE
            print(f"{scene['id']}: {scene['duration']:.2f}s",flush=True)
    await asyncio.gather(*(prepare(scene) for scene in scenes))
    (OUT/'manifest.json').write_text(json.dumps(scenes,indent=2),encoding='utf-8')
    print(f"Narrated duration: {sum(s['duration'] for s in scenes):.2f}s; no padding",flush=True)

if __name__=='__main__':
    asyncio.run(main())
