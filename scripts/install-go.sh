#!/usr/bin/env bash

set -euo pipefail

if command -v go >/dev/null 2>&1; then
  echo "Go is already installed: $(go version)"
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS only." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh and rerun this script." >&2
  exit 1
fi

echo "Installing Go with Homebrew..."
brew install go

if ! command -v go >/dev/null 2>&1; then
  brew_prefix="$(brew --prefix)"
  export PATH="${brew_prefix}/bin:${PATH}"
fi

if ! command -v go >/dev/null 2>&1; then
  echo "Go was installed but is not available on PATH." >&2
  exit 1
fi

echo "Installation complete: $(go version)"
echo "Go executable: $(command -v go)"
