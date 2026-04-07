#!/usr/bin/env bash
set -euo pipefail

# Build apptainer image in local WSL2 build workspace.
# Default workspace from user requirement:
#   /home/lijiyao/container_build

BUILD_ROOT="${BUILD_ROOT:-/home/lijiyao/container_build}"
REPO_MNT="${REPO_MNT:-/mnt/c/wind-agent}"
IMAGE_TAG="${IMAGE_TAG:-wind-agent-offline:20260403}"
TAR_NAME="${TAR_NAME:-wind-agent-offline_20260403.tar}"

mkdir -p "${BUILD_ROOT}/artifacts/containers"
cd "${REPO_MNT}"

echo "[1/2] docker build -> ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" .

echo "[2/2] docker save -> ${BUILD_ROOT}/artifacts/containers/${TAR_NAME}"
docker save "${IMAGE_TAG}" -o "${BUILD_ROOT}/artifacts/containers/${TAR_NAME}"

echo "Done."
echo "Tar output: ${BUILD_ROOT}/artifacts/containers/${TAR_NAME}"
