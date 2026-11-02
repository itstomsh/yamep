#!/bin/bash

# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# build-lite.sh - build the wheel and sdist for the lite variant.
#
# The variant is chosen by pyproject.toml, so it is swapped in for the build
# and put back afterwards: leaving it swapped meant the next plain
# `pip install .` silently produced the other variant.
set -euo pipefail
cd "$(dirname "$0")"

cp pyproject.toml pyproject.toml.orig
trap 'mv pyproject.toml.orig pyproject.toml' EXIT

cp pyproject-lite.toml pyproject.toml
rm -rf dist/ build/
python -m build
