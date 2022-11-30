import os
import psycopg2
from psycopg2 import extras


def query_sample(imageid):
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/mapillary"
    # DATABASE_URL='postgresql://postgres:postgres@postgres:5432/mapillary'
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT * FROM mly_table where imageid='{}'".format(imageid))
    rows = cur.fetchall()
    # for row in rows:
    #     print(row)
    cur.close()
    conn.close()

    return rows


def main():

    out = query_sample(819455065366628)  # 819455065366628 as test
    print(out)


if __name__ == "__main__":
    main()
