import os
import psycopg2

# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary'

def main():

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    conn.autocommit = True

    #Creating a table
    cur.execute(    # query to create a table
         'CREATE TABLE mly_table (imageid bigint NOT NULL, sequence char(30), unixtime bigint, type char(20), angle decimal, jsonb_data jsonb, image bytea, location geography(POINT, 4326), PRIMARY KEY(imageid))'
         )
    print("table created successfully........")
    #print(cur.fetchone())
    
    #Closing the connection
    cur.close()
    conn.close()
   
if __name__ == '__main__':
    main()
