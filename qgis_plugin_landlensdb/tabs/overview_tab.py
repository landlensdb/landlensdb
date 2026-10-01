# -*- coding: utf-8 -*-

from qgis.PyQt import QtWidgets


class OverviewTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(OverviewTab, self).__init__(parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Landlensdb QGIS Plugin")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        title.setFont(font)
        layout.addWidget(title)

        content = QtWidgets.QTextBrowser(self)
        content.setOpenExternalLinks(True)
        content.setReadOnly(True)
        content.setHtml(
            """
            <p>Landlensdb is a geospatial image workflow for storing image records, thumbnails, footprints, and metadata in PostgreSQL/PostGIS and then working with them directly in QGIS. It is useful for organizing local and remote imagery, keeping metadata queryable, and turning SQL results into QGIS layers without manual export steps.</p>

            <h3>Setup</h3>
            <p>Use <b>Setup</b> to create PostGIS extension SQL and save the PostgreSQL connection used by Import and Query. The plugin depends on QPIP for Python package installation, which should have already installed the required packages.</p>

            <h3>Import</h3>
            <p><b>Import Parameters</b> opens a <b>Search Glob</b> field that automatically saves valid path-pattern edits while preserving the other loaded settings. Enable <b>Advanced settings</b> to edit the full JSON, then use <b>Save</b>. <b>Open Template Folder</b> opens the preset files. Presets cover EXIF-geotagged photos, georeferenced rasters, and images with sidecar metadata. Imports are grouped by the SHA-256 digest of their normalized parameters. Each row stores that digest in <code>input_sha</code> and the configuration as an object at <code>metadata.import_params</code>.</p>
            <p>The JSON controls one full-path wcmatch file glob, field sources, geometry extraction, user-defined metadata, thumbnails, and fingerprints. Threads, batch size, error handling, and output CRS are controls below the table. Output CRS must match the destination table; new tables use the chosen CRS.</p>
            <p><b>Add</b> imports new images using the saved <b>Import Parameters</b> and leaves existing images unchanged. <b>Actions</b> beside <b>Refresh</b> applies to every import group in the chosen table. Each row's <b>Actions</b> applies only to that group. Use these menus to update images, remove old or all rows, or fetch metadata structure. <b>Update New</b> skips existing image paths.</p>
            <p><b>Folder Update</b> and <b>Folder Update New</b> use the group's original glob within a selected folder and preserve its import parameters and hash. <b>Folder Drop Old</b> and <b>Folder Drop All</b> let you select a folder, extensions, and optional recursive search. Drop Old removes selected rows whose images no longer match the original search; Drop All removes all selected rows. Image files and other import groups are unchanged.</p>

            <h3>Additional Metadata</h3>
            <p>An optional <code>metadata.sidecar_path</code> names one file relative to each image's directory: <code>./{base}.json</code> is adjacent, <code>./metadata.json</code> uses a fixed name, and <code>../{base}.json</code> goes up one directory. Paths must start with <code>./</code> or <code>../</code>. Only <code>{base}</code> (the image filename without its final extension) is substituted; globs and other placeholders are unsupported. Filenames and field paths are defined in JSON; filename case follows the filesystem. Missing sidecars leave sidecar metadata empty and the image import continues. JSON, GeoJSON, YAML, and IMD files are converted to a JSON-like mapping before metadata expressions are evaluated. Metadata values can reference EXIF, raster, sidecar, file, geometry, or automatic EXIF time parsing. The reserved metadata sidecar path is excluded from stored metadata. Only required image metadata is read. Other values are stored literally.</p>

            <p>Thumbnails use <code>"enabled": "source"</code> to use the source image or <code>"enabled": "sidecar"</code> to use a browse image. Browse thumbnails require an explicit <code>thumbnail.sidecar_path</code> in the JSON, using the same relative-path rules. Missing browse files leave thumbnails empty. Both modes keep full resolution when resize settings are omitted. The photo and raster templates set a 256 × 256 size with Lanczos resampling. Resizing requires all three settings: <code>width</code>, <code>height</code>, and <code>resampling</code>. <code>false</code> disables thumbnails.</p>
            <p>Add, Update, Drop Old, Drop All, and folder actions run in the background so QGIS remains interactive. Cancel stops at the next checkpoint after the current file or database operation returns. Previously saved batches remain in the database.</p>

            <h3>Query</h3>
            <p>Use <b>Query</b> to preview SQL results and build spatial and metadata expressions. The query text is the source for previewing, viewing, grouping, and metadata copy actions.</p>
            <p><b>File Spatial Query</b> inserts a spatial condition from a vector file. <b>Select Bbox Query</b> lets you drag a rectangle on the QGIS map, then returns to the query editor with an intersection condition. Press Escape or right-click to cancel. Both spatial helpers transform the source geometry into the database geometry's CRS.</p>
            <p>The SQL must return <code>image_url</code>. If <code>image_url</code> is a string, each row is added directly. If it is a list of strings, the other columns define the QGIS group hierarchy from left to right.</p>

            <h3>View And Copy</h3>
            <p>Query results can be viewed in QGIS as geometry and, where available, thumbnails. The <b>View</b> tab can display multiple selected Landlensdb images in a zoomable grid, navigate through the selected layer by an organized metadata field, and optionally rotate images to north-up. <b>Source</b> selects the stored <b>Preview</b>, the original <b>image_url</b>, or a local image path from any field in <b>Metadata</b>. Relative paths use each image's original directory, and <code>{base}</code> uses its filename without the final extension. For WorldView browse JPGs, choose <b>Metadata → import_params → thumbnail → sidecar_path</b>. This works with existing stored import parameters. Changing the source preserves checked images; adding them to the map still uses their original image URLs.</p>
            <p>Staged metadata fields can also be copied from the current query into CSV output for the matching rows. If the query is grouped, each group is separated by a heading line before its CSV block, using a format like <code>Year=2024.Month=05</code> based on the grouping columns and values.</p>
            """
        )
        layout.addWidget(content, 1)
