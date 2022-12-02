import os
import psycopg2

# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL = "postgresql://postgres:postgres@postgresql:5432/postgres"


def main():
    # cursor = psycopg2.connect(DATABASE_URL)
    # print(cursor)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("select version()")
    print(cur.fetchone())

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
