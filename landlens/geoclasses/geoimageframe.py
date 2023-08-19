import base64
import folium
import os

import requests
from geopandas import GeoDataFrame
from shapely.geometry import Point

from folium.features import CustomIcon
from sqlalchemy import DDL, MetaData, Table


def generate_arrow_icon(compass_angle):
    svg = generate_arrow_svg(compass_angle)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    data_url = f"data:image/svg+xml;base64,{encoded}"

    icon = CustomIcon(icon_image=data_url, icon_size=(45, 45))
    return icon


def generate_arrow_svg(compass_angle):
    return f"""
<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
    <!-- Background circle (lighter blue dot) -->
    <circle cx="100" cy="100" r="40" fill="#6699FF"/>

    <g transform="rotate({compass_angle}, 100, 100)">
        <!-- Field of view arc. This example shows a FOV centered on the top (north) and spans 45 degrees -->
        <path d="M100,100 L150,50 A70,70 0 0,0 50,50 Z" fill="rgba(0,0,255,0.3)"/>
    </g>

    <!-- Camera icon, adjusted to center -->
    <rect x="80" y="86.5" width="40" height="27" fill="white"/>
    <circle cx="100" cy="99.5" r="9" fill="#6699FF" stroke="white" stroke-width="2.5"/>
    <rect x="90" y="79.5" width="20" height="7" fill="white"/>
</svg>
    """


