import folium
import os
import datetime

from google.cloud import storage
from folium.map import Marker


class Visualize:
    """
    Basic visualization class. Includes helper functions to visualize data on interactive maps.
    """

    def __init__(self, data):
        self.private_key = os.environ.get("SERVICE_ACCOUNT_PRIVATE_KEY", "")
        self.data = data

    def _generate_download_signed_url_v4(self, blob_name, bucket_name):
        """
        Generates a v4 signed URL for downloading a blob.

        Note that this method requires a service account key file. You can not use
        this if you are using Application Default Credentials from Google Compute
        Engine or from the Google Cloud SDK.

        Parameters
        ----------
        blob_name: str
            blob name
        bucket_name: str
            bucket name
        Returns
        -------
        String: signed url
        """
        storage_client = storage.Client.from_service_account_json(self.private_key)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
        )
        return url

    def _signed_url_from_row(self, row):
        """
        Generates a v4 signed URL for a given row of the visualization dataframe.

        Note that this method requires a service account key file. You can not use
        this if you are using Application Default Credentials from Google Compute
        Engine or from the Google Cloud SDK.

        Parameters
        ----------
        row: int
            row index of dataframe for visualization.
        Returns
        -------
        String: signed url
        """
        image_url = row["image_url"]
        image_path = image_url.split(".com/")[1]
        bucket_name = image_path.split("/")[0]
        blob_name = "/".join(image_path.split("/")[1:])
        url = self._generate_download_signed_url_v4(blob_name, bucket_name)
        return url

    def _popup_html(self, row, geom, image_url):
        """
        Creates html for marker popup.

        Parameters
        ----------
        row: int
            row index of dataframe for visualization.
        Returns
        -------
        String: html string of popup.
        """
        image = self.data.id[row]
        seq = self.data.seq[row]
        cam = self.data.camera_type[row]
        html = f"""
                    <!DOCTYPE html>
                    <html>
                        <center>
                            <table style="height: 126px; width: 305px;">
                                <tbody>
                                    <tr>
                                        <td style="background-color: #3e95b5;">
                                            <span style="color: #ffffff; padding-left: 5px;">
                                                Image
                                            </span>
                                        </td>
                                        <td style="width: 200px; padding-left: 5px; background-color: #f2f9ff;">
                                            {image}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="background-color: #3e95b5;">
                                            <span style="color: #ffffff; padding-left: 5px;">
                                                Sequence
                                            </span>
                                        </td>
                                        <td style="width: 200px; padding-left: 5px; background-color: #f2f9ff;">
                                            {seq}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="background-color: #3e95b5;">
                                            <span style="color: #ffffff; padding-left: 5px;">
                                                Camera
                                            </span>
                                        </td>
                                        <td style="width: 200px; padding-left: 5px; background-color: #f2f9ff;">
                                            {cam}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="background-color: #3e95b5;">
                                            <span style="color: #ffffff; padding-left: 5px;">
                                                Geometry
                                            </span>
                                        </td>
                                        <td style="width: 200px; padding-left: 5px; background-color: #f2f9ff;">
                                            {geom}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </center>
                        <center>
                            <img src="{image_url}" width=305>
                        </center>
                    </html>
                    """

        return html

    def add_signed_urls(self):
        """
        Adds a column of signed urls to the class dataset.

        Returns
        -------
        void
        """
        self.data["signed_url"] = self.data.apply(
            lambda row: self._signed_url_from_row(row), axis=1
        )

    def map(
        self,
        tiles="OpenStreetMap",
        zoom_start=18,
        additional_geometries=None,
        use_signed_urls=False,
    ):
        """
        Creates a folium map with markers for each image in class visualization data.

        Returns
        -------
        Folium map
        """
        geometries = ["geometry"]
        folium_colors = [
            "blue",
            "red",
            "green",
            "purple",
            "orange",
            "darkred",
            "lightred",
            "beige",
            "darkblue",
            "darkgreen",
            "cadetblue",
            "darkpurple",
            "white",
            "pink",
            "lightblue",
            "lightgreen",
            "gray",
            "black",
            "lightgray",
        ]
        if additional_geometries:
            geometries += additional_geometries

        x = self.data.geometry[0].xy[0][0]
        y = self.data.geometry[0].xy[1][0]

        map = folium.Map(location=[y, x], tiles=tiles, zoom_start=zoom_start)

        image_urls = []
        for j, geom in enumerate(geometries):
            points = [[point.xy[1][0], point.xy[0][0]] for point in self.data[geom]]
            for i, coordinates in enumerate(points):
                if j == 0:
                    if use_signed_urls:
                        url = self._signed_url_from_row(self.data.loc[i])
                    else:
                        url = self.data.image_url[i]
                    image_urls.append(url)
                else:
                    url = image_urls[i]
                html = self._popup_html(i, geom, url)
                popup = folium.Popup(html=html, max_width=500, lazy=True)
                map.add_child(
                    Marker(
                        location=coordinates,
                        popup=popup,
                        icon=folium.Icon(color=folium_colors[j]),
                    )
                )

        return map
