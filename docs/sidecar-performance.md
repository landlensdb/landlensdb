# Sidecar lookup and local import performance audit

## Path lookup

Use `metadata.sidecar_path` or `thumbnail.sidecar_path` relative to each discovered image's directory. The only
placeholder is `{base}`, the image filename without its final extension. Paths
must start with `./` or `../`; bare filenames and unprefixed subfolders are rejected.
Use forward slashes for this required prefix on all platforms.
Examples: `./{base}.json`, `./metadata.yaml`, `../metadata/{base}.json`, and
`../../{base}.IMD`. The WorldView template uses `./{base}.IMD` for metadata
and `./{base}-BROWSE.JPG` for browse thumbnails. The metadata path is a reserved
control, excluded from stored metadata.

Each lookup substitutes `{base}`, joins the path, and performs one `is_file()`
check. Only a present regular file is opened and parsed. There is no glob,
directory enumeration, sorting, or Python `resolve()` walk. The filesystem
handles parent directories and symlinks, preserving the meaning of `..` after
a symlink. Filename case follows the filesystem; there is no extension search.

A missing file leaves sidecar metadata empty and the image import continues.
Required geometry, name, or URL values must still resolve; their failures and
invalid sidecar contents follow the configured `on_error` policy.

Validation is cached by template in a bounded cache. File existence and parsed
contents are checked afresh, so edits and newly created sidecars are visible.
The old top-level `sidecar_glob` and `sidecar_path` options report a migration
error pointing to `metadata.sidecar_path`. Thumbnail mode `"sidecar"` requires an
explicit `thumbnail.sidecar_path`, uses the same lookup, and reads the browse
image without loading the source. IMD parsing preserves raw keys and nested
groups; metadata paths and corner selection are defined entirely in JSON. Missing
browse files produce a null thumbnail; there is no source-image fallback.
Both thumbnail modes use the full image by default. Resizing requires explicit
`width`, `height`, and `resampling` settings. Browse images without georeferencing
use the four configured geometry corners (for example, from WorldView IMD metadata)
to warp onto a map grid in the selected Output CRS. This georeferencing step
requires resampling at native preview resolution, without a default 256-pixel
limit. Explicit resizing is applied in the same warp, avoiding a second pass.
Already georeferenced images keep their native CRS and geotransform; without
all three resize settings their pixels are read unchanged.

## Other work removed from the import loop

- Determine required metadata sources once per import, including geometry,
  name, URL, and nested metadata objects and arrays. Open images through Pillow
  for EXIF or GDAL for raster metadata only when those sources are needed.
- Read file size and timestamps only when those fields are referenced.
- Initialize timezone lookup data once per worker that needs it, instead of
  once per photo. Each worker has its own instance.
- Hash the already normalized import JSON rather than validating and
  serializing it again to calculate the input hash.
- Avoid the unused file-size check for robust fingerprints.

Image discovery still uses `file_glob`. Enabled thumbnails still require image
processing; robust fingerprints still read the complete file. These operations
can dominate total import time for large imagery. Disable thumbnails and
fingerprints for imports that need only metadata and footprints. Discovered paths are retained in memory, but only one batch per worker is queued.
Completed futures are released as batches are consumed. Folder updates share their
discovered paths with the importer, avoiding a second glob pass.

## QGIS responsiveness

The former plugin ran discovery, waits for image batches, database writes, and
result refreshes on the UI thread. Its image-level thread pool did not protect
those phases, and calling `processEvents()` only at progress updates left QGIS
unresponsive between updates.

Add, Update, Drop Old, Drop All, and folder actions run as `QgsTask` background jobs.
The task receives a snapshot of settings, creates and disposes its own database
engine, and fetches refreshed import groups before completing. Qt signals deliver
progress, status, errors, and final records to the widgets on the main thread.
The task never accesses widgets. This follows the [QGIS task threading rules](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/tasks.html).

Cancellation is checked before discovery, between glob matches, between images
and batches, and before database mutations. Queued batches are canceled on exit.
An in-progress filesystem call, a glob traversal before its next match, a GDAL
operation, or a database statement must return before cancellation can take effect.
Already committed batches are retained and reflected in the table after canceling.

## Local measurement

