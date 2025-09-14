#!/usr/bin/env bash
set -euo pipefail

# Build, tag, and (optionally) push the Docker image for this project.
# Usage:
#   ./tag_and_push_images.sh                 # build local, no push
#   PUSH=1 ./tag_and_push_images.sh          # build & push
#   IMAGE_TAG=v1.2.3 PUSH=1 ./tag_and_push_images.sh PLATFORMS="linux/amd64,linux/arm64"

REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
NAMESPACE="${IMAGE_NAMESPACE:-YOUR_ORG}"
IMAGE_NAME="${IMAGE_NAME:-whos-on-first-bot}"
PLATFORMS="${IMAGE_PLATFORMS:-linux/amd64}"
PUSH="${PUSH:-0}"

resolve_tag() {
  if [[ -n "${IMAGE_TAG:-}" ]]; then
    echo "$IMAGE_TAG"
    return
  fi
  if tag=$(git describe --tags --always 2>/dev/null); then
    echo "$tag"
    return
  fi
  if sha=$(git rev-parse --short HEAD 2>/dev/null); then
    echo "$sha"
    return
  fi
  date +"%Y%m%d-%H%M%S"
}

TAG="$(resolve_tag)"
FULL_VERSION="${REGISTRY}/${NAMESPACE}/${IMAGE_NAME}:${TAG}"
FULL_LATEST="${REGISTRY}/${NAMESPACE}/${IMAGE_NAME}:latest"

echo "Building image:"
echo "  Name (version): ${FULL_VERSION}"
echo "  Name (latest):  ${FULL_LATEST}"
echo "  Platforms:      ${PLATFORMS}"
echo "  Push:           ${PUSH}"

# Ensure buildx builder exists
if ! docker buildx ls | grep -q 'wof_builder'; then
  echo "Creating buildx builder 'wof_builder'..."
  docker buildx create --name wof_builder --use >/dev/null
else
  docker buildx use wof_builder >/dev/null
fi

# GHCR login if pushing and using ghcr.io
if [[ "${PUSH}" == "1" && "${REGISTRY}" == "ghcr.io" ]]; then
  if [[ -z "${GHCR_USERNAME:-}" || -z "${GHCR_TOKEN:-}" ]]; then
    echo "ERROR: GHCR_USERNAME and GHCR_TOKEN must be set to push to GHCR." >&2
    exit 1
  fi
  echo -n "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

if [[ "${PUSH}" == "1" ]]; then
  echo "Building and pushing multi-arch image..."
  docker buildx build --push \
    --platform "${PLATFORMS}" \
    -t "${FULL_VERSION}" \
    -t "${FULL_LATEST}" \
    .
else
  echo "Building image locally (no push)..."
  docker buildx build --load \
    --platform "${PLATFORMS}" \
    -t "${FULL_VERSION}" \
    -t "${FULL_LATEST}" \
    .
  echo "Local images now available:"
  echo "  ${FULL_VERSION}"
  echo "  ${FULL_LATEST}"
  echo "Tip: docker push ${FULL_VERSION} ; docker push ${FULL_LATEST}"
fi
