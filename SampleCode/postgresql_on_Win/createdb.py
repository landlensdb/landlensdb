import os
import psycopg2

# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL='postgresql://postgres:postgres@localhost:5432/postgres'

def main():

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    conn.autocommit = True

    #Creating a database
    cur.execute(    # query to create a database
         'CREATE database mapillary'
         )
    print("Database created successfully........")
    print(cur.fetchone())
    
    #Closing the connection
    cur.close()
    conn.close()
   
if __name__ == '__main__':
    main()
