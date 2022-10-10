import os
import psycopg2
from psycopg2  import extras

#DATABASE_URL='postgresql://postgres:postgres@postgresql:5432/mapillary' 
DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary' 

    
def main():

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    conn.autocommit = True

    #insert a data
    cur.execute(
            "SELECT imageid, image from mly_table where id=4" 
            )

    mypic = cur.fetchone()
    open('./'+ str(mypic[0]) + '.jpg', 'wb').write(bytes(mypic[1]))

    
    #Closing the connection
    cur.close()
    conn.close()
   
if __name__ == '__main__':
    main()
