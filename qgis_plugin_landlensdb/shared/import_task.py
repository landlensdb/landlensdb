"""Background import operations; only signals cross back to the widgets."""

import threading

from qgis.PyQt import QtCore
from qgis.core import QgsTask
from sqlalchemy import create_engine, func, select

from ..landlensdb import Postgres, import_local_images, parse_import_json
from ..landlensdb.handlers.importer import (
    discover_image_paths,
    filter_folder_image_urls,
    prepare_import_paths,
)
from ..landlensdb.handlers.local import ImportCancelledError


def open_database(url, connect_args, table_name):
    engine = create_engine(url, connect_args=connect_args)
    try:
        database = Postgres(engine)
        database.table(table_name)
        return database
    except Exception:
        engine.dispose()
        raise


def read_import_groups(database):
    table = database.selected_table
    statement = (
        select(
            table.c.input_sha,
            func.count(),
            func.min(table.c.metadata["import_params"].astext),
        )
        .where(table.c.input_sha.is_not(None))
        .group_by(table.c.input_sha)
        .order_by(table.c.input_sha)
    )
    with database.engine.connect() as connection:
        return [
            {"input_sha": row[0], "row_count": row[1], "import_params": row[2]}
            for row in connection.execute(statement)
        ]


class ImportTask(QgsTask):
    progress_updated = QtCore.pyqtSignal(int, int)
    phase_changed = QtCore.pyqtSignal(str)
    completed = QtCore.pyqtSignal(object, object)

    def __init__(
        self,
        operation,
        configs,
        *,
        database_url,
        connect_args,
        table_name,
        output_crs=None,
        output_srid=None,
        max_workers=4,
        batch_size=100,
        on_error="skip",
        skip_existing=False,
        search_folder=None,
        extensions=None,
        recursive=False,
        cancel_event=None,
    ):
        if operation not in {"add", "update", "drop_old", "drop_all"}:
            raise ValueError("Unsupported import operation: {}".format(operation))
        super().__init__("Landlensdb {}".format(operation), QgsTask.CanCancel)
        self.operation = operation
        self.configs = tuple(configs)
        self.database_url = database_url
        self.connect_args = dict(connect_args)
        self.table_name = table_name
        self.output_crs = output_crs
        self.output_srid = output_srid
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.on_error = on_error
        self.skip_existing = skip_existing
        self.search_folder = search_folder
        self.extensions = tuple(extensions or ())
        self.recursive = recursive
        self.cancel_event = (
            cancel_event if cancel_event is not None else threading.Event()
        )
        self.result = None
        self.error = None

    def check_cancelled(self):
        if self.cancel_event.is_set() or self.isCanceled():
            raise ImportCancelledError("Operation cancelled.")

    def cancel(self):
        self.cancel_event.set()
        super().cancel()

    def update_progress(self, processed, total):
        self.progress_updated.emit(processed, total)
        if total:
            self.setProgress(100 * processed / total)

    def folder_image_urls(self, database, input_sha, config):
        table = database.selected_table
        statement = select(table.c.image_url).where(table.c.input_sha == input_sha)
        with database.engine.connect() as connection:
            rows = connection.execute(statement.execution_options(yield_per=1000))
            return filter_folder_image_urls(
                config,
                (row[0] for row in rows),
                self.search_folder,
                self.extensions,
                recursive=self.recursive,
                cancel_event=self.cancel_event,
            )

    def run(self):
        database = None
        try:
            self.check_cancelled()
            self.phase_changed.emit("Connecting to database…")
            database = open_database(
                self.database_url, self.connect_args, self.table_name
            )
            updating = self.operation in {"add", "update"}
            if updating:
                geometry_column = database.selected_table.c.get("geometry")
                srid = (
                    getattr(geometry_column.type, "srid", 0)
                    if geometry_column is not None
                    else 0
                )
                if srid > 0 and srid != self.output_srid:
                    raise ValueError(
                        "Output CRS must match the selected table's geometry SRID ({}).".format(
                            srid
                        )
                    )
            # Validate every configuration before the first mutation.
            configs = []
            needs_config = (
                self.operation != "drop_all" or self.search_folder is not None
            )
            for sha, text in self.configs:
                self.check_cancelled()
                if needs_config and not text:
                    table = database.selected_table
                    with database.engine.connect() as connection:
                        text = connection.execute(
                            select(table.c.metadata["import_params"].astext)
                            .where(table.c.input_sha == sha)
                            .limit(1)
                        ).scalar()
                    if not text:
                        raise ValueError(
                            "This import group has no stored import parameters."
                        )
                configs.append(
                    (
                        sha,
                        (parse_import_json(text) if needs_config else None),
                    )
                )
            deleted = 0
            wrote = False
            for input_sha, config in configs:
                self.check_cancelled()
                paths = None
                scope = {}
                if self.search_folder is not None and not updating:
                    self.phase_changed.emit("Finding rows in the selected folder…")
                    scope["scope_image_urls"] = self.folder_image_urls(
                        database, input_sha, config
                    )
                    self.check_cancelled()
                if self.operation == "drop_old":
                    self.phase_changed.emit("Finding images…")
                    discovery_options = (
                        {
                            "search_folder": self.search_folder,
                            "recursive": self.recursive,
                        }
                        if self.search_folder is not None
                        else {}
                    )
                    paths = discover_image_paths(
                        config["file_glob"],
                        cancel_event=self.cancel_event,
                        **discovery_options,
                    )
                    self.check_cancelled()
                    self.phase_changed.emit("Removing stale rows…")
                    paths, image_urls = prepare_import_paths(config, paths)
                    self.check_cancelled()
                    deleted += database.remove_unmatched_for_input(
                        input_sha, image_urls, **scope
                    )
                elif self.operation == "drop_all":
                    self.phase_changed.emit("Removing rows…")
                    deleted += database.remove_all_for_input(input_sha, **scope)
                if updating:
                    self.check_cancelled()
                    self.phase_changed.emit("Finding images…")
                    if self.search_folder is not None:
                        # Limit this run's discovery without changing the stored
                        # parameters or the SHA that identifies the import group.
                        paths = discover_image_paths(
                            config["file_glob"],
                            cancel_event=self.cancel_event,
                            search_folder=self.search_folder,
                        )
                        self.check_cancelled()
                        if not paths:
                            raise ValueError(
                                "No files match `file_glob`: {} in folder {}".format(
                                    config["file_glob"], self.search_folder
                                )
                            )
                    batches = None
                    try:
                        batches = import_local_images(
                            config,
                            output_crs=self.output_crs,
                            max_workers=self.max_workers,
                            batch_size=self.batch_size,
                            return_as_yield=True,
                            progress_callback=self.update_progress,
                            skip_images_in_postgresql=database,
                            skip_existing=self.skip_existing,
                            on_error=self.on_error,
                            cancel_event=self.cancel_event,
                            discovered_paths=paths,
                        )
                        for images in batches:
                            self.check_cancelled()
                            database.upsert_images(
                                images,
                                self.table_name,
                                conflict=(
                                    "nothing" if self.operation == "add" else "update"
                                ),
                                input_sha=(
                                    None if self.operation == "add" else input_sha
                                ),
                            )
                            wrote = True
                    except ValueError as exc:
                        if not (
                            self.skip_existing and "No new files match" in str(exc)
                        ):
                            raise
                    finally:
                        if batches is not None and hasattr(batches, "close"):
                            batches.close()
            self.check_cancelled()
            self.phase_changed.emit("Refreshing import groups…")
            records = read_import_groups(database)
            self.result = {
                "operation": self.operation,
                "wrote": wrote,
                "deleted": deleted,
                "records": records,
            }
            return True
        except Exception as exc:
            self.error = exc
            # Reflect any batches committed before failure/cancellation, off the UI thread.
            if database is not None:
                try:
                    self.result = {"records": read_import_groups(database)}
                except Exception:
                    pass
            return False
        finally:
            if database is not None:
                try:
                    database.engine.dispose()
                except Exception as exc:
                    if self.error is None:
                        self.error = exc

    def finished(self, success):
        # QGIS invokes this on the main thread, including cancellation before run.
        if not success and self.error is None:
            self.error = ImportCancelledError("Operation cancelled.")
        self.completed.emit(self.result, self.error)
