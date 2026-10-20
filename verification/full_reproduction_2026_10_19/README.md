# Verified full reproduction evidence

Upstream scientific baseline: `e105f6217db78222e72633a663871c070d630ed3`.

All 12 fresh native batches and independent postflight passed: 132,600 runs and 1,932,600 exported rows, including 3,600 trajectory runs (1,803,600 trajectory rows). Bounded native diagnostic runs are additional.

- [Pipeline and exact commands](pipeline.json)
- [Independent full-run postflight](postflight/full_reproduction_verification.json)
- [Fresh R analysis receipt](analysis/analysis_receipt.json)
- [Raw batch hashes, sizes and local archive identity](raw_batches.json)
- [Complete local ZIP member hashes](archive_member_manifest.json)
- [Original 12 native provenance records, gzip JSON](native_provenance.json.gz)

The complete raw CSVs, diagnostic states, figures, R outputs and logs are preserved in a verified local ZIP. The ZIP is not uploaded and has no remote download URL. The hashes here support identity checking; they do not substitute for distributing the raw observations. Regenerate every batch using `python run_all.py reproduce --threads 4 --output-root results/my_fresh_reproduction`.

The compact evidence retains all original validation CSVs and small result tables; clean run-level duplicates and PNG copies remain in the local ZIP. The native provenance gzip retains full seed lists and original source hashes.