class GeoImageFrame(GeoDataFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._verify_structure()

    def _verify_structure(self):
        required_columns = {"image_url": str, "name": str, "geometry": Point}

        for col, dtype in required_columns.items():
            if col not in self.columns:
                raise ValueError(f"The required column '{col}' is missing.")

            # Check if the elements are of the correct type
            wrong_type_mask = ~self[col].apply(lambda x: isinstance(x, dtype))
            if wrong_type_mask.any():
                raise TypeError(f"Column '{col}' contains wrong data type.")

    def to_dict_records(self):
        return self.to_dict("records")

    def to_file(self, filename, **kwargs):
        for col in self.columns:
            if col != "geometry":
                self[col] = self[col].apply(
                    lambda x: x.wkt if isinstance(x, Point) else x
                )

        super().to_file(filename, **kwargs)

    def to_postgis(self, name, engine, if_exists="fail", *args, **kwargs):
        required_columns = ["name", "image_url", "geometry"]
        for col in required_columns:
            if col not in self.columns:
                raise ValueError(f"Column '{col}' is missing.")

        if not self["name"].apply(isinstance, args=(str,)).all():
            raise TypeError("All entries in 'name' column must be of type string.")

        if not self["image_url"].apply(isinstance, args=(str,)).all():
            raise TypeError("All entries in 'image_url' column must be of type string.")

        if self["image_url"].duplicated().any():
            raise ValueError(
                "'image_url' column has duplicate entries. It must be unique."
            )

        if not all(geom.geom_type == "Point" for geom in self["geometry"]):
            raise TypeError("All geometries must be of type Point.")

        if self.crs != "EPSG:4326":
            raise ValueError("CRS must be EPSG:4326.")

        metadata = MetaData(bind=engine)
        table_exists = engine.has_table(name)

        if not table_exists:
            super().to_postgis(name, engine, if_exists=if_exists, *args, **kwargs)

            table = Table(name, metadata, autoload=True, autoload_with=engine)

            for col in required_columns:
                stmt = DDL(f"ALTER TABLE {table.name} ALTER COLUMN {col} SET NOT NULL")
                engine.execute(stmt)

            stmt = DDL(
                f"ALTER TABLE {table.name} ADD CONSTRAINT unique_image_url UNIQUE (image_url)"
            )
            engine.execute(stmt)

        else:
            if if_exists == "fail":
                raise ValueError(f"Table '{name}' already exists.")

            elif if_exists == "replace":
                table = Table(name, metadata, autoload=True, autoload_with=engine)
                table.drop(engine)
                super().to_postgis(name, engine, if_exists="replace", *args, **kwargs)

                table = Table(name, metadata, autoload=True, autoload_with=engine)

                for col in required_columns:
                    stmt = DDL(
                        f"ALTER TABLE {table.name} ALTER COLUMN {col} SET NOT NULL"
                    )
                    engine.execute(stmt)

                stmt = DDL(
                    f"ALTER TABLE {table.name} ADD CONSTRAINT unique_image_url UNIQUE (image_url)"
                )
                engine.execute(stmt, table=table.name)

            elif if_exists == "append":
                super().to_postgis(name, engine, if_exists="append", *args, **kwargs)

    @staticmethod
    def _download_image_from_url(url, dest_path):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        except requests.RequestException as e:
            print(f"Error downloading {url}. Error: {e}")
            return None

        return dest_path

    def download_images_to_local(self, dest_dir, filename_column=None):
        """
        Download images specified in the 'image_url' column of the GeoDataFrame to a specified local directory.
        """
        if "image_url" not in self.columns:
            raise ValueError("The GeoImageFrame must have a column named 'image_url'.")

        gdf_copy = self.copy()

        for index, row in gdf_copy.iterrows():
            image_url = row["image_url"]

            if not image_url.startswith(("http://", "https://")):
                print(f"Skipping {image_url}. It's not a valid URL.")
                continue

            original_filename = image_url.split("/")[-1].split(".")[
                0
            ]  # Extract filename from URL
            filename_value = row.get(filename_column, original_filename)

            destination_path = os.path.join(dest_dir, f"{filename_value}.jpg")

            local_path = self._download_image_from_url(image_url, destination_path)

            if local_path:
                gdf_copy.at[index, "image_url"] = local_path

        return GeoImageFrame(gdf_copy, geometry="geometry")

    @staticmethod
    def _create_table_row(label, value):
        value = value if value else "Unknown"
        return f"""
                <tr>
                    <td style="background-color: #3e95b5;">
                        <span style="color: #ffffff; padding-left: 5px;">
                            {label}
                        </span>
                    </td>
                    <td style="width: 200px; padding-left: 5px; background-color: #f2f9ff;">
                        {value}
                    </td>
                </tr>
                """

    def _popup_html(self, row, image_url, additional_properties):
        table_rows = ""
        table_rows += self._create_table_row("Image", self.name[row])

        for prop in additional_properties:
            table_rows += self._create_table_row(
                prop.capitalize(), self.get(prop, [None])[row]
            )

        if os.path.exists(image_url):
            with open(image_url, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode()
                image_url = f"data:image/jpg;base64,{encoded_image}"

        html = f"""
                    <!DOCTYPE html>
                    <html>
                        <center>
                            <table style="width: 305px;">
                                <tbody>
                                    {table_rows}
                                </tbody>
                            </table>
                        </center>
                        <center>
                            <img src="{image_url}" width=305>
                        </center>
                    </html>
                    """

        return html

    def map(
        self,
        tiles="OpenStreetMap",
        zoom_start=18,
        max_zoom=19,
        additional_properties=None,
        additional_geometries=None,
    ):
        if additional_properties is None:
            additional_properties = []

        x = self.geometry[0].xy[0][0]
        y = self.geometry[0].xy[1][0]

        map_obj = folium.Map(
            location=[y, x], tiles=tiles, zoom_start=zoom_start, max_zoom=max_zoom
        )

        image_urls = []

        def add_markers_to_group(geo_col, angle_col, group_name):
            nonlocal image_urls
            marker_group = folium.FeatureGroup(name=group_name)

            points = [
                [point.xy[1][0], point.xy[0][0]] for point in self[geo_col] if point
            ]
            for i, coordinates in enumerate(points):
                url = image_urls[i] if image_urls else self.image_url[i]
                html = self._popup_html(i, url, additional_properties)
                popup = folium.Popup(html=html, max_width=500, lazy=True)

                compass_angle = getattr(self, angle_col)[i]
                icon = generate_arrow_icon(compass_angle)

                marker = folium.Marker(location=coordinates, popup=popup, icon=icon)
                marker.add_to(marker_group)

            marker_group.add_to(map_obj)

        add_markers_to_group("geometry", "compass_angle", "Images")
        for geom_dict in additional_geometries:
            add_markers_to_group(
                geom_dict["geometry"], geom_dict["angle"], geom_dict["label"]
            )

        folium.LayerControl().add_to(map_obj)

        return map_obj
