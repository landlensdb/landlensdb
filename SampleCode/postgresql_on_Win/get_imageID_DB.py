import os
import psycopg2
from psycopg2 import extras


def get_imageID_DB():
    imageID_DB = []
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/mapillary"
    # DATABASE_URL='postgresql://postgres:postgres@postgres:5432/mapillary'
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT imageid FROM mly_table")

    rows = cur.fetchall()
    for row in rows:
        # print(row[0])
        imageID_DB.append(row[0])

    cur.close()
    conn.close()

    return imageID_DB


def main():

    out = get_imageID_DB()
    print(out)


if __name__ == "__main__":
    main()
