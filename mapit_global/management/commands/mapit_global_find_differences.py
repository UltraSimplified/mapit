# import_global_osm.py:
#
# This script is used to import administrative boundaries from
# OpenStreetMap into MaPit.
#
# It takes KML data generated by get-boundaries-by-admin-level.py, so
# you need to have run that first.
#
# This script is heavily based on import_norway_osm.py by Matthew
# Somerville.
#
# Copyright (c) 2011, 2012 UK Citizens Online Democracy. All rights reserved.
# Email: mark@mysociety.org; WWW: http://www.mysociety.org

from __future__ import print_function

import os
import re
import xml.sax

from django.core.management.base import LabelCommand
from django.contrib.gis.gdal import DataSource
from django.utils.encoding import smart_str

from mapit.models import Code, CodeType
from mapit.management.command_utils import KML
import csv


def empty_if_none(o):
    return '' if o is None else o


class Command(LabelCommand):
    help = 'Import OSM administrative boundary data'
    args = '<KML-DIRECTORY>'

    def handle_label(self, directory_name, **options):
        if not os.path.isdir(directory_name):
            raise Exception("'%s' is not a directory" % (directory_name,))

        os.chdir(directory_name)
        skip_up_to = None
        # skip_up_to = 'relation-80370'

        skipping = bool(skip_up_to)

        osm_elements_seen_in_new_data = set([])

        with open("/home/mark/difference-results.csv", 'w') as fp:
            csv_writer = csv.writer(fp)
            csv_writer.writerow(["ElementType",
                                 "ElementID",
                                 "ExistedPreviously",
                                 "PreviousEmpty",
                                 "PreviousArea",
                                 "NewEmpty",
                                 "NewArea",
                                 "SymmetricDifferenceArea",
                                 "GEOSEquals",
                                 "GEOSEqualsExact"])

            for admin_directory in sorted(x for x in os.listdir('.') if os.path.isdir(x)):

                if not re.search('^[A-Z0-9]{3}$', admin_directory):
                    print("Skipping a directory that doesn't look like a MapIt type:", admin_directory)

                if not os.path.exists(admin_directory):
                    continue

                files = sorted(os.listdir(admin_directory))

                for i, e in enumerate(files):

                    if skipping:
                        if skip_up_to in e:
                            skipping = False
                        else:
                            continue

                    if not e.endswith('.kml'):
                        continue

                    m = re.search(r'^(way|relation)-(\d+)-', e)
                    if not m:
                        raise Exception("Couldn't extract OSM element type and ID from: " + e)

                    osm_type, osm_id = m.groups()

                    osm_elements_seen_in_new_data.add((osm_type, osm_id))

                    kml_filename = os.path.join(admin_directory, e)

                    # Need to parse the KML manually to get the ExtendedData
                    kml_data = KML()
                    print("parsing", kml_filename)
                    xml.sax.parse(kml_filename, kml_data)

                    useful_names = [n for n in kml_data.data.keys() if not n.startswith('Boundaries for')]
                    if len(useful_names) == 0:
                        raise Exception("No useful names found in KML data")
                    elif len(useful_names) > 1:
                        raise Exception("Multiple useful names found in KML data")
                    name = useful_names[0]
                    print(" ", smart_str(name))

                    if osm_type == 'relation':
                        code_type_osm = CodeType.objects.get(code='osm_rel')
                    elif osm_type == 'way':
                        code_type_osm = CodeType.objects.get(code='osm_way')
                    else:
                        raise Exception("Unknown OSM element type: " + osm_type)

                    ds = DataSource(kml_filename)
                    if len(ds) != 1:
                        raise Exception("We only expect one layer in a DataSource")

                    layer = ds[0]
                    if len(layer) != 1:
                        raise Exception("We only expect one feature in each layer")

                    feat = layer[0]

                    osm_codes = list(Code.objects.filter(type=code_type_osm, code=osm_id))
                    osm_codes.sort(key=lambda e: e.area.generation_high.created)

                    new_area = None
                    new_empty = None

                    previous_area = None
                    previous_empty = None

                    symmetric_difference_area = None

                    g = feat.geom.transform(4326, clone=True)

                    for polygon in g:
                        if polygon.point_count < 4:
                            new_empty = True
                    if not new_empty:
                        new_geos_geometry = g.geos.simplify(tolerance=0)
                        new_area = new_geos_geometry.area
                        new_empty = new_geos_geometry.empty

                    geos_equals = None
                    geos_equals_exact = None

                    most_recent_osm_code = None
                    if osm_codes:
                        most_recent_osm_code = osm_codes[-1]
                        previous_geos_geometry = most_recent_osm_code.area.polygons.collect()
                        previous_empty = previous_geos_geometry is None

                        if not previous_empty:
                            previous_geos_geometry = previous_geos_geometry.simplify(tolerance=0)
                            previous_area = previous_geos_geometry.area

                            if not new_empty:
                                symmetric_difference_area = previous_geos_geometry.sym_difference(
                                    new_geos_geometry).area
                                geos_equals = previous_geos_geometry.equals(new_geos_geometry)
                                geos_equals_exact = previous_geos_geometry.equals_exact(new_geos_geometry)

                    csv_writer.writerow([osm_type,
                                         osm_id,
                                         bool(osm_codes),  # ExistedPreviously
                                         empty_if_none(previous_empty),
                                         empty_if_none(previous_area),
                                         empty_if_none(new_empty),
                                         empty_if_none(new_area),
                                         empty_if_none(symmetric_difference_area),
                                         empty_if_none(geos_equals),
                                         empty_if_none(geos_equals_exact)])
