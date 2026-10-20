# Recovered baseline analysis

The four numerical analysis/calibration scripts in this directory are restored **byte for byte** from the local report workspaces that produced the released analyses. The plot-only `make_static_figures.R` retains a verbatim copy under `baseline/`; its working version fixes the recovery figure's clipped title and clarifies average-window recovery and uncensored medians. `source_manifest.json` records original and current hashes and this presentation-only change. These scripts were absent from GitHub baseline commit `e105f6217db78222e72633a663871c070d630ed3`. The added Python wrapper handles paths, dependencies, logs, and output isolation; it does not change sampling rules, parameters, estimators, bootstrap seeds, or recovery definitions.

These scripts use base R. The published analysis used R 4.5.3; use that version for exact seeded percentile-bootstrap replay. PNG rendering can differ across graphics devices and operating systems even when the numeric results agree.

## Verify the public endpoint data

From the repository root:

```text
python scripts/verify_statistics.py --rscript "/path/to/Rscript"
```

Rscript is auto-discovered on PATH or a standard Windows R installation when the option is omitted. The default output is `verification/statistics/`; use `--output-dir` to choose another **empty** directory. Source data are read only. The audit reconstructs estimator inputs from `raw_main_final.csv` and `raw_peer_check.csv`, then compares the published summary means and selected exact bootstrap intervals. It also checks the frozen message table against its estimation counts and the model constants. It does not read full individual trajectories and therefore cannot verify recovery delays.

The small `verify_bootstrap.R` helper only resamples the independently reconstructed audit vectors. It does not import any recovered analysis script. Its explicit seeds and replicate counts reproduce six published Experiment 1 regret-level intervals and the four principal Experiment 1/2 paired regret intervals. Separately labelled Experiment 0 audit intervals use audit-specific seeds and are not represented as published intervals.

## Rebuild the complete original analysis

```text
python scripts/analysis/run_analysis.py --experiment all --raw-root /path/to/raw --output-root results/analysis/new_run --rscript /path/to/Rscript
```

Use `--experiment 0`, `1`, `2`, or `calibration` to run one stage. The output root must be empty, must not be `data/` or below it, and must not contain an input file. Missing inputs are diagnosed before analysis begins. The wrapper does not launch NetLogo. Existing published endpoint files may supply `raw_main_final.csv` and Experiment 0 `raw_peer_check.csv` when they are absent under the raw root; all full trajectory and calibration exports must be supplied explicitly.

Expected raw layout:

```text
raw/
  experiment_0/
    raw_main_final.csv
    raw_peer_check.csv
    raw_trajectories.csv
  experiment_1/
    raw_main_final.csv
    raw_trajectories.csv
  experiment_2/
    raw_main_final.csv
    raw_trajectories.csv
    raw_exact_trajectories.csv
    calibration_estimate_good_raw.csv
    calibration_estimate_bad_raw.csv
    calibration_heldout_good_raw.csv
    calibration_heldout_bad_raw.csv
```

The exact trajectory file can alternatively be named `raw_exact_regression_trajectories.csv`. For replaying the original local evidence, the wrapper also recognizes sibling directories `experiment_0_bandit_base_report`, `experiment_1_evidence_bandit_report`, and `experiment_2_opaque_credence_report` beneath `--raw-root`. This is a compatibility option; those large local files are **not** part of the public GitHub release.

| Stage | Required inputs beyond its own endpoint | Outputs under the new output root |
|---|---|---|
| Calibration | Four expert-only raw calibration exports, 50,000 estimation and 10,000 held-out runs per world | Frozen table, held-out audit, 13 checks |
| Experiment 0 | Complete Experiment 0 raw trajectories and sharing-on/off endpoint export | Endpoint/expertise/network summaries, trajectory summary, 36 checks, four PNGs |
| Experiment 1 | Complete Experiment 1 trajectories; Experiment 0 endpoints and complete trajectories | Endpoint and paired summaries, recovery tables, trajectory tables, 33 checks, three PNGs |
| Experiment 2 | Complete coarse-message and exact-regression trajectories; complete Experiment 1 trajectories; released frozen table and held-out audit | Endpoint/paired/recovery tables, exact-message regression, 21 checks, three PNGs |

All newly generated CSVs that have published counterparts are compared column by column with a relative/absolute numeric tolerance of `1e-10`; a mismatch fails the wrapper. Frozen-table `table_version` is treated as metadata. Calibration outputs must agree numerically with the released table and held-out audit; they never automatically patch a model or replace the released frozen table. `analysis_receipt.json` records commands, logs, R version, input hashes, script hashes, and comparison results.

Experiment 1's original plot script expects a relative `report_source_regret_contrasts.csv`. The wrapper obtains this by filtering the newly reconstructed `paired_contrasts.csv` to `metric=post_regret`, then invokes the unchanged plot script from the new output directory. No SQLite database, report artifact, or external report folder is required.

## Limits of the public files

Published chart aggregates do not contain individual run histories. They cannot reconstruct a run's first recovery time, censoring, exact-message trajectory identity, or the original trajectory-dependent checks. Recreate the full raw exports with the BehaviorSpace experiments in each `.nlogox` model before claiming complete analysis replication. The wrapper refuses to replace those inputs with chart summaries.

The original recovery definitions are preserved and differ between experiments. Experiment 1 finds the first 20-round window whose **mean** classroom correct-choice rate is at least 60%, reports uncensored medians, and separately records censoring. Experiment 2 requires the rate to be at least 60% in **each** of 20 consecutive rounds; unrecovered runs receive a restricted delay of 476. Their recovery statistics should not be interpreted as the same estimand.

On Windows the wrapper removes invalid inherited Unix locale variables for R and uses existing ASCII short paths when available. This lets the unchanged scripts work in non-ASCII workspace paths; it does not alter their scientific calculations.
