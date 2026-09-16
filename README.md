# AI Video Dubbing & Vocal Isolation Studio

A unified Streamlit application that downloads or accepts media, obtains or creates subtitles, removes original human vocals with Demucs, creates synchronized Khmer speech with Edge TTS, mixes that speech with the speech-removed background, and muxes the result into the original video stream.

> Only process content you own or are authorized to use. The app does not bypass DRM, private access controls, paywalls, or login restrictions. API keys are never hardcoded or written to output files.

## Windows installation

### 1. Install Python and create a virtual environment

Install 64-bit Python 3.10 or 3.11, then open PowerShell in the project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` in an authorized PowerShell session.

### 2. Install FFmpeg

Install an FFmpeg Windows build and add its `bin` directory to the system PATH. Restart the terminal and verify:

```powershell
ffmpeg -version
ffprobe -version
```

FFmpeg is a system executable and is intentionally not listed in `requirements.txt`.

### 3. Install packages

```powershell
pip install -r requirements.txt
```

PyTorch CUDA builds are hardware and CUDA-version specific. If you have a supported NVIDIA GPU, install the matching PyTorch build from the official PyTorch installation selector before or after installing the requirements. Verify with:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

Demucs and faster-whisper fall back to CPU. CPU transcription uses int8 and can be much slower for long media.

### 4. Run

```powershell
streamlit run unified_app.py
```

## Usage

### Upload File

Open **Upload File**, select MP4, MOV, MKV, WEBM, MP3, WAV, M4A, or FLAC, then click **Prepare uploaded media**. The project is stored under the operating system temporary directory and remains available for downloads until you clear project data or the OS removes temporary files.

### Paste Link

Open **Paste Link**, enter a valid HTTP or HTTPS URL supported by yt-dlp, and click **Download one media item**. Playlist downloading is disabled and only one item is requested. Best video and audio streams are selected and FFmpeg merges them when needed.

### Obtain subtitles

Choose one source:

- **Upload Subtitle**: Upload SRT or VTT in UTF-8, UTF-8-SIG, UTF-16, or a fallback encoding.
- **Extract Embedded Subtitle**: Select a detected subtitle stream and convert it to UTF-8 SRT.
- **Download Available Subtitle**: For URL media, inspect manual and automatic captions, select a language, and download without downloading the media again.
- **AI Automatic Transcription**: Select a faster-whisper model, language, VAD, word timestamps, beam size, optional prompt, and optional English translation.

The editable table is the authoritative subtitle source for TTS. Save edits before processing. Warnings identify overlaps, empty cues, invalid times, short cues, and long text.

### Generate AI voice

Select Sreymom or Piseth. Smart Fit removes edge silence, uses one or more FFmpeg `atempo` filters, then trims only when necessary. Strict Timing trims at cue end. Preserve Complete Speech allows speech to extend and may overlap later cues.

### Vocal separation and mixing

Demucs creates `isolated_vocals` and `background_audio`. The application mixes only `background_audio + generated_ai_voice`. The original audio and isolated vocal track are not included in the final mix by default. Four-stem mode recombines drums, bass, and other as the background.

Optional ducking lowers the background only inside subtitle cue intervals. A limiter helps prevent clipping.

### Render final video

The application ignores the source audio, copies the original video stream when MP4 compatibility allows, adds the final mixed AAC track, and matches the original duration. If stream copy fails, it falls back to H.264 using the selected CRF and preset. Subtitles can be omitted, added as a selectable track, or burned into the image.

For burned Khmer subtitles, install a Khmer Unicode font such as Noto Sans Khmer on Windows. FFmpeg/libass must be able to find it. The current UI uses the installed font name; selectable custom font upload can be added without changing the rendering pipeline.

Audio-only inputs support transcription, separation, TTS, mixing, and audio downloads. Video rendering is skipped.

## Outputs

The app can preview and download the final SRT, original extracted WAV, isolated vocals, speech-removed background, generated AI voice, final mixed WAV, final dubbed MP4, and a selected ZIP archive. Large ZIPs are created on disk rather than assembled entirely in memory.

## Troubleshooting

- **FFmpeg not found**: Add the FFmpeg `bin` directory to PATH, restart the terminal, and rerun `ffmpeg -version` and `ffprobe -version`.
- **Demucs model download fails**: The first use of a model may require internet access. Retry after checking firewall and connectivity.
- **CUDA out of memory**: Select CPU, close GPU applications, use the standard `htdemucs` model, or process shorter media.
- **TTS cue fails**: Check internet access because Edge TTS is an online service. Completed cue files remain in the project, and failed cues are listed in the synchronization report.
- **No online subtitles**: Switch to AI Automatic Transcription.
- **Stream copy fails**: The app automatically falls back to H.264. MKV, MOV, or WEBM video codecs are not always MP4-compatible.
- **Burned subtitles fail**: Verify the FFmpeg build includes libass and install a Khmer-compatible font.
- **Long processing time**: Use CUDA when available, a smaller Whisper model, and two-stem Demucs mode.
- **Windows file lock**: Stop media playback, close duplicate Streamlit sessions, and retry clearing project data.

## Privacy and API keys

Local Whisper and Demucs run on the machine. Edge TTS sends subtitle text to its service to synthesize speech. URL downloads contact the source platform. Do not process confidential media unless those data flows are acceptable.

The current implementation does not fake API transcription. A modular API TTS base class exists, but selecting an unconfigured external provider raises a setup error. Any future API keys should be entered with `st.text_input(type="password")`, read from environment variables or Streamlit secrets, excluded from logs, and never saved with outputs.
