from google.cloud import storage


class DataUtils:
    def __init__(self, data):
        self.data = data

    def _image_paths(self):
        image_urls = self.data["image_url"].to_list()
        image_paths = [image_url.split(".com/")[1] for image_url in image_urls]
        return image_paths

    def write_image_list(self, file_name):
        """
        Creates a txt file with download links to images on GCP. This will allow for fast download of many files.

        Parameters
        ----------
        file_name: str
          path to file to write list of images urls to. Must have extension .txt.

        Returns
        -------
        void
        """

        image_paths = self._image_paths()
        image_urls = ["gs://" + image_path for image_path in image_paths]
        with open(file_name, "w") as f:
            for image_url in image_urls:
                f.write(f"{image_url}\n")

    def download_gcp_image(self, image_id, download_dir):
        """
        Downloads image by image id. Very slow.

        Parameters
        ----------
        image_id: int
            id of image to download
        download_dir: str
            path to save downloaded image.

        Returns
        -------
            void
        """
        image_url = self.data.loc[self.data["id"] == image_id]["image_url"].values[0]
        image_path = image_url.split(".com/")[1]

        bucket_name = image_path.split("/")[0]
        rel_path = "/".join(image_path.split("/")[1:])
        image_name = image_path.split("/")[-1]
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(bucket_name)
        blob = bucket.blob(f"{rel_path}")
        filename = f"{download_dir}/{image_name}"
        blob.download_to_filename(filename)
