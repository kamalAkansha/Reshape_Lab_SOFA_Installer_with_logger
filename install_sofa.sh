#!/usr/bin/env bash
# =============================================================================
# install_sofa.sh  --  one-shot SOFA Defrost Bundle installer
#
# What it does:
#   1. Checks / installs git, curl, unzip, podman
#   2. Clones https://github.com/ARNAVVGUPTAA/Reshape_Lab_SOFA_Installer_with_logger
#      to get the Dockerfile and gripper_logger.py
#   3. Downloads + extracts the DefrostSofaBundle from GitHub releases
#   4. Builds the podman image from the cloned Dockerfile
#   5. Installs gripper_logger.py as sofa.gripper_logger inside the bundle
#      so  "from sofa import gripper_logger"  works in any scene
#   6. Writes the sofa + sp aliases to bash / zsh / fish
#
# Usage:
#   bash install_sofa.sh
#
# Env overrides (all optional):
#   SOFA_INSTALL_DIR   parent dir for the bundle   (default: ~/dev/sofa)
#   SOFA_BUNDLE_VER    release tag                 (default: v22.06.01)
#   SOFA_PYTHON_VER    python slot in bundle name  (default: python3.10)
# =============================================================================

set -euo pipefail

REPO_URL="https://github.com/ARNAVVGUPTAA/Reshape_Lab_SOFA_Installer_with_logger"
INSTALL_DIR="${SOFA_INSTALL_DIR:-$HOME/dev/sofa}"
BUNDLE_VER="${SOFA_BUNDLE_VER:-v22.06.01}"
PYTHON_VER="${SOFA_PYTHON_VER:-python3.10}"
IMAGE_NAME="sofa-defrost-env"

BUNDLE_NAME="DefrostSofaBundle_linux_${PYTHON_VER}_${BUNDLE_VER}"
BUNDLE_DIR="$INSTALL_DIR/$BUNDLE_NAME"
CLONE_DIR="$INSTALL_DIR/.sofa_installer_src"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
_b='\033[1m'; _blu='\033[34m'; _grn='\033[32m'; _red='\033[31m'; _r='\033[0m'
banner() { printf "\n${_b}==> %s${_r}\n"    "$*"; }
info()   { printf "  ${_blu}..${_r} %s\n"   "$*"; }
ok()     { printf "  ${_grn}ok${_r} %s\n"   "$*"; }
warn()   { printf "  ${_b}!!${_r} %s\n"     "$*"; }
die()    { printf "  ${_red}ERROR${_r} %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# OS guard -- Linux only
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Linux" ]] || die "This script is Linux only."

# ---------------------------------------------------------------------------
# 1. Dependencies
# ---------------------------------------------------------------------------
banner "Checking dependencies"

install_pkg() {
    local pkg="$1"
    if command -v "$pkg" &>/dev/null; then
        ok "$pkg"
        return
    fi
    info "Installing $pkg ..."
    if   command -v apt-get &>/dev/null; then sudo apt-get install -y "$pkg"
    elif command -v dnf     &>/dev/null; then sudo dnf     install -y "$pkg"
    elif command -v pacman  &>/dev/null; then sudo pacman  -S --noconfirm "$pkg"
    else
        die "No supported package manager (apt/dnf/pacman). Install $pkg manually and re-run."
    fi
    ok "$pkg installed"
}

install_pkg git
install_pkg curl
install_pkg unzip
install_pkg podman

# ---------------------------------------------------------------------------
# 2. Clone installer repo (Dockerfile + gripper_logger.py live here)
# ---------------------------------------------------------------------------
banner "Installer repo"

mkdir -p "$INSTALL_DIR"

if [[ -d "$CLONE_DIR/.git" ]]; then
    info "Repo already cloned at $CLONE_DIR -- pulling latest ..."
    git -C "$CLONE_DIR" pull --ff-only
    ok "Up to date"
else
    info "Cloning $REPO_URL ..."
    git clone --depth 1 "$REPO_URL" "$CLONE_DIR"
    ok "Cloned to $CLONE_DIR"
fi

[[ -f "$CLONE_DIR/Dockerfile"        ]] || die "Dockerfile not found in cloned repo."
[[ -f "$CLONE_DIR/gripper_logger.py" ]] || die "gripper_logger.py not found in cloned repo."

# ---------------------------------------------------------------------------
# 3. Download + extract DefrostSofaBundle
# ---------------------------------------------------------------------------
banner "SOFA Defrost Bundle"

BUNDLE_URL="https://github.com/SofaDefrost/DefrostSofaBundle/releases/download/${BUNDLE_VER}/${BUNDLE_NAME}.zip"

if [[ -d "$BUNDLE_DIR" ]]; then
    ok "Bundle already at $BUNDLE_DIR -- skipping download"
else
    info "Downloading $BUNDLE_NAME.zip ..."
    curl -L --progress-bar -o "/tmp/${BUNDLE_NAME}.zip" "$BUNDLE_URL" \
        || die "Download failed. Check SOFA_BUNDLE_VER / SOFA_PYTHON_VER or your connection."
    info "Extracting ..."
    unzip -q "/tmp/${BUNDLE_NAME}.zip" -d "$INSTALL_DIR"
    rm -f "/tmp/${BUNDLE_NAME}.zip"
    ok "Extracted to $BUNDLE_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Build podman image
# ---------------------------------------------------------------------------
banner "Podman image"

if podman image exists "$IMAGE_NAME" 2>/dev/null; then
    ok "Image '$IMAGE_NAME' already exists -- skipping build"
else
    info "Building '$IMAGE_NAME' from $CLONE_DIR/Dockerfile (this may take a few minutes) ..."
    podman build -t "$IMAGE_NAME" -f "$CLONE_DIR/Dockerfile" "$CLONE_DIR"
    ok "Image built: $IMAGE_NAME"
fi

# ---------------------------------------------------------------------------
# 5. Install gripper_logger as sofa.gripper_logger
#
#    Bundle layout:
#      $BUNDLE_DIR/
#        sofa/
#          __init__.py
#          gripper_logger.py      <-- from cloned repo
#
#    The alias passes -e PYTHONPATH=/bundle so inside the container
#    "from sofa import gripper_logger" resolves to /bundle/sofa/gripper_logger.py
# ---------------------------------------------------------------------------
banner "gripper_logger"

SOFA_PKG="$BUNDLE_DIR/sofa"
mkdir -p "$SOFA_PKG"

[[ -f "$SOFA_PKG/__init__.py" ]] || \
    printf '# sofa package -- custom utilities for DefrostSofaBundle\n' \
    > "$SOFA_PKG/__init__.py"

cp "$CLONE_DIR/gripper_logger.py" "$SOFA_PKG/gripper_logger.py"
ok "gripper_logger.py installed at $SOFA_PKG/gripper_logger.py"

# ---------------------------------------------------------------------------
# 6. Shell aliases
#
#   sofa  -- xhost + podman run with bundle mounted + PYTHONPATH=/bundle
#   sp    -- web_search startpage
# ---------------------------------------------------------------------------
banner "Shell aliases"

detect_shell_rc() {
    if   [[ -f "$HOME/.zshrc" ]];       then echo "zsh:$HOME/.zshrc"
    elif [[ -f "$HOME/.bashrc" ]];      then echo "bash:$HOME/.bashrc"
    elif [[ -d "$HOME/.config/fish" ]]; then echo "fish:$HOME/.config/fish/config.fish"
    elif [[ -n "${SHELL:-}" ]]; then
        case "$(basename "$SHELL")" in
            zsh)  echo "zsh:$HOME/.zshrc" ;;
            fish) echo "fish:$HOME/.config/fish/config.fish" ;;
            *)    echo "bash:$HOME/.bashrc" ;;
        esac
    else
        echo "bash:$HOME/.bashrc"
    fi
}

