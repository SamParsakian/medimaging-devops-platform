# GPU Demo Plan

`ai-inference` runs entirely on CPU today (see `docs/ai-model-config.md`'s "Runtime mode" section) - a deliberate choice, and fast enough for a demo running one image at a time. This document plans out what running it on a real GPU would take, without actually renting one yet. It's split out from `docs/deployment.md` because it's a separate decision: the rest of the stack (Orthanc, Postgres, MinIO, the API, monitoring) never needs a GPU regardless of what happens here.

## Local Mac ARM64 vs cloud GPU amd64

This project is developed on a Mac with an Apple Silicon chip. Checking what Docker actually reports confirms the architecture in play:

```text
$ uname -m
arm64

$ docker info --format '{{.OSType}}/{{.Architecture}}'
linux/aarch64
```

Every image built locally so far (`docker compose build`) is therefore an arm64 Linux image, produced by Docker Desktop's own Linux VM. A rented GPU server is a different machine entirely - almost every consumer and cloud GPU on the market (NVIDIA) runs on `amd64`/`x86_64` Linux hosts, not arm64. Docker images are architecture-specific: an image built on this Mac cannot simply be copied to an amd64 GPU server and run - it has to be rebuilt there, from the same Dockerfile and source, targeting `linux/amd64`. `docker buildx` supports building for a different target architecture than the machine doing the build (cross-compilation), but the simpler and more reliable plan here is to build directly on the target server once it exists, the same way the image is built locally today - no cross-compilation step to get right in advance.

## CPU mode vs GPU mode for ai-inference

`services/ai-inference/Dockerfile` currently installs torch and torchvision from PyTorch's CPU-only wheel index on purpose:

```dockerfile
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
```

Nothing in `services/ai-inference/main.py` ever moves the model or a tensor onto a GPU (`XRAY_MODEL = xrv.models.DenseNet(...)` and every tensor built from it stay on the CPU device that PyTorch defaults to) - confirmed directly, there is no `.cuda()` or `.to("cuda")` call anywhere in the file. Switching to GPU mode would need two changes, neither made yet:

1. **A GPU build variant** - installing torch/torchvision from a CUDA-matched wheel index instead (which CUDA version depends on what the rented GPU and its driver actually support, so this can't be pinned down before that server exists) instead of the `/whl/cpu` index above.
2. **Moving the model and its input tensors onto the GPU device** - `XRAY_MODEL.to("cuda")` once at load time, and each input tensor moved the same way before every inference call.

Both are small, well-understood code changes - the reason they aren't made now is that there's no GPU anywhere to test them against yet, and untested GPU code is worse than no GPU code.

## NVIDIA Container Toolkit requirement

A container doesn't get GPU access just because the host machine has a GPU - Docker needs a separate integration layer, the [NVIDIA Container Toolkit](https://github.com/NVIDIA/nvidia-container-toolkit), installed directly on the host (not something this repository can install or configure, since it depends on the host's own OS and driver setup). Without it installed and configured, a container asking for GPU access (however that's declared in Compose) either fails to start or silently can't see the device - there's no partial or automatic fallback. Any future GPU deployment would need to confirm the toolkit is installed on the VPS as a first step, before docker compose is even involved.

## `nvidia-smi` check

`nvidia-smi` is NVIDIA's own command-line tool for checking that a GPU is actually visible and healthy - it reports the driver version, the GPU model, and current memory/utilization. Running it right now, on this Mac, confirms the expected result:

```text
$ nvidia-smi
zsh: command not found: nvidia-smi
```

That's correct and expected - there's no NVIDIA GPU on this machine at all, let alone a driver. On a real GPU VPS, the plan is to run `nvidia-smi` twice: once directly on the host, to confirm the driver itself is installed and the GPU is recognized before Docker is even involved, and once inside a test container started with GPU access requested, to confirm the NVIDIA Container Toolkit is correctly passing the device through. Both need to succeed before trusting `ai-inference` to actually use the GPU.

## Docker Compose deployment flow (GPU)

`docker-compose.gpu.example.yml` (added in this step) is a second optional override, layered on top of the base file and the production override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.example.yml -f docker-compose.gpu.example.yml --env-file .env.production up -d --build
```

It only adds a device reservation to the `ai-inference` service, requesting one NVIDIA GPU through Compose's own `deploy.resources.reservations.devices` syntax - see the file itself for the exact block. It does not switch the Dockerfile to CUDA wheels or add any `.to("cuda")` code, since that's real, untested code (see above) that shouldn't be written until there's a GPU to actually test it against. Using this file today, with no GPU present, would simply fail to start `ai-inference` - which is expected and correct; it's meant to be added only once a GPU server exists.

## Expected VPS/GPU resource table

Real numbers, not estimates - each image's actual built size, and each container's actual memory use while idle, measured directly from this Mac's own Docker install:

```text
Service        Image size   Idle memory use
orthanc        2.23 GB      87 MiB
ai-inference   1.89 GB      405 MiB
grafana        1.49 GB      165 MiB
postgres       411 MB       49 MiB
prometheus     335 MB       64 MiB
api            327 MB       53 MiB
minio          228 MB       203 MiB
```

Total image storage today is roughly 6.9 GB, plus whatever the persistent volumes grow to over time (currently well under 1 GB combined - mostly test/demo data). Idle memory across all seven containers is only around 1 GB total, but that's this Mac sitting idle with no real inference load - `ai-inference` alone already uses about 400 MiB just holding the DenseNet model in memory before a single request comes in, and a GPU variant would add the GPU driver's own memory overhead on top of that (typically a few hundred MB to a few GB, depending on the specific GPU and driver, not something worth guessing a precise number for before one is actually rented). A realistic VPS plan for this stack, GPU or not, should budget well above these idle numbers - real DICOM series and concurrent requests use meaningfully more than the small demo dataset this project runs today - and should be checked directly against whatever specific GPU tier ends up being rented, rather than assumed from this table alone.
