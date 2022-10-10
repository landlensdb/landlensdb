import os
import requests
import psycopg2
import datetime
from psycopg2  import extras
import json
from shapely.geometry import Point
import mercantile, mapbox_vector_tile
from vt2geojson.tools import vt_bytes_to_geojson

def get_imageID_DB():
    imageID_DB = []
    DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary'
    #DATABASE_URL='postgresql://postgres:postgres@postgres:5432/mapillary'
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT imageid FROM mly_table")

    rows = cur.fetchall()
    for row in rows:
        #print(row[0])
        imageID_DB.append(row[0])
    cur.close()
    conn.close()

    return imageID_DB


def get_seqID_DB():
    seqID_DB = []
    DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary'
    #DATABASE_URL='postgresql://postgres:postgres@postgres:5432/mapillary'
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT sequence FROM mly_table")

    rows = cur.fetchall()
    for row in rows:
        #print(row[0])
        seqID_DB.append(row[0])
    cur.close()
    conn.close()

    return seqID_DB


def Mapillary4_imageID2json(access_token, imageID, export_path, export_img = True):

  """
      Get a json from an image ID and save the image.

      Parameters
      ----------
      access_token : Character
          Your Mapillary access_token (API v4) obtained via https://www.mapillary.com/dashboard/developers
      imageID : Character
          a Specific Mapillary image key.
      export_path: Character
        a path for exporting geopackages of points.
      export_img: Boolean
        whether the obtained image is exported


      Returns
      -------
      json : json with imageID, sequenceID, camera_type,captured_at,compass_angle,computed_compass_angle,and Image URL
  """

  url = 'https://graph.mapillary.com/{}?fields=id,sequence,camera_type,captured_at,compass_angle,computed_compass_angle,sequence,geometry,computed_geometry,thumb_1024_url&access_token={}'.format(imageID,access_token)
  # or instead of adding it to the url, add the token in headers (strongly recommended for user tokens)
  #pdb.set_trace()
  headers= { "Authorization" : "OAuth {}".format(access_token) }
  response = requests.get(url, headers=headers)
  data = response.json()

  if 'thumb_1024_url' in data.keys():
    image_url = data['thumb_1024_url']
  else:
    image_url = None

  sequence_id = data['sequence']
  if export_img and image_url is not None:
    # save each image with ID as filename to directory by sequence ID
    if not os.path.exists('{}/{}'.format(export_path, sequence_id)):
        os.makedirs('{}/{}'.format(export_path, sequence_id))

    with open('{}/{}/image_{}.jpg'.format(export_path, sequence_id, imageID), 'wb') as handler:
        image_data = requests.get(image_url, stream=True).content
        handler.write(image_data)

  return data


def Mapillary4_seqID2ImageIDs(access_token, seqID):

  """
      Get an imge ID from a sequence ID.

      Parameters
      ----------
      access_token : Character
          Your Mapillary access_token (API v4) obtained via https://www.mapillary.com/dashboard/developers
      seqID : Character
          a specific Mapillary sequence ID.

      Returns
      -------
      list: A list of imageID in the target sequence.
  """

  url = 'https://graph.mapillary.com/image_ids?sequence_id={}&access_token={}'.format(seqID,access_token)
  headers= { "Authorization" : "OAuth {}".format(access_token) }
  response = requests.get(url, headers=headers)
  data = response.json()

  out_list = []
  for item in data['data']:
     out_list.append(item['id'])


  return out_list


def Mapillary4_SeqIDs_fromRegion(access_token, west, south, east, north, zoom_level,start_date, end_date):

  """
      Get an imge URL and geopandas point found in a bounding box.

      Parameters
      ----------
      access_token : Character
          Your Mapillary access_token (API v4) obtained via https://www.mapillary.com/dashboard/developers
      west : Character
          west longitude in decimal degrees.
      south : Character
          south latitude in decimal degrees.
      east : Character
          east longitude in decimal degrees.
      north : Character
          north latitude in decimal degrees.
      zoom_level: Integer
          6-14
      start_date: YYYY-MM-DD
      end_date: YYYY-MM-DD

      Returns
      -------
      List : A list of sequence IDs found whithin the boundary box.
  """
  start = start_date + ' 00:00:00.000'
  end = end_date + ' 00:00:00.000'
  start_timestamp = datetime.datetime.strptime(start, '%Y-%m-%d %H:%M:%S.%f').timestamp()
  end_timestamp = datetime.datetime.strptime(end, '%Y-%m-%d %H:%M:%S.%f').timestamp()


  output = []

  # vector tile endpoints -- change this in the API request to reference the correct endpoint
  tile_coverage = 'mly1_public'

  # tile layer depends which vector tile endpoints:
  # 1. if map features or traffic signs, it will be "point" always
  # 2. if looking for coverage, it will be "image" for points, "sequence" for lines, or "overview" for far zoom
  tile_layer = "sequence"

    # get the list of tiles with x and y coordinates which intersect our bounding box
  # MUST be at zoom level 14 where the data is available, other zooms currently not supported
  tiles = list(mercantile.tiles(west, south, east, north, zoom_level))
  print(tiles)
  # loop through list of tiles to get tile z/x/y to plug in to Mapillary endpoints and make request
  for tile in tiles:
      #pdb.set_trace()
      tile_url = 'https://tiles.mapillary.com/maps/vtp/{}/2/{}/{}/{}?access_token={}'.format(tile_coverage,tile.z,tile.x,tile.y,access_token)
      response = requests.get(tile_url)
      data = vt_bytes_to_geojson(response.content, tile.x, tile.y, tile.z,layer=tile_layer)
      #print(data)

      #if data['features'] exists:
      for feature in data['features']:
            unixtime=feature['properties']['captured_at']
            timeJP = datetime.datetime.fromtimestamp(int(unixtime)/1000,
                                                    datetime.timezone(datetime.timedelta(hours=9))).timestamp()

            #print(feature['properties']['id'])
            if int(timeJP) > int(start_timestamp) and int(timeJP) < int(end_timestamp):
                  output.append(feature['properties']['id'])

  return output


