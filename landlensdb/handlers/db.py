import json

from geoalchemy2 import WKBElement
from shapely.wkb import loads
from shapely import Point
from sqlalchemy import create_engine, MetaData, Table, select, and_
from sqlalchemy.dialects.postgresql import insert

from landlensdb.geoclasses.geoimageframe import GeoImageFrame


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
        self.engine = create_engine(self.DATABASE_URL)
        self.result_set = None
        self.selected_table = None

    @staticmethod
    def _convert_points_to_wkt(record):
        """
        Converts Point objects to WKT (Well-Known Text) format.

        Args:
            record (dict): A dictionary containing keys and values, where values can be Point objects.

        Returns:
            dict: The record with Point objects converted to WKT strings.
        """
        for key, value in record.items():
            if isinstance(value, Point):
                record[key] = value.wkt
        return record

    @staticmethod
    def _convert_dicts_to_json(record):
        """
        Converts dictionary values in a record to JSON strings.

        Args:
            record (dict): A dictionary where values may include other dictionaries.

        Returns:
            dict: The modified record with dict values converted to JSON strings.
        """
        for key, value in record.items():
            if isinstance(value, dict):
                record[key] = json.dumps(value)
        return record

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

    def upsert_images(self, gif, table_name, conflict="update"):
        """
        Inserts or updates image data in the specified table.

        Args:
            gif (GeoImageFrame): The data frame containing image data.
            table_name (str): The name of the table to upsert into.
            conflict (str, optional): Conflict resolution strategy ("update" or "nothing"). Defaults to "update".

        Raises:
            ValueError: If an invalid conflict resolution type is provided.
        """
        data = gif.to_dict(orient="records")

        meta = MetaData()
        table = Table(table_name, meta, autoload_with=self.engine)

        with self.engine.begin() as conn:
            for record in data:
                record = self._convert_points_to_wkt(record)
                record = self._convert_dicts_to_json(record)
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
                        set_=updates
                    )
                elif conflict == "nothing":
                    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
                else:
                    raise ValueError(
                        "Invalid conflict resolution type. Choose 'update' or 'nothing'."
                    )

                conn.execute(on_conflict_stmt)
