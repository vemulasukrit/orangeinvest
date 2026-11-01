"""Record real UI actions paced to narration. No target-duration padding.
Optional: playwright, edge-tts, imageio-ffmpeg; installed Chrome.
Run prepare_narration.py first. Recording uses its own temporary database.
"""
import json
from contextlib import ExitStack
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
import imageio_ffmpeg
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from errand.agent import Agent
from server import handler
OUT = ROOT / 'output'


def record(dry_run=False):
    scenes = json.loads((OUT / 'narration/manifest.json').read_text())
    timeline = []
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as cleanup, sync_playwright() as p:
        agent = Agent(str(Path(tmp) / 'demo.db'))
        http = ThreadingHTTPServer(('127.0.0.1', 0), handler(agent))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        cleanup.callback(agent.close)
        cleanup.callback(http.server_close)
        cleanup.callback(http.shutdown)
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000}, record_video_dir=str(OUT / 'recordings/v2'), record_video_size={'width':1440,'height':1000})
        capture_start = time.monotonic()
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{http.server_port}')
        page.wait_for_function('state !== null')
        errors = []
        page.on('pageerror',lambda error:errors.append(str(error)))

        def overlay(title):
            page.evaluate('''title => {
                let label=document.querySelector('#chapter');
                if(!label){label=document.createElement('div');label.id='chapter';document.body.append(label);}
                Object.assign(label.style,{position:'fixed',top:'156px',right:'140px',maxWidth:'460px',padding:'10px 18px',borderRadius:'24px',background:'#242426',color:'#fff',font:'13px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',zIndex:100,pointerEvents:'none',boxShadow:'0 4px 20px #0001'});
                label.textContent=title;
                label.animate([{opacity:0},{opacity:1}],{duration:220});
                if(!document.querySelector('#demo-pointer')){
                    let dot=document.createElement('div');dot.id='demo-pointer';Object.assign(dot.style,{position:'fixed',width:'14px',height:'14px',borderRadius:'50%',border:'2px solid white',background:'#29292d',boxShadow:'0 1px 5px #0005',pointerEvents:'none',zIndex:101,left:'720px',top:'180px'});document.body.append(dot);
                    document.addEventListener('mousemove',e=>{dot.style.left=(e.clientX-7)+'px';dot.style.top=(e.clientY-7)+'px';});
                    document.addEventListener('mousedown',()=>dot.animate([{transform:'scale(1)'},{transform:'scale(1.8)',opacity:.4},{transform:'scale(1)',opacity:1}],{duration:300}));
                }
            }''',title)

        def point(locator):
            locator.scroll_into_view_if_needed()
            box=locator.bounding_box()
            if box: page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2,steps=18)

        def click(locator):
            point(locator)
            locator.click()
            page.wait_for_function('!busy')

        def button(name): return page.get_by_role('button',name=name,exact=True)
        def fill(selector,value):
            loc=page.locator(selector);click(loc);loc.fill(value)
        def close(): click(page.locator('#close-panel'))
        def show_trace(name):
            item=page.locator('.trace-item').filter(has=page.locator('.trace-name',has_text=name)).first
            item.scroll_into_view_if_needed()
            if item.get_attribute('open') is None: item.locator('summary').click()
            point(item.locator('summary'))

        def run(scene,actions):
            overlay(scene['title'])
            started=time.monotonic()
            timeline.append({**scene,'start':started-capture_start})
            print(scene['id'],flush=True)
            for fraction,action in actions:
                delay=started+scene['duration']*fraction-time.monotonic()
                if delay>0 and not dry_run: page.wait_for_timeout(delay*1000)
                action()
            remaining=started+scene['duration']-time.monotonic()
            if remaining>0 and not dry_run:page.wait_for_timeout(remaining*1000)
            timeline[-1]['end']=time.monotonic()-capture_start

        def send_request():
            click(page.locator('#composer-input'))
            page.locator('#composer-input').press_sequentially('Find a plumber in Indiranagar tomorrow morning, under ₹1,500.',delay=24)
            click(button('Send request'))
            expect(page.locator('.provider').first).to_be_visible()
        def correct():
            click(page.locator('[data-action=edit]').first)
            fill('#edit-form [name=budget]','1200')
        def approve():
            click(page.locator('#side-panel [data-action=approve]'))
            expect(page.locator('.receipt-status')).to_contain_text('Booking confirmed')
        def repeat():
            fill('#composer-input','yes');click(button('Send request'))
            expect(page.locator('#booking-count')).to_have_text('1')
        def reload():
            page.reload();page.wait_for_function('state !== null');overlay(scenes[7]['title'])
            expect(page.locator('#booking-count')).to_have_text('1')
        def cancel():
            click(button('Confirm cancellation'))
            expect(page.locator('.receipt-status')).to_contain_text('Cancellation confirmed')
        run(scenes[0],[(.18,lambda:point(page.locator('#composer-input'))),(.5,lambda:point(page.locator('#ticket'))),(.78,lambda:point(page.locator('.journey')))])
        run(scenes[1],[(.02,send_request),(.5,lambda:point(page.locator('.ticket-facts'))),(.76,lambda:point(page.locator('.provider').first.locator('h3')))])
        run(scenes[2],[(.05,correct),(.25,lambda:click(button('Update my request'))),(.52,lambda:point(page.locator('.ticket-facts'))),(.8,lambda:point(page.locator('.provider').first))])
        run(scenes[3],[(.05,lambda:point(page.locator('.provider').first)),(.22,lambda:click(page.locator('.provider details').first.locator('summary'))),(.4,lambda:point(page.locator('.provider details').first)),(.84,lambda:point(page.get_by_role('button',name='Your errands',exact=False).first))])
        run(scenes[4],[(.02,lambda:click(page.locator('[data-select-provider]').first)),(.25,lambda:point(page.locator('.ticket-facts'))),(.5,lambda:point(page.locator('.ticket-total'))),(.78,lambda:point(page.locator('#approve-button')))])
        run(scenes[5],[(.02,lambda:click(button('Activity'))),(.15,lambda:page.locator('#scenario-select').select_option('timeout_after_success')),(.23,lambda:click(button('Use this scenario'))),(.6,lambda:point(page.locator('.inspector-approval')))])
        run(scenes[6],[(.01,approve),(.17,lambda:show_trace('book')),(.4,lambda:show_trace('get_booking_status')),(.69,close),(.83,lambda:point(page.locator('.ticket-total')))])
        run(scenes[7],[(.05,repeat),(.22,reload),(.38,lambda:point(page.locator('#booking-count'))),(.65,lambda:point(page.locator('.receipt-id')))])
        run(scenes[8],[(.01,lambda:click(page.get_by_role('button',name='Your errands',exact=False).first)),(.09,lambda:click(button('Cancel this errand'))),(.3,lambda:point(button('Confirm cancellation'))),(.4,cancel),(.61,lambda:click(button('Activity'))),(.72,lambda:show_trace('cancel'))])
        run(scenes[9],[(.01,close),(.05,lambda:click(button('Memory'))),(.12,lambda:fill('#memory-form [name=value]','Whitefield')),(.2,lambda:click(button('Save preference'))),(.32,lambda:point(page.locator('.memory-badge').last)),(.4,lambda:click(button('Correct'))),(.47,lambda:fill('#memory-form [name=value]','Indiranagar')),(.53,lambda:click(button('Save preference'))),(.68,lambda:click(button('Forget')))])
        run(scenes[10],[(.02,close),(.25,lambda:point(page.locator('.receipt-status'))),(.55,lambda:point(page.locator('.journey')))])
        assert not errors,errors
        timeline[-1]['end']=time.monotonic()-capture_start
        video=page.video
        context.close();video.save_as(str(OUT/'recordings/raw-v2.webm'))
        browser.close()
    (OUT/'narration/timeline.json').write_text(json.dumps(timeline,indent=2))
    if not dry_run: assemble(timeline)


