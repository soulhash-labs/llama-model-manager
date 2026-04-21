#!/bin/sh
set -eu

REPO_OWNER="${LLAMA_MODEL_MANAGER_REPO_OWNER:-soulhash-labs}"
REPO_NAME="${LLAMA_MODEL_MANAGER_REPO_NAME:-llama-model-manager}"
REPO_REF="${LLAMA_MODEL_MANAGER_REF:-main}"
ARCHIVE_URL="${LLAMA_MODEL_MANAGER_ARCHIVE_URL:-https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_REF}}"
TMP_ROOT="${TMPDIR:-/tmp}"
WORK_DIR="$(mktemp -d "${TMP_ROOT%/}/llama-model-manager-install.XXXXXX")"
ARCHIVE_PATH="${WORK_DIR}/repo.tar.gz"
EXTRACT_DIR="${WORK_DIR}/extract"

cleanup() {
    rm -rf "$WORK_DIR"
}

trap cleanup EXIT INT TERM HUP

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download_archive() {
    if need_cmd curl; then
        curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE_PATH"
        return 0
    fi

    if need_cmd wget; then
        wget -qO "$ARCHIVE_PATH" "$ARCHIVE_URL"
        return 0
    fi

    printf '%s\n' "error: curl or wget is required to download ${ARCHIVE_URL}" >&2
    exit 1
}

printf '%s\n' "Downloading ${REPO_OWNER}/${REPO_NAME} (${REPO_REF})..."
mkdir -p "$EXTRACT_DIR"
download_archive

printf '%s\n' "Extracting installer payload..."
tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"

SOURCE_DIR="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$SOURCE_DIR" ] || {
    printf '%s\n' "error: extracted archive did not contain a source directory" >&2
    exit 1
}

if ! need_cmd bash; then
    printf '%s\n' "error: bash is required to run the local installer" >&2
    exit 1
fi

printf '%s\n' "Running llama-model-manager installer..."
if [ -r /dev/tty ]; then
    exec bash "$SOURCE_DIR/install.sh" </dev/tty
fi

exec bash "$SOURCE_DIR/install.sh"