SHELL_INFO="$(detect_shell_rc)"
SHELL_TYPE="${SHELL_INFO%%:*}"
SHELL_RC="${SHELL_INFO##*:}"
info "Shell: $SHELL_TYPE  -->  $SHELL_RC"

write_alias_bash_zsh() {
    local rc="$1"
    if grep -qE "^function sofa|^alias sofa=" "$rc" 2>/dev/null; then
        ok "sofa already in $rc -- skipping"
        return
    fi
    cat >> "$rc" <<RCEOF

# SOFA Defrost Bundle -- added by install_sofa.sh
function sofa() {
    xhost +local: && \\
    podman run -it --rm \\
      --net=host \\
      -e DISPLAY=\$DISPLAY \\
      -e QTWEBENGINE_DISABLE_SANDBOX=1 \\
      -e XDG_RUNTIME_DIR=/tmp/runtime-root \\
      -e PYTHONPATH=/bundle \\
      -v /tmp/.X11-unix:/tmp/.X11-unix:ro \\
      -v ${BUNDLE_DIR}:/bundle \\
      ${IMAGE_NAME}
}
alias sp='web_search startpage'
RCEOF
    ok "Aliases written to $rc"
}

write_alias_fish() {
    local cfg="$1"
    mkdir -p "$(dirname "$cfg")"
    if grep -q "^function sofa" "$cfg" 2>/dev/null; then
        ok "sofa already in $cfg -- skipping"
        return
    fi
    cat >> "$cfg" <<FISHEOF

# SOFA Defrost Bundle -- added by install_sofa.sh
function sofa
    xhost +local:
    podman run -it --rm \\
      --net=host \\
      -e DISPLAY=\$DISPLAY \\
      -e QTWEBENGINE_DISABLE_SANDBOX=1 \\
      -e XDG_RUNTIME_DIR=/tmp/runtime-root \\
      -e PYTHONPATH=/bundle \\
      -v /tmp/.X11-unix:/tmp/.X11-unix:ro \\
      -v ${BUNDLE_DIR}:/bundle \\
      ${IMAGE_NAME}
end
alias sp 'web_search startpage'
FISHEOF
    ok "sofa function written to $cfg"
}

case "$SHELL_TYPE" in
    zsh|bash) write_alias_bash_zsh "$SHELL_RC" ;;
    fish)     write_alias_fish     "$SHELL_RC" ;;
    *)
        warn "Unknown shell '$SHELL_TYPE' -- falling back to ~/.bashrc"
        write_alias_bash_zsh "$HOME/.bashrc"
        ;;
esac

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
banner "All done"

printf "  Bundle    : %s\n"   "$BUNDLE_DIR"
printf "  Image     : %s\n"   "$IMAGE_NAME"
printf "  Logger    : %s/sofa/gripper_logger.py\n" "$BUNDLE_DIR"
printf "  Shell rc  : %s\n\n" "$SHELL_RC"
printf "  Reload your shell:\n"
printf "    source %s\n\n" "$SHELL_RC"
printf "  Launch SOFA:\n"
printf "    sofa\n\n"
printf "  Inside any scene file:\n"
printf "    from sofa import gripper_logger\n\n"
