# DGX Spark — Hardware & System Setup Notes

Notes on the state of this NVIDIA DGX Spark machine as of 2026-04-24.

## Identity

- Hostname: redacted
- Machine: NVIDIA DGX Spark (developer SoC platform, ARM64)
- GPU/SoC: **NVIDIA GB10** (Grace–Blackwell)
- OS: Ubuntu 24.04 (DGX OS variant) on aarch64
- Default kernel after 2026-04-24: `6.17.0-1014-nvidia` (older `6.11.0-1014-nvidia` still installed and selectable from GRUB)
- NVIDIA driver: open kernel module **580.126.09**, CUDA 13.0 userspace
- Display server: **Xorg** (set as the default GDM session because Wayland on
  this driver/mutter combination is currently unstable — see "Display server
  caveat" below)

## Connected peripherals

### Display

- Connector: `HDMI-A-1` on the GB10's display engine (DRM card1)
- Monitor: **Raspberry Pi 15.6″ Portable Monitor** (1920×1080)
  - EDID manufacturer ID: `RPL`
  - EDID product name: `RPI MON156`
  - ASCII serial: `81005595671`
  - Manufactured: week 9 of 2023
  - Native: 1920×1080 @ 60 Hz
  - Has built-in stereo speakers, audible via HDMI

#### Reducing resolution (when a higher-res monitor is connected)

If a 4K-capable monitor is plugged in and the desktop is rendering at
3840×2160 (text too small, GPU under unnecessary load), drop it to 1080p
at runtime via `xrandr`:

```sh
DISPLAY=:0 xrandr --output HDMI-0 --mode 1920x1080 --rate 60
```

The X output name on this box is `HDMI-0` under Xorg/NVIDIA (DRM connector
is `HDMI-A-1`). 1920×1080 is a clean 2× downscale of 4K. List available
modes with `DISPLAY=:0 xrandr`. This is a runtime change only; to make it
persist across logins, set the resolution from GNOME's *Settings → Displays*
panel (which writes `~/.config/monitors.xml`).

### Audio

- Output device: HDMI stereo via the monitor's built-in speakers
- PipeWire sink name: `Built-in Audio Digital Stereo (HDMI)`
- The monitor has its own physical volume control on the side panel —
  if HDMI audio plays without sound, check that hardware control first.

### Input

- **Apple Magic Trackpad** (USB, vendor `0x05AC` product `0x0265`)
- **Apple Magic Keyboard** (USB, vendor `0x05AC` product `0x029C`)
- Both connect to USB controller `NVDA8000`.

#### Magic Trackpad cursor-stall caveat

When making circular finger motions on the Magic Trackpad, the cursor pauses
briefly at certain points. Cause: the Linux `magicmouse` kernel module
exposes the trackpad as **two** xinput slave-pointer devices (mouse mode and
multi-touch mode), and its gesture detector intercepts circular motions as
candidate rotation/zoom gestures, briefly suspending pointer reporting while
it decides.

The `magicmouse` module on this kernel exposes no tunable parameters, so
this is not adjustable from userspace. Practical responses:

1. **Live with it.** Long-standing Magic Trackpad-on-Linux limitation.
2. **Try disabling one of the duplicate xinput devices**:
   `DISPLAY=:0 xinput list` (find the two "Apple Inc. Magic Trackpad" entries,
   and try `xinput disable <id>` on one). Reversible with `xinput enable <id>`.
   To make persistent if a particular one helps, write an Xorg input config
   under `/etc/X11/xorg.conf.d/`.
3. **Use a non-Apple pointing device** (any cheap USB mouse) — bypasses
   `magicmouse` entirely.

#### Magic Keyboard: ⌘ → Super (stock behavior)

By default on Linux, the physical Command (⌘) key on an Apple keyboard
produces `Super_L` / `Super_R` (the Windows/Meta key). This means:

- `⌘` alone opens the GNOME Activities Overview.
- `⌘+number` launches the Nth dock favorite.
- `⌘+C` does **not** copy in apps (in most apps the copy shortcut is
  `Ctrl+C`, and `Ctrl` is the physical Control key — left of ⌥).

Tempting fix: set `options hid_apple swap_ctrl_cmd=1` to make ⌘ produce
`Ctrl`. **Do not do this** without also installing a context-aware
remapper. The kernel-level swap collapses macOS's two physically-separate
keys (Cmd and Control) into one Linux key, which means the terminal can
no longer distinguish "⌘+C copy" (the GUI sense) from "Ctrl+C interrupt"
(the SIGINT sense). Pressing ⌘+C inside Claude Code, vim, ssh, etc. would
just escape/interrupt the running process. There's no clean way to fix
that purely in-terminal.

The right approach if you want full macOS-style keybindings (Cmd+C copies
in terminals AND Ctrl+C still sends SIGINT) is a per-app keymap layer
that watches the focused window class and rewrites events accordingly.
The two well-known options:

- **Toshy** — <https://github.com/RedBearAK/toshy>. Actively maintained,
  X11 + Wayland (KDE), auto-detects Apple keyboards, ships per-app
  layers including a "terminals" group.
- **Kinto** — <https://kinto.sh/>. The original; X11-focused.

Neither is installed yet on this box. Install one of them *instead of*
the kernel-level swap if you want the macOS workflow.

#### Caps Lock → Escape

Caps Lock is remapped to `Escape` via XKB:

```sh
gsettings set org.gnome.desktop.input-sources xkb-options "['caps:escape']"
```

Persists across reboots. Revert with
`gsettings reset org.gnome.desktop.input-sources xkb-options`.

### Bluetooth

- Paired device: `Xenon_CCB_SN_24310B06BA` — Honeywell Xenon barcode scanner
  (input device, not audio).

## Display server caveat (Wayland vs. Xorg)

The default GDM session for this user is **Ubuntu on Xorg**, set via
`/var/lib/AccountsService/users/htong: Session=ubuntu-xorg`.

Reason: Wayland with NVIDIA 580.126.09 (open kernel module) + mutter 46.0
on this hardware fails to keep mutter's KMS frame-submission thread on a
stable schedule. The journal fills with:

```
gnome-shell: Failed to make thread 'KMS thread' realtime scheduled: Device or resource busy
gnome-shell: Failed to make thread 'KMS thread' normally scheduled: Device or resource busy
```

several times per second, and the visible result is:

- The Ubuntu Dock flickers / fails to persist
- The Activities Overview dismisses itself mid-animation
- The cursor microhitches

Xorg uses NVIDIA's mature DDX path and does not exhibit any of those
symptoms. To switch back to Wayland later (after future driver/mutter
updates), edit the AccountsService file:

```
sudo sed -i 's/^Session=.*/Session=ubuntu/' /var/lib/AccountsService/users/htong
```

…or pick the Wayland session at GDM via the gear icon next to the password
field.

## Modprobe state

Original DGX OOBE image shipped with `/etc/modprobe.d/zz-nvidia-drm-override.conf`
containing `options nvidia-drm modeset=0`, which forced the system to run on
the bootloader's `simple-framebuffer` (no NVIDIA KMS, no HDMI audio, no EDID,
no `nvidia-smi`). That override was moved aside (`.bak`) on 2026-04-24 to
enable the NVIDIA display driver and HDMI audio.

