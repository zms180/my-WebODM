import math

import numpy as np
from pyproj import CRS, Transformer


def ecef_to_enu(x, y, z, reference_ecef, latitude, longitude):
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    delta_x = x - reference_ecef[0]
    delta_y = y - reference_ecef[1]
    delta_z = z - reference_ecef[2]

    return np.array([
        -math.sin(lon) * delta_x + math.cos(lon) * delta_y,
        -math.sin(lat) * math.cos(lon) * delta_x - math.sin(lat) * math.sin(lon) * delta_y + math.cos(lat) * delta_z,
        math.cos(lat) * math.cos(lon) * delta_x + math.cos(lat) * math.sin(lon) * delta_y + math.sin(lat) * delta_z,
    ])


def create_enu_obj(input_obj, output_obj, source_srs, source_offset, reference_lla):
    source_to_ecef = Transformer.from_crs(CRS.from_user_input(source_srs), CRS.from_epsg(4978), always_xy=True)
    lla_to_ecef = Transformer.from_crs(CRS.from_epsg(4979), CRS.from_epsg(4978), always_xy=True)

    latitude = float(reference_lla['latitude'])
    longitude = float(reference_lla['longitude'])
    altitude = float(reference_lla['altitude'])
    offset_east = float(source_offset[0])
    offset_north = float(source_offset[1])
    reference_ecef = lla_to_ecef.transform(longitude, latitude, altitude)

    def projected_to_enu(east, north, height):
        ecef = source_to_ecef.transform(east, north, height)
        return ecef_to_enu(*ecef, reference_ecef, latitude, longitude)

    origin_enu = projected_to_enu(offset_east, offset_north, altitude)
    normal_matrix = np.linalg.inv(np.column_stack([
        projected_to_enu(offset_east + 1, offset_north, altitude) - origin_enu,
        projected_to_enu(offset_east, offset_north + 1, altitude) - origin_enu,
        projected_to_enu(offset_east, offset_north, altitude + 1) - origin_enu,
    ])).T

    with open(input_obj, 'r') as source:
        with open(output_obj, 'w') as target:
            for line in source:
                if line.startswith("v "):
                    values = line.split()
                    vertex = projected_to_enu(
                        float(values[1]) + offset_east,
                        float(values[2]) + offset_north,
                        float(values[3]),
                    )
                    suffix = " " + " ".join(values[4:]) if len(values) > 4 else ""
                    target.write("v %.9f %.9f %.9f%s\n" % (*vertex, suffix))
                elif line.startswith("vn "):
                    values = line.split()
                    normal = normal_matrix.dot(np.array(list(map(float, values[1:4]))))
                    length = np.linalg.norm(normal)
                    if length > 0:
                        normal /= length
                    target.write("vn %.9f %.9f %.9f\n" % tuple(normal))
                else:
                    target.write(line)