def assemble(timeline):
    rate=48000
    origin=timeline[0]['start']
    duration=timeline[-1]['end']-origin
    pcm=bytearray(round(duration*rate)*2)
    for scene in timeline:
        with wave.open(str(ROOT/scene['audio']),'rb') as audio:
            assert audio.getframerate()==rate and audio.getnchannels()==1
            data=audio.readframes(audio.getnframes())
        offset=round((scene['start']-origin)*rate)*2
        pcm[offset:offset+len(data)]=data
    wav=OUT/'narration/full.wav'
    with wave.open(str(wav),'wb') as audio:
        audio.setparams((1,2,rate,0,'NONE','not compressed'));audio.writeframes(pcm)
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg,'-y','-ss',str(origin),'-i',str(OUT/'recordings/raw-v2.webm'),'-i',str(wav),'-t',str(duration),'-map','0:v','-map','1:a','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(OUT/'demo.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Keep the previous shared filename useful, now with the same narration.
    subprocess.run([ffmpeg,'-y','-i',str(OUT/'demo.mp4'),'-c:v','libvpx','-deadline','realtime','-cpu-used','8','-b:v','1400k','-c:a','libopus','-b:a','96k',str(OUT/'demo.webm')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print(f'Created voiced MP4 and WebM: {duration:.2f}s, actual narration pacing.',flush=True)

if __name__=='__main__':record('--dry-run' in sys.argv)
