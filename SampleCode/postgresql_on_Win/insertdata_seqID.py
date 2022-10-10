import os
import requests
import psycopg2
from psycopg2  import extras
import json
from shapely.geometry import Point


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

  IMAGE_ID = JSON_data['id']
  SEQ_ID = JSON_data['sequence']
  UNIXTIME = JSON_data['captured_at']
  CTYPE = JSON_data['camera_type']
  ANGLE = JSON_data['computed_compass_angle']
  LOC =  "SRID=4326;" + Point(JSON_data['geometry']['coordinates']).wkt

  PIC = open('/config/temp/{}/image_{}.jpg'.format(SEQ_ID, IMAGE_ID), 'rb').read()

  conn = psycopg2.connect(DATABASE_URL)
  cur = conn.cursor()

  conn.autocommit = True

  #insert a data
  cur.execute(
      "INSERT INTO mly_table (imageid, sequence, unixtime, type, angle, jsonb_data, image, location) VALUES  (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", [IMAGE_ID, SEQ_ID, UNIXTIME, CTYPE, ANGLE, json.dumps(JSON_data),PIC, LOC]
        )
  print("insert " + IMAGE_ID + " successfully........")

  #Closing the connection
  cur.close()
  conn.close()



# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL='postgresql://postgres:postgres@postgresql:5432/mapillary'

def main():
  token = "YOUR ACCESS TOKEN"
  IMGID = Mapillary4_seqID2ImageIDs(access_token=token,
                                    #seqID = 'IoZHShY9ulG0I0a2d0eVrA'
                                    seqID = '7uTyqT51C0AKY6nDYzo87A'
                                    )

  for ID in IMGID:
    out = Mapillary4_insertDB(access_token=token,
                              imageID = ID,
                              export_path = "/config/temp",
                              export_img = True
    )

if __name__ == '__main__':
    main()
