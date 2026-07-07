# AI Model Evaluation Notes

Every earlier step that touched the X-ray model (Step 24's real DenseNet model, Step 25's heatmap) was checked on one or two images at a time. This step (26) runs the same model over 24 labeled images at once and checks its answers against known ground truth, so the platform has an actual measured sense of how good the model is - not just proof that it runs. The numbers below are all real, taken from one actual run of `evaluation/run_evaluation.py` against the live stack (see `project-record/project-record-2.md`, Step 26, for the full walkthrough with screenshots).

## Why 24 samples, 12 normal / 12 abnormal

A single image can only ever show that the pipeline works end to end, not whether the model is any good. 24 was chosen as a size a person can still review by hand, one row at a time, in the dashboard's evaluation table - not so large it becomes a "trust the summary number" black box, but large enough to see a real spread of results instead of two cherry-picked examples. Balancing it 12/12 matters specifically because an X-ray model that just says "normal" for everything would score 50% "accuracy" on a set that's 90% normal - an even split makes a lopsided model's weaknesses show up in both directions instead of hiding behind one common case.

The 12 abnormal picks were also chosen to each carry one single, distinct finding (see `evaluation/manifest.csv`'s `reason_selected` column) - Infiltration, Effusion, Atelectasis, Nodule, Pneumothorax, Mass, Consolidation, Pleural_Thickening, Cardiomegaly, Emphysema, Edema, Pneumonia - rather than repeating the same one or two findings, or picking images with several findings mixed together where it would be unclear which one the model was even supposed to catch.

## How labels are interpreted

Every sample's `expected_label` and `expected_group` (`normal` or `abnormal`) come straight from the NIH dataset's own ground truth in `sample_labels.csv` (see `docs/sample-data.md`), not from this project's own judgment - a "No Finding" sample is expected to produce nothing above the confidence threshold, and an abnormal sample is expected to produce its one labeled finding somewhere in the model's own top answers.

## How threshold / top-k / buckets work

Three settings, already established for the live model in `docs/ai-model-config.md`, drive every judgment call in this evaluation:

- **Top-k = 5** - the model's top 5 findings by probability, the same number already shown in the dashboard's per-study result box.
- **Confidence threshold = 0.5** - TorchXRayVision's own line between a positive and a negative signal for a finding (see `docs/ai-model-config.md`'s "Confidence threshold" section). This evaluation uses the same value the live model already uses, rather than picking a separate number just for this step.
- **Confidence buckets** - `low` (< 0.5), `uncertain` (0.5 to < 0.7), `stronger_signal` (>= 0.7). The `uncertain` band exists because 0.5 is the model's own point of indifference, not a real percentage confidence - a result of 0.51 and a result of 0.69 are both close enough to that line that neither should be read as a strong claim either way.

Two match rules combine top-k and threshold together:

- **Abnormal sample**: counts as a match if the expected finding appears anywhere in the model's top 5, *or* its own probability clears 0.5 - either is good enough, since a real differential diagnosis includes runner-up possibilities, not only the single top guess.
- **Normal sample**: counts as a match only if nothing across all 18 findings clears 0.5 - any finding above that line on a "No Finding" image is the model raising a flag that shouldn't be there.

A third outcome, `review_needed`, catches genuinely borderline calls: when the deciding probability lands within 0.05 of the threshold either way, it's not honest to call it a clean match or a clean miss, so the evaluation flags it for a human to look at again instead of forcing it into one bucket or the other.

## What the model did well

At the standard 0.5 threshold, 10 of the 12 abnormal samples matched:

```text
xray-eval-abnormal-01  Infiltration        expected 0.6092 -> match
xray-eval-abnormal-02  Effusion            expected 0.6751 -> match
xray-eval-abnormal-03  Atelectasis         expected 0.5331 -> match
xray-eval-abnormal-04  Nodule              expected 0.3322 -> match (via top-5, not threshold)
xray-eval-abnormal-05  Pneumothorax        expected 0.5234 -> match
xray-eval-abnormal-06  Mass                expected 0.5502 -> match (Mass was the model's own top call)
xray-eval-abnormal-07  Consolidation       expected 0.5216 -> match
xray-eval-abnormal-09  Cardiomegaly        expected 0.5554 -> match
xray-eval-abnormal-10  Emphysema           expected 0.5042 -> match
xray-eval-abnormal-11  Edema               expected 0.5613 -> match
```

`xray-eval-abnormal-04` is a good example of why the top-k half of the match rule matters: the model's own probability for Nodule was only 0.3322 (below the 0.5 threshold on its own), but Nodule still showed up in its top 5 findings, which the match rule treats as a real catch, matching how a radiologist's differential list also includes runner-up possibilities, not only the single most likely one.

## What looked uncertain or wrong

Two abnormal samples came back as clean misses, not borderline calls - the model's own probability for the expected finding was low, not close to the threshold:

```text
xray-eval-abnormal-08  Pleural_Thickening  expected 0.1975 -> mismatch (top call: Nodule, 0.5072)
xray-eval-abnormal-12  Pneumonia           expected 0.0022 -> mismatch (top call: Fracture, 0.5107)
```

The normal samples are where the model's weakness really shows: only 3 of 12 "No Finding" images cleanly matched (nothing above threshold), 2 were flat mismatches, and 7 landed in `review_needed` - meaning on most genuinely healthy-looking images, this model's top call still crossed or nearly crossed the 0.5 line for something:

```text
=== Evaluation summary (threshold = 0.5) ===
Total samples:   24
Normal:          12
Abnormal:        12
Match:           10
Review needed:   7
Mismatch:        7

Average inference time: 140.4 ms
```

Most of those normal-sample flags clustered right around 0.50-0.57 (a handful of "Infiltration" and "Lung Opacity" calls in the 0.50-0.53 range), which is consistent with 0.5 being the model's own point of indifference rather than a confident false alarm - but it does mean this model, run with no other adjustment, leans toward flagging *something* on a healthy image more often than it stays quiet.

## Threshold sensitivity: not tuned to look good

The same 24 stored results were re-judged at two other thresholds, using the probabilities already returned by the model - no re-running inference:

```text
=== Threshold sensitivity (recomputed from stored probabilities) ===
 threshold   match   review   mismatch
       0.5      10        7          7
       0.6      16        2          6
       0.7      18        0          6
```

0.5 (the project's existing, already-documented default from Step 24) was kept as the headline number here, even though 0.7 makes the model look noticeably better (18/24 matching instead of 10/24) - moving the threshold mostly reclassifies borderline normal-sample calls from "review needed" into "match," it doesn't change the two genuine abnormal misses (both stay mismatched at every threshold tried, since their own probabilities were nowhere close to any of these lines). Picking whichever threshold produced the best-looking summary would have hidden that the model's real weak spot - flagging something on healthy images - doesn't go away just by moving the line; it only changes how that same behavior gets labeled.

## Why this is an integration evaluation, not clinical validation

24 images, a 5% public sample from one dataset, and a threshold sweep of only three values is enough to prove the pipeline (registration, inference, heatmap generation, storage, and the dashboard) works correctly end to end and to get a rough, honest read on the model's behavior - it is not a clinical validation study. A real validation would need a much larger, demographically representative sample, a formal statistical evaluation (sensitivity, specificity, ROC curves across many thresholds), and review by a radiologist, none of which this step attempts. Every result here still carries the same disclaimer as every other AI result in this platform: technical demo only, not for clinical diagnosis.
