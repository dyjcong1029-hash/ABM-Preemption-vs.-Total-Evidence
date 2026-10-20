"""Independently audit published endpoint statistics without launching NetLogo.

The estimator inputs come only from raw run-level exports. Published summaries
are comparison targets. Exact baseline percentile CI replay uses R's seeded
sampling algorithm, via a small separate helper; no original analysis is sourced.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
from run_analysis import find_rscript, r_environment, safe_r_path

WORLDS = ("B-good", "B-bad")
E1 = {
    "post_regret": "mean_lay_post_intervention_regret",
    "early_wrong_rate": "early_window_wrong_choice_rate",
    "post_correct_rate": "post_intervention_correct_choice_rate",
    "post_payoff": "post_intervention_realized_payoff",
    "post_b_pulls": "mean_lay_post_intervention_b_pulls",
    "final_truth_mass": "mean_lay_posterior_truth_mass",
    "late_wrong_rate": "final_window_wrong_choice_rate",
    "persistent_run_rate": "run_finite_horizon_persistent_error",
}
E2 = {
    "post_regret": "mean_lay_post_intervention_regret",
    "early_wrong_rate": "early_window_wrong_choice_rate",
    "post_correct_rate": "post_intervention_correct_choice_rate",
    "late_correct_rate": "final_window_correct_choice_rate",
    "final_brier": "mean_lay_final_brier_score",
}


def read_csv(path: Path, behavior: bool = False) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as h:
        if behavior:
            for _ in range(6):
                next(h)
        rows = list(csv.DictReader(h))
    if behavior:
        rows = [{re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_"): v
                 for k, v in row.items()} for row in rows]
    return rows


def number(value: str) -> float:
    if str(value).lower() in ("true", "false"):
        return float(str(value).lower() == "true")
    return float(value)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", type=Path, default=ROOT / "data")
    p.add_argument("--output-dir", type=Path, default=ROOT / "verification" / "statistics")
    p.add_argument("--rscript")
    args = p.parse_args()
    data, out = args.data_root.resolve(), args.output_dir.resolve()
    if out == data or data in out.parents:
        p.error("Verification output must be outside source data.")
    if out.exists() and any(out.iterdir()):
        p.error("Output directory is not empty; use a fresh directory.")
    rscript = find_rscript(args.rscript)
    out.mkdir(parents=True, exist_ok=True)
    checks, jobs, targets, results, hashes = [], [], {}, [], {}

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(condition), "detail": detail})

    def close(name: str, actual: float, expected: float) -> None:
        check(name, math.isfinite(actual) and abs(actual - expected) <= 1e-10 * max(1.0, abs(expected)),
              f"recomputed={actual:.17g}; published={expected:.17g}")

    def load(exp: int, filename: str, behavior: bool = False) -> list[dict]:
        path = data / f"experiment_{exp}" / filename
        hashes[str(path.relative_to(data))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read_csv(path, behavior)

    def bootstrap(label: str, values: list[float], seed: int, count: int,
                  published: dict | None = None) -> None:
        jobs.extend({"job": label, "value": v, "seed": seed, "replicates": count} for v in values)
        if published:
            targets[label] = published

    # All datasets use a complete classroom run as the statistical unit.
    datasets = {i: load(i, "raw_main_final.csv", True) for i in range(3)}
    expected_counts = {0: 1000, 1: 3000, 2: 3000}
    for exp, rows in datasets.items():
        check(f"E{exp}_run_count", len(rows) == expected_counts[exp], str(len(rows)))
        key = "evidence_policy" if exp == 1 else "credence_policy" if exp == 2 else None
        unique = {(r["hidden_world"], r["actual_seed"], r[key] if key else "baseline") for r in rows}
        check(f"E{exp}_unique_run_keys", len(unique) == len(rows))
        check(f"E{exp}_fixed_endpoint_budget", all(number(r["ticks"]) == 500 and
              number(r["expert_total_pulls"]) == 125 and number(r["total_lay_pulls"]) == 5000 for r in rows))
        check(f"E{exp}_seed_and_world_preserved", all(r["actual_seed"] == r["run_seed"] and
              r["hidden_world"] == r["world_mode"] and r["peer_sharing"].lower() == "true" for r in rows))
        valid_columns = [k for k in rows[0] if k.endswith("_valid") or k in ("expert_packet_unique", "inbox_empty_at_intervention")]
        check(f"E{exp}_all_exported_invariants", all(number(r[k]) == 1 for r in rows for k in valid_columns), str(valid_columns))
        error_columns = [k for k in rows[0] if k.startswith("maximum_") and k.endswith("_error")]
        maximum = max(number(r[k]) for r in rows for k in error_columns)
        check(f"E{exp}_exported_error_bounds", maximum < 1e-9, f"maximum={maximum}")
        gap = max(abs(number(r["mean_lay_cumulative_regret"]) -
                  .05 * 500 * (1 - number(r["cumulative_lay_correct_choice_rate"])))
                  for r in rows) if exp != 2 else 0.0
        check(f"E{exp}_regret_choice_identity", gap < 1e-9, str(gap))
        if exp:
            gap = max(abs(number(r["mean_lay_post_intervention_regret"]) -
                      .05 * 475 * (1 - number(r["post_intervention_correct_choice_rate"]))) for r in rows)
            check(f"E{exp}_post_regret_choice_identity", gap < 1e-9, str(gap))
            blocks = defaultdict(list)
            for r in rows:
                blocks[(r["hidden_world"], r["actual_seed"])].append(r)
            check(f"E{exp}_1000_complete_policy_blocks", len(blocks) == 1000 and all(len(v) == 3 for v in blocks.values()))
            invariants = [k for k in rows[0] if k.endswith("_at_25")]
            if exp == 1:
                invariants += ["expert_packet_llr_from_raw", "expert_packet_size_at_intervention"]
            else:
                invariants += ["private_expert_q_at_intervention", "broadcast_message_bin", "broadcast_message_llr"]
            gap = max(max(number(r[k]) for r in v) - min(number(r[k]) for r in v)
                      for v in blocks.values() for k in invariants)
            check(f"E{exp}_paired_preintervention_identity", gap < 1e-12, f"maximum range={gap}")

    # Baseline expertise and sharing effects are derived directly, not from figures.
    for world in WORLDS:
        rows = sorted((r for r in datasets[0] if r["hidden_world"] == world), key=lambda r: int(r["actual_seed"]))
        delta = [number(r["expert_truth_mass_at_25"]) - number(r["mean_lay_truth_mass_at_25"]) for r in rows]
        results.append({"experiment": 0, "world": world, "n_runs": len(rows),
                        "expert_truth_mass_at_25": statistics.mean(number(r["expert_truth_mass_at_25"]) for r in rows),
                        "lay_truth_mass_at_25": statistics.mean(number(r["mean_lay_truth_mass_at_25"]) for r in rows),
                        "share_expert_above_lay": statistics.mean(v > 0 for v in delta),
                        "mean_regret": statistics.mean(number(r["mean_lay_cumulative_regret"]) for r in rows)})
        bootstrap(f"E0/{world}/expert_gap_audit", delta, 20260801 + len(results), 4000)
    peer = load(0, "raw_peer_check.csv", True)
    pairs = defaultdict(dict)
    for r in peer:
        pairs[(r["hidden_world"], r["actual_seed"])][r["peer_sharing"].lower()] = r
    check("E0_sharing_pairs", len(peer) == 2000 and len(pairs) == 1000 and all(set(v) == {"true", "false"} for v in pairs.values()))
    for world in WORLDS:
        ds = [number(v["true"]["mean_lay_cumulative_regret"]) - number(v["false"]["mean_lay_cumulative_regret"])
              for (w, _), v in sorted(pairs.items()) if w == world]
        results.append({"experiment": 0, "world": world, "sharing_regret_on_minus_off": statistics.mean(ds), "n_pairs": len(ds)})

    # Reconstruct every published paired point estimate and endpoint mean.
    for exp, metrics, prefix, policy_column, summary_name in (
        (1, E1, "E", "evidence_policy", "paired_contrasts.csv"),
        (2, E2, "C", "credence_policy", "paired_policy_effects.csv"),
    ):
        rows = datasets[exp]
        indexed = {(r["hidden_world"], int(r["actual_seed"]), r[policy_column]): r for r in rows}
        summaries = load(exp, "endpoint_summary.csv")
        for row in summaries:
            selected = sorted((r for r in rows if r["hidden_world"] == row["world"] and r[policy_column] == row["policy"]),
                              key=lambda r: int(r["actual_seed"]))
            check(f"E{exp}_endpoint_count/{row['world']}/{row['policy']}", len(selected) == int(row["n_runs"]))
            selected_metrics = {row["metric"]: metrics[row["metric"]]} if exp == 2 else metrics
            for metric, column in selected_metrics.items():
                values = [number(r[column]) for r in selected]
                label = f"E{exp}/endpoint/{row['world']}/{row['policy']}/{metric}"
                close(label, statistics.mean(values), number(row["mean"] if exp == 2 else row[metric]))
                if exp == 2:
                    close(label + "/sd", statistics.stdev(values), number(row["sd"]))
                    close(label + "/se", statistics.stdev(values) / math.sqrt(len(values)), number(row["se"]))
                elif metric == "post_regret":
                    endpoint_index = WORLDS.index(row["world"]) * 3 + ["No Deference", "E-Preemption", "E-Total Evidence"].index(row["policy"]) + 1
                    bootstrap(label, values, 1000 + endpoint_index * 50 + 1, 4000,
                              {"ci_low": row["post_regret_low"], "ci_high": row["post_regret_high"]})
        contrasts = load(exp, summary_name)
        for index, row in enumerate(contrasts, 1):
            seeds = sorted({int(r["actual_seed"]) for r in rows if r["hidden_world"] == row["world"]})
            column = metrics[row["metric"]]
            differences = [number(indexed[(row["world"], seed, row["policy_1"])][column]) -
                           number(indexed[(row["world"], seed, row["policy_0"])][column]) for seed in seeds]
            label = f"E{exp}/contrast/{row['world']}/{row['comparison']}/{row['metric']}"
            check(label + "/n", len(differences) == int(row["n_pairs"]))
            close(label + "/estimate", statistics.mean(differences), number(row["estimate"]))
            if row["metric"] == "post_regret" and row["comparison"] == f"{prefix}-Total Evidence - {prefix}-Preemption":
                bootstrap(label, differences, (5000 if exp == 1 else 10000) + index,
                          4000 if exp == 1 else 10000, row)
                results.append({"experiment": exp, "world": row["world"], "comparison": row["comparison"],
                                "n_pairs": len(differences), "estimate": statistics.mean(differences)})

    # Frozen message evidential force reconstructed from the published counts.
    table = load(2, "frozen_credence_message_table.csv")
    lambdas = []
    for row in table:
        pg = (number(row["estimate_count_good"]) + .5) / (number(row["estimate_n_good"]) + 5)
        pb = (number(row["estimate_count_bad"]) + .5) / (number(row["estimate_n_bad"]) + 5)
        value = math.log(pg / pb)
        lambdas.append(value)
        close(f"calibration/bin{row['message_bin']}/lambda", value, number(row["message_lambda"]))
        close(f"calibration/bin{row['message_bin']}/posterior", pg / (pg + pb), number(row["implied_p_good_given_message"]))
    source = (ROOT / "models/experiment_2/experiment_2_opaque_credence_bandit.nls").read_text(encoding="utf-8-sig")
    match = re.search(r"set report-llr-table \(list ([^)]+)\)", source)
    source_values = list(map(float, match.group(1).split())) if match else []
    check("calibration_model_table_identity", len(source_values) == 10 and max(abs(a-b) for a,b in zip(source_values,lambdas)) < 1e-12)

    input_path, ci_path = out / "bootstrap_inputs.csv", out / "bootstrap_recomputed.csv"
    with input_path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=["job", "value", "seed", "replicates"])
        writer.writeheader()
        writer.writerows(jobs)
    command = [safe_r_path(x) for x in [rscript, ROOT / "scripts/analysis/verify_bootstrap.R", input_path, ci_path]]
    run = subprocess.run(command, env=r_environment(), capture_output=True, text=True, encoding="utf-8", errors="replace")
    (out / "bootstrap.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    check("R_bootstrap_exit", run.returncode == 0, str(run.returncode))
    if run.returncode == 0:
        for row in read_csv(ci_path):
            if row["job"] in targets:
                for field in ("ci_low", "ci_high"):
                    close(row["job"] + "/" + field, number(row[field]), number(targets[row["job"]][field]))
    receipt = {"status": "passed" if all(c["passed"] for c in checks) else "failed",
               "independence": "Raw endpoint reconstruction in Python; no original R analysis sourced. R only supplies the original seeded percentile-bootstrap sampling algorithm.",
               "rscript_version": subprocess.run([rscript, "--version"], env=r_environment(), capture_output=True,
                   text=True, encoding="utf-8", errors="replace").stdout.strip(),
               "data_sha256": hashes, "checks": checks, "key_results": results,
               "bootstrap_scope": "Exact published CI replay for six E1 regret levels and four main paired regret contrasts. E0 audit intervals use explicitly labelled independent audit seeds; no published CI target is available for E0.",
               "trajectory_scope": "No full raw trajectories read. This endpoint audit does not verify recovery delays, full trajectory summaries, or the 33/21 trajectory-dependent original checks."}
    (out / "statistics_verification.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "checks": len(checks), "passed": sum(c["passed"] for c in checks),
                      "output": str(out)}, ensure_ascii=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
