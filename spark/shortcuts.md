# GNOME Terminal Shortcuts

> **Mac-style ⌘ shortcuts:** Toshy is installed (2026-07-03), so on the
> Magic Keyboard `⌘+C` / `⌘+V` / `⌘+T` / `⌘+W` are rewritten to the
> `Ctrl+Shift+…` terminal shortcuts below, and `⌘+.` sends `Ctrl+C`
> (SIGINT). Physical `Ctrl+C` still interrupts as normal. Details in
> [`toshy.md`](./toshy.md).

## Tabs

| Action | Shortcut |
| --- | --- |
| Next tab | `Ctrl+Right` (custom) or `Ctrl+PageDown` |
| Previous tab | `Ctrl+Left` (custom) or `Ctrl+PageUp` |
| Jump to tab N (1–9) | `Alt+1` … `Alt+9` |
| Move tab right | `Ctrl+Shift+PageDown` |
| Move tab left | `Ctrl+Shift+PageUp` |
| New tab | `Ctrl+Shift+T` |
| Close tab | `Ctrl+Shift+W` |

> **Note:** `Ctrl+Left` / `Ctrl+Right` are bound at the terminal level, which overrides readline's word-jump on the command line. To restore word-jump there, use `Alt+B` / `Alt+F` instead.

Apply the custom binding with:

```bash
gsettings set org.gnome.Terminal.Legacy.Keybindings:/org/gnome/terminal/legacy/keybindings/ next-tab '<Primary>Right'
gsettings set org.gnome.Terminal.Legacy.Keybindings:/org/gnome/terminal/legacy/keybindings/ prev-tab '<Primary>Left'
```

## Windows

| Action | Shortcut |
| --- | --- |
| New window | `Ctrl+Shift+N` |
| Close window | `Ctrl+Shift+Q` |
| Toggle fullscreen | `F11` |

## Editing

| Action | Shortcut |
| --- | --- |
| Copy | `Ctrl+Shift+C` |
| Paste | `Ctrl+Shift+V` |
| Select all | `Ctrl+Shift+A` |
| Find | `Ctrl+Shift+F` |
| Find next | `Ctrl+Shift+G` |
| Find previous | `Ctrl+Shift+H` |
| Clear screen | `Ctrl+L` |

## Zoom

| Action | Shortcut |
| --- | --- |
| Zoom in | `Ctrl++` |
| Zoom out | `Ctrl+-` |
| Reset zoom | `Ctrl+0` |