If the system needs to be returned to the original simpledrm-only state
(e.g., for stability while waiting for an updated driver/mutter), restore
the override:

```
sudo mv /etc/modprobe.d/zz-nvidia-drm-override.conf.bak /etc/modprobe.d/zz-nvidia-drm-override.conf
sudo update-initramfs -u
sudo reboot
```

## Other system tweaks in place

- `/etc/security/limits.d/99-htong-rtprio.conf` — grants `htong` rtprio 95,
  nice -19, unlimited memlock (so mutter can use real-time scheduling for
  its KMS thread on Wayland; harmless on Xorg).
- `/etc/systemd/system/user-.slice.d/50-rt.conf` — `DisableControllers=cpu`
  on user slices, so the cpu cgroup controller doesn't restrict RT
  bandwidth for user processes.
- GNOME screen-lock disabled:
  - `org.gnome.desktop.screensaver lock-enabled = false`
  - `org.gnome.desktop.screensaver ubuntu-lock-on-suspend = false`
- GNOME top bar clock shows seconds:
  - `org.gnome.desktop.interface clock-show-seconds = true`

## GNOME top bar — Vitals extension

The **Vitals** GNOME Shell extension is installed for top-bar
network up/download speed (plus CPU, memory, temperature).

- UUID: `Vitals@CoreCoding.com`, version 75
- Source: <https://extensions.gnome.org/extension/1460/vitals/>
- Installed per-user at
  `~/.local/share/gnome-shell/extensions/Vitals@CoreCoding.com`
