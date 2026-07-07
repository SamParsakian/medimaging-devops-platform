# AI Model Configuration

This documents every setting that controls how the X-ray AI model runs and how its output should be read, and - for the settings where a real alternative existed - what that alternative would have looked like and why it wasn't chosen. The values themselves live in `services/ai-inference/model_config.py`, and the running service exposes them over HTTP at `GET /config` (proxied by the API at `GET /ai-config`, and shown in the dashboard's "AI Model Configuration" panel).

## Model weights: `densenet121-res224-all`

TorchXRayVision ships several pretrained weight sets for the same DenseNet121 architecture, each trained on a different dataset or combination of datasets: `nih` (NIH ChestX-ray14 only), `pc` (PadChest only), `chex` (CheXpert only), `rsna`, `mimic_nb`, `mimic_ch`, and `all` (trained on a blend of all of them together).

Since this project's own sample images come from the NIH dataset, the obvious-looking default would be the `nih` weights - trained on exactly the same source as the test data. Running the Cardiomegaly sample through both shows why that instinct doesn't hold up:

```text
weights="nih" (single-dataset, matches the sample's own source)
  Cardiomegaly    0.6672
  Effusion        0.5665
  Mass            0.5322
  Fibrosis        0.5249
  Atelectasis     0.5225

weights="densenet121-res224-all" (multi-dataset, what this project uses)
  Cardiomegaly    0.6215
  Fibrosis        0.5402
  Infiltration    0.5220
  Pleural_Thickening 0.5104
  Nodule          0.5092
```

Both agree on the top finding, which is reassuring, but everything below it differs - a model trained on one hospital's data learns that hospital's particular imaging equipment and patient population along with the diseases themselves. `all` was chosen specifically because a demo tool has no guarantee it will only ever see NIH-style images; a weight set trained across seven different sources is less likely to be thrown off by an X-ray that doesn't look like the one dataset it was trained on.

## Input size and architecture: 224x224 DenseNet121

TorchXRayVision also ships a higher-resolution option, `resnet50-res512-all` (a ResNet50 reading 512x512 images instead of DenseNet121's 224x224). Higher resolution can pick up finer detail, so it's a real alternative, not a strawman. Timing a single inference of each, on the same CPU, on the same image:

```text
224x224 DenseNet121:  24.7 ms
512x512 ResNet50:    116.0 ms
```

The 512 variant takes roughly 4.7x longer per image. On a GPU that difference might not matter; on the CPU-only setup this project deliberately uses (see "Runtime mode" below), it does. 224x224 DenseNet121 was chosen to keep inference fast without needing a GPU.

## Preprocessing

Before an image reaches the model, it's converted to grayscale, normalized to the `[-1024, 1024]` pixel range TorchXRayVision's models expect (not the usual 0-255 or 0-1), center-cropped, then resized to 224x224. This isn't a setting with an alternative to weigh - it's simply what the chosen weights require as input - but it's documented here since getting any one of these steps wrong (e.g. feeding in a 0-255 image unnormalized) would silently produce meaningless output rather than an error.

## Top findings shown: 5

The model scores 18 possible findings independently. Showing all 18 in the dashboard would bury the meaningful ones under a long tail of near-zero scores - for the Cardiomegaly sample, the bottom of the full list looks like this:

```text
Hernia          0.0127
Pneumonia       0.1801
Edema           0.2129
```

Five was chosen as a reasonable "differential" length - enough to see whether the top finding has real competition from others, without the noise of every low-probability score. This is purely a display choice; the API's `finding_probabilities` field still returns all 18 regardless of this setting.

## Confidence threshold: 0.5

TorchXRayVision's own convention treats 0.5 as the line between a positive and a negative signal for a given finding - it isn't a percentage confidence in the everyday sense. This project doesn't use it to filter anything (the top 5 findings show up regardless of whether they clear 0.5), but it's documented and shown in the dashboard because it explains results like this one, taken from a real run:

```text
Atelectasis   0.5058
```

Without knowing 0.5 is the model's own indifference point, a number like 0.5058 could easily be misread as a fairly confident "yes." It's barely above the line the model itself doesn't consider meaningful.

## Runtime mode: CPU

Nothing in this project ever moves a tensor or the model onto a GPU - if left to a machine that happens to have one, PyTorch's default behavior would still run everything on CPU here, since no `.cuda()` call exists anywhere in the code. The choice is also enforced one level down, in how the container image itself is built: `services/ai-inference/Dockerfile` installs `torch`/`torchvision` from PyTorch's CPU-only wheel index specifically, so the CUDA-enabled build (and its much larger `nvidia-*` dependencies) is never even downloaded, regardless of what hardware the container happens to run on.

## Heatmap target rule: top finding only

Decided before the heatmap feature was built: a heatmap explains exactly one finding, and it's always the single highest-probability one - not an overlay for every finding shown in the table. Multiple overlapping heatmaps for five different findings on one small chest X-ray would be unreadable; a single clear one for the model's actual top call is more honest about what the model is claiming to prioritize.
