# Installing on macOS

The Mac app (`TripMapMaker-macos-arm64.dmg`) is **ad-hoc signed but not notarized
by Apple** (notarization needs a paid Apple Developer account). It's safe — it's
just not registered with Apple — so macOS blocks the *first* launch until you
approve it once.

Apple Silicon only (M1 and newer, i.e. every Mac since late 2020).

## Install

1. Open the `.dmg` and drag **My Maps Generator** onto **Applications**.
2. Open **My Maps Generator** from Applications. macOS blocks it and shows
   *"…was blocked to protect your Mac."*
3. Open **System Settings → Privacy & Security**, scroll down to the message
   about *My Maps Generator*, and click **Open Anyway**.
4. Launch the app again and click **Open** on the confirmation. That's it — the
   approval is remembered, so future launches open normally.

## Skip the prompt entirely (optional)

To clear the block in one step instead of clicking through Settings, run this in
**Terminal** after copying the app to Applications — it removes the "downloaded
from the internet" quarantine flag so the app opens with no warning at all:

```bash
xattr -dr com.apple.quarantine "/Applications/My Maps Generator.app"
```

## Updating

Download the new `.dmg`, drag the new app over the old one in Applications. Your
keys, Google login, and settings live under `~/Library` / the app's data folder
and are untouched. If macOS re-prompts after an update, repeat the steps above.
