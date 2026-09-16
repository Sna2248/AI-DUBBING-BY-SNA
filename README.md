# AI Video Dubbing & Vocal Isolation Studio

កម្មវិធី Streamlit សម្រាប់បញ្ចូលសំឡេង AI ភាសាខ្មែរទៅក្នុងវីដេអូ ដកសំឡេងនិយាយដើមដោយ Demucs បង្កើត Subtitle SRT ដោយ faster-whisper និងលាយសំឡេងថ្មីជាមួយតន្ត្រី Sound Effects និងសំឡេងបរិយាកាសដើម។

## មុខងារសំខាន់ៗ

- Upload វីដេអូប្រភេទ MP4, MOV, MKV និង WEBM
- ទាញយកវីដេអូពី URL ដែល yt-dlp គាំទ្រ
- Generate Subtitle ជា SRT ដោយ faster-whisper
- Upload SRT ដែលបានបកប្រែជាភាសាខ្មែរ
- ពិនិត្យ និងកែអត្ថបទ Start Time និង End Time របស់ Subtitle
- ដកសំឡេងនិយាយដើមដោយ Demucs
- បង្កើត AI Voice ជាភាសាខ្មែរដោយ Edge TTS
- គាំទ្រសំឡេង `km-KH-SreymomNeural` និង `km-KH-PisethNeural`
- Smart Fit, Strict Timing និង Preserve Complete Speech
- លាយ `background_audio + generated_ai_voice`
- Background ducking នៅពេល AI Voice កំពុងនិយាយ
- Render ជា Final MP4 ដោយរក្សាគុណភាពវីដេអូដើមតាមដែលអាចធ្វើបាន
- Auto CPU/GPU: ប្រើ NVIDIA CUDA បើមាន និងត្រឡប់ទៅ CPU បើគ្មាន

## តម្រូវការប្រព័ន្ធ

- Windows 10 ឬ Windows 11 64-bit
- Python 3.10 ឬ Python 3.11 ត្រូវបានណែនាំ
- FFmpeg និង FFprobe នៅក្នុង PATH
- Internet សម្រាប់ Edge TTS
- Internet សម្រាប់ទាញ Whisper និង Demucs models នៅពេលប្រើលើកដំបូង
- NVIDIA GPU ជាជម្រើសបន្ថែមសម្រាប់ CUDA

## Clone Repository

បើក PowerShell ហើយរត់៖

```powershell
git clone https://github.com/YOUR_USERNAME/AI-DUBBING-BY-SNA.git
cd AI-DUBBING-BY-SNA
```

ប្ដូរ `YOUR_USERNAME` ទៅ GitHub username របស់ម្ចាស់ Repository។

## បង្កើត Virtual Environment

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

បើ PowerShell មិនអនុញ្ញាតឱ្យ Activate៖

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

បន្ទាប់មក Activate ម្ដងទៀត៖

```powershell
.\venv\Scripts\Activate.ps1
```

## ដំឡើង Dependencies សម្រាប់ CPU

```powershell
python -m pip install -r requirements.txt
```

ពិនិត្យថា Packages សំខាន់ៗ Import បាន៖

```powershell
python -c "import streamlit, torch, edge_tts, yt_dlp; from faster_whisper import WhisperModel; print('Dependencies OK')"
```

## ដំឡើង FFmpeg លើ Windows

ដំឡើង FFmpeg ហើយបន្ថែម Folder `bin` របស់ FFmpeg ទៅ Windows PATH។ បិទ និងបើក Terminal ឡើងវិញ រួចពិនិត្យ៖

```powershell
ffmpeg -version
ffprobe -version
```

Command ទាំងពីរត្រូវបង្ហាញព័ត៌មាន Version។ FFmpeg មិនមែនជា Python package ហើយមិនត្រូវបានដាក់ក្នុង `requirements.txt` ទេ។

## ប្រើ NVIDIA GPU និង CPU Fallback

កម្មវិធីមាន Processor modes ចំនួនបី៖

- `auto`: ប្រើ CUDA GPU បើអាចប្រើបាន និង fallback ទៅ CPU បើមិនមាន
- `cuda`: បង្ខំប្រើ NVIDIA GPU
- `cpu`: បង្ខំប្រើ CPU

សម្រាប់ការចែកចាយ និងការប្រើទូទៅ គួរជ្រើស `auto`។

### ពិនិត្យ NVIDIA Driver

```powershell
nvidia-smi
```

### ដំឡើង PyTorch CUDA

`pip install -r requirements.txt` អាចដំឡើង PyTorch CPU build។ អ្នកប្រើ NVIDIA GPU ត្រូវលុប PyTorch ចាស់ ហើយដំឡើង CUDA wheel ដែលត្រូវនឹងការណែនាំនៅ PyTorch Installation Selector។ ឧទាហរណ៍ CUDA 12.6៖

