#!/usr/bin/env bash
# Merge a native arm64 .app and a native x86_64 .app into one Universal2 .app.
#
# PyInstaller can't emit a universal2 build here because deps like numpy/pyarrow
# ship arch-only wheels (no fat wheel to bundle). So we build the app natively on
# each arch, then lipo every Mach-O binary together — that fattens even the
# thin-wheel deps, which --target-arch universal2 cannot.
#
#   ./merge_universal.sh <arm64.app> <x86_64.app> <out.app>
#
# The result is ad-hoc codesigned (signing must happen AFTER lipo, which would
# otherwise invalidate any per-arch signature).
set -euo pipefail

ARM_APP="${1:?arm64 .app path}"
X86_APP="${2:?x86_64 .app path}"
OUT_APP="${3:?output .app path}"

for d in "$ARM_APP" "$X86_APP"; do
  [ -d "$d" ] || { echo "Error: $d not found." >&2; exit 1; }
done

echo "Seeding universal tree from arm64 build..."
rm -rf "$OUT_APP"
cp -R "$ARM_APP" "$OUT_APP"

is_macho() { file -b "$1" | grep -q 'Mach-O'; }

# Pass 1: for every file in the (arm64-seeded) output that also exists in the
# x86_64 build and is a thin Mach-O, lipo the two slices into a fat binary.
echo "Fattening Mach-O binaries (arm64 + x86_64)..."
fattened=0
while IFS= read -r -d '' f; do
  rel="${f#"$OUT_APP"/}"
  x="$X86_APP/$rel"
  [ -f "$x" ] || continue
  is_macho "$f" || continue
  # Skip if already universal (contains x86_64 slice).
  if lipo -archs "$f" 2>/dev/null | grep -qw 'x86_64'; then continue; fi
  if lipo -create "$f" "$x" -output "$f.__univ" 2>/dev/null; then
    mv "$f.__univ" "$f"
    fattened=$((fattened + 1))
  else
    rm -f "$f.__univ"  # same-arch or non-lipoable; leave arm64 copy
  fi
done < <(find "$OUT_APP" -type f -print0)
echo "  fattened $fattened binaries"

# Pass 2: copy over any file that exists ONLY in the x86_64 build (arch-specific
# module the arm64 build didn't produce), so the universal app isn't missing an
# Intel-only dependency.
echo "Adding x86_64-only files..."
added=0
while IFS= read -r -d '' x; do
  rel="${x#"$X86_APP"/}"
  out="$OUT_APP/$rel"
  if [ ! -e "$out" ]; then
    mkdir -p "$(dirname "$out")"
    cp -R "$x" "$out"
    added=$((added + 1))
  fi
done < <(find "$X86_APP" -type f -print0)
echo "  added $added files"

echo "Ad-hoc codesigning the universal app..."
codesign --remove-signature "$OUT_APP" 2>/dev/null || true
codesign --force --deep --sign - "$OUT_APP"
# Top-level must pass; the deep walk hits the bundled Chromium.app, which trips
# --strict after PyInstaller's copy + lipo. Warn instead of failing the build.
codesign --verify --strict "$OUT_APP"
codesign --verify --deep --strict "$OUT_APP" \
  || echo "WARNING: deep verify failed (usually the bundled Chromium) — app signature itself is valid."

# The bundled Chromium has to be fat too. Pass 1 leaves the arm64 copy in place
# when lipo fails, which would ship an Intel user a browser that cannot start —
# silently, since nothing else touches it until the first publish.
CHROME="$(find "$OUT_APP" -path '*chrome-mac*/Chromium.app/Contents/MacOS/Chromium' -print -quit)"
if [ -z "$CHROME" ]; then
  echo "Error: no bundled Chromium in the merged app." >&2
  exit 1
fi
CHROME_ARCHS="$(lipo -archs "$CHROME" 2>/dev/null || echo '?')"
case "$CHROME_ARCHS" in
  *x86_64*arm64* | *arm64*x86_64*) ;;
  *) echo "Error: bundled Chromium is not universal ($CHROME_ARCHS)." >&2; exit 1 ;;
esac

BIN="$OUT_APP/Contents/MacOS/My Maps Generator"
echo
echo "Done. Universal app: $OUT_APP  ($(du -sh "$OUT_APP" | cut -f1))"
echo "  arch: $(lipo -archs "$BIN" 2>/dev/null || echo '?')"
echo "  bundled Chromium: $CHROME_ARCHS"
