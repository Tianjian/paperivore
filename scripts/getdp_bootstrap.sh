#!/usr/bin/env bash
# Rootless GetDP install (Ubuntu/Debian) for scripts/afpm_getdp.py.
# Extracts the getdp-sparskit package and its shared-library dependencies into
# $GETDP_PREFIX (default: ~/.cache/paperivore/getdp) using apt-get download +
# dpkg -x, so no root / system change is needed.
set -euo pipefail
PREFIX="${GETDP_PREFIX:-$HOME/.cache/paperivore/getdp}"
mkdir -p "$PREFIX/debs" "$PREFIX/root"
cd "$PREFIX/debs"
PKGS=(getdp-sparskit libgsl27 libgslcblas0 libopenmpi3t64
      libevent-core-2.1-7t64 libevent-pthreads-2.1-7t64 libhwloc15 libfabric1)
for p in "${PKGS[@]}"; do
  apt-get download "$p" >/dev/null 2>&1 || echo "warn: could not download $p"
done
for d in ./*.deb; do dpkg -x "$d" "$PREFIX/root"; done
BIN="$PREFIX/root/usr/bin/getdp-sparskit"
if [ ! -x "$BIN" ]; then echo "error: $BIN not found" >&2; exit 1; fi
export LD_LIBRARY_PATH="$PREFIX/root/usr/lib/x86_64-linux-gnu:$PREFIX/root/usr/lib:${LD_LIBRARY_PATH:-}"
"$BIN" --version
echo "GetDP ready: $BIN"
echo "Use: GETDP=$BIN python scripts/afpm_getdp.py --job <dir>"