```powershell
python -m pip uninstall torch torchaudio torchvision -y
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

ពិនិត្យ CUDA៖

```powershell
python -c "import torch; print('Torch:', torch.__version__); print('CUDA runtime:', torch.version.cuda); print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU mode')"
```

បើ `CUDA available: True` កម្មវិធីអាចប្រើ GPU សម្រាប់ Demucs។ faster-whisper GPU ក៏ត្រូវការ CUDA/cuBLAS និង cuDNN ដែលសមស្របជាមួយ CTranslate2 ផងដែរ។ បើ GPU backend បរាជ័យនៅ Auto mode កម្មវិធីព្យាយាមប្រើ CPU int8។

## ដំណើរការកម្មវិធី

```powershell
python -m streamlit run unified_app.py
```

បើ Browser មិនបើកដោយស្វ័យប្រវត្តិ សូមបើក៖

```text
http://localhost:8501
```

## Workflow សម្រាប់បញ្ចូលសំឡេងរឿង

### 1. បញ្ចូលវីដេអូ

1. ចូលផ្នែក Upload File
2. ជ្រើស MP4, MOV, MKV ឬ WEBM
3. ចុច `Prepare uploaded media`
4. រង់ចាំ Media Information បង្ហាញ

### 2. បង្កើត SRT ដោយ faster-whisper

1. ជ្រើស `Generate SRT with faster-whisper`
2. ជ្រើស Whisper Model
3. កំណត់ Original Audio Language ជា `Auto Detect` ឬ Language code ដូចជា `en`
4. បើក Voice Activity Detection បើសំឡេងនិយាយច្បាស់
5. ចុច `Generate SRT with faster-whisper`
6. ចុច `Download SRT for Translation`

Settings ណែនាំសម្រាប់ CPU៖

```text
Whisper Model: small
Language: Auto Detect
Voice Activity Detection: On
Beam Size: 5
```

### 3. បកប្រែ និង Upload SRT

បកប្រែតែអត្ថបទក្នុង SRT ហើយរក្សា Index និង Timestamp ដដែល។ Save ជា UTF-8 `.srt`។

បន្ទាប់មក៖

1. ជ្រើស `Upload SRT`
2. Upload SRT ដែលបានបកប្រែ
3. ចុច `Load SRT`
4. ពិនិត្យតារាង Subtitle
5. ចុច `Save Subtitle Changes`

### 4. បំបែកសំឡេងដើម

Settings ណែនាំ៖

```text
Processor: auto
Demucs Model: htdemucs
Four Stems: Off
```

កម្មវិធីបង្កើត៖

- `original_audio`: សំឡេងដើមពីវីដេអូ
- `isolated_vocals`: សំឡេងនិយាយ ឬច្រៀងដើម
- `background_audio`: តន្ត្រី Sound Effects និងបរិយាកាសដែលបានកាត់បន្ថយសំឡេងមនុស្ស

### 5. បង្កើត AI Voice

Settings ណែនាំ៖

```text
AI Voice: Sreymom ឬ Piseth
Synchronization: Smart Fit
Maximum Speech Speed: 1.65x
```

Smart Fit បង្កើនល្បឿនតែ Cue ដែលវែងជាង Subtitle duration ហើយមិនបង្ខំឱ្យគ្រប់ Cue រត់នៅ 1.65x ទេ។

### 6. លាយសំឡេង

Settings ណែនាំ៖

```text
Background Volume: 75% ដល់ 100%
AI Voice Volume: 120% ដល់ 140%
Background Ducking: On
Ducking Reduction: 8 dB
```

Final mix ប្រើតែ៖

```text
background_audio + generated_ai_voice
```

`original_audio` និង `isolated_vocals` មិនត្រូវបានបញ្ចូលក្នុង Final mix តាមលំនាំដើមទេ។

### 7. Render Final Video

Settings ណែនាំ៖

```text
CRF: 18
Preset: fast សម្រាប់សាកល្បង
Preset: medium សម្រាប់ Final output
Subtitle Mode: No visible subtitles ឬ Selectable track
```

កម្មវិធីព្យាយាម Copy Video stream ដើមជាមុន។ បើមិនអាច Copy ទៅ MP4 បាន វាប្រើ H.264 fallback។

## Outputs

កម្មវិធីអាចបង្កើត និង Download៖

- Final SRT
- Original extracted audio
- Isolated original vocals
- Speech-removed background audio
- Generated AI voice
- Final mixed audio
- Final dubbed MP4
- ZIP archive នៃ Outputs ដែលបានជ្រើស

## Troubleshooting

### FFmpeg not found

```powershell
ffmpeg -version
ffprobe -version
```

បើ Command មិនដំណើរការ សូមដំឡើង FFmpeg និងកែ Windows PATH។

### CUDA បង្ហាញ False

```powershell
nvidia-smi
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

បើ `torch.version.cuda` ជា `None` អាចមានន័យថា PyTorch CPU-only build ត្រូវបានដំឡើង។

### faster-whisper បង្កើត No cues found

- ស្ដាប់ Original Extracted Audio ថាមានសំឡេងនិយាយឬអត់
- សាកបិទ Voice Activity Detection
- កំណត់ Language code ដោយផ្ទាល់
- សាក Model `small` ឬ `medium`

### Edge TTS មិន Generate Audio

- ពិនិត្យ Internet
- Update package៖

```powershell
python -m pip install --upgrade edge-tts
```

- ពិនិត្យ Technical Logs ក្នុងកម្មវិធី

### Processing យូរ

CPU mode អាចយូរ ជាពិសេស Demucs។ ប្រើ៖

```text
Demucs: htdemucs
Four Stems: Off
Whisper: small
Preset: fast
```

## Update Source ពី GitHub

```powershell
git pull
python -m pip install -r requirements.txt
```

## Privacy

- Demucs និង local faster-whisper ដំណើរការនៅលើកុំព្យូទ័រ
- Edge TTS ត្រូវផ្ញើអត្ថបទ Subtitle ទៅសេវា TTS ដើម្បីបង្កើតសំឡេង
- URL download ទាក់ទងទៅ Platform ប្រភព
- កុំ Commit API keys, cookies, `.env` ឬ `.streamlit/secrets.toml` ទៅ GitHub

## ការប្រើប្រាស់ដោយស្របច្បាប់

ប្រើតែ Video និង Audio ដែលអ្នកជាម្ចាស់ ឬមានការអនុញ្ញាតឱ្យប្រើ។ កម្មវិធីនេះមិនមានគោលបំណងរំលង DRM, Paywall, Login restriction ឬ Access control ទេ។
