"""Verify or reproduce the pinned classroom baseline without overwriting published data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MODELS = {
    0: ROOT / 'models/experiment_0/experiment_0_bandit_base.nlogox',
    1: ROOT / 'models/experiment_1/experiment_1_evidence_bandit.nlogox',
    2: ROOT / 'models/experiment_2/experiment_2_opaque_credence_bandit.nlogox',
}
FULL_JOBS = [
    (2, 'experiment-2-calibration-estimate-good', 'calibration_estimate_good_raw.csv'),
    (2, 'experiment-2-calibration-estimate-bad', 'calibration_estimate_bad_raw.csv'),
    (2, 'experiment-2-calibration-heldout-good', 'calibration_heldout_good_raw.csv'),
    (2, 'experiment-2-calibration-heldout-bad', 'calibration_heldout_bad_raw.csv'),
    (0, 'experiment-0-bandit-main-final', 'raw_main_final.csv'),
    (0, 'experiment-0-bandit-peer-check', 'raw_peer_check.csv'),
    (0, 'experiment-0-bandit-trajectories', 'raw_trajectories.csv'),
    (1, 'experiment-1-evidence-main-final', 'raw_main_final.csv'),
    (1, 'experiment-1-evidence-trajectories', 'raw_trajectories.csv'),
    (2, 'experiment-2-opaque-main-final', 'raw_main_final.csv'),
    (2, 'experiment-2-opaque-trajectories', 'raw_trajectories.csv'),
    (2, 'experiment-2-exact-regression-trajectories', 'raw_exact_trajectories.csv'),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='verify',
                        choices=['verify', 'smoke', 'analyze', 'reproduce'])
    parser.add_argument('--output-root', type=Path, help='New, empty result directory')
    parser.add_argument('--raw-root', type=Path, help='Existing full raw exports for analyze')
    parser.add_argument('--rscript', help='Rscript executable; baseline version is R 4.5.3')
    parser.add_argument('--netlogo', help='NetLogo 7.0.3 installation directory')
    parser.add_argument('--java', help='Optional Java executable for native runs')
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error('--threads must be positive')
    if args.command == 'analyze' and args.raw_root is None:
        parser.error('analyze requires --raw-root containing full trajectory exports')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = (args.output_root or ROOT / 'verification' / f'{args.command}_{stamp}_{os.getpid()}').resolve()
    published = ROOT / 'data'
    if output == published or published in output.parents:
        parser.error('Result output must be outside published data/.')
    if output.exists() and not output.is_dir():
        parser.error('--output-root must name a directory, not an existing file.')
    if output.exists() and any(output.iterdir()):
        parser.error('Refusing to overwrite a nonempty result directory; select a new --output-root.')
    output.mkdir(parents=True, exist_ok=True)
    sources = [*ROOT.glob('models/*/*.nls'), *ROOT.glob('models/*/*.nlogox'),
               *ROOT.glob('scripts/**/*.py'), *ROOT.glob('scripts/**/*.R'),
               *ROOT.glob('scripts/java_support/*'), ROOT / 'run_all.py', ROOT / 'run_all.ps1']
    sources = [p for p in sorted(sources) if p.is_file()]
    receipt = {'status': 'running', 'command': args.command,
               'upstream': json.loads((ROOT / 'source_manifest.json').read_text(encoding='utf-8'))['ref'],
               'started_utc': datetime.now(timezone.utc).isoformat(),
               'scientific_parameters_changed': False,
               'sources': {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in sources},
               'steps': [],
               'coverage_note': 'verify checks all published endpoints; smoke adds bounded native runs. '
                                'Only reproduce regenerates every full BehaviorSpace batch.'}
    receipt_file = output / 'pipeline.json'

    def step(name: str, command: list[str]) -> None:
        log = output / f'{len(receipt["steps"]):02d}_{name}.log'
        item = {'name': name, 'command': command, 'started_utc': datetime.now(timezone.utc).isoformat(),
                'log': log.name}
        receipt['steps'].append(item)
        receipt_file.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(f'Running {name}; log: {log}', flush=True)
        with log.open('x', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        item['returncode'] = result.returncode
        item['completed_utc'] = datetime.now(timezone.utc).isoformat()
        if result.returncode:
            raise RuntimeError(f'{name} failed (exit {result.returncode}); inspect {log}')
        print(f'Passed {name}', flush=True)

    py = [sys.executable, '-X', 'utf8']
    r_args = ['--rscript', args.rscript] if args.rscript else []
    native_args = ['--threads', str(args.threads)]
    if args.netlogo:
        native_args += ['--netlogo', args.netlogo]
    if args.java:
        native_args += ['--java', args.java]
    try:
        step('model', py + ['scripts/verify_model.py', '--output-dir', str(output / 'model')])
        step('verifier_mutations', py + ['-m', 'unittest', 'discover', '-s', 'scripts',
             '-p', 'test_verify_model.py', '-v'])
        step('statistics', py + ['scripts/verify_statistics.py', '--output-dir', str(output / 'statistics')] + r_args)
        if args.command in ('smoke', 'reproduce'):
            step('native', py + ['scripts/native_checks.py', '--output-dir', str(output / 'native')] + native_args)
            step('native_baseline', py + ['scripts/compare_native_baseline.py', '--native-dir', str(output / 'native'),
                 '--output-dir', str(output / 'native_baseline')])
        if args.command == 'reproduce':
            raw_root = output / 'raw'
            for exp, experiment, filename in FULL_JOBS:
                step(experiment, py + ['scripts/run_netlogo.py', '--model', str(MODELS[exp]),
                     '--experiment', experiment, '--output', str(raw_root / f'experiment_{exp}' / filename)] + native_args)
            step('analysis', py + ['scripts/analysis/run_analysis.py', '--experiment', 'all',
                 '--raw-root', str(raw_root), '--output-root', str(output / 'analysis')] + r_args)
        elif args.command == 'analyze':
            step('analysis', py + ['scripts/analysis/run_analysis.py', '--experiment', 'all',
                 '--raw-root', str(args.raw_root.resolve()), '--output-root', str(output / 'analysis')] + r_args)
        for path in sources:
            key = str(path.relative_to(ROOT)).replace('\\', '/')
            if digest(path) != receipt['sources'][key]:
                raise RuntimeError(f'Source changed during this pipeline: {key}')
        receipt['status'] = 'passed'
    except Exception as exc:
        receipt['status'] = 'failed'
        receipt['error'] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        receipt['completed_utc'] = datetime.now(timezone.utc).isoformat()
        receipt_file.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'Pipeline {receipt["status"]}: {receipt_file}', flush=True)
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
