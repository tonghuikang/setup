# macOS setup

[TOC]

## Recommended first processes

#### Initiation

- You should be given a freshly reformatted Mac with the latest OS installed.
- Do not enable Siri and Apple Pay.
- Do log in to your Apple ID if that is your intention.
- Do not forget the computer password, just write it down somewhere first.
- Please restart the computer to ensure that your password still works.

#### Essential apps

- (You should install these apps first to make installing easier)
- Google Chrome (the web browser you will be using anyway)

#### iCloud

- Create an iCloud account, remember the username and password
- If you cannot create iCloud account, try doing that in the App Store
- Please restart the computer to ensure that your password still works
- Enable Find My Mac

## Application setup

#### Personal preferences

- Hot Corners (Mission Control, Desktop, Launchpad, Put Display to Sleep)
- Dock Settings (Disable "Show suggested and recent apps in Dock")
- Date & Time (24-hour, Display the time with seconds in the menu bar)
- Keyboard 
  - Key Repeat (Fast), Delay Until Repeat (Short)
  - Text Input - Input Sources - Edit - uncheck "Add full stop with double-space", "Use smart quotes"
  - Modifer keys - Caps lock to Escape
    - (if your keyboard is broken - install Karabinder Elements)
- Finder - Favourites - add home folder
- Trackpad - Uncheck "Swipe between pages"
- Accessibility
  - Zoom (not the app) > Use scroll gesture (Command) > Advanced > Appearance > Continuously with pointer
  - Pointer Control > Trackpad Options > Enable dragging (three finger drag)
- Dark mode - Appearance - Dark

```bash
# show hidden files
defaults write com.apple.finder AppleShowAllFiles YES

# add pathbar to title
defaults write com.apple.finder _FXShowPosixPathInTitle -bool true

# restart finder
killall Finder;
```

#### Apps to download in your computer

- Chrome (if not already downloaded)
  - Stop asking to save password, use LastPass
  - Extensions
    - [Lastpass](https://chromewebstore.google.com/detail/lastpass-free-password-ma/hdokiejnpimakedhajhdlcegeplioahd)
    - [Competitive Companion](https://chromewebstore.google.com/detail/competitive-companion/cjnmckjndlpiamhfimnnjmnckgghkjbl) (for competitive programming)
    - Self-served [Jupyter Cell Filler extension](https://github.com/tonghuikang/jupyter-autocomplete)
- Zoom
- Logitech Options (if you own Logitech devices)
- VSCode

#### Allow screen recording for certain apps

- (This is so that you have less panic when you really need to screen record with those apps)
- Relevant apps: Google Chrome, Zoom, Slack, QuickTime Player
- Attempt to record screen with the app. Then go to Security & Privacy > Privacy > Screen Recording > Enable


## Development setup

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

echo >> /Users/htong/.zprofile
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> /Users/htong/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

```
brew install --cask iterm2
brew install zsh
```

Set up `~/.zshrc` - this is mine [.zshrc](./.zshrc)

```
brew install wget htop
```

```
ssh-keygen -t ed25519 -C "your_email@example.com"

eval "$(ssh-agent -s)"
touch ~/.ssh/config
open ~/.ssh/config

# add to config
Host github.com
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519

pbcopy < ~/.ssh/id_ed25519.pub
# https://github.com/settings/keys
```

```
brew install --cask obsidian
brew install --cask spotify
brew install --cask rectangle
```

Java installation tbc

Python package manager installation tbc


## Miscellaneous

#### How to fix your computer

- (no longer required for M* laptops)
  - reset NVRAM or PRAM https://support.apple.com/en-us/HT204063
  - reset the SMC https://support.apple.com/en-sg/HT201295
- run diagnostics https://support.apple.com/en-sg/HT202731
- reset the computer if all else fails https://support.apple.com/en-gb/HT208496

#### References

- https://eugeneyan.com/writing/mac-setup/
