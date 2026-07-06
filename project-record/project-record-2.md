# Project Record (continued)

This continues [project-record.md](project-record.md), which covers Steps 0 through 19 - the local stack, the pipeline, monitoring, and CI. This file picks up at Step 20, where the project moves from a local-only build to something actually pushed to GitHub and checked by real automation.

## Step 20 - GitHub Remote and Real CI Verification

In this step, the project was connected to its real GitHub repository for the first time, and the CI workflow from Step 19 was verified running for real instead of only locally.

```bash
git remote add origin https://github.com/SamParsakian/medimaging-devops-platform.git
git push -u origin main
```

Pushing `main` sent the full project history to GitHub and triggered the CI workflow automatically. It finished in 21 seconds, with every step passing on the very first real run.

A single passing run could just be luck, so the workflow was checked a second way too: by making a real change, opening a pull request, and watching CI react to it at every stage, the same way it would for any future change to this project.

Before touching anything, the local change waiting to be pushed was confirmed directly in the editor - the Step 20 entry being added to `project-record.md`:

![VS Code Source Control panel showing one pending change: project-record.md, with the new Step 20 section visible in the diff](images/step-20-local-change-vscode.png)

That change was committed and pushed on its own branch, not straight to `main`:

```bash
git add project-record/project-record.md
git commit -m "docs: record GitHub CI verification result"
git push -u origin feature/github-remote-ci-verification
```

