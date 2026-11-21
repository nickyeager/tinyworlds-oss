#!/usr/bin/env bash
# Build a Bevy project to a browser-ready WASM bundle.
# Usage: bevy_build.sh <project_dir>
# Writes: <project_dir>/dist/{<crate>.js, <crate>_bg.wasm, index.html}
set -euo pipefail

PROJECT_DIR="${1:?usage: bevy_build.sh <project_dir>}"
: "${CARGO_TARGET_DIR:?must be set (normally provided by the bevy-builder docker image)}"
cd "$PROJECT_DIR"

# Extract [package].name. Strip both single and double quotes (TOML allows
# either). Awk's first match wins; if Cargo.toml is a workspace root with no
# [package] section, CRATE_NAME comes back empty and we bail explicitly so
# the user gets a clear error instead of a confusing wasm-bindgen "file not
# found" later.
CRATE_NAME="$(awk -F' *= *' "/^name *=/ {gsub(/['\\''\"]/,\"\",\$2); print \$2; exit}" Cargo.toml)"
if [[ -z "$CRATE_NAME" ]]; then
  echo "[bevy_build] error: could not extract [package].name from $PROJECT_DIR/Cargo.toml" >&2
  exit 1
fi

DIST="$PROJECT_DIR/dist"
TEMPLATE="${BEVY_INDEX_TEMPLATE:-/app/templates/bevy_index.html}"

echo "[bevy_build] crate=$CRATE_NAME target=$CARGO_TARGET_DIR"

cargo fetch --target wasm32-unknown-unknown

# Resolve first so incompatible bindings fail before expensive compilation.
# Cargo.lock now exists. Assert the wasm-bindgen crate the project resolved
# matches the wasm-bindgen-cli installed in the image. A mismatch produces
# ABI-incompatible JS glue and the page fails at runtime with cryptic
# "function signature mismatch" — much better to bail here.
WB_RESOLVED="$(awk '/^name = "wasm-bindgen"$/{getline; gsub(/version = |"/, ""); print; exit}' Cargo.lock)"
WB_INSTALLED="$(wasm-bindgen --version | awk '{print $2}')"
if [[ -n "$WB_RESOLVED" && "$WB_RESOLVED" != "$WB_INSTALLED" ]]; then
  echo "[bevy_build] error: wasm-bindgen version mismatch" >&2
  echo "  Cargo.lock resolved: $WB_RESOLVED" >&2
  echo "  installed in image:  $WB_INSTALLED" >&2
  echo "  fix: pin wasm-bindgen = \"=$WB_INSTALLED\" in Cargo.toml, or deliberately update the builder toolchain" >&2
  exit 1
fi

cargo build --locked --release --target wasm32-unknown-unknown

WASM_INPUT="$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/${CRATE_NAME}.wasm"
mkdir -p "$DIST"

wasm-bindgen --target web --no-typescript --out-dir "$DIST" "$WASM_INPUT"

# wasm-opt is best-effort; -Oz is slow but worth it for ship size.
#
# IMPORTANT: enable only the features rustc + wasm-bindgen actually emit.
# The previous `--all-features` enabled reference-types AND gc, which let
# wasm-opt's optimization passes write `ref null heap-type` bytes (0x6B)
# into the type section. Chrome's V8 then rejected the binary at
# instantiateStreaming with "invalid value type 0x6B at offset N" and the
# user saw a black canvas with no diagnostic. Confirmed root cause of
# bevy-4b86463c failure 2026-05-11.
if command -v wasm-opt >/dev/null 2>&1; then
  wasm-opt \
    --enable-bulk-memory \
    --enable-sign-ext \
    --enable-multivalue \
    --enable-mutable-globals \
    --enable-nontrapping-float-to-int \
    -Oz \
    -o "$DIST/${CRATE_NAME}_bg.wasm.opt" \
    "$DIST/${CRATE_NAME}_bg.wasm"
  mv "$DIST/${CRATE_NAME}_bg.wasm.opt" "$DIST/${CRATE_NAME}_bg.wasm"
fi

sed -e "s/{{title}}/${CRATE_NAME}/g" -e "s/{{module}}/${CRATE_NAME}/g" \
    "$TEMPLATE" > "$DIST/index.html"

echo "[bevy_build] done: $DIST"
ls -lh "$DIST"