- Added to `org.gnome.shell enabled-extensions`

Install steps used (no sudo, no browser):

```sh
# Resolve the download URL for the running shell version
curl -sf "https://extensions.gnome.org/extension-info/?uuid=Vitals@CoreCoding.com&shell_version=$(gnome-shell --version | awk '{print $3}')" \
  | python3 -c 'import sys,json,urllib.parse; d=json.load(sys.stdin); print("https://extensions.gnome.org"+d["download_url"])'

# Download and install
curl -sfL -o /tmp/vitals.zip "<url from above>"
gnome-extensions install --force /tmp/vitals.zip

# Add to enabled list (gnome-extensions enable can't see it until shell reloads,
# so set the gsetting directly)
gsettings set org.gnome.shell enabled-extensions \
  "$(gsettings get org.gnome.shell enabled-extensions \
     | python3 -c 'import sys,ast; xs=ast.literal_eval(sys.stdin.read()); xs.append("Vitals@CoreCoding.com"); print(xs)')"

# Reload GNOME Shell to pick up the new extension (Xorg only — apps stay open)
killall -HUP gnome-shell
```

On Wayland the in-place reload doesn't work; log out and back in instead.

### Voltage / fan sensors show no data

Vitals reads voltage and fan from `/sys/class/hwmon`, surfaced by
`lm-sensors`. Checked on 2026-04-25:

```sh
for h in /sys/class/hwmon/hwmon*; do
  echo "$(cat $h/name): $(ls $h | grep -Eo '^(fan|in|curr|power)[0-9]+_input' | sort -u | tr '\n' ' ')"
done
```

All 10 hwmon devices on this box (`acpitz`, `nvme`, `r8169`, four `mlx5`,
`mt7925_phy0`, two HID battery nodes) expose only `tempN_input` — no
`fan*_input`, no `in*_input`, no `curr*` / `power*`. So even after
`apt install lm-sensors && sensors-detect`, Vitals' fan/voltage panels
would stay empty. Temperature panels work without `lm-sensors` (Vitals
reads `tempN_input` directly).

## Software to install

User-space tooling that should be present on this box. Add to the list as
new things become standard.

### Telegram

```sh
sudo snap install telegram-desktop
```

(arm64 build is published in the Snap Store. Alternatively, install the
official `.tar.xz` from <https://desktop.telegram.org/> if you'd rather
avoid snap.)

### Web browser (Chromium, not Chrome)

Google does not publish Google Chrome for Linux ARM64 — the only Linux
builds Google ships are amd64. The closest equivalent on this box is
**Chromium**, the open-source upstream Chrome is built from. Install via
snap (the Ubuntu archive `chromium-browser` package is itself a snap
shim, so this is the supported path):

```sh
sudo snap install chromium
```

Firefox is also available (`sudo snap install firefox`) and ships
preinstalled on most Ubuntu desktop images.

#### Blank new tab and homepage (Firefox)

