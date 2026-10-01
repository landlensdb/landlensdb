import json
import math
import numbers
import os
from typing import TYPE_CHECKING

from geoalchemy2 import WKBElement
from geopandas import GeoDataFrame
from shapely.geometry.base import BaseGeometry
from shapely.wkb import loads
from sqlalchemy import create_engine, MetaData, Table, select, and_, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.inspection import inspect

if TYPE_CHECKING:
    from ..geoclasses.geoimageframe import GeoImageFrame


IMPORT_TABLE_COLUMNS = {
    "image_url": "text",
    "name": "text",
    "geometry": "geometry",
    "metadata": "jsonb",
    "thumbnail": "raster",
    "fingerprint": "text",
    "input_sha": "text",
}


def validate_table(cursor, table_name, required_columns, schema="public"):
    """Check required PostgreSQL column names and types without changing the table."""
    cursor.execute(
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table_name),
    )
    columns = dict(cursor.fetchall())
    if not columns:
        raise ValueError(
            "Table {}.{} does not exist or is not accessible.".format(
                schema, table_name
            )
        )
    errors = []
    for name, expected_type in required_columns.items():
        actual_type = columns.get(name)
        if actual_type is None:
            errors.append("missing {} ({})".format(name, expected_type))
        elif actual_type != expected_type:
            errors.append(
                "{} is {}; expected {}".format(name, actual_type, expected_type)
            )
    if errors:
        raise ValueError(
            "Invalid table {}.{}: {}.".format(schema, table_name, "; ".join(errors))
        )


