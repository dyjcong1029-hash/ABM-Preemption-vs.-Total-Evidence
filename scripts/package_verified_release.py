"""Package a completed, independently verified full reproduction without mutation.

Requires pipeline.json and postflight/full_reproduction_verification.json to
have status='passed'. The entire run directory is archived locally; a compact
evidence directory is prepared for GitHub. There is no network operation and no
claim that the local ZIP is remotely downloadable. All output paths must be new.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
TOTALS = {'batches': 12, 'runs': 132600, 'rows': 1932600,
          'trajectory_runs': 3600, 'trajectory_rows': 1803600}
JOBS = [
    (2, 'calibration_estimate_good_raw.csv', 'experiment-2-calibration-estimate-good', 50000, 50000),
    (2, 'calibration_estimate_bad_raw.csv', 'experiment-2-calibration-estimate-bad', 50000, 50000),
    (2, 'calibration_heldout_good_raw.csv', 'experiment-2-calibration-heldout-good', 10000, 10000),
    (2, 'calibration_heldout_bad_raw.csv', 'experiment-2-calibration-heldout-bad', 10000, 10000),
    (0, 'raw_main_final.csv', 'experiment-0-bandit-main-final', 1000, 1000),
    (0, 'raw_peer_check.csv', 'experiment-0-bandit-peer-check', 2000, 2000),
    (0, 'raw_trajectories.csv', 'experiment-0-bandit-trajectories', 400, 200400),
    (1, 'raw_main_final.csv', 'experiment-1-evidence-main-final', 3000, 3000),
    (1, 'raw_trajectories.csv', 'experiment-1-evidence-trajectories', 1200, 601200),
    (2, 'raw_main_final.csv', 'experiment-2-opaque-main-final', 3000, 3000),
    (2, 'raw_trajectories.csv', 'experiment-2-opaque-trajectories', 1200, 601200),
    (2, 'raw_exact_trajectories.csv', 'experiment-2-exact-regression-trajectories', 800, 400800),
]
EXCLUDED_ANALYSIS_TABLES = {'main_run_level_clean.csv', 'peer_check_run_level_clean.csv',
                            'peer_check_paired_runs.csv'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest_stream(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''):
        result.update(chunk)
    return result.hexdigest()


def digest(path):
    with path.open('rb') as stream:
        return digest_stream(stream)


def metadata(path):
    before = path.stat()
    sha256 = digest(path)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            f'Input changed while hashing: {path}')
    return {'bytes': after.st_size, 'sha256': sha256}


def verify_expected(snapshots):
    """Rebind every audited input, including sources and all R evidence."""
    for path, expected in snapshots.items():
        require(path.is_file() and not path.is_symlink(), f'Missing or linked audited input: {path}')
        require(metadata(path) == expected, f'Audited input changed since independent postflight/snapshot: {path}')


def expected_for(path, snapshots):
    """Use accepted hashes when available; snapshot all additional evidence."""
    current = metadata(path)
    if path in snapshots:
        require(current == snapshots[path], f'Audited input changed since independent postflight/snapshot: {path}')
    else:
        snapshots[path] = current
    return snapshots[path]


def read_expected_json(path, snapshots):
    require(path in snapshots, f'JSON receipt was not independently audited: {path}')
    raw = path.read_bytes()
    require({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} == snapshots[path],
            f'Audited JSON changed since independent postflight: {path}')
    return json.loads(raw.decode('utf-8-sig'))


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def files_under(root):
    require(root.is_dir(), f'Missing input directory: {root}')
    result = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), f'Refusing a symlink in evidence: {path}')
        if path.is_file():
            require(path.resolve().is_relative_to(root), f'File outside input root: {path}')
            result.append(path)
    return result


def preflight(run, postflight, output, archive):
    require(not output.exists(), '--output-root must be a new directory')
    require(not archive.exists(), '--raw-archive must be a new ZIP path')
    require(archive.suffix.lower() == '.zip', '--raw-archive must end in .zip')
    require(run != postflight and not postflight.is_relative_to(run) and not run.is_relative_to(postflight),
            'run-root and postflight-root must be separate directories')
    for destination in (output, archive):
        require(not any(destination == root or destination.is_relative_to(root) for root in (run, postflight)),
                'Output cannot be inside a frozen input directory')
    require(not archive.is_relative_to(output) and not output.is_relative_to(archive),
            'Keep the local raw ZIP outside the compact publication directory')
    pipeline = read_json(run / 'pipeline.json')
    post = read_json(postflight / 'full_reproduction_verification.json')
    require(pipeline.get('status') == 'passed' and pipeline.get('command') == 'reproduce',
            'The full reproduction pipeline has not passed')
    require(post.get('status') == 'passed' and post.get('totals') == TOTALS,
            'Independent full-reproduction postflight has not passed its fixed 12-batch totals')
    require(Path(post.get('run_root', '')).resolve() == run,
            'Independent postflight belongs to a different run-root')
    audited = post.get('input_files', {})
    require(audited, 'Independent postflight has no audited input hashes')
    snapshots = {Path(name).resolve(): {'bytes': item['bytes'], 'sha256': item['sha256']}
                 for name, item in audited.items()}
    verify_expected(snapshots)
    pipeline = read_expected_json(run / 'pipeline.json', snapshots)
    require(pipeline.get('scientific_parameters_changed') is False and pipeline.get('completed_utc'),
            'Missing unchanged-science/completion assertion')
    steps = pipeline.get('steps', [])
    require(steps and all(step.get('returncode') == 0 for step in steps), 'An incomplete/failed pipeline step exists')
    names = [step['name'] for step in steps]
    require(len(names) == len(set(names)), 'Duplicate pipeline step name')
    require({job[2] for job in JOBS} | {'model', 'verifier_mutations', 'statistics', 'native',
             'native_baseline', 'analysis'} <= set(names), 'Required full-run pipeline stages are missing')
    analysis = read_expected_json(run / 'analysis' / 'analysis_receipt.json', snapshots)
    require(analysis.get('status') == 'passed', 'The fresh R analysis has not passed')
    require(analysis.get('steps') and all(x.get('returncode') == 0 for x in analysis['steps']),
            'Missing/failed R analysis stages')
    batches, provenance = [], []
    for experiment, filename, name, runs, rows in JOBS:
        relative = Path('raw') / f'experiment_{experiment}' / filename
        path = run / relative
        receipt = Path(str(path) + '.provenance.json')
        record = read_expected_json(receipt, snapshots)
        native_check = record.get('postflight', {})
        require(record.get('status') == 'passed' and record.get('exit_code') == 0,
                f'Native run has not passed: {name}')
        require(record.get('experiment') == name and record.get('seed_subset_only') is False,
                f'Wrong experiment or bounded seed subset: {name}')
        require(native_check.get('passed') is True and native_check.get('runs') == runs and
                native_check.get('rows') == rows, f'Native completion grid mismatch: {name}')
        info = metadata(path)
        require(info['sha256'] == record.get('table_sha256'), f'Raw CSV changed since native verification: {name}')
        require(snapshots.get(path) == info and snapshots.get(receipt) == metadata(receipt),
                f'Raw CSV/provenance is not bound to the independent postflight: {name}')
        seeds = record.get('seeds', [])
        require(seeds, f'Missing seed namespace: {name}')
        batches.append({'path': relative.as_posix(), 'experiment': name, 'runs': runs, 'rows': rows,
                        **info, 'seeds': {'count': len(seeds), 'first': min(seeds), 'last': max(seeds)},
                        'provenance_path': receipt.relative_to(run).as_posix(),
                        'provenance_sha256': digest(receipt)})
        provenance.append({'path': receipt.relative_to(run).as_posix(),
                           'original_sha256': digest(receipt), 'document': record})
    require(len(list((run / 'raw').rglob('*.csv'))) == 12, 'Unexpected raw CSV files; expected exactly 12')
    return pipeline, post, batches, provenance, snapshots


def archive_run(run, archive, snapshots):
    """Archive every original file, verify CRC, then SHA-256 of every member."""
    paths = files_under(run)
    members = []
    archive_root = run.name
    for path in paths:
        relative = path.relative_to(run).as_posix()
        members.append({'path': relative, 'archive_member': f'{archive_root}/{relative}',
                        **expected_for(path, snapshots)})
    manifest = {'schema_version': 1, 'archive_root': archive_root,
                'scope': 'Every original file under the completed run-root, without filtering',
                'members': members,
                'manifest_self_not_listed': True}
    embedded = f'{archive_root}/_archive_member_manifest.json'
    require(embedded not in {x['archive_member'] for x in members}, 'Archive manifest name collision')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as zipped:
        for path, member in zip(paths, members):
            zipped.write(path, member['archive_member'])
        zipped.writestr(embedded, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    with zipfile.ZipFile(archive) as zipped:
        require(zipped.testzip() is None, 'ZIP CRC test failed')
        require(len(zipped.namelist()) == len(members)+1 and
                len(set(zipped.namelist())) == len(members)+1, 'ZIP member count/uniqueness mismatch')
        for path, member in zip(paths, members):
            with zipped.open(member['archive_member']) as stream:
                require(digest_stream(stream) == member['sha256'], f"ZIP member hash mismatch: {member['path']}")
            require(metadata(path) == {k: member[k] for k in ('bytes', 'sha256')},
                    f'Frozen input changed while archiving: {path}')
    require(files_under(run) == paths, 'Run-root file list changed while archiving')
    return manifest, {'availability': 'local', 'path': str(archive), **metadata(archive),
                       'original_files': len(members), 'zip_members': len(members)+1,
                       'crc_test_passed': True, 'all_member_sha256_verified': True,
                       'remote_download_url': None,
                       'note': 'Local archive only. Raw trajectories are not uploaded to GitHub; regenerate with the recorded command.'}


def package(args):
    run, postflight, output, archive = (getattr(args, field).resolve() for field in
                                       ('run_root', 'postflight_root', 'output_root', 'raw_archive'))
    pipeline, post, batches, provenance, snapshots = preflight(run, postflight, output, archive)
    postflight_paths = files_under(postflight)
    for path in postflight_paths:
        expected_for(path, snapshots)
    prefix = PurePosixPath(args.repo_prefix or f'verification/{run.name}')
    require(not prefix.is_absolute() and '..' not in prefix.parts and '\\' not in str(prefix),
            '--repo-prefix must be a safe repository-relative POSIX path')
    manifest, archive_info = archive_run(run, archive, snapshots)
    output.mkdir(parents=True, exist_ok=False)
    copied, omitted = [], []

    def copy(source, relative):
        target = output / relative
        require(source.is_file() and not source.is_symlink(), f'Invalid evidence input: {source}')
        expected = expected_for(source, snapshots)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as original, target.open('xb') as destination:
            shutil.copyfileobj(original, destination, length=1024*1024)
        require(metadata(source) == expected and metadata(target) == expected,
                f'Copy differs from independent postflight/snapshot: {source}')
        copied.append(relative.as_posix())

    copy(run / 'pipeline.json', Path('pipeline.json'))
    for source in sorted(run.glob('*.log')):
        copy(source, Path(source.name))
    # Preserve every independent postflight receipt/comparison/log. Large raw
    # exports and duplicate images are not expected here and are not selected.
    for source in postflight_paths:
        relative = source.relative_to(postflight)
        if source.suffix.lower() in ('.json', '.csv', '.log', '.md', '.gz'):
            copy(source, Path('postflight') / relative)
        else:
            omitted.append({'scope': 'postflight', 'path': relative.as_posix(), 'reason': 'not a receipt/comparison/log'})
    for directory in ('model', 'statistics', 'native', 'native_baseline'):
        for source in files_under(run / directory):
            relative = source.relative_to(run)
            if source.suffix.lower() in ('.json', '.csv', '.log', '.md'):
                require(source.stat().st_size <= 8*1024*1024, f'Unexpectedly large diagnostic evidence: {relative}')
                copy(source, relative)
            else:
                omitted.append({'scope': 'run', 'path': relative.as_posix(), 'reason': 'not selected diagnostic evidence'})
    for source in files_under(run / 'analysis'):
        relative = source.relative_to(run)
        keep = source.suffix.lower() in ('.json', '.log') or (
            source.suffix.lower() == '.csv' and source.name not in EXCLUDED_ANALYSIS_TABLES and
            source.stat().st_size <= 1024*1024)
        # All original validation CSVs are mandatory, not size-filtered.
        if source.name in ('validation_checks.csv', 'calibration_validation_checks.csv'):
            keep = True
        if keep:
            copy(source, relative)
        else:
            omitted.append({'scope': 'run', 'path': relative.as_posix(),
                            'reason': 'raw/clean run-level table, large table, or duplicate image; preserved in local ZIP'})
    plot_receipt = args.plot_receipt or PROJECT / 'verification/plot_layout_fix/receipt.json'
    if plot_receipt.is_file():
        copy(plot_receipt, Path('figure_layout') / 'receipt.json')
    write_json(output / 'archive_member_manifest.json', manifest)
    write_json(output / 'raw_batches.json', {'totals': TOTALS, 'batches': batches,
                                            'path_scope': 'Original run-root / ZIP-root relative; not compact repository download paths',
                                            'raw_archive': archive_info})
    compressed = output / 'native_provenance.json.gz'
    original = json.dumps({'schema_version': 1,
                           'path_scope': 'Original run-root relative; documents preserve original local paths',
                           'files': provenance}, ensure_ascii=False).encode('utf-8')
    with compressed.open('xb') as handle:
        with gzip.GzipFile(filename='', fileobj=handle, mode='wb', mtime=0) as stream:
            stream.write(original)
    with gzip.open(compressed, 'rb') as stream:
        require(stream.read() == original, 'Gzip provenance integrity test failed')
    # No passed publication index is issued if anything changed after the gate,
    # including audited files outside run-root and supplementary small records.
    verify_expected(snapshots)
    require(files_under(postflight) == postflight_paths, 'Postflight file list changed during packaging')
    readme = (
        '# Verified full reproduction evidence\n\n'
        f'Upstream scientific baseline: `{pipeline["upstream"]}`.\n\n'
        'All 12 fresh native batches and independent postflight passed: '
        '132,600 runs and 1,932,600 exported rows, including 3,600 trajectory runs '
        '(1,803,600 trajectory rows). Bounded native diagnostic runs are additional.\n\n'
        '- [Pipeline and exact commands](pipeline.json)\n'
        '- [Independent full-run postflight](postflight/full_reproduction_verification.json)\n'
        '- [Fresh R analysis receipt](analysis/analysis_receipt.json)\n'
        '- [Raw batch hashes, sizes and local archive identity](raw_batches.json)\n'
        '- [Complete local ZIP member hashes](archive_member_manifest.json)\n'
        '- [Original 12 native provenance records, gzip JSON](native_provenance.json.gz)\n\n'
        'The complete raw CSVs, diagnostic states, figures, R outputs and logs are '
        'preserved in a verified local ZIP. The ZIP is not uploaded and has no remote '
        'download URL. The hashes here support identity checking; they do not substitute '
        'for distributing the raw observations. Regenerate every batch using '
        '`python run_all.py reproduce --threads 4 --output-root results/my_fresh_reproduction`.\n\n'
        'The compact evidence retains all original validation CSVs and small result tables; '
        'clean run-level duplicates and PNG copies remain in the local ZIP. '
        'The native provenance gzip retains full seed lists and original source hashes.\n'
    )
    (output / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    evidence = [{'path': path.relative_to(output).as_posix(), **metadata(path)} for path in files_under(output)]
    index = {'schema_version': 1, 'status': 'passed', 'upstream_commit': pipeline['upstream'],
             'created_utc': datetime.now(timezone.utc).isoformat(), 'totals': TOTALS,
             'run_pipeline': 'pipeline.json',
             'independent_postflight': 'postflight/full_reproduction_verification.json',
             'raw_archive': archive_info, 'raw_batch_index': 'raw_batches.json',
             'native_provenance': {'path': compressed.name, **metadata(compressed)},
             'evidence_files': evidence, 'repo_prefix': prefix.as_posix(),
             'evidence_file_hash_list_excludes': ['index.json', 'publication_files.json'],
             'omitted_from_compact_evidence': omitted,
             'packager_sha256': digest(Path(__file__)),
             'scope': 'Compact publication evidence plus verified local archive; no GitHub write or remote asset upload.'}
    write_json(output / 'index.json', index)
    if args.publication_files:
        entries = [{'local_path': str(path),
                    'repo_relative_path': (prefix / path.relative_to(output).as_posix()).as_posix(),
                    **metadata(path)} for path in files_under(output)]
        write_json(output / 'publication_files.json', {
            'scope': 'Local upload plan only; this plan does not list or hash itself.', 'files': entries})
    return {'status': 'passed', 'evidence_root': str(output), 'index': str(output / 'index.json'),
            'raw_archive': archive_info, 'publication_files': str(output / 'publication_files.json') if args.publication_files else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--postflight-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True, help='New compact evidence directory')
    parser.add_argument('--raw-archive', type=Path, required=True, help='New local .zip outside the inputs/output directory')
    parser.add_argument('--repo-prefix', help='Upload destination prefix; default verification/<run-root name>')
    parser.add_argument('--plot-receipt', type=Path, help='Optional plot-layout receipt; defaults to the existing reviewed receipt')
    parser.add_argument('--publication-files', action='store_true', help='Write local upload plan publication_files.json')
    args = parser.parse_args(argv)
    try:
        result = package(args)
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