def Mapillary4_insertDB(access_token, imageID,export_path,export_img):

  """
      Get a json from an image ID and save the image.

      Parameters
      ----------
      access_token : Character
          Your Mapillary access_token (API v4) obtained via https://www.mapillary.com/dashboard/developers
      imageID : Character
          a Specific Mapillary image key.
      export_path: Character
        a path for exporting geopackages of points.
      export_img: Boolean
        whether the obtained image is exported

  """

  JSON_data = Mapillary4_imageID2json(access_token = access_token,
                                      imageID = imageID,
                                      export_path = export_path,
                                      export_img = export_img)

  IMAGE_ID = JSON_data.get('id')
  SEQ_ID = JSON_data.get('sequence')
  UNIXTIME = JSON_data.get('captured_at')
  CTYPE = JSON_data.get('camera_type')
  ANGLE = JSON_data.get('computed_compass_angle')
  LOC =  "SRID=4326;" + Point(JSON_data.get('geometry').get('coordinates')).wkt

  PIC = open(export_path + '/{}/image_{}.jpg'.format(SEQ_ID, IMAGE_ID), 'rb').read()

  conn = psycopg2.connect(DATABASE_URL)
  cur = conn.cursor()

  conn.autocommit = True

  #insert a data
  cur.execute(
      "INSERT INTO mly_table (imageid, sequence, unixtime, type, angle, jsonb_data, image, location) VALUES  (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", [IMAGE_ID, SEQ_ID, UNIXTIME, CTYPE, ANGLE, json.dumps(JSON_data),PIC, LOC]
        )
  #print("insert " + IMAGE_ID + " successfully........")

  #Closing the connection
  cur.close()
  conn.close()



# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary'

def main():
  token = "YOUR ACCESS TOKEN"
  imageID_DB = get_imageID_DB()
  print(len(imageID_DB))
  sequenceID_DB = get_seqID_DB()
  print(len(sequenceID_DB))

  # Muroran 2019
  # SEQIDs = Mapillary4_SeqIDs_fromRegion(access_token=token,
  #                                         west = 140.8282500,
  #                                         south = 42.2625132,
  #                                         east =  141.1812100,
  #                                         north = 42.4647410,
  #                                         zoom_level=14,
  #                                         start_date = '2019-10-22',
  #                                         end_date = '2019-10-24')

  # Saitama U 2022
  # SEQIDs = Mapillary4_SeqIDs_fromRegion(
  #     access_token=token,
  #     west = 139.605081,
  #     south = 35.860682,
  #     east = 139.609698,
  #     north = 35.865680,
  #     zoom_level=14,
  #     start_date = '2022-03-15',
  #     end_date = '2022-04-19'
  # )

  # Aizuwakamatsu 2019
  # SEQIDs = Mapillary4_SeqIDs_fromRegion(
  #     access_token=token,
  #     west = 139.914228, #西若松駅
  #     south = 37.480485, #会津高校
  #     east = 139.958768, #東鳳
  #     north = 37.511046, #学鳳高校
  #     zoom_level=14,
  #     start_date = '2019-04-01',
  #     end_date = '2019-04-30')

  #Aizuwakamatsu 2015-2022
  SEQIDs = Mapillary4_SeqIDs_fromRegion(
      access_token=token,
      west = 139.83,
      south = 37.30,
      east = 140.07,
      north = 37.59,
      zoom_level=14,
      start_date = '2015-01-01',
      end_date = '2022-07-11'
      )


  for SEQID in sorted(set(SEQIDs)):
    #if SEQID + '        ' not in sequenceID_DB:
      IMGIDs = Mapillary4_seqID2ImageIDs(access_token = token,
                                         seqID = SEQID)

      for IMGID in sorted(set(IMGIDs)):
        #print(IMGID + " at " + SEQID)
        if int(IMGID) not in imageID_DB:

          out = Mapillary4_insertDB(access_token= token,
                                    imageID = IMGID,
                                    export_path = './images',
                                    export_img = True)
          print(IMGID + " is added to DB.")

      print('##### sequence: ' + SEQID + "with total " + str(len(IMGIDs)) +" images are at DB! #####")

if __name__ == '__main__':
    main()
