<div align="center">

# 🎬 Hindi Video Generator (4K UHD)

✨ Automated Hindi alphabet learning videos for kids — generate stunning **1080p / 2K / 4K** MP4s featuring Devanagari letters, vibrant words, delightful cliparts, and an animated mascot! 🐻

</div>

## 📽️ What It Does

🎯 One **12-second video per letter** — renders the complete Hindi varnmala in order:

- 🔤 **13 Swar** (vowels)
- 🔠 **33 Vyanjan** (consonants)
- 🔡 **3 Sanyukt** (compound letters)

= **49 beautifully crafted videos!** 🎉

## 🚀 Quick Start

### 📦 Installation

```bash
pip install -r requirements.txt
```

> ⚠️ **Requirements:** Python 3.9+ with Tkinter
>
> - ✅ Included with the Windows / macOS installers
> - 🐧 Ubuntu / Debian: `sudo apt install python3-tk`

### ▶️ Running the Generator

```bash
python hindi_videos.py
```

Follow these simple steps:

| Step | Action |
|:---:|---|
| 1️⃣ | Pick resolution (1080p / 2K / 4K) and FPS |
| 2️⃣ | Choose mascot image and clipart folder (skipped if saved in `config.json`) |
| 3️⃣ | Confirm the slate in the preview window (auto-detected and cached) |
| 4️⃣ | Sit back — videos render to `OUTPUT_VIDEOS/` |

Output naming: `000_अ_अनार.mp4`, `001_आ_आम.mp4`, ...

💡 **Smart Resume:** already-rendered videos are skipped automatically (`"resume": true`). Stop anytime, continue later!

## ⚙️ Configuration

Copy `config.example.json` → `config.json` and customize. Relative paths are relative to the project folder.

```json
{
  "output": { "width": 3840, "height": 2160, "fps": 30, "duration": 12 }
}
```

| 🔧 Key | 📝 Description |
|---|---|
| `output` | Width, height, FPS, duration, fade-out, x264 preset |
| `timing` | Seconds when letter / "से" / word / picture / burst appear |
| `layout`, `particles`, `colors` | Positions, confetti and RGB colors (designed on 1920×1080, auto-scaled) |
| `workers` | Parallel render processes (1–6) |
| `resume` | Skip already-rendered videos |
| `only_letters` | e.g. `["अ", "आ"]` renders only these; `[]` renders all |
| `mascot_path`, `clipart_dir` | Default paths for the file pickers |
| `background_image` | Optional background picture |

## 🎨 Assets

### 📁 Cliparts

```text
assets/cliparts/Hindi/<word>.png
```

- 🖼️ One picture per word — the filename must match the Hindi word (e.g. `अनार.png`)
- ℹ️ Letters ङ, ञ, ण, अः have no words → rendered as letter-only videos

### 🐾 Mascots

```text
assets/mascots/
```

- 🎭 Each mascot needs a red slate/board for the letter
- ✅ Auto-detected: `01.png`, `02.png`, `03.png`, `Bear`, `Deer`, `Fox`, `Penguin`
- ✏️ Others: adjust the slate manually in the preview window

## 🔧 Troubleshooting

| ❗ Issue | 💡 Solution |
|---|---|
| Video failed | Check `render.log` for the full error |
| `ModuleNotFoundError: tkinter` | Install Tkinter (see Installation) |
| Broken matras | `pip install uharfbuzz` |
| Missing cliparts | Listed before rendering starts — those letters are skipped |

<div align="center">

🎬 **Happy Rendering!** 🎬

Made with ❤️ for little learners

</div>
