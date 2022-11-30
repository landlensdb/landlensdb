import os
import psycopg2


class InitializeMapillary:
    """
    Mapillary database tables and data initializer.

    Contains functions to create tables and other objects for Mapillary data.
    """

    def __init__(self):
        self.DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/mapillary')

    def create_image_table(self):
        """
        Creates mly_image table.

        Returns:
        void
        """
        conn = psycopg2.connect(self.DATABASE_URL)
        cur = conn.cursor()

        conn.autocommit = True
        cur.execute(
            '''
               CREATE TABLE IF NOT EXISTS 
               mly_images (
                   id  bigint NOT NULL,
                   seq char(30),
                   altitude real,
                   computed_altitude real,
                   camera_parameters jsonb,
                   camera_type varchar(20),
                   captured_at timestamp with time zone,
                   compass_angle real,
                   computed_compass_angle real,
                   exif_orientation varchar(200),
                   merge_cc bigint,
                   mesh jsonb,
                   sfm_cluster jsonb,
                   detections jsonb,
                   image_url varchar(2048),
                   computed_geometry geography(POINT, 4326),
                   geometry geography(POINT, 4326),
                   PRIMARY KEY(id)
               );
               CREATE INDEX idx_computed_geom ON mly_images USING gist (geometry);
               CREATE INDEX idx_geom ON mly_images USING gist (computed_geometry);
            '''
        )
        cur.close()
        conn.close()
