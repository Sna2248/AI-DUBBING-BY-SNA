"""AI Video Dubbing & Vocal Isolation Studio.

A single Streamlit pipeline for media acquisition, subtitle acquisition/editing,
Demucs vocal removal, Khmer Edge TTS, timed audio mixing, and final muxing.
Only process media you own or are authorized to use. DRM and access controls are
not bypassed.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

try:
    import edge_tts
except ImportError:
    edge_tts = None
try:
    import pysrt
except ImportError:
    pysrt = None
try:
    import webvtt
except ImportError:
    webvtt = None
try:
    import yt_dlp
except ImportError:
    yt_dlp = None
try:
    import torch
except ImportError:
    torch = None

APP_NAME = "AI Video Dubbing & Vocal Isolation Studio"
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
SUB_EXTS = {".srt", ".vtt"}
PROJECT_ROOT = Path(tempfile.gettempdir()) / "ai_dubbing_studio_projects"
MAX_UPLOAD_MB_DEFAULT = 2048
MAX_DOWNLOAD_MB_DEFAULT = 4096
SUBPROCESS_TIMEOUT_DEFAULT = 7200
VOICES = {"Sreymom (Khmer, Female)": "km-KH-SreymomNeural", "Piseth (Khmer, Male)": "km-KH-PisethNeural"}
STEPS = ["Add Video or Media", "Obtain Subtitles", "Review and Edit Subtitles", "Extract and Separate Audio", "Generate AI Voice", "Mix Audio", "Render Final Video", "Preview and Download"]
STATUS_ICONS = {"Not started": "⚪", "Processing": "🔵", "Completed": "🟢", "Failed": "🔴"}

TEXT = {
    "English": {"start":"Start Complete Processing", "advanced":"Advanced Mode", "simple":"Simple Mode", "upload":"Upload File", "link":"Paste Link", "clear":"Clear All Project Data", "logs":"Technical Logs", "source":"Subtitle Source", "review":"Subtitle Review and Editing"},
    "ខ្មែរ": {"start":"ចាប់ផ្តើមដំណើរការទាំងមូល", "advanced":"របៀបកម្រិតខ្ពស់", "simple":"របៀបសាមញ្ញ", "upload":"បញ្ចូល File", "link":"ដាក់ Link", "clear":"សម្អាតទិន្នន័យ Project", "logs":"កំណត់ហេតុបច្ចេកទេស", "source":"ប្រភព Subtitle", "review":"ពិនិត្យ និងកែ Subtitle"},
}

@dataclass
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str
    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    frame_rate: float
    video_codec: str
    audio_codec: str
    sample_rate: int
    channels: int
    has_video: bool
    has_audio: bool
    subtitle_streams: list[dict[str, Any]]

@dataclass
class Settings:
    processor: str = "auto"
    demucs_model: str = "htdemucs"
    four_stems: bool = False
    voice: str = "km-KH-SreymomNeural"
    sync_mode: str = "smart"
    max_tempo: float = 1.65
    background_volume: float = 1.0
    voice_volume: float = 1.2
    ducking: bool = False
    duck_db: float = 8.0
    fade_ms: int = 120
    crf: int = 18
    preset: str = "medium"
    subtitle_mode: str = "none"
    duration_policy: str = "match"
    sample_rate: int = 48000
    subprocess_timeout: int = SUBPROCESS_TIMEOUT_DEFAULT

class PipelineError(RuntimeError):
    pass

class TTSProvider:
    async def synthesize(self, text: str, voice: str, output: Path) -> None:
        raise NotImplementedError

class EdgeTTSProvider(TTSProvider):
    async def synthesize(self, text: str, voice: str, output: Path) -> None:
        if edge_tts is None:
            raise PipelineError("edge-tts is not installed.")
        await edge_tts.Communicate(text=text, voice=voice).save(str(output))

class APIBasedTTSProvider(TTSProvider):
    async def synthesize(self, text: str, voice: str, output: Path) -> None:
        raise PipelineError("External TTS provider is not configured. Configure a provider before selecting it.")

def init_state() -> None:
    defaults = {
        "language":"English", "interface_mode":"Simple", "project_dir":None,
        "source_media":None, "original_video":None, "original_audio":None,
        "subtitle_srt":None, "subtitle_cues":[], "isolated_vocals":None,
        "background_audio":None, "generated_ai_voice":None,
        "final_mixed_audio":None, "final_video":None, "media_info":None,
        "output_dir":None, "persisted_final_video":None,
        "source_url":"", "url_info":None, "logs":[], "settings":{},
        "signatures":{}, "tts_report":{}, "translated_srt_loaded":False,
        "pipeline_status":{step:"Not started" for step in STEPS},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def log(message: str) -> None:
    safe = re.sub(r"(?i)(api[_ -]?key|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", str(message))
    st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] {safe}")
    st.session_state.logs = st.session_state.logs[-1000:]

def set_status(step: int, status: str) -> None:
    st.session_state.pipeline_status[STEPS[step-1]] = status

def sanitize_filename(name: str, fallback: str = "media") -> str:
    stem = Path(name).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._")[:100]
    return stem or fallback

def valid_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except ValueError:
        return False

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def signature(*items: Any) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()

def ensure_project(media_hash: str) -> Path:
    path = PROJECT_ROOT / media_hash[:20]
    path.mkdir(parents=True, exist_ok=True)
    st.session_state.project_dir = str(path)
    return path

def run_cmd(cmd: list[str], timeout: int, purpose: str) -> subprocess.CompletedProcess[str]:
    log("COMMAND: " + " ".join(cmd))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"{purpose} timed out after {timeout} seconds.") from exc
    if cp.stdout: log(cp.stdout[-8000:])
    if cp.stderr: log(cp.stderr[-12000:])
    if cp.returncode:
        raise PipelineError(f"{purpose} failed (exit {cp.returncode}).\n{cp.stderr[-5000:]}")
    return cp

def ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value: raise PipelineError("FFmpeg was not found in PATH.")
    return value

def ffprobe() -> str:
    value = shutil.which("ffprobe")
    if not value: raise PipelineError("FFprobe was not found in PATH.")
    return value

def rational(value: str) -> float:
    try:
        a, b = value.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        try: return float(value)
        except Exception: return 0.0

def probe_media(path: Path, timeout: int = 60) -> MediaInfo:
    cp = run_cmd([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], timeout, "Media inspection")
    data = json.loads(cp.stdout)
    streams = data.get("streams", [])
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    audio = next((x for x in streams if x.get("codec_type") == "audio"), {})
    subs = [{"index":x.get("index"), "codec":x.get("codec_name", ""), "language":x.get("tags",{}).get("language","und"), "title":x.get("tags",{}).get("title","")} for x in streams if x.get("codec_type") == "subtitle"]
    return MediaInfo(float(data.get("format",{}).get("duration") or 0), int(video.get("width") or 0), int(video.get("height") or 0), rational(video.get("avg_frame_rate","0/1")), video.get("codec_name", ""), audio.get("codec_name", ""), int(audio.get("sample_rate") or 0), int(audio.get("channels") or 0), bool(video), bool(audio), subs)

def prepare_uploaded(upload, max_mb: int) -> Path:
    suffix = Path(upload.name).suffix.lower()
    if suffix not in MEDIA_EXTS: raise PipelineError("Unsupported media type.")
    if upload.size > max_mb * 1024 * 1024: raise PipelineError(f"Upload exceeds {max_mb} MB.")
    data = upload.getvalue()
    media_hash = hashlib.sha256(data).hexdigest()
    root = ensure_project(media_hash)
    target = root / f"source{suffix}"
    if not target.exists() or target.stat().st_size != len(data): target.write_bytes(data)
    register_media(target)
    return target

def ytdlp_progress(d: dict[str, Any]) -> None:
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        got = d.get("downloaded_bytes") or 0
        st.session_state["download_fraction"] = min(1.0, got / total) if total else 0.0

def download_media(url: str, max_mb: int, timeout: int) -> Path:
    if yt_dlp is None: raise PipelineError("yt-dlp is not installed.")
    if not valid_url(url): raise PipelineError("Enter a valid http:// or https:// URL.")
    root = PROJECT_ROOT / ("url_" + hashlib.sha256(url.encode()).hexdigest()[:20]); root.mkdir(parents=True, exist_ok=True)
    opts = {"format":"bestvideo*+bestaudio/best", "outtmpl":str(root / "download.%(ext)s"), "merge_output_format":"mkv", "noplaylist":True, "playlist_items":"1", "restrictfilenames":True, "socket_timeout":30, "retries":3, "progress_hooks":[ytdlp_progress], "max_filesize":max_mb*1024*1024, "quiet":True, "no_warnings":True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            st.session_state.url_info = info
    except Exception as exc:
        raise PipelineError(f"Download failed. Protected, private, DRM-controlled, or unauthorized media is not supported.\n{exc}") from exc
    files = [p for p in root.iterdir() if p.is_file() and p.suffix not in {".part", ".ytdl", ".json"}]
    if not files: raise PipelineError("yt-dlp completed but no media file was found.")
    target = max(files, key=lambda p:p.stat().st_size)
    if target.stat().st_size > max_mb*1024*1024: raise PipelineError("Downloaded media exceeds configured limit.")
    register_media(target)
    return target

def register_media(path: Path) -> None:
    info = probe_media(path)
    if not info.has_audio: raise PipelineError("The media has no readable audio stream.")
    st.session_state.source_media = str(path)
    st.session_state.original_video = str(path) if info.has_video else None
    st.session_state.media_info = asdict(info)
    st.session_state.signatures["media_signature"] = hash_file(path)
    set_status(1, "Completed")

def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try: return data.decode(enc)
        except UnicodeError: pass
    return data.decode("utf-8", errors="replace")

def ms_from_stamp(value: str) -> int:
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*", value)
    if not m: raise ValueError(f"Invalid timestamp: {value}")
    h, minute, sec, milli = m.groups()
    return ((int(h or 0)*60+int(minute))*60+int(sec))*1000+int(milli.ljust(3,"0")[:3])

def stamp(ms: int, vtt: bool = False) -> str:
    ms=max(0,int(ms)); h, rem=divmod(ms,3600000); m,rem=divmod(rem,60000); s,x=divmod(rem,1000)
    return f"{h:02d}:{m:02d}:{s:02d}{'.' if vtt else ','}{x:03d}"

def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(text)))
    return re.sub(r"\s+", " ", text).strip()

def parse_subtitles(content: str, ext: str) -> list[Cue]:
    cues: list[Cue] = []
    if ext == ".srt":
        blocks = re.split(r"\n\s*\n", content.replace("\r\n","\n").strip())
        for block in blocks:
            lines=block.splitlines(); timing=next((i for i,x in enumerate(lines) if "-->" in x),None)
            if timing is None: continue
            a,b=[x.strip().split()[0] for x in lines[timing].split("-->",1)]
            text=clean_text(" ".join(lines[timing+1:]))
            if text: cues.append(Cue(len(cues)+1, ms_from_stamp(a), ms_from_stamp(b), text))
    elif ext == ".vtt":
        content=re.sub(r"^WEBVTT.*?(?:\n\s*\n|$)","",content,flags=re.S)
        for block in re.split(r"\n\s*\n",content):
            lines=block.splitlines(); timing=next((i for i,x in enumerate(lines) if "-->" in x),None)
            if timing is None: continue
            a,b=[x.strip().split()[0] for x in lines[timing].split("-->",1)]
            text=clean_text(" ".join(lines[timing+1:]))
            if text: cues.append(Cue(len(cues)+1,ms_from_stamp(a),ms_from_stamp(b),text))
    else: raise PipelineError("Only SRT and VTT subtitles are supported.")
    return validate_cues(cues, fail=True)

def validate_cues(cues: Iterable[Cue], fail: bool=False) -> list[Cue]:
    result=[]; errors=[]; previous_end=-1
    for n,c in enumerate(sorted(cues,key=lambda x:x.start_ms),1):
        text=clean_text(c.text)
        if not text: errors.append(f"Cue {n}: empty text")
        if c.end_ms <= c.start_ms: errors.append(f"Cue {n}: end must be after start")
        if c.start_ms < previous_end: errors.append(f"Cue {n}: overlaps previous cue")
        if 0 < c.end_ms-c.start_ms < 250: errors.append(f"Cue {n}: duration below 250 ms")
        if len(text)>120: errors.append(f"Cue {n}: text is very long")
        result.append(Cue(n,max(0,int(c.start_ms)),int(c.end_ms),text)); previous_end=max(previous_end,c.end_ms)
    st.session_state["subtitle_warnings"] = errors
    fatal=[x for x in errors if "empty" in x or "end must" in x]
    if fail and (not result or fatal): raise PipelineError("Invalid subtitles:\n"+"\n".join(fatal or ["No cues found."]))
    return result

def cues_to_srt(cues: Iterable[Cue]) -> str:
    return "\n\n".join(f"{i}\n{stamp(c.start_ms)} --> {stamp(c.end_ms)}\n{c.text}" for i,c in enumerate(cues,1))+"\n"

def save_cues(cues: list[Cue]) -> Path:
    project_value = st.session_state.get("project_dir")
    if project_value:
        root = Path(project_value)
    else:
        seed = st.session_state.get("signatures", {}).get("media_signature") or hashlib.sha256(str(time.time_ns()).encode()).hexdigest()
        root = ensure_project(seed)
    root.mkdir(parents=True, exist_ok=True)
    path=root/"final_subtitles.srt"
    path.write_text(cues_to_srt(cues),encoding="utf-8")
    st.session_state.subtitle_cues=[asdict(c) for c in cues]; st.session_state.subtitle_srt=str(path)
    st.session_state.signatures["subtitle_signature"]=signature(st.session_state.signatures.get("media_signature"),st.session_state.subtitle_cues)
    set_status(2,"Completed"); set_status(3,"Completed"); return path

def extract_embedded(stream_index: int, timeout: int) -> Path:
    source=Path(st.session_state.source_media); out=Path(st.session_state.project_dir)/"embedded.srt"
    run_cmd([ffmpeg(),"-y","-i",str(source),"-map",f"0:{stream_index}","-c:s","srt",str(out)],timeout,"Embedded subtitle extraction")
    cues=parse_subtitles(out.read_text(encoding="utf-8",errors="replace"),".srt"); return save_cues(cues)

def list_online_subtitles(url: str) -> dict[str, Any]:
    if yt_dlp is None: raise PipelineError("yt-dlp is not installed.")
    with yt_dlp.YoutubeDL({"skip_download":True,"noplaylist":True,"quiet":True,"no_warnings":True}) as ydl: info=ydl.extract_info(url,download=False)
    st.session_state.url_info=info
    return {"manual":info.get("subtitles",{}),"automatic":info.get("automatic_captions",{})}

def download_online_subtitle(url: str, lang: str, prefer_manual: bool, timeout: int) -> Path:
    root=Path(st.session_state.project_dir); template=str(root/"online.%(ext)s")
    opts={"skip_download":True,"noplaylist":True,"writesubtitles":prefer_manual,"writeautomaticsub":not prefer_manual,"subtitleslangs":[lang],"subtitlesformat":"srt/vtt/best","outtmpl":template,"quiet":True,"no_warnings":True}
    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
    files=list(root.glob("online*.srt"))+list(root.glob("online*.vtt"))
    if not files and prefer_manual: return download_online_subtitle(url,lang,False,timeout)
    if not files: raise PipelineError("No selected subtitle was downloaded. Use AI transcription.")
    p=files[0]; cues=parse_subtitles(decode_text(p.read_bytes()),p.suffix.lower()); return save_cues(cues)

def transcribe_local(model_name: str, language: Optional[str], word_ts: bool, vad: bool, beam: int, prompt: str, translate: bool) -> Path:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError("faster-whisper មិនទាន់បានដំឡើង។ រត់: pip install faster-whisper") from exc
    source_value = st.session_state.get("original_audio") or st.session_state.get("source_media")
    if not source_value:
        raise PipelineError("រកមិនឃើញ Source Audio។ សូមចុច Prepare uploaded media មុន។")
    source = Path(source_value)
    if not source.exists():
        raise PipelineError(f"Source Audio មិនមាននៅទីតាំង៖ {source}")
    project_value = st.session_state.get("project_dir")
    if not project_value:
        project = ensure_project(hash_file(source))
    else:
        project = Path(project_value)
        project.mkdir(parents=True, exist_ok=True)
    st.session_state.project_dir = str(project)
    selected_language = (language or "").strip()
    whisper_language = None if not selected_language or selected_language.lower() in {"auto", "auto detect"} else selected_language
    cuda=bool(torch and torch.cuda.is_available())
    device="cuda" if cuda else "cpu"
    compute="float16" if cuda else "int8"
    log(f"faster-whisper: model={model_name}, device={device}, compute={compute}, source={source.name}")
    try:
        model=WhisperModel(model_name,device=device,compute_type=compute)
        segments,_=model.transcribe(str(source),language=whisper_language,word_timestamps=word_ts,vad_filter=vad,beam_size=beam,initial_prompt=prompt or None,task="translate" if translate else "transcribe")
    except Exception as exc:
        log(f"faster-whisper error: {type(exc).__name__}: {exc}")
        raise PipelineError(f"faster-whisper មិនអាចដំណើរការ៖ {type(exc).__name__}: {exc}") from exc
    cues=[]
    for seg in segments:
        text=clean_text(seg.text)
        if not text: continue
        start=int(seg.start*1000); end=max(start+300,int(seg.end*1000))
        if len(text)<=100: cues.append(Cue(len(cues)+1,start,end,text))
        else:
            parts=re.split(r"(?<=[.!?។៕])\s+",text)
            for part in parts:
                ratio=len(part)/max(1,len(text)); duration=max(300,int((end-start)*ratio)); s=start if not cues or cues[-1].end_ms<=start else cues[-1].end_ms; cues.append(Cue(len(cues)+1,s,min(end,s+duration),part))
    return save_cues(validate_cues(cues,fail=True))

def extract_audio(settings: Settings) -> Path:
    source_value = st.session_state.get("source_media")
    if not source_value:
        raise PipelineError("រកមិនឃើញ Media។ សូមចុច Prepare uploaded media មុន។")
    source = Path(source_value)
    if not source.exists():
        raise PipelineError(f"Media file មិនមាន៖ {source}")
    project_value = st.session_state.get("project_dir")
    root = Path(project_value) if project_value else ensure_project(hash_file(source))
    root.mkdir(parents=True, exist_ok=True)
    st.session_state.project_dir = str(root)
    out=root/"original_audio.wav"
    run_cmd([ffmpeg(),"-y","-i",str(source),"-vn","-c:a","pcm_s24le","-ar",str(settings.sample_rate),"-ac","2",str(out)],settings.subprocess_timeout,"Audio extraction")
    if not out.exists() or not out.stat().st_size: raise PipelineError("Extracted audio was not created.")
    st.session_state.original_audio=str(out); return out

def demucs_models() -> list[str]:
    return ["htdemucs","htdemucs_ft","htdemucs_6s","mdx_extra","mdx_extra_q"]

def separate_audio(settings: Settings) -> tuple[Path,Path]:
    original=extract_audio(settings); outroot=Path(st.session_state.project_dir)/"demucs"
    device=("cuda" if torch and torch.cuda.is_available() else "cpu") if settings.processor=="auto" else settings.processor
    cmd=[sys.executable,"-m","demucs","--name",settings.demucs_model,"--device",device,"--out",str(outroot)]
    if not settings.four_stems: cmd.append("--two-stems=vocals")
    cmd.append(str(original)); run_cmd(cmd,settings.subprocess_timeout,"Demucs separation")
    folder=outroot/settings.demucs_model/original.stem; vocals=folder/"vocals.wav"
    if settings.four_stems:
        bg=Path(st.session_state.project_dir)/"background_audio.wav"
        run_cmd([ffmpeg(),"-y","-i",str(folder/"drums.wav"),"-i",str(folder/"bass.wav"),"-i",str(folder/"other.wav"),"-filter_complex","amix=inputs=3:normalize=0,alimiter=limit=0.98","-c:a","pcm_s24le",str(bg)],settings.subprocess_timeout,"Stem recombination")
    else: bg=folder/"no_vocals.wav"
    if not vocals.exists() or not bg.exists(): raise PipelineError(f"Expected Demucs output missing: {folder}")
    st.session_state.isolated_vocals=str(vocals); st.session_state.background_audio=str(bg)
    st.session_state.signatures["separation_signature"]=signature(hash_file(original),settings.demucs_model,settings.processor,settings.four_stems)
    set_status(4,"Completed"); return vocals,bg

def atempo_chain(tempo: float) -> str:
    values=[]
    while tempo>2.0: values.append(2.0); tempo/=2.0
    while tempo<0.5: values.append(0.5); tempo/=0.5
    values.append(tempo)
    return ",".join(f"atempo={x:.8f}" for x in values)

def trim_silence(audio: AudioSegment) -> AudioSegment:
    ranges=detect_nonsilent(audio,min_silence_len=80,silence_thresh=-42)
    if not ranges: return audio
    return audio[max(0,ranges[0][0]-30):min(len(audio),ranges[-1][1]+30)]

def fit_clip(path: Path, duration: int, settings: Settings, work: Path) -> tuple[AudioSegment,dict[str,bool]]:
    clip=trim_silence(AudioSegment.from_file(path).set_frame_rate(24000).set_channels(1).set_sample_width(2)); info={"accelerated":False,"trimmed":False,"extreme":False}
    if settings.sync_mode=="preserve": return clip,info
    if settings.sync_mode=="strict": info["trimmed"]=len(clip)>duration; return clip[:duration],info
    if len(clip)>duration:
        required=len(clip)/max(1,duration); tempo=min(required,settings.max_tempo); info.update(accelerated=True,extreme=required>settings.max_tempo)
        src=work/"fit_in.wav"; dst=work/"fit_out.wav"; clip.export(src,format="wav")
        run_cmd([ffmpeg(),"-y","-i",str(src),"-filter:a",atempo_chain(tempo),"-ar","24000","-ac","1",str(dst)],settings.subprocess_timeout,"Speech timing")
        clip=AudioSegment.from_file(dst)
        if len(clip)>duration: clip=clip[:duration].fade_out(min(40,duration//5)); info["trimmed"]=True
    return clip,info

def generate_tts(settings: Settings, retry_indexes: Optional[set[int]]=None) -> Path:
    cues=[Cue(**x) for x in st.session_state.subtitle_cues]; root=Path(st.session_state.project_dir); clips=root/"tts_clips"; clips.mkdir(exist_ok=True)
    provider=EdgeTTSProvider(); report={"total":len(cues),"success":0,"failed":0,"accelerated":0,"trimmed":0,"extreme":0,"failed_indexes":[]}; overlays=[]; end=max(c.end_ms for c in cues)
    async def synth_all() -> None:
        nonlocal end
        for cue in cues:
            raw=clips/f"cue_{cue.index:05d}.mp3"
            if retry_indexes is None or cue.index in retry_indexes or not raw.exists():
                try: await provider.synthesize(cue.text,settings.voice,raw)
                except Exception as exc: report["failed"]+=1; report["failed_indexes"].append(cue.index); log(f"TTS cue {cue.index}: {exc}"); continue
            try:
                with tempfile.TemporaryDirectory() as td: fitted,info=fit_clip(raw,cue.duration_ms,settings,Path(td))
                overlays.append((cue.start_ms,fitted)); end=max(end,cue.start_ms+len(fitted)); report["success"]+=1
                for k in ("accelerated","trimmed","extreme"): report[k]+=int(info[k])
            except Exception as exc: report["failed"]+=1; report["failed_indexes"].append(cue.index); log(f"TTS cue {cue.index}: {exc}")
    asyncio.run(synth_all())
    if not overlays: raise PipelineError("All TTS cues failed.")
    track=AudioSegment.silent(duration=end,frame_rate=24000).set_channels(1).set_sample_width(2)
    for pos,clip in overlays: track=track.overlay(clip,position=pos)
    out=root/"generated_ai_voice.wav"; track.export(out,format="wav"); report["duration_seconds"]=len(track)/1000
    st.session_state.generated_ai_voice=str(out); st.session_state.tts_report=report
    st.session_state.signatures["tts_signature"]=signature(st.session_state.signatures.get("subtitle_signature"),settings.voice,settings.sync_mode,settings.max_tempo)
    set_status(5,"Completed"); return out

def activity_expression(cues: list[Cue]) -> str:
    pieces=[f"between(t,{c.start_ms/1000:.3f},{c.end_ms/1000:.3f})" for c in cues]
    return "+".join(pieces) or "0"

def mix_audio(settings: Settings) -> Path:
    bg=Path(st.session_state.background_audio); voice=Path(st.session_state.generated_ai_voice); out=Path(st.session_state.project_dir)/"final_mixed_audio.wav"
    bg_gain=settings.background_volume; voice_gain=settings.voice_volume
    if settings.ducking:
        cues=[Cue(**x) for x in st.session_state.subtitle_cues]; active=activity_expression(cues); duck=10**(-settings.duck_db/20)
        filtergraph=f"[0:a]aresample={settings.sample_rate},volume='{bg_gain}*if(gt({active},0),{duck},1)':eval=frame[bg];[1:a]aresample={settings.sample_rate},aformat=channel_layouts=stereo,volume={voice_gain}[v];[bg][v]amix=inputs=2:duration=first:dropout_transition={settings.fade_ms/1000:.3f},alimiter=limit=0.97[out]"
    else:
        filtergraph=f"[0:a]aresample={settings.sample_rate},volume={bg_gain}[bg];[1:a]aresample={settings.sample_rate},aformat=channel_layouts=stereo,volume={voice_gain}[v];[bg][v]amix=inputs=2:duration=first:dropout_transition={settings.fade_ms/1000:.3f},alimiter=limit=0.97[out]"
    run_cmd([ffmpeg(),"-y","-i",str(bg),"-i",str(voice),"-filter_complex",filtergraph,"-map","[out]","-c:a","pcm_s24le",str(out)],settings.subprocess_timeout,"Audio mixing")
    if not out.exists(): raise PipelineError("Final mixed audio was not created.")
    st.session_state.final_mixed_audio=str(out); st.session_state.signatures["mixing_signature"]=signature(st.session_state.signatures.get("separation_signature"),st.session_state.signatures.get("tts_signature"),settings.background_volume,settings.voice_volume,settings.ducking,settings.duck_db)
    set_status(6,"Completed"); return out

def escape_sub_filter(path: Path) -> str:
    value=str(path.resolve()).replace("\\","/").replace(":","\\:").replace("'","\\'").replace("[","\\[").replace("]","\\]").replace(",","\\,")
    return value

def persistent_output_dir() -> Path:
    """Create a persistent output folder next to the application source."""
    app_dir = Path(__file__).resolve().parent
    output_dir = app_dir / "output"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        test_file = output_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except OSError:
        output_dir = Path.home() / "AI_Dubbing_Studio_Output"
        output_dir.mkdir(parents=True, exist_ok=True)
    st.session_state.output_dir = str(output_dir)
    return output_dir


def validate_final_video(path: Path, timeout: int = 120) -> dict[str, Any]:
    """Validate that the rendered MP4 contains playable video and audio streams."""
    if not path.exists() or path.stat().st_size == 0:
        raise PipelineError("Final video file មិនបានបង្កើត ឬមានទំហំ 0 byte។")
    result = run_cmd(
        [ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        timeout,
        "Final video validation",
    )
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise PipelineError("Final MP4 មិនមាន Video stream។")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise PipelineError("Final MP4 មិនមាន Audio stream។")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise PipelineError("Final MP4 មាន duration មិនត្រឹមត្រូវ។")
    return {"duration": duration, "size": path.stat().st_size}


def persist_final_video(rendered: Path, source_video: Path, timeout: int) -> Path:
    """Copy a validated final video into the persistent output directory."""
    validate_final_video(rendered, min(timeout, 120))
    output_dir = persistent_output_dir()
    source_name = sanitize_filename(source_video.stem, "dubbed_video")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    destination = output_dir / f"{source_name}_dubbed_{timestamp}.mp4"
    counter = 1
    while destination.exists():
        destination = output_dir / f"{source_name}_dubbed_{timestamp}_{counter}.mp4"
        counter += 1
    shutil.copy2(rendered, destination)
    validate_final_video(destination, min(timeout, 120))
    st.session_state.persisted_final_video = str(destination)
    st.session_state.final_video = str(destination)
    log(f"Final video saved permanently: {destination}")
    return destination


def open_output_folder(path: Path) -> None:
    """Open a trusted application output directory on the local desktop."""
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], shell=False)
    else:
        subprocess.Popen(["xdg-open", str(path)], shell=False)

def render_video(settings: Settings, font_file: Optional[Path]=None) -> Optional[Path]:
    info=st.session_state.media_info
    if not info or not info["has_video"]: set_status(7,"Completed"); return None
    video=Path(st.session_state.original_video); audio=Path(st.session_state.final_mixed_audio); out=Path(st.session_state.project_dir)/"final_dubbed_video.mp4"; duration=float(info["duration"])
    prepared=Path(st.session_state.project_dir)/"render_audio.m4a"
    af=f"apad,atrim=0:{duration:.3f}" if settings.duration_policy=="match" else "anull"
    run_cmd([ffmpeg(),"-y","-i",str(audio),"-af",af,"-c:a","aac","-b:a","320k",str(prepared)],settings.subprocess_timeout,"Audio duration preparation")
    base=[ffmpeg(),"-y","-i",str(video),"-i",str(prepared),"-map","0:v:0","-map","1:a:0"]
    if settings.subtitle_mode=="soft" and st.session_state.subtitle_srt:
        base += ["-i",str(st.session_state.subtitle_srt),"-map","2:0"]
    copy=base+["-c:v","copy","-c:a","aac","-b:a","320k"]
    if settings.subtitle_mode=="soft": copy += ["-c:s","mov_text","-metadata:s:s:0","language=khm"]
    copy += ["-t",f"{duration:.3f}","-movflags","+faststart",str(out)]
    try:
        if settings.subtitle_mode=="burn": raise PipelineError("Burning requires video filtering.")
        run_cmd(copy,settings.subprocess_timeout,"Video stream-copy render")
    except PipelineError as first:
        log(f"Stream copy unavailable: {first}")
        vf=[]
        if settings.subtitle_mode=="burn" and st.session_state.subtitle_srt:
            sub=escape_sub_filter(Path(st.session_state.subtitle_srt)); style="FontName=Noto Sans Khmer,FontSize=22,Outline=2"
            fonts=f":fontsdir='{escape_sub_filter(font_file.parent)}'" if font_file else ""
            vf=["-vf",f"subtitles='{sub}'{fonts}:force_style='{style}'"]
        fallback=base+vf+["-c:v","libx264","-crf",str(settings.crf),"-preset",settings.preset,"-c:a","aac","-b:a","320k","-t",f"{duration:.3f}","-movflags","+faststart",str(out)]
        run_cmd(fallback,settings.subprocess_timeout,"H.264 fallback render")
    saved_video = persist_final_video(out, video, settings.subprocess_timeout)
    st.session_state.final_video=str(saved_video); st.session_state.signatures["video_signature"]=signature(st.session_state.signatures.get("mixing_signature"),settings.crf,settings.preset,settings.subtitle_mode,settings.duration_policy)
    set_status(7,"Completed"); return saved_video

def build_zip(selected: list[str]) -> Path:
    out=Path(st.session_state.project_dir)/"selected_outputs.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED,allowZip64=True) as z:
        for key in selected:
            value=st.session_state.get(key)
            if value and Path(value).exists(): z.write(value,Path(value).name)
    return out

def dependency_report() -> dict[str,str]:
    checks={"ffmpeg":shutil.which("ffmpeg") or "Missing: install FFmpeg and add it to PATH", "ffprobe":shutil.which("ffprobe") or "Missing: included with FFmpeg", "Demucs":"Installed" if importlib.util.find_spec("demucs") else "Missing: pip install demucs", "yt-dlp":"Installed" if yt_dlp else "Missing: pip install yt-dlp", "faster-whisper":"Installed" if importlib.util.find_spec("faster_whisper") else "Missing: pip install faster-whisper", "edge-tts":"Installed" if edge_tts else "Missing: pip install edge-tts", "CUDA":str(bool(torch and torch.cuda.is_available()))}
    return checks

def invalidate_from(stage: int) -> None:
    keys_by_stage={3:["generated_ai_voice","final_mixed_audio","final_video"],4:["isolated_vocals","background_audio","final_mixed_audio","final_video"],5:["generated_ai_voice","final_mixed_audio","final_video"],6:["final_mixed_audio","final_video"],7:["final_video"]}
    for s,keys in keys_by_stage.items():
        if s>=stage:
            for key in keys: st.session_state[key]=None

def run_complete(settings: Settings, transcribe_options: dict[str,Any]) -> None:
    if not st.session_state.source_media: raise PipelineError("Add media first.")
    if not st.session_state.subtitle_cues or not st.session_state.get("translated_srt_loaded"):
        raise PipelineError("សូម Upload SRT ដែលបានបកប្រែរួច ហើយចុច Load SRT ជាមុន។")
    set_status(4,"Processing"); separate_audio(settings)
    set_status(5,"Processing"); generate_tts(settings)
    set_status(6,"Processing"); mix_audio(settings)
    set_status(7,"Processing"); render_video(settings)
    set_status(8,"Completed")

def file_download(label: str, key: str, mime: str, element_id: str = "") -> None:
    """Render a download button with a unique deterministic Streamlit key."""
    value=st.session_state.get(key)
    if value and Path(value).exists():
        path=Path(value)
        slug=re.sub(r"[^a-zA-Z0-9]+","_",label).strip("_").lower()
        unique=element_id or slug or hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
        with path.open("rb") as file_handle:
            st.download_button(label,data=file_handle,file_name=path.name,mime=mime,use_container_width=True,key=f"download_{key}_{unique}")

def main() -> None:
    st.set_page_config(page_title=APP_NAME,page_icon="🎬",layout="wide")
    init_state(); lang=st.session_state.language; t=TEXT[lang]
    st.markdown("""<style>.block-container{max-width:1400px}.hero{padding:1.4rem;border:1px solid #334155;border-radius:18px;background:linear-gradient(135deg,#111827,#172554)}.step{padding:.65rem;border:1px solid #334155;border-radius:10px;margin:.2rem 0}</style>""",unsafe_allow_html=True)
    with st.sidebar:
        st.header("⚙️ Settings")
        language=st.selectbox("Language",["English","ខ្មែរ"],index=["English","ខ្មែរ"].index(lang));
        if language!=lang: st.session_state.language=language; st.rerun()
        mode=st.radio("Interface Mode",[t["simple"],t["advanced"]]); advanced=mode==t["advanced"]
        max_upload=st.number_input("Maximum upload size (MB)",128,10240,MAX_UPLOAD_MB_DEFAULT,128)
        max_download=st.number_input("Maximum download size (MB)",128,20480,MAX_DOWNLOAD_MB_DEFAULT,128)
        processor=st.selectbox("Processor",["auto","cuda","cpu"])
        model=st.selectbox("Demucs model",demucs_models()); four=st.checkbox("Four stems",False)
        voice_label=st.selectbox("AI Voice",list(VOICES)); sync=st.selectbox("Synchronization",["Smart Fit","Strict Timing","Preserve Complete Speech"]); max_tempo=st.slider("Maximum speech speed",1.0,5.0,1.65,.05)
        bgv=st.slider("Background volume",0,200,100)/100; vv=st.slider("AI voice volume",0,300,120)/100
        duck=st.checkbox("Background ducking",False); duck_db=st.slider("Ducking reduction (dB)",1.0,30.0,8.0,.5)
        crf=st.slider("Fallback H.264 CRF",14,30,18); preset=st.selectbox("Encoding preset",["fast","medium"]); submode=st.selectbox("Final subtitle mode",["No visible subtitles","Selectable track","Burn subtitles"])
        timeout=st.number_input("Subprocess timeout (seconds)",60,43200,SUBPROCESS_TIMEOUT_DEFAULT,60) if advanced else SUBPROCESS_TIMEOUT_DEFAULT
        settings=Settings(processor,model,four,VOICES[voice_label],{"Smart Fit":"smart","Strict Timing":"strict","Preserve Complete Speech":"preserve"}[sync],max_tempo,bgv,vv,duck,duck_db,120,crf,preset,{"No visible subtitles":"none","Selectable track":"soft","Burn subtitles":"burn"}[submode],"match",48000,int(timeout))
        with st.expander("Hardware and dependencies"): st.json(dependency_report())
        if st.button("🗑️ "+t["clear"],use_container_width=True):
            p=st.session_state.get("project_dir")
            if p and Path(p).is_dir() and PROJECT_ROOT in Path(p).parents: shutil.rmtree(p,ignore_errors=True)
            for k in list(st.session_state): del st.session_state[k]
            st.rerun()
    st.markdown(f'<div class="hero"><h1>🎬 {APP_NAME}</h1><p>Remove original speech, generate synchronized Khmer AI speech, preserve background audio, and render one final video.</p></div>',unsafe_allow_html=True)
    cols=st.columns(4)
    for i,step in enumerate(STEPS):
        status=st.session_state.pipeline_status[step]; cols[i%4].markdown(f'<div class="step">{STATUS_ICONS[status]} <b>{i+1}. {step}</b><br><small>{status}</small></div>',unsafe_allow_html=True)
    up_tab,url_tab=st.tabs(["📁 "+t["upload"],"🔗 "+t["link"]])
    with up_tab:
        upload=st.file_uploader("Media",type=[x[1:] for x in sorted(MEDIA_EXTS)])
        if upload and st.button("Prepare uploaded media"):
            try: prepare_uploaded(upload,int(max_upload)); st.success("Media prepared.")
            except Exception as exc: set_status(1,"Failed"); st.error(str(exc))
    with url_tab:
        url=st.text_input("YouTube or supported media URL",value=st.session_state.source_url)
        st.caption("Only process media you own or are authorized to use. DRM, private access, and paywalls are not bypassed.")
        if st.button("Download one media item",disabled=not url):
            try: st.session_state.source_url=url; download_media(url,int(max_download),settings.subprocess_timeout); st.success("Media downloaded and prepared.")
            except Exception as exc: set_status(1,"Failed"); st.error(str(exc))
    if st.session_state.media_info:
        info=st.session_state.media_info; st.subheader("Media Information"); st.json(info,expanded=False)
        if info["has_video"]: st.video(st.session_state.source_media)
        else: st.audio(st.session_state.source_media)
    st.subheader("2. Subtitle SRT")
    st.caption("មានតែ 2 ជម្រើស៖ Upload SRT ឬប្រើ faster-whisper បង្កើត SRT ពី Video។")
    subtitle_mode=st.radio("Subtitle Option",["1. Upload SRT","2. Generate SRT with faster-whisper"],horizontal=True)
    transcribe_options={"model_name":"small","language":"Auto Detect","word_ts":False,"vad":True,"beam":5,"prompt":"","translate":False}
    if subtitle_mode=="1. Upload SRT":
        sub=st.file_uploader("Upload SRT",type=["srt"],key="subtitle_upload")
        if sub and st.button("📥 Load SRT",type="primary",use_container_width=True):
            try:
                cues=parse_subtitles(decode_text(sub.getvalue()),".srt")
                save_cues(cues)
                st.session_state.translated_srt_loaded=True
                invalidate_from(5)
                st.success(f"Load SRT បានជោគជ័យ៖ {len(cues)} cues។")
            except Exception as exc:
                set_status(2,"Failed"); st.error(f"Load SRT បរាជ័យ៖ {exc}")
    else:
        st.info("faster-whisper នឹងស្ដាប់សំឡេងក្នុង Video និងបង្កើត SRT ដែលអាច Download ទៅបកប្រែ។")
        c1,c2=st.columns(2)
        with c1:
            transcribe_options["model_name"]=st.selectbox("Whisper Model",["tiny","base","small","medium","large-v3"],index=2)
            transcribe_options["language"]=st.text_input("Original audio language: Auto Detect ឬ code", "Auto Detect")
        with c2:
            transcribe_options["vad"]=st.checkbox("Voice Activity Detection",True)
            transcribe_options["beam"]=st.slider("Beam Size",1,10,5)
        if st.button("🎧 Generate SRT with faster-whisper",type="primary",use_container_width=True,disabled=not st.session_state.source_media):
            try:
                set_status(2,"Processing")
                if not st.session_state.original_audio: extract_audio(settings)
                transcribe_local(**transcribe_options)
                st.session_state.translated_srt_loaded=False
                set_status(2,"Completed")
                st.success("Generate SRT បានជោគជ័យ។ Download ទៅបកប្រែ រួច Upload វិញតាម Option 1។")
            except Exception as exc:
                set_status(2,"Failed")
                log(f"Generate SRT failed: {type(exc).__name__}: {exc}")
                st.error(f"faster-whisper បរាជ័យ៖ {exc}")
                with st.expander("មើល faster-whisper Logs"):
                    st.code("\n".join(st.session_state.logs[-100:]), language="text")
        if st.session_state.subtitle_srt and Path(st.session_state.subtitle_srt).exists() and not st.session_state.translated_srt_loaded:
            file_download("⬇️ Download SRT for Translation","subtitle_srt","application/x-subrip","whisper_srt")
    if st.session_state.subtitle_cues:
        st.subheader("3. "+t["review"])
        q=st.text_input("Search subtitle text")
        rows=[{"Index":x["index"],"Start time":stamp(x["start_ms"]),"End time":stamp(x["end_ms"]),"Text":x["text"]} for x in st.session_state.subtitle_cues if not q or q.lower() in x["text"].lower()]
        edited=st.data_editor(pd.DataFrame(rows),num_rows="dynamic",use_container_width=True,key="subtitle_editor")
        if st.button("Save subtitle changes"):
            try:
                cues=[Cue(i+1,ms_from_stamp(str(r["Start time"])),ms_from_stamp(str(r["End time"])),str(r["Text"])) for i,r in edited.fillna("").iterrows()]
                save_cues(validate_cues(cues,fail=True)); invalidate_from(5); st.success("Edited subtitles saved.")
            except Exception as exc: st.error(str(exc))
        for warning in st.session_state.get("subtitle_warnings",[]): st.warning(warning)
        file_download("Download final SRT","subtitle_srt","application/x-subrip","final_srt")
    if st.button("✨ "+t["start"],type="primary",use_container_width=True):
        try:
            with st.status("Running complete pipeline",expanded=True): run_complete(settings,transcribe_options)
            st.success("Complete processing finished.")
        except Exception as exc:
            for i,s in enumerate(STEPS,1):
                if st.session_state.pipeline_status[s]=="Processing": set_status(i,"Failed")
            st.error(str(exc))
    if advanced and st.session_state.source_media:
        st.subheader("Advanced step controls")
        a,b,c,d=st.columns(4)
        if a.button("Run separation"):
            try: set_status(4,"Processing"); separate_audio(settings)
            except Exception as exc: set_status(4,"Failed"); st.error(str(exc))
        if b.button("Run TTS",disabled=not st.session_state.subtitle_cues):
            try: set_status(5,"Processing"); generate_tts(settings)
            except Exception as exc: set_status(5,"Failed"); st.error(str(exc))
        if c.button("Run mixing",disabled=not(st.session_state.background_audio and st.session_state.generated_ai_voice)):
            try: set_status(6,"Processing"); mix_audio(settings)
            except Exception as exc: set_status(6,"Failed"); st.error(str(exc))
        if d.button("Render final",disabled=not st.session_state.final_mixed_audio):
            try: set_status(7,"Processing"); render_video(settings)
            except Exception as exc: set_status(7,"Failed"); st.error(str(exc))
    st.subheader("8. Preview and Download")
    if st.session_state.tts_report: st.json(st.session_state.tts_report,expanded=False)
    outputs=[("Original extracted audio","original_audio","audio/wav"),("Isolated original vocals","isolated_vocals","audio/wav"),("Speech-removed background","background_audio","audio/wav"),("Generated AI voice","generated_ai_voice","audio/wav"),("Final mixed audio","final_mixed_audio","audio/wav")]
    for label,key,mime in outputs:
        if st.session_state.get(key): st.markdown("**"+label+"**"); st.audio(st.session_state[key]); file_download("Download "+label,key,mime)
    if st.session_state.final_video and Path(st.session_state.final_video).exists():
        final_path = Path(st.session_state.final_video)
        st.markdown("**Final dubbed video**")
        st.success(f"Final Video បានរក្សាទុកក្នុង Folder៖ {final_path.parent}")
        st.code(str(final_path), language="text")
        try:
            st.video(str(final_path))
        except Exception as preview_error:
            log(f"Browser preview unavailable: {preview_error}")
            st.warning("Browser មិនអាច Preview Video នេះបាន ប៉ុន្តែ File ត្រូវបានរក្សាទុកក្នុង Output Folder រួច។ សូម Download ឬបើកជាមួយ VLC។")
        file_download("Download final dubbed video","final_video","video/mp4","final_video_download")
        if st.button("📂 Open Output Folder", use_container_width=True, key="open_output_folder"):
            try:
                open_output_folder(final_path.parent)
                st.success("បានបើក Output Folder។")
            except Exception as folder_error:
                st.error(f"មិនអាចបើក Output Folder៖ {folder_error}")
    available=[k for k in ["subtitle_srt","background_audio","generated_ai_voice","final_mixed_audio","final_video","original_audio","isolated_vocals"] if st.session_state.get(k)]
    if available:
        selected=st.multiselect("ZIP contents",available,default=[x for x in available if x in {"subtitle_srt","background_audio","generated_ai_voice","final_mixed_audio","final_video"}])
        total=sum(Path(st.session_state[x]).stat().st_size for x in selected)
        if total>1024**3: st.warning("The selected ZIP may exceed 1 GB and take substantial time and disk space.")
        if st.button("Create ZIP archive"):
            z=build_zip(selected); st.session_state["zip_output"]=str(z)
        file_download("Download selected outputs ZIP","zip_output","application/zip")
    with st.expander(t["logs"]): st.code("\n".join(st.session_state.logs[-300:]) or "No logs yet.",language="text")

if __name__ == "__main__":
    main()