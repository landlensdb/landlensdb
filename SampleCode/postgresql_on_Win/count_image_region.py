import os
import requests
import psycopg2
import datetime
from psycopg2  import extras
import json
from shapely.geometry import Point
import mercantile, mapbox_vector_tile
from vt2geojson.tools import vt_bytes_to_geojson


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
  #print(tiles)
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



# DATABASE_URL='postgresql://postgre:postgre@localhost:5432/postgres'
DATABASE_URL='postgresql://postgres:postgres@localhost:5432/mapillary'

def main():
  token = "YOUR ACCESS TOKEN"
  SEQIDs = Mapillary4_SeqIDs_fromRegion(access_token=token,
                                          west = 140.8282500,
                                          south = 42.2625132,
                                          east =  141.1812100,
                                          north = 42.4647410,
                                          zoom_level=14,
                                          start_date = '2019-10-22',
                                          end_date = '2019-10-24')

  sum_IMGIDs = 0
  allIMGIDs = []
  for SEQID in SEQIDs:
    IMGIDs = Mapillary4_seqID2ImageIDs(access_token=token,
                                    seqID = SEQID
                                    )
    allIMGIDs.extend(IMGIDs)
    sum_IMGIDs += len(IMGIDs)

  print('sum of IMAGEID (duplicated included): ' + str(sum_IMGIDs))
  print('sum of SEQID: ' + str(len(SEQIDs)))
  print('sum of IMAGEID: ' + str(len(set(allIMGIDs))))
  return sum_IMGIDs, allIMGIDs

if __name__ == '__main__':
    main()