Measured on macOS 26.2 (arm64), Python 3.10.20, against the resolver from commit
`80091d6`. Both versions used the same temporary directory and a small JSON
sidecar with nested metadata. The baseline used `{parent}/{base}.json` and the
current implementation used `./{base}.json`. For absent files, the baseline's
missing-file exception was caught to continue the benchmark.

Times below are microseconds per lookup, including parsing when present, using
the median of three warmed runs (10 lookups per baseline run and 1,000 per new
run). Neighboring files were unrelated `.txt` files. These measurements describe
this local filesystem and cache state, not an end-to-end import speed guarantee.

| Neighboring files | Sidecar | Old glob (µs) | Direct path (µs) |
| ---: | --- | ---: | ---: |
| 0 | Missing | 3,225.32 | 5.43 |
| 0 | Present | 2,992.35 | 36.75 |
| 1,000 | Missing | 4,792.05 | 5.30 |
| 1,000 | Present | 4,456.08 | 72.47 |
| 10,000 | Missing | 18,064.55 | 5.34 |
| 10,000 | Present | 17,768.84 | 41.27 |

Regression tests assert exactly one file check and zero directory-search or
`resolve()` calls per sidecar lookup. They also cover adjacent and ancestor
paths, symlinks, literal special characters in image basenames, missing and
changing files, parsing failures, threaded imports, metadata source selection,
and timezone instance reuse. These operation-count tests protect the lookup
behavior independently of timing noise.

Run the offline library suite with:

```sh
python -m pytest tests --ignore=tests/test_tutorial_core.py
```

The excluded tutorial module also contains live PostgreSQL, Mapillary, and road
network integration examples that need their external services.

## Validation of background imports and thumbnail modes

- 205 offline library tests pass, including required `./` and `../` prefixes,
  real source/browse thumbnail reads, sidecar metadata selection, bounded batch
  scheduling, and cancellation.
- 45 QGIS action/editor tests pass using the real Qt event loop and QgsTask
  manager with mocked database I/O. A blocked discovery test verifies that Qt
  timers still fire and cancellation prevents subsequent writes.
- The QGIS UI test runner replaces the unused timezone constructor because its
  optional H3 wheel cannot load into the local signed QGIS Python executable.
  Timezone behavior is covered by the separate unmocked library tests.
- Live database and remote-service integration tests were not run.

## Further import speed opportunities

The following settings are available now:

- Use browse-sidecar thumbnails for WorldView products, or disable thumbnails
  when they are not needed. Keep fingerprints disabled unless content-based
  duplicate detection is needed: robust fingerprinting reads the whole source.
- Use Add/Update New to filter existing paths before image processing. Limit
  `file_glob` to the relevant directory and avoid recursive matching when the
  images are directly in that directory.
- If lower-quality previews are acceptable, reduce thumbnail dimensions and
  use `nearest` resampling. Nearest selects a source pixel instead of combining
  multiple pixels; see [GDAL's resampling options](https://gdal.org/en/stable/programs/gdal_translate.html).
- Measure a representative subset with different worker counts. Workers affect
  image processing, while database writes remain sequential; additional workers
  cannot remove the database bottleneck.

Code inspection and an instrumented run identified these next implementation
opportunities. They are findings, not changes included in the path-prefix update:

| Opportunity | Observed current behavior | Expected benefit |
| --- | --- | --- |
| Bulk database upserts and thumbnail updates | A mocked 100-row batch performs 100 write executions without thumbnails, or 200 with thumbnails, plus one table reflection request. Fingerprints were disabled and all rows inserted successfully. | Fewer database round trips, especially for a remote database. |
| Reuse table metadata across batches | `upsert_images()` requests table reflection on every call. | Fewer schema queries per import. Schema changes would need explicit invalidation. |
| Share the source GDAL dataset | A real raster import requiring raster metadata and a source thumbnail opened the same image twice. | Avoid reopening the source and rereading its metadata. Browse-sidecar thumbnails already avoid the source thumbnail read. |

The write counts were measured using mocked database I/O, so they are operation
counts rather than database timing results. Bulk upserts must preserve the
existing input-group and conflict rules. For large initial loads, a staging
`COPY` followed by a scoped merge is another option; PostgreSQL documents why
[COPY is more efficient for bulk loading](https://www.postgresql.org/docs/current/populate.html).