![Terminal output of the add, commit, and push commands above, ending with GitHub's own suggestion to open a pull request](images/step-20-git-add-commit-push.png)

GitHub noticed the new branch immediately and offered to open a pull request for it:

![The repository's GitHub page showing a banner: "feature/github-remote-ci-verification had recent pushes" with a "Compare & pull request" button](images/step-20-github-compare-pr-prompt.png)

The pull request was opened with a short summary of the change, and GitHub's own diff view confirmed it was exactly the intended edit to `project-record.md` - nothing else:

![The "Open a pull request" page, showing the PR title, description, and the real diff of project-record.md underneath](images/step-20-pr-created-with-diff.png)

Before merging anything, the Actions history was checked as a baseline: two runs so far, both from the very first push of the whole project.

![GitHub Actions page showing 2 workflow runs, both green](images/step-20-actions-two-runs-baseline.png)

Opening the pull request triggered CI again on its own, this time as a pull-request check rather than a plain push. Once it finished, GitHub showed the pull request as ready to merge, with both of its checks green:

![The pull request page showing "All checks have passed" with 2 successful checks, and a green "Merge pull request" button](images/step-20-pr-checks-passed.png)

The pull request was merged from the GitHub UI, the same way any real pull request would be:

![The pull request page after merging, showing a purple "Merged" badge and "Pull request successfully merged and closed"](images/step-20-pr-merged.png)

Merging into `main` triggered CI a third time. The Actions history now showed four runs in total instead of the two from before - the original push, the pull request's own check, and the merge into `main` - every single one green:

![GitHub Actions page now showing 4 workflow runs, all green, including the two new ones from the pull request and the merge](images/step-20-actions-four-runs.png)

Opening that last run shows exactly what CI actually checks on every push: each step of the workflow from Step 19, in order, including the 5 unit tests passing:

![Detailed view of the post-merge CI run, with every step expanded: checkout, Python setup, docker compose config, shell syntax check, dependency install, compileall, and the pytest run showing "5 passed"](images/step-20-post-merge-run-detail.png)

That screenshot is where this check ends: the same workflow from Step 19, holding up through a real push, a real pull request, and a real merge, without a single line of it needing to change.

## Step 21 - Local AI Inference Service

In this step, a new AI inference service was added: its own container, its own FastAPI app, that takes a study's preview image and returns an AI result as JSON.

This step focuses on the plumbing around an AI component - its own container, an input/output contract, and a dashboard hook - built first with a lightweight classifier based on pixel-intensity statistics, ahead of a trained model in a later step.

The new service lives in `services/ai-inference/`, containerized the same way every other service in this project is, and added to `docker-compose.yml` as its own entry:

```yaml
ai-inference:
  build:
    context: ./services/ai-inference
  container_name: ai-inference
  restart: unless-stopped
  ports:
    - "${AI_INFERENCE_PORT:-8100}:8100"
  environment:
    MINIO_HOST: minio
    MINIO_PORT: 9000
    MINIO_ROOT_USER: ${MINIO_ROOT_USER}
    MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    MINIO_BUCKET: ${MINIO_BUCKET}
  depends_on:
    minio:
      condition: service_healthy
```

Docker Desktop shows it running as its own container, separate from the API, alongside everything else in the stack:

![Docker Desktop container list showing ai-inference as its own running container on port 8100, next to api, orthanc, postgres, minio, prometheus, and grafana](images/step-21-docker-desktop-ai-inference-container.png)

The classifier itself, `classify_pixels` in `services/ai-inference/main.py`, converts the image to grayscale and measures how much its pixel intensities vary relative to their average brightness. That single number gets bucketed into one of three labels:

```python
if variation >= HIGH_VARIATION_THRESHOLD:
    label = "high_variation_region"
elif variation <= LOW_VARIATION_THRESHOLD:
    label = "low_variation_region"
else:
    label = "moderate_variation_region"
```

Every result the service returns also carries a fixed disclaimer field, `"Technical demo only. Not for clinical diagnosis."`, alongside the label.

The service exposes two endpoints:

```text
GET  /health
POST /infer
```

`/health` was checked directly through the service's own Swagger page:

![Swagger UI for the ai-inference service, GET /health executed, showing a 200 response with {"status": "ok"}](images/step-21-ai-inference-health-check.png)

`/infer` takes the MinIO path of a preview image already produced by the existing pipeline (Step 6's preview generator) and returns the model name, version, the input path, the predicted label, a confidence score, how long the classification took, and the disclaimer:

![Swagger UI for POST /infer, request body pointing at a real preview PNG, showing a 200 response with model_name, prediction_label "moderate_variation_region", confidence, inference_time_ms, and the disclaimer](images/step-21-ai-inference-infer-response.png)

The existing `services/api` gained one new endpoint, `POST /studies/{id}/infer`, so a caller never has to know the ai-inference service or MinIO exist at all - it looks up the study's own preview path from Postgres and calls ai-inference on the caller's behalf, the same pattern the API already uses for streaming preview images:

```python
object_path = study["preview_object_path"]
ai_response = requests.post(
    f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/infer",
    json={"object_path": object_path},
    timeout=10,
)
```

This endpoint sits behind the same API key middleware as every other endpoint in this project, so it was not given any auth logic of its own.

The dashboard's Study Detail panel got one new button, "Run AI Demo Inference," which calls that endpoint and shows the result inline. Clicking it on the MR series from Step 18 produced this result, and the audit trail underneath shows the `run_inference` event that click created:

![Dashboard Study Detail panel for the MR study, showing the Run AI Demo Inference button, a result of Model demo-image-stat-classifier, Prediction high_variation_region, Confidence 0.99, Inference Time 6.9 ms, the disclaimer text, and a run_inference row in the Recent Audit Events table below](images/step-21-dashboard-ai-inference-result.png)

The button always analyzes the study's one stored preview image, the same one shown before any slice is picked with Previous/Next - not whichever slice happens to be selected in the slider at the time.

Three small unit tests were added for `classify_pixels`, following the same pattern as every other pure-logic test in this project - no MinIO, no running containers, just the function itself against known pixel arrays:

```python
def test_classify_pixels_labels_a_uniform_image_as_low_variation():
    pixels = np.full((32, 32), 120, dtype=np.uint8)
    label, confidence = classify_pixels(pixels)
    assert label == "low_variation_region"
```

The service runs on CPU only, with no external AI API involved.
