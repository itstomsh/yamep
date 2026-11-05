#!/bin/bash

# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Build the Flatpak for either variant, or both.
#
#   ./build-flatpak.sh full             build the full variant and bundle it
#   ./build-flatpak.sh lite --install   build, bundle and install the lite one
#   ./build-flatpak.sh both
#
# Each manifest picks its own pyproject file inside the build sandbox, so the
# variants can be built in any order and the pyproject.toml in this folder is
# never touched.
set -euo pipefail
cd "$(dirname "$0")"

REPO=yamep-repo
variants=()
install=no
bundle=yes

usage() {
    echo "Usage: $0 [full|lite|both] [--install] [--no-bundle]" >&2
    exit 2
}

for arg in "$@"; do
    case "$arg" in
        full|lite)   variants+=("$arg") ;;
        both)        variants=(full lite) ;;
        --install)   install=yes ;;
        --no-bundle) bundle=no ;;
        -h|--help)   usage ;;
        *)           echo "Unknown argument: $arg" >&2; usage ;;
    esac
done
[ ${#variants[@]} -gt 0 ] || usage

command -v flatpak-builder >/dev/null || {
    echo "flatpak-builder is not installed (pacman -S flatpak-builder)" >&2
    exit 1
}

for variant in "${variants[@]}"; do
    case "$variant" in
        full) app_id=io.github.itstomsh.yamep ;;
        lite) app_id=io.github.itstomsh.yamep.lite ;;
    esac
    manifest="flatpak/yamep-$variant.flatpak.json"
    build_dir=".flatpak-build/$variant"
    bundle_file="yamep-$variant.flatpak"

    echo "==> Building $app_id"
    args=(--user --force-clean --install-deps-from=flathub --repo="$REPO")
    [ "$install" = yes ] && args+=(--install)
    flatpak-builder "${args[@]}" "$build_dir" "$manifest"

    if [ "$bundle" = yes ]; then
        echo "==> Writing $bundle_file"
        # The runtime is not in the bundle. Naming Flathub lets
        # "flatpak install" offer to fetch it on a system without it.
        flatpak build-bundle \
            --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
            "$REPO" "$bundle_file" "$app_id"
        du -h "$bundle_file" | sed 's/^/    /'
    fi
    if [ "$install" = yes ]; then
        # flatpak-builder also installs .Debug and .Locale extensions, each
        # from its own generated remote, which clutters the remote list.
        # Drop them; they can be installed from the repo when debugging.
        flatpak uninstall --user -y "$app_id.Debug" "$app_id.Locale" \
            >/dev/null 2>&1 || true
        echo "    installed; run it with: flatpak run $app_id"
    fi
done