class Postgres:
    """
    A class for managing image-related postgres database operations.

    Attributes:
        DATABASE_URL (str): The URL of the database to connect to.
        engine (Engine): SQLAlchemy engine for database connections.
        result_set (ResultProxy): The result of the last query executed.
        selected_table (Table): The table object for query operations.
    """

    def __init__(self, database_url):
        """
        Initializes the ImageDB class with the given database URL.

        Args:
            database_url (str): The URL of the database to connect to.
        """
        self.DATABASE_URL = database_url
        if hasattr(database_url, "connect"):
            self.engine = database_url
        else:
            self.engine = create_engine(self.DATABASE_URL)
        self.result_set = None
        self.selected_table = None

    @staticmethod
    def _convert_geometries_to_wkt(record):
        """
        Converts Shapely geometries to WKT (Well-Known Text) format.

        Args:
            record (dict): A dictionary containing keys and values, where values can be Shapely geometries.

        Returns:
            dict: The record with geometry objects converted to WKT strings.
        """
        for key, value in record.items():
            if isinstance(value, BaseGeometry):
                record[key] = value.wkt
        return record

    @staticmethod
    def _convert_dicts_to_json(record):
        """
        Normalize records so JSON/JSONB values contain only JSON-serializable types.

        Args:
            record (dict): A dictionary where values may include other dictionaries.

        Returns:
            dict: The normalized record.
        """

        def _clean_string(value):
            return value.replace("\x00", "")

        def _normalize_json_value(value):
            if isinstance(value, dict):
                return {
                    _clean_string(str(key)): _normalize_json_value(item)
                    for key, item in value.items()
                }
            if isinstance(value, (list, tuple, set)):
                return [_normalize_json_value(item) for item in value]
            if isinstance(value, str):
                return _clean_string(value)
            if value is None or isinstance(value, bool):
                return value
            if isinstance(value, BaseGeometry):
                return value.wkt
            if hasattr(value, "item"):
                try:
                    return _normalize_json_value(value.item())
                except Exception:
                    pass
            if hasattr(value, "tolist"):
                try:
                    return _normalize_json_value(value.tolist())
                except Exception:
                    pass
            if hasattr(value, "numerator") and hasattr(value, "denominator"):
                try:
                    return _normalize_json_value(float(value))
                except Exception:
                    pass
            if isinstance(value, numbers.Integral):
                return int(value)
            if isinstance(value, numbers.Real):
                numeric_value = float(value)
                return numeric_value if math.isfinite(numeric_value) else None
            if isinstance(value, bytes):
                return _clean_string(value.decode("utf-8", errors="replace"))
            return _clean_string(str(value))

        def _default_json(value):
            return _normalize_json_value(value)

        normalized_record = _normalize_json_value(record)
        return json.loads(
            json.dumps(normalized_record, default=_default_json, allow_nan=False)
        )

    def table(self, table_name):
        """
        Selects a table for performing queries on.

        Args:
            table_name (str): Name of the table to select.

        Returns:
            ImageDB: Returns self to enable method chaining.
        """
        metadata = MetaData()
        self.selected_table = Table(table_name, metadata, autoload_with=self.engine)
        self.result_set = self.selected_table.select()
        return self

    def filter(self, **kwargs):
        """
        Applies filters to the selected table based on provided conditions.

        Args:
            **kwargs: Key-value pairs representing filters to apply.

        Returns:
            ImageDB: Returns self to enable method chaining.

        Raises:
            ValueError: If an unsupported operation or a nonexistent column is specified.
        """
        filters = []

        for k, v in kwargs.items():
            if "__" in k:
                field_name, operation = k.split("__", 1)
            else:
                field_name = k
                operation = "eq"

            column = getattr(self.selected_table.columns, field_name, None)
            if column is None:
                raise ValueError(
                    f"Column '{field_name}' not found in table '{self.selected_table.name}'"
                )

            if operation == "eq":
                filters.append(column == v)
            elif operation == "gt":
                filters.append(column > v)
            elif operation == "lt":
                filters.append(column < v)
            elif operation == "gte":
                filters.append(column >= v)
            elif operation == "lte":
                filters.append(column <= v)
            else:
                raise ValueError(f"Unsupported operation '{operation}'")

        self.result_set = self.result_set.where(and_(*filters))
        return self

    def all(self):
        """
        Executes the query and returns the result as a GeoImageFrame.

        Returns:
            GeoImageFrame: The result of the query as a GeoImageFrame object.

        Raises:
            TypeError: If geometries are not of type Point.
        """
        from ..geoclasses.geoimageframe import GeoImageFrame

        with self.engine.connect() as conn:
            result = conn.execute(self.result_set)
            data = [row._asdict() for row in result.fetchall()]

        if not data:
            return GeoImageFrame([])  # Adjust according to your GeoImageFrame handling

        df_data = {col: [] for col in data[0].keys()}

        for d in data:
            for col, value in d.items():
                if isinstance(value, WKBElement):
                    try:
                        point_geom = loads(
                            bytes(value.data)
                        )  # convert WKBElement to Shapely geometry
                        if point_geom.geom_type != "Point":
                            raise TypeError("All geometries must be of type Point.")
                        df_data[col].append(point_geom)
                    except Exception as e:
                        print(f"Failed to process data {value.data}. Error: {e}")
                else:
                    df_data[col].append(value)

        return GeoImageFrame(df_data)

    def get_distinct_values(self, table_name, column_name):
        """
        Gets distinct values from a specific column of a table.

        Args:
            table_name (str): Name of the table to query.
            column_name (str): Name of the column to get distinct values from.

        Returns:
            list: A list of distinct values from the specified column.

        Raises:
            ValueError: If the specified column is not found in the table.
        """
        metadata = MetaData()
        metadata.reflect(bind=self.engine)

        if table_name not in metadata.tables:
            raise ValueError(f"Table '{table_name}' not found.")

        table = metadata.tables[table_name]

        if column_name not in table.columns:
            raise ValueError(
                f"Column '{column_name}' not found in table '{table_name}'"
            )

        column = table.columns[column_name]

        distinct_query = select(column).distinct()
        with self.engine.connect() as conn:
            result = conn.execute(distinct_query)

        distinct_values = [row[0] for row in result.fetchall()]
        return distinct_values

    def filter_existing_rows(self, image_paths):
        if self.selected_table is None:
            raise ValueError("Select a table first with `table(table_name)`.")

        normalized_paths = [str(path) for path in image_paths]
        if not normalized_paths:
            return []

        existing_paths = set()
        image_url_column = getattr(self.selected_table.c, "image_url", None)
        if image_url_column is None:
            raise ValueError(
                f"Column 'image_url' not found in table '{self.selected_table.name}'."
            )

        with self.engine.connect() as conn:
            for start in range(0, len(normalized_paths), 1000):
                chunk = normalized_paths[start : start + 1000]
                result = conn.execute(
                    select(image_url_column).where(image_url_column.in_(chunk))
                )
                existing_paths.update(row[0] for row in result.fetchall())

        return [path for path in normalized_paths if path not in existing_paths]

    def remove_unmatched_for_input(
        self, input_sha, image_paths, *, scope_image_urls=None
    ):
        """Delete unmatched rows in a group, optionally limited to selected URLs."""
        if self.selected_table is None:
            raise ValueError("Select a table first with `table(table_name)`.")
        if "input_sha" not in self.selected_table.c:
            raise ValueError("The selected table has no 'input_sha' column.")
        matched_paths = [str(path) for path in image_paths]
        filters = [self.selected_table.c.input_sha == input_sha]
        if scope_image_urls is not None:
            scope_image_urls = [str(path) for path in scope_image_urls]
            if not scope_image_urls:
                return 0
            filters.append(self.selected_table.c.image_url.in_(scope_image_urls))
        if matched_paths:
            filters.append(~self.selected_table.c.image_url.in_(matched_paths))
        with self.engine.begin() as conn:
            result = conn.execute(self.selected_table.delete().where(and_(*filters)))
        return result.rowcount or 0

    def remove_all_for_input(self, input_sha, *, scope_image_urls=None):
        """Delete all rows in a group, optionally limited to selected URLs."""
        return self.remove_unmatched_for_input(
            input_sha, [], scope_image_urls=scope_image_urls
        )

    @staticmethod
    def _qualified_table_name(table):
        table_name = table.name.replace('"', '""')
        if table.schema:
            schema_name = table.schema.replace('"', '""')
            return '"{}"."{}"'.format(schema_name, table_name)
        return '"{}"'.format(table_name)

    @staticmethod
    def _thumbnail_to_gdal_raster(thumbnail_dataset):
        from osgeo import gdal

        vsi_path = f"/vsimem/{os.urandom(16).hex()}.tif"
        try:
            gtiff_driver = gdal.GetDriverByName("GTiff")
            gtiff_driver.CreateCopy(vsi_path, thumbnail_dataset)
            raster_bytes = gdal.VSIGetMemFileBuffer_unsafe(vsi_path)
            return bytes(raster_bytes)
        finally:
            gdal.Unlink(vsi_path)

    @staticmethod
    def _ensure_unique_constraint(conn, table_name, constraint_name, column_name):
        table_ident = table_name.replace('"', '""')
        constraint_ident = constraint_name.replace('"', '""')
        column_ident = column_name.replace('"', '""')
        conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = '{constraint_ident}'
                    ) THEN
                        EXECUTE 'ALTER TABLE "{table_ident}" '
                             || 'ADD CONSTRAINT "{constraint_ident}" '
                             || 'UNIQUE ("{column_ident}")';
                    END IF;
                END
                $$;
                """
            )
        )

    def upsert_images(
        self,
        gif,
        table_name,
        conflict="update",
        if_exists="upsert",
        *args,
        input_sha=None,
        **kwargs,
    ):
        """
        Write image data to the specified table.

        Args:
            gif (GeoImageFrame): The data frame containing image data.
            table_name (str): The name of the table to write into.
            conflict (str, optional): Conflict resolution strategy for upsert mode
                ("update" or "nothing"). Defaults to "update".
            if_exists (str, optional): Write behavior ("fail", "replace",
                "append", or "upsert"). Defaults to "upsert".
            input_sha (str, optional): Restrict updates to this import group.

        Raises:
            ValueError: If an invalid write mode or conflict resolution type is provided.
        """
        gif._verify_structure()

        if if_exists in ("fail", "replace", "append"):
            gdf_to_write = GeoDataFrame(
                gif.drop(columns=["thumbnail"], errors="ignore"),
                geometry="geometry",
                crs=gif.crs,
            )
            dtype = kwargs.pop("dtype", {}).copy()
            if "metadata" in gdf_to_write.columns:
                dtype["metadata"] = JSONB
                gdf_to_write["metadata"] = gdf_to_write["metadata"].apply(
                    lambda value: (
                        json.dumps(self._convert_dicts_to_json(value))
                        if isinstance(value, dict)
                        else value
                    )
                )

            metadata = MetaData()
            metadata.reflect(bind=self.engine)

            if not inspect(self.engine).has_table(table_name):
                gdf_to_write.to_postgis(
                    table_name,
                    self.engine,
                    if_exists=if_exists,
                    *args,
                    dtype=dtype,
                    **kwargs,
                )
            else:
                if if_exists == "fail":
                    raise ValueError(f"Table '{table_name}' already exists.")
                if if_exists == "replace":
                    table = metadata.tables[table_name]
                    with self.engine.connect() as conn:
                        table.drop(conn)
                    gdf_to_write.to_postgis(
                        table_name,
                        self.engine,
                        if_exists="replace",
                        *args,
                        dtype=dtype,
                        **kwargs,
                    )
                elif if_exists == "append":
                    gdf_to_write.to_postgis(
                        table_name,
                        self.engine,
                        if_exists="append",
                        *args,
                        dtype=dtype,
                        **kwargs,
                    )

            metadata.reflect(bind=self.engine)
            table = metadata.tables[table_name]

            with self.engine.connect() as conn:
                conn.execute(text("SET postgis.gdal_enabled_drivers = 'GTiff'"))
                if "metadata" in gdf_to_write.columns:
                    conn.execute(
                        text(
                            f"ALTER TABLE {self._qualified_table_name(table)} "
                            f'ALTER COLUMN "metadata" TYPE jsonb USING "metadata"::jsonb'
                        )
                    )

                for col in gif.required_columns:
                    stmt = text(
                        f"ALTER TABLE {self._qualified_table_name(table)} "
                        f"ALTER COLUMN {col} SET NOT NULL"
                    )
                    conn.execute(stmt)

                self._ensure_unique_constraint(
                    conn, table.name, f"{table.name}_image_url_key", "image_url"
                )
                if "fingerprint" in gif.columns:
                    self._ensure_unique_constraint(
                        conn,
                        table.name,
                        f"{table.name}_fingerprint_key",
                        "fingerprint",
                    )

                if "thumbnail" in gif.columns:
                    conn.execute(
                        text(
                            f"ALTER TABLE {self._qualified_table_name(table)} "
                            f"ADD COLUMN IF NOT EXISTS thumbnail raster"
                        )
                    )

                    update_stmt = text(
                        f"UPDATE {self._qualified_table_name(table)} "
                        f"SET thumbnail = ST_FromGDALRaster(:thumbnail_raster) "
                        f"WHERE image_url = :image_url"
                    )

                    for _, row in gif.iterrows():
                        thumbnail_dataset = row.get("thumbnail")
                        if thumbnail_dataset is None:
                            continue

                        thumbnail_raster = self._thumbnail_to_gdal_raster(
                            thumbnail_dataset
                        )
                        conn.execute(
                            update_stmt,
                            {
                                "thumbnail_raster": thumbnail_raster,
                                "image_url": row["image_url"],
                            },
                        )

                conn.connection.commit()
            return

        if if_exists != "upsert":
            raise ValueError(
                "Invalid if_exists value. Choose 'fail', 'replace', 'append', or 'upsert'."
            )

        data = gif.to_dict(orient="records")
        srid = gif.crs.to_epsg() if gif.crs is not None else None

        meta = MetaData()
        table = Table(table_name, meta, autoload_with=self.engine)
        thumbnail_updates = []

        with self.engine.begin() as conn:
            geometry_column = table.columns.get("geometry")
            if geometry_column is not None:
                current_geometry_type = getattr(
                    geometry_column.type, "geometry_type", None
                )
                current_geometry_type = (
                    current_geometry_type.upper()
                    if isinstance(current_geometry_type, str)
                    else None
                )
                if current_geometry_type not in (None, "GEOMETRY"):
                    table_srid = max(getattr(geometry_column.type, "srid", 0), 0)
                    conn.execute(
                        text(
                            "ALTER TABLE {} "
                            "ALTER COLUMN geometry TYPE geometry(Geometry, {}) "
                            "USING geometry".format(
                                self._qualified_table_name(table), table_srid
                            )
                        )
                    )
            for record in data:
                thumbnail_value = record.pop("thumbnail", None)
                record = self._convert_geometries_to_wkt(record)
                record = self._convert_dicts_to_json(record)
                if srid and record.get("geometry"):
                    record["geometry"] = "SRID={};{}".format(srid, record["geometry"])
                fingerprint_value = record.get("fingerprint")

                if (
                    conflict == "update"
                    and fingerprint_value
                    and "fingerprint" in table.columns
                ):
                    updates = {key: value for key, value in record.items()}
                    fingerprint_update = (
                        update(table)
                        .where(table.c.fingerprint == fingerprint_value)
                        .values(**updates)
                    )
                    if input_sha is not None:
                        fingerprint_update = fingerprint_update.where(
                            table.c.input_sha == input_sha
                        )
                    fingerprint_result = conn.execute(fingerprint_update)
                    if fingerprint_result.rowcount:
                        continue
                elif (
                    conflict == "nothing"
                    and fingerprint_value
                    and "fingerprint" in table.columns
                ):
                    fingerprint_exists = conn.execute(
                        select(table.c.fingerprint).where(
                            table.c.fingerprint == fingerprint_value
                        )
                    ).first()
                    if fingerprint_exists:
                        continue

                insert_stmt = insert(table).values(**record)
                if conflict == "update":
                    updates = {
                        key: getattr(insert_stmt.excluded, key)
                        for key in record
                        if key != "image_url"
                    }
                    constraint_name = f"{table.name}_image_url_key"
                    on_conflict_stmt = insert_stmt.on_conflict_do_update(
                        constraint=constraint_name,
                        set_=updates,
                        where=(
                            table.c.input_sha == input_sha
                            if input_sha is not None
                            else None
                        ),
                    )
                elif conflict == "nothing":
                    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
                else:
                    raise ValueError(
                        "Invalid conflict resolution type. Choose 'update' or 'nothing'."
                    )

                written = conn.execute(
                    on_conflict_stmt.returning(table.c.image_url)
                ).first()
                if written is None:
                    continue

                if thumbnail_value is not None:
                    thumbnail_updates.append(
                        {
                            "image_url": record["image_url"],
                            "thumbnail": thumbnail_value,
                        }
                    )

            if thumbnail_updates and "thumbnail" in table.columns:
                update_stmt = text(
                    f"UPDATE {self._qualified_table_name(table)} "
                    f"SET thumbnail = ST_FromGDALRaster(:thumbnail_raster) "
                    f"WHERE image_url = :image_url"
                )
                for update_values in thumbnail_updates:
                    thumbnail_raster = self._thumbnail_to_gdal_raster(
                        update_values["thumbnail"]
                    )
                    conn.execute(
                        update_stmt,
                        {
                            "thumbnail_raster": thumbnail_raster,
                            "image_url": update_values["image_url"],
                        },
                    )
