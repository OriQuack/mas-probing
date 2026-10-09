#!/bin/bash
# Build the doh_minpilot conda env: min_pilot (no camel/OWL) + Chromium for the Playwright page reader.
# Usage (from the repo root, CPU-only):
#   bash envs/doh_minpilot/setup.sh                  # install the exact versions in requirements.lock (default)
#   UPDATE_LOCK=1 bash envs/doh_minpilot/setup.sh    # resolve requirements.txt anew and rewrite requirements.lock
# The lock is the reproducible input; requirements.txt only lists what to resolve when updating it.
set -euo pipefail

ENV_NAME=doh_minpilot
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export CONDA_ENVS_PATH="$HOME/.conda/envs" CONDA_PKGS_DIRS="$HOME/.conda/pkgs"
source /home/compu/anaconda3/etc/profile.d/conda.sh

conda env list | grep -q "^$ENV_NAME " || conda create -n "$ENV_NAME" python=3.11 -y
# Chromium (Playwright) needs these shared libs; the host lacks them and we have no sudo to apt-install.
conda install -n "$ENV_NAME" -c conda-forge -y alsa-lib at-spi2-atk at-spi2-core libgbm

PREFIX="$HOME/.conda/envs/$ENV_NAME"
PY="$PREFIX/bin/python"

LOCK="$REPO_ROOT/envs/$ENV_NAME/requirements.lock"
if [ "${UPDATE_LOCK:-0}" = "1" ]; then
    "$PY" -m pip install -r "$REPO_ROOT/envs/$ENV_NAME/requirements.txt"
    "$PY" -m pip freeze --exclude-editable > "$LOCK"
    echo "Rewrote $LOCK; review and commit it."
else
    "$PY" -m pip install -r "$LOCK"
fi
"$PY" -m pip install --no-deps -e "$REPO_ROOT"
"$PY" -m playwright install chromium

# Expose only the 4 Chromium libs (not all of $PREFIX/lib, which would shadow system libs like libtinfo).
mkdir -p "$PREFIX/chromium_libs" "$PREFIX/etc/conda/activate.d" "$PREFIX/etc/conda/deactivate.d"
for l in libasound.so.2 libatk-bridge-2.0.so.0 libatspi.so.0 libgbm.so.1; do
    ln -sf "$PREFIX/lib/$l" "$PREFIX/chromium_libs/$l"
done
cat > "$PREFIX/etc/conda/activate.d/chromium_libs.sh" <<'EOS'
export _DOH_MINPILOT_OLD_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="$CONDA_PREFIX/chromium_libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
EOS
cat > "$PREFIX/etc/conda/deactivate.d/chromium_libs.sh" <<'EOS'
export LD_LIBRARY_PATH="${_DOH_MINPILOT_OLD_LD_LIBRARY_PATH:-}"; unset _DOH_MINPILOT_OLD_LD_LIBRARY_PATH
[ -z "$LD_LIBRARY_PATH" ] && unset LD_LIBRARY_PATH
EOS

echo "Done. Activate with: conda activate $ENV_NAME"
