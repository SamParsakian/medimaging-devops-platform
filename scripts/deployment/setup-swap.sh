#!/usr/bin/env bash
# Adds a swap file to a small VPS node so it doesn't OOM under memory
# pressure (Docker image builds, torch/torchxrayvision loading a real model
# in RAM - see docs/deployment.md). Safe to re-run: does nothing if
# /swapfile is already active as swap.
#
# Usage: setup-swap.sh <size-in-gb>
set -euo pipefail

SIZE_GB="${1:?Usage: setup-swap.sh <size-in-gb>}"

if swapon --show=NAME --noheadings | grep -q "^/swapfile$"; then
  echo "[ OK ] /swapfile is already active, nothing to do."
  swapon --show
  exit 0
fi

fallocate -l "${SIZE_GB}G" /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

if ! grep -q "^/swapfile " /etc/fstab; then
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "[ OK ] ${SIZE_GB}G swap file created and enabled."
swapon --show
free -h