By default Firefox opens new tabs at `about:newtab` (activity stream:
top sites, recommended stories, sponsored tiles) and the homepage / new
windows at `about:home` (similar content). To make both completely
empty, two prefs are involved:

- `browser.newtabpage.enabled = false` — new tabs fall back to
  `about:blank`.
- `browser.startup.homepage = "about:blank"` — homepage and new windows
  use `about:blank`.

Either flip both to "Blank Page" in `about:preferences#home`, or pin
them in `user.js` so they survive a profile reset:

```sh
# active profile = the Default= line under [Install...] in profiles.ini
profile=$(awk -F= '/^\[Install/ {f=1; next} f && /^Default=/ \
    {print $2; exit}' ~/.mozilla/firefox/profiles.ini)
cat >> ~/.mozilla/firefox/"$profile"/user.js <<'EOF'
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.startup.homepage", "about:blank");
EOF
```

`user.js` is re-applied on every Firefox start, so this overrides any
later UI change. Restart Firefox to take effect.

### Claude Code

Anthropic's official CLI. ARM64 Linux is supported.

Install via the official shell installer at <https://claude.ai/install.sh>
(it drops the `claude` binary into `~/.local/bin`). Full install
instructions and alternative methods are at
<https://docs.claude.com/en/docs/claude-code>.

Verify with `claude --version`. On first launch, `claude` prompts an
interactive login.

#### Font fix for Claude Code glyph rendering

Claude Code's TUI uses Unicode symbols like `⏵` (U+23F5,
"Black Medium Right-Pointing Triangle") in its status line — e.g. the
`⏵⏵ auto mode on` indicator. These live in the *Miscellaneous Technical*
block, which `DejaVu Sans Mono` and `Noto Mono` (the only mono fonts
shipped on this box by default) don't cover, so they render as tofu /
hex codepoint boxes. Tracked upstream as
[anthropics/claude-code#24102](https://github.com/anthropics/claude-code/issues/24102).

Workaround installed: `fonts-symbola`, which fontconfig now uses as the
fallback for these glyphs.

```sh
sudo apt install fonts-symbola
fc-cache -f
# verify U+23F5 has a covering font:
fc-match -s ':charset=23F5' | head -1   # → Symbola
```

Restart any open terminals after install to pick up the new fontconfig
cache.

### Codex CLI

OpenAI's Codex CLI, distributed on npm as `@openai/codex` (ARM64 Linux is
supported — the package ships a prebuilt aarch64 binary).

```sh
npm install -g @openai/codex
```

The npm global prefix on this box is the unpacked Node tarball directory
itself (`/home/htong/.local/node-v22.11.0-linux-arm64`), so the binary lands
at `<prefix>/bin/codex` — which is **not** on `PATH`. `~/.local/bin` is on
`PATH` and already holds symlinks to `node` and `npm` pointing into that
prefix; symlink `codex` the same way:

```sh
ln -s /home/htong/.local/node-v22.11.0-linux-arm64/bin/codex \
      ~/.local/bin/codex
```

Verify with `codex --version`. First launch prompts an interactive sign-in.

Any future `npm install -g <pkg>` that ships a CLI binary will need the
same symlink treatment unless the npm prefix is moved to `~/.local`
(`npm config set prefix ~/.local`), which would put `bin/` directly on
`PATH` but mix npm-managed files into the same tree as everything else
under `~/.local`.

### VS Code

Microsoft publishes an aarch64 `code` package in their apt repo, so the
clean install path is to add the repo and let `apt` manage updates (rather
than dropping a one-off `.deb` or going through snap, which on this box
would be a second package manager for one app).

```sh
# Microsoft GPG key → /etc/apt/keyrings
wget -qO- https://packages.microsoft.com/keys/microsoft.asc \
  | gpg --dearmor | sudo install -D -o root -g root -m 644 /dev/stdin \
      /etc/apt/keyrings/packages.microsoft.gpg

# Repo entry (deb822 format, arm64 only)
sudo tee /etc/apt/sources.list.d/vscode.sources >/dev/null <<'EOF'
Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: arm64
Signed-By: /etc/apt/keyrings/packages.microsoft.gpg
EOF

sudo apt update
sudo apt install -y code
```

