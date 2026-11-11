"""Produce a vertical Shorts upload from an exact, audio-assessed source.

The source is verified before this function runs. The audio stream is copied,
not mixed, muted or altered. Encoding errors and videos exceeding 3 minutes are
blocked, never silently shortened. Preserve the whole landscape scene with a
blurred portrait background rather than cropping important footage.
"""
import json, math, os, subprocess, tempfile
from pathlib import Path

SHORTS_FORMAT='vertical_720x1280_v1'
def render_short(data):
    if not isinstance(data,bytes) or not data:
        raise ValueError('missing source video')
    with tempfile.TemporaryDirectory(prefix='shorts-render-') as d:
        os.chmod(d,0o700)
        src=Path(d)/'source.mp4'; dst=Path(d)/'short.mp4'
        src.write_bytes(data); os.chmod(src,0o600)
        def probe(path):
            raw=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height,codec_name','-of','json',str(path)],capture_output=True,check=True,timeout=45)
            return json.loads(raw.stdout)
        info=probe(src)
        duration=float(info.get('format',{}).get('duration',0))
        streams=info.get('streams',[])
        if not math.isfinite(duration) or duration<=0 or duration>180 or not any(x.get('codec_type')=='video' for x in streams):
            raise ValueError('source exceeds Shorts duration or lacks video')
        # First stream is selected explicitly, just as its audio assessment probes.
        vf='[0:v:0]split=2[bg][fg];[bg]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=20:2[background];[fg]scale=720:1280:force_original_aspect_ratio=decrease[foreground];[background][foreground]overlay=(W-w)/2:(H-h)/2,setsar=1[v]'
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(src),'-filter_complex',vf,'-map','[v]','-map','0:a:0?','-map_metadata','-1','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(dst)],check=True,timeout=240,capture_output=True)
        result=probe(dst); outduration=float(result.get('format',{}).get('duration',0)); outstreams=result.get('streams',[])
        video=next((s for s in outstreams if s.get('codec_type')=='video'),None)
        oldaudio=[s for s in streams if s.get('codec_type')=='audio']; newaudio=[s for s in outstreams if s.get('codec_type')=='audio']
        if not video or (video.get('width'),video.get('height')) != (720,1280) or outduration<=0 or outduration>180 or abs(outduration-duration)>0.25:
            raise ValueError('rendered Shorts dimensions or duration invalid')
        if bool(oldaudio)!=bool(newaudio) or (oldaudio and oldaudio[0].get('codec_name')!=newaudio[0].get('codec_name')):
            raise ValueError('original audio missing or changed')
        return dst.read_bytes()
