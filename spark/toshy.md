# Toshy — macOS-style keybindings (⌘+C / ⌘+V etc.)

Installed 2026-07-03 so the Apple Magic Keyboard's Command key works like
it does on a Mac: `⌘+C` copies everywhere — including in terminals, where
plain `Ctrl+C` still sends SIGINT. Background on why a kernel-level
Cmd/Ctrl swap is the wrong tool is in
[`setup.md` → "Magic Keyboard: ⌘ → Super"](./setup.md).

- Source: <https://github.com/RedBearAK/toshy> (GPL-3.0), cloned to
  `~/toshy`, installed with `./setup_toshy.py install`
- Installed at commit `b6f9e1a` (2026-07-03); config service version
  `20250822`, keymapper engine `xwaykeyz` v1.23.3
- The installer needs sudo (native apt packages only, then `sudo -k`),
  creates `~/.config/toshy/` with its own Python venv, and adds the user
  to the `input` group — **log out/in once after install** before it works.
- Vetted before install: repo public since 2023, ~1k stars, plain
  readable installer, no `curl | bash` / obfuscated code. Note that any
  evdev keymapper necessarily reads every keystroke — that trust applies
  to Toshy, Kinto, keyd, and the whole category alike.

## How it works

Toshy's keymapper (`xwaykeyz`, RedBearAK's fork of the
keyszer/xkeysnail lineage) grabs input devices exclusively at the evdev
level and re-emits translated events through a uinput virtual device
named `XWayKeyz (virtual) Keyboard`. On this box it grabs:

- `Apple Inc. Magic Keyboard`
- **both** `Apple Inc. Magic Trackpad` event nodes — the trackpad
  advertises keyboard-like capabilities, so the keyboard autodetect
  picks it up too. Harmless in practice (pointer events pass through),
  but worth knowing when debugging input weirdness: `xwaykeyz` is in
  the path for the trackpad as well.

Remaps are **per-focused-app**: on this Xorg session it reads
`_NET_ACTIVE_WINDOW` → `WM_CLASS` via python-xlib. The terminal keymap
matches this box's gnome-terminal (`WM_CLASS = gnome-terminal-server`).

## What the keys do now

GUI apps: `⌘+C/V/X/Z/A/F/T/W/N …` are translated to their `Ctrl+…`
equivalents, plus a large set of Mac-behavior extras (`⌘+Tab` app
switching, `⌘+Space` launcher, wordwise `⌥/⌘+Backspace`, …).

Terminals get a dedicated keymap (the point of using Toshy at all):

| Mac habit | Toshy sends | Effect in gnome-terminal |
| --- | --- | --- |
| `⌘+C` | `Ctrl+Shift+C` | Copy (**`Ctrl+C` still = SIGINT**) |
| `⌘+V` | `Ctrl+Shift+V` | Paste |
| `⌘+.` | `Ctrl+C` | Cancel command, Mac-style |
| `⌘+T` / `⌘+W` | `Ctrl+Shift+T` / `Ctrl+Shift+W` | New / close tab |
| `⌘+F` | `Ctrl+Shift+F` | Find |
| `⌘+N` | `Ctrl+Shift+N` | New window |
| `⌘+Backspace` | `Ctrl+U` | Delete line left of cursor |
| `⌥+Backspace` | `Ctrl+W` | Delete word left of cursor |

App-specific keymaps sit on top (VS Code, browsers, file managers) —
e.g. VS Code's copy is sent as `Ctrl+Insert` instead, so `Ctrl+Shift+C`
stays available there. Full mappings: `~/.config/toshy/toshy_config.py`.

## Services & ops

Two systemd **user** services (plus a tray icon app started via
autostart):

```sh
systemctl --user status toshy-config     # the actual keymapper
systemctl --user status toshy-session-monitor
journalctl --user -u toshy-config -b     # logs
```

- Tray icon (Toshy) can pause/resume remapping, restart services, and
  toggle options without touching the CLI.
- CLI equivalents: `toshy-services-restart`, `toshy-services-status`,
  `toshy-config-start-verbose` (foreground, per-keystroke debug — stop
  the service first) — all in `~/.local/bin`.
- **Log caveat:** the service's stdout is block-buffered, so the
  `(+K) Grabbing …` / `Ready to process input` lines may not appear in
  the journal until the process exits. An apparently "stuck" log right
  after boot does not mean the grab failed — verify directly:

```sh
# which event devices the keymapper actually holds
ls -l /proc/$(pgrep -f 'bin/xwaykeyz')/fd | grep -o 'event[0-9]*' | sort -u
```

## Config file

`~/.config/toshy/toshy_config.py`. User customizations belong inside
the `SLICE_MARK_START/END` blocks (e.g. `user_custom_lists`,
`user_apps`) — the installer preserves those slices across upgrades and
**overwrites everything else**. There are commented-out
`keymap("User overrides terminals", …)` stubs near the top of the
keymap section to copy from.

Upgrade = `git -C ~/toshy pull && ~/toshy/setup_toshy.py install`
(re-runs are supported; slices are carried over).

## Debugging a "copy/paste doesn't work" report

Chain to check, in order:

1. **Grab active?** — `/proc/<xwaykeyz pid>/fd` trick above.
2. **Window context right?** — the terminal must be detected as a
   terminal, or `⌘+C` becomes `Ctrl+C` (= SIGINT!). Quick check that the
   focused window's `WM_CLASS` is in the config's `terminals` list
   (`gnome-terminal-server` is).
3. **What is Toshy actually emitting?** — snoop the virtual keyboard's
   output while pressing the key (reader must be in the `input` group):

   ```sh
   # find the virtual device node
   grep -A4 'XWayKeyz' /proc/bus/input/devices | grep -o 'event[0-9]*'
   # then read EV_KEY events off it with python-evdev
   # (~/.config/toshy/.venv has evdev installed)
   ```

4. **Terminal side** — gnome-terminal's Copy accelerator silently does
   nothing when there is **no active selection**, and VTE drops the
   selection whenever the selected screen area is redrawn. Full-screen
   TUIs that repaint constantly (Claude Code's spinner/status line) can
   clear a selection between "select" and "press ⌘+C". Selecting older
   scrollback text away from the repainting region avoids it.

### Known issue: copying out of Claude Code (diagnosed 2026-07-04)

`⌘+C` copy works in GUI apps, plain shells, and Codex CLI, but copying
text out of a running Claude Code TUI is unreliable. Diagnosis:

- Toshy's side is correct — a live capture of the virtual keyboard
  showed `⌘+C` in the Claude Code window emitting
  `RightCtrl+Shift+C`, and gnome-terminal's `copy` binding is the
  default `<Control><Shift>c`, enabled.
- Terminal modes are not the cause: Claude Code enables bracketed
  paste + kitty keyboard protocol but **no mouse tracking**; Codex
  enables the same kitty protocol *plus* mouse tracking and copying
  from it works fine.
- Root cause is item 4 above: **Claude Code (Ink-based) repaints its
  frame continuously whenever a turn is running** (spinner, token
  counter, status line), and VTE drops the mouse selection the moment
  the selected region is redrawn — so by the time `Ctrl+Shift+C`
  arrives there is no selection and gnome-terminal silently copies
  nothing. Codex (ratatui) diff-renders and leaves quiet cells alone,
  so selections there survive.

In practice: **copy from Claude Code while it is idle** (no spinner
running) and it works normally. For grabbing text mid-generation, use
`/export` to push the conversation to the clipboard (needs
`sudo apt install xclip`), or ask Claude to write the output to a file.
