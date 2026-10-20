# Reproducible verification of the existing baseline

This working copy is pinned to upstream commit `e105f6217db78222e72633a663871c070d630ed3`. The six core model files and published data retain the upstream scientific rules and parameters. The new Python tooling uses the standard library; the recovered baseline statistical and plotting scripts require R. Native runs require NetLogo 7.0.3. The baseline analysis used R 4.5.3.

Read [the scope and acceptance criteria in Chinese](docs/MODEL_SCOPE.zh.md) before interpreting results. The generated receipt records what actually ran and whether it passed.

## Completed full reproduction: 2026-10-19

The completed [pipeline](verification/full_reproduction_2026_10_19/pipeline.json) freshly ran all 12 original native batches and R analysis. [Independent postflight](verification/full_reproduction_2026_10_19/postflight/full_reproduction_verification.json) checked 132,600 runs and 1,932,600 exported rows, the original seed grids, every raw file hash, matched endpoints, full trajectory regressions and 13 reconstructed published tables. Scientific models and published data were not changed.

The actual invocation and engine/script versions are preserved in the pipeline and [compressed original native provenance](verification/full_reproduction_2026_10_19/native_provenance.json.gz). Full raw outputs and all logs are retained in a verified local ZIP. [Raw batch hashes and sizes](verification/full_reproduction_2026_10_19/raw_batches.json) identify it as `availability=local`, with no remote download URL. The compact evidence can be inspected in this repository; reproducing all raw observations requires the complete command below.

## Commands

From this directory, with Python 3.10 or newer:

```text
python run_all.py verify
python run_all.py smoke --threads 2
```

On the current Windows/Codex host, `python` on PATH can be a Windows Store alias. The convenience wrapper discovers the bundled interpreter instead:

```powershell
.\run_all.ps1 verify
.\run_all.ps1 smoke -Threads 2
```

It also accepts `-PythonPath`, `-OutputRoot`, `-RawRoot`, `-NetLogo`, `-Rscript`, and `-JavaPath`.

`verify` checks source consistency, probability identities, published run grids, pairing and published endpoint statistics. `smoke` additionally invokes actual NetLogo for bounded diagnostic runs and cross-model regressions. Each invocation creates a new timestamped directory under `verification/`; `pipeline.json` records the commands, hashes, status and logs. Select a new location with `--output-root PATH`. Existing nonempty result directories are refused.

Use `--netlogo PATH`, `--java PATH`, and `--rscript PATH` when an installation cannot be discovered. On this Windows installation the defaults discover NetLogo under `C:/Program Files/NetLogo 7.0.3` and R under `C:/Program Files/R`. The Windows launcher can use NetLogo's bundled `jli.dll` when the distribution has no standalone `java.exe`; its in-process PreferencesFactory avoids writing to the Windows registry. It does not install software or change system preferences.

List or run an original embedded BehaviorSpace experiment directly:

```text
python scripts/run_netlogo.py --model models/experiment_1/experiment_1_evidence_bandit.nlogox --list
python scripts/run_netlogo.py --model models/experiment_1/experiment_1_evidence_bandit.nlogox --experiment experiment-1-evidence-smoke --output results/my_smoke.csv --threads 2
```

The native launcher refuses existing output paths and verifies output completeness after the engine exits. A bounded seed subset uses an external XML setup file without editing the source model. Native diagnostics and full reproduction are different scopes.

## Full regeneration

```text
python run_all.py reproduce --threads 4 --output-root results/full_reproduction_01
```

This runs every original calibration batch, main endpoint batch, peer-check and full trajectory batch, then invokes the recovered R analyses. It retains the original seed ranges and scientific settings. Full trajectory CSVs total hundreds of megabytes and may take substantial time and memory. This is an explicit full reproduction command, not the default verification mode.

After the pipeline completes, independently audit the newly generated files:

```text
python scripts/verify_full_reproduction.py --run-root results/full_reproduction_01 --output-dir verification/full_reproduction_postflight_01
```

This audit requires all 12 complete original grids: 132,600 runs and 1,932,600 exported rows, including 3,600 complete trajectories. It compares 9,000 main and peer-check endpoints with the pinned public records, checks trajectory endpoints against the new main batches, and aligns cross-model trajectories by seed, world, policy and tick. It also independently reconstructs calibration-bin counts and likelihood ratios, verifies each R command's inputs, and compares 13 regenerated public tables. Physical ordering of different runs is not used as a pairing key. Exit code 2 means required upstream results are incomplete; exit code 1 means a failed check. The audit never launches a simulation.

To preserve a completed run and prepare compact publication evidence:

```text
python scripts/package_verified_release.py --run-root results/full_reproduction_01 --postflight-root verification/full_reproduction_postflight_01 --output-root verification/release_evidence_01 --raw-archive ../ABM_full_simulation_raw_01.zip --publication-files
```

Packaging requires both full receipts to pass, refuses existing output paths, and verifies the archive's CRC and member hashes. The archive remains local; the evidence index records its size and SHA256 without implying a remote download. Original raw provenance receipts are retained as gzip files in the compact evidence directory.

For complete raw exports that already exist in the standard `experiment_0`, `experiment_1`, `experiment_2` layout:

```text
python run_all.py analyze --raw-root PATH_TO_RAW_EXPORTS --output-root results/reanalysis_01
```

See [the analysis wrapper](scripts/analysis/run_analysis.py) and its `--help` for required filenames. The wrapper also recognizes the original local report-directory names; each receipt records the actual inputs and hashes. The public trajectory summaries cannot reconstruct individual recovery delays. Missing raw trajectories are reported as missing, rather than silently replaced by aggregate curves.

The four calibration exports regenerate a comparison table. Version-label differences are distinguished from numerical differences; analysis never silently replaces the frozen report table embedded in the scientific model.

## Files and provenance

- `source_manifest.json`: the pinned GitHub tree and original Git blob hashes.
- `scripts/verify_model.py`: structural and mathematical checks with explicit scope.
- `scripts/verify_statistics.py`: endpoint and paired-statistic verification from published raw CSVs.
- `scripts/run_netlogo.py`, `scripts/native_checks.py`: native execution, diagnostic regressions and output validation.
- `scripts/verify_full_reproduction.py`: independent verification of every newly generated full batch and its analysis inputs.
- `scripts/package_verified_release.py`: verified local archive and compact publication evidence, available only after full acceptance.
- `scripts/analysis/`: recovered baseline analyses, their source manifest, and a portable wrapper.
- `verification/`: actual receipts, comparison tables and logs from the present review.
- `version 1.1.nlogox` and `version 2.nlogox`: retained historical models; they are outside the current Experiments 0–2 baseline and the core acceptance suite.

Source audits check the scientific model files against upstream. This documentation and the additional tooling are deliberate additions; their hashes appear in run receipts. `verify` and `smoke` retain their limited coverage; this publication additionally includes the completed `reproduce` pipeline and independent full-run postflight linked above.

The recovery figure has a presentation-only correction: additional title/caption margin and labels stating the average-window criterion and recovered-run median. The original plot script is preserved under `scripts/analysis/baseline/`, and `verification/full_reproduction_2026_10_19/figure_layout/receipt.json` records the correction. Statistical tables and model behavior are unchanged. PNG bytes can differ between graphics environments even when all underlying numeric values match.