Verify with `code --version`. The `code` CLI is on `PATH` after install,
so `code .` from a terminal opens the current directory in a window.

#### Disable Copilot and telemetry

Stock VS Code bundles GitHub Copilot / Copilot Chat as built-in extensions
and ships chat surface area in the title bar even when no account is
signed in. Two settings in `~/.config/Code/User/settings.json` turn the
whole thing off:

```json
{
    "chat.disableAIFeatures": true,
    "telemetry.telemetryLevel": "off"
}
```

- `chat.disableAIFeatures` is the single MS-blessed switch that "disables
  and hides features like chat or inline suggestions in VS Code and
  disables the Copilot extensions" — no need to uninstall the bundled
  Copilot extensions separately.
- `telemetry.telemetryLevel: "off"` covers VS Code's own telemetry to
  Microsoft, which is independent of Copilot. Set this if you don't want
  editor usage data leaving the box regardless of Copilot state.

Reload the window (`Ctrl+Shift+P → Developer: Reload Window`) for the
chat UI to disappear.

## Shell

Default shell is bash (`/bin/bash`); zsh is not installed. The repo keeps a
shared aliases/functions file at the repo root [`../.zshrc`](../.zshrc) that
both the macOS (zsh) and Spark (bash) setups source — most aliases are
shell-agnostic. The macOS-only ones (`caffeinate`, the `code` shim that
calls `open -a`) are wrapped in a `case "$(uname -s)" in Darwin) … ;;`
guard, so they don't trigger under bash on Linux. (`code` on Linux is
provided as a real binary by the VS Code .deb at `/usr/bin/code`; no
alias needed.)

`~/.bashrc` ends with:

```bash
if [ -f "$HOME/Desktop/macOS_setup/.zshrc" ]; then
    . "$HOME/Desktop/macOS_setup/.zshrc"
fi
```

So edits to the repo's `.zshrc` apply to new shells on this box without any
further action.

## Remote access

SSH-from-anywhere is set up via a Cloudflare Tunnel — the public hostname
`spark.huikang.dev` proxies to `localhost:22` on this box. Full details
(architecture, server config, client setup, debugging) live in
[`ssh.md`](./ssh.md).

## Inference

A vLLM OpenAI-compatible server runs as a systemd-managed Docker container
on `127.0.0.1:8000` and is exposed via the same Cloudflare Tunnel at
`https://vllm.huikang.dev`. Setup, model switching, auth, and ops live in
[`vllm.md`](./vllm.md).

## Useful one-liners for this box

```sh
# Quick health snapshot
nvidia-smi --query-gpu=name,driver_version,utilization.gpu,power.draw,temperature.gpu --format=csv

# Confirm GPU driver is actually in charge of the display
ls -l /sys/class/drm/card*    # card1 → pci..., not simple-framebuffer

# Confirm HDMI audio sink is real (not "Dummy Output")
wpctl status | sed -n '/^Audio/,/^Video/p'

# Read the connected monitor's EDID identity
python3 -c '
d=open("/sys/class/drm/card1-HDMI-A-1/edid","rb").read()
m=int.from_bytes(d[8:10],"big")
print(chr(((m>>10)&31)+64)+chr(((m>>5)&31)+64)+chr((m&31)+64),
      "prod=", int.from_bytes(d[10:12],"little"))
for i in (54,72,90,108):
    b=d[i:i+18]
    if b[:3]==b"\\x00\\x00\\x00" and b[3] in (0xfc,0xff):
        print(("name" if b[3]==0xfc else "serial")+":",
              b[5:18].split(b"\\n")[0].decode("ascii","replace").strip())
'
```
