"""Compare newly generated native endpoints with the pinned published raw runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_table(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        records = csv.reader(stream)
        for row in records:
            if row and row[0] == '[run number]':
                return list(csv.DictReader(stream, fieldnames=row))
    raise ValueError(f'BehaviorSpace header missing: {path}')


def key(row, policy_name=None, alias=None):
    policy = row[policy_name] if policy_name else ''
    if alias:
        policy = alias[policy]
    return (int(float(row['run-seed'])), row['world-mode'], row['peer-sharing?'], policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error('Refusing to overwrite an existing comparison directory.')
    output.mkdir(parents=True)
    comparisons = [
        ('smoke_0.csv', 0, 'raw_main_final.csv', None, None, None),
        ('smoke_1.csv', 1, 'raw_main_final.csv', 'evidence-policy', 'evidence-policy', None),
        ('smoke_2.csv', 2, 'raw_main_final.csv', 'credence-policy', 'credence-policy', None),
        ('peer_check.csv', 0, 'raw_peer_check.csv', None, None, None),
        ('evidence_trajectories.csv', 1, 'raw_main_final.csv', 'evidence-policy', 'evidence-policy', None),
        ('exact_trajectories.csv', 1, 'raw_main_final.csv', 'credence-policy', 'evidence-policy',
         {'Exact-C-Preemption': 'E-Preemption', 'Exact-C-Total Evidence': 'E-Total Evidence'}),
    ]
    report = {'status': 'running', 'scope': 'All common endpoint fields in bounded native runs vs published raw baselines',
              'comparisons': [], 'input_sha256': {}}
    try:
        for native_name, exp, reference_name, native_policy, reference_policy, alias in comparisons:
            native_path = args.native_dir / native_name
            reference_path = ROOT / 'data' / f'experiment_{exp}' / reference_name
            for path in (native_path, reference_path):
                report['input_sha256'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            native = [row for row in read_table(native_path) if int(float(row['[step]'])) == 500]
            reference = {key(row, reference_policy): row for row in read_table(reference_path)}
            if not native:
                raise ValueError(f'No native endpoints: {native_name}')
            checked, maximum_error, cases = 0, 0.0, set()
            columns = set()
            for row in native:
                case = key(row, native_policy, alias)
                if case in cases or case not in reference:
                    raise ValueError(f'Duplicate or unmatched native endpoint: {native_name}, {case}')
                cases.add(case)
                baseline = reference[case]
                common = (set(row) & set(baseline)) - {'[run number]', 'evidence-policy', 'credence-policy'}
                columns.update(common)
                for column in sorted(common):
                    a, b = row[column], baseline[column]
                    try:
                        na, nb = float(a), float(b)
                    except ValueError:
                        if a != b:
                            raise ValueError(f'{native_name} {case} {column}: {a!r} != {b!r}')
                    else:
                        if not math.isfinite(na) or not math.isfinite(nb):
                            raise ValueError(f'Nonfinite comparison: {native_name} {case} {column}')
                        difference = abs(na - nb)
                        maximum_error = max(maximum_error, difference)
                        if difference > 1e-10:
                            raise ValueError(f'{native_name} {case} {column}: {a} != {b}')
                    checked += 1
            report['comparisons'].append({'native': native_name, 'reference': str(reference_path.relative_to(ROOT)),
                                          'endpoints': len(native), 'field_comparisons': checked,
                                          'columns': sorted(columns), 'maximum_absolute_error': maximum_error})
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
    target = output / 'native_baseline_comparison.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(target), 'error': report.get('error')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
