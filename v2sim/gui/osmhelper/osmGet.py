#!/usr/bin/env python
# Eclipse SUMO, Simulation of Urban MObility; see https://eclipse.dev/sumo
# Copyright (C) 2009-2025 German Aerospace Center (DLR) and others.
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# https://www.eclipse.org/legal/epl-2.0/
# This Source Code may also be made available under the following Secondary
# Licenses when the conditions for such availability set forth in the Eclipse
# Public License 2.0 are satisfied: GNU General Public License, version 2
# or later which is available at
# https://www.gnu.org/licenses/old-licenses/gpl-2.0-standalone.html
# SPDX-License-Identifier: EPL-2.0 OR GPL-2.0-or-later

# @file    osmGet.py
# @author  Daniel Krajzewicz
# @author  Jakob Erdmann
# @author  Michael Behrisch
# @date    2009-08-01

import sys
import os
import gzip
import ssl
import json
import collections
import math
import tempfile
import shutil
import xml.etree.ElementTree as ET
import re
import time
import uuid
import socket
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib.request import Request, urlopen

import sumolib

THIS_DIR = os.path.abspath(os.path.dirname(__file__))
TYPEMAP_DIR = os.path.join(THIS_DIR, "typemap")


class OverpassDownloadError(RuntimeError):
    """Actionable error from an Overpass request."""

    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _download_query(endpoint, query, filename, options):
    """POST an Overpass query and atomically write validated OSM XML.

    Only transient transport errors and HTTP 429/502/503/504 are retried.
    A successful HTTP response containing an Overpass error page is rejected.
    """
    request = Request(
        endpoint,
        data=urlparse.urlencode({"data": query}).encode("utf-8"),
        headers={
            "Accept": "application/xml, text/xml, */*",
            "Accept-Encoding": "identity",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "V2Sim-OSM-Wizard/2.0 (+https://github.com/hesl-seu/v2sim)",
        },
        method="POST",
    )
    attempts = 3
    for attempt in range(1, attempts + 1):
        tmp = "%s.%s.tmp" % (filename, uuid.uuid4().hex)
        retry_after = 0
        try:
            with urlopen(request, timeout=180) as response:
                if options.verbose:
                    print("Overpass: HTTP %s from %s" % (response.status, endpoint))
                stream = (gzip.GzipFile(fileobj=response)
                          if response.headers.get("Content-Encoding", "").lower() == "gzip"
                          else response)
                # Verify that the response is XML in OSM format before saving.
                head = stream.read(16384)
                if not head or b"<osm" not in head or b"<html" in head.lower():
                    raise OverpassDownloadError(
                        "Overpass returned a non-OSM response: %s" %
                        head[:500].decode("utf-8", "replace"), retryable=True)
                if b"<remark" in head and (b"error" in head.lower() or b"runtime" in head.lower()):
                    raise OverpassDownloadError(
                        "Overpass reported a query error: %s" %
                        head[:1000].decode("utf-8", "replace"), retryable=True)
                # Preserve the previous SUMO provenance header injection.
                declaration = re.match(rb"\s*<\?xml[^>]*\?>", head)
                if declaration:
                    pos = declaration.end()
                else:
                    pos = 0
                tail = head[-256:]
                with (gzip.open(tmp, "wb") if filename.endswith(".gz") else open(tmp, "wb")) as out:
                    out.write(head[:pos])
                    out.write(b"\n" + sumolib.xml.buildHeader(options=options).encode())
                    out.write(head[pos:])
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        tail = (tail + chunk)[-256:]
                if b"</osm>" not in tail:
                    raise OverpassDownloadError("Overpass returned truncated OSM XML", retryable=True)
            os.replace(tmp, filename)
            return filename
        except urlerror.HTTPError as exc:
            content = exc.read(1500).decode("utf-8", "replace")
            retryable = exc.code in (429, 502, 503, 504)
            try:
                retry_after = max(0, min(300, int(exc.headers.get("Retry-After", "0"))))
            except (ValueError, TypeError):
                retry_after = 0
            error = OverpassDownloadError(
                "Overpass HTTP %s (%s): %s" % (exc.code, exc.reason, content),
                status=exc.code, retryable=retryable)
        except (urlerror.URLError, TimeoutError, socket.timeout,
                ConnectionResetError, ConnectionAbortedError, ssl.SSLEOFError,
                EOFError, gzip.BadGzipFile) as exc:
            error = OverpassDownloadError("Overpass connection failed: %s" % exc,
                                          retryable=True)
        except OverpassDownloadError as exc:
            error = exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if not error.retryable or attempt == attempts:
            raise error
        delay = max(10 * (3 ** (attempt - 1)), retry_after)
        print("Overpass request %s/%s failed: %s; retrying in %ss" %
              (attempt, attempts, error, delay), file=sys.stderr)
        time.sleep(delay)


def readCompressed(options, endpoint, query, roadTypesJSON, getShapes, filename):
    # generate query string for each road-type category
    queryStringNode = []

    commonQueryStringNode = """
    <query type="nwr">
            %s
            %s
        </query>"""

    for category in roadTypesJSON:
        if len(roadTypesJSON[category]) > 0:
            typeList = "|".join(roadTypesJSON[category])
            regvQueryString = '<has-kv k="%s" modv="" regv="%s"/>' % (category, typeList)
            queryStringNode.append(commonQueryStringNode % (regvQueryString, query))

    if getShapes and roadTypesJSON:
        keyValueDict = collections.defaultdict(set)
        for typemap in ["osmPolyconvert.typ.xml", "osmPolyconvertRail.typ.xml"]:
            with open(os.path.join(TYPEMAP_DIR, typemap), 'r') as osmPolyconvert:
                for polygon in sumolib.xml.parse(osmPolyconvert, 'polygonType'):
                    keyValue = polygon.id.split('.') + ["."]
                    keyValueDict[keyValue[0]].add(keyValue[1])

        for category, value in keyValueDict.items():
            if category in roadTypesJSON:
                continue
            if '.' in value:
                regvQueryString = '<has-kv k="%s"/>' % category
            else:
                typeList = "|".join(value)
                regvQueryString = '<has-kv k="%s" modv="" regv="%s"/>' % (category, typeList)
            queryStringNode.append(commonQueryStringNode % (regvQueryString, query))

    if queryStringNode:
        # include all nodes that are relevant for public transport
        regvQueryString = '<has-kv k="public_transport" modv="" regv="."/>'
        queryStringNode.append(commonQueryStringNode % (regvQueryString, query))

    if queryStringNode and getShapes:
        unionQueryString = """
    <union into="nodesBB">
      %s
    </union>
    <union into="waysBB">
       %s
    </union>
    <union into="waysBB2">
       <item from="waysBB"/>
       <recurse type="way-node"/>
       <recurse type="node-relation"/>
       <recurse type="way-relation"/>
     </union>
     <union into="waysBB3">
       <item from="waysBB2"/>
       <recurse type="relation-way"/>
       <recurse type="way-node"/>
    </union>
    <query type="node">
       <item from="nodesBB"/>
       <item from="waysBB3"/>
    </query>
    <query type="way" into="waysBB4">
       <item from="waysBB3"/>
    </query>
    <query type="relation" into="relsBB4">
       <item from="waysBB3"/>
    </query>
   <union>
     <item/>
     <item from="waysBB4"/>
     <item from="relsBB4"/>
   </union>
    """ % (query, "\n".join(queryStringNode))

    elif queryStringNode:
        unionQueryString = """
    <union>
       %s
    </union>
    <union>
       <item/>
       <recurse type="way-node"/>
       <recurse type="node-relation"/>
       <recurse type="way-relation"/>
    </union>""" % "\n".join(queryStringNode)

    else:
        unionQueryString = """
    <union>
       %s
       <recurse type="node-relation" into="rels"/>
       <recurse type="node-way"/>
       <recurse type="way-relation"/>
     </union>
     <union>
        <item/>
        <recurse type="way-node"/>
     </union>""" % query

    finalQuery = """
    <osm-script timeout="120" element-limit="268435456">
       %s
    <print mode="body"/>
    </osm-script>""" % unionQueryString

    if options.query_output:
        with open(options.query_output, "w", encoding="utf-8") as outf:
            outf.write(finalQuery)

    return _download_query(endpoint, finalQuery, filename, options)



# A grid bounds each individual Overpass query. One HTTP request at a time.
# The 1-second cooldown is applied between completed HTTP downloads.
DEFAULT_TILE_KM = 5.0
MAX_INITIAL_TILES = 256
MAX_TOTAL_TILES = 1024
MAX_SPLIT_DEPTH = 3


def _bbox_grid(west, south, east, north, tile_km):
    """Yield west/south/east/north cells, approximately tile_km per side."""
    mean_lat = math.radians((south + north) / 2.0)
    width_km = 111.32 * max(0.01, math.cos(mean_lat)) * (east - west)
    height_km = 111.32 * (north - south)
    cols = max(1, math.ceil(width_km / tile_km))
    rows = max(1, math.ceil(height_km / tile_km))
    if cols * rows > MAX_INITIAL_TILES:
        raise ValueError(
            "Selected area requires %d tiles at %.1f km; limit is %d. "
            "Choose a larger tile size or smaller map area."
            % (cols * rows, tile_km, MAX_INITIAL_TILES)
        )
    for row in range(rows):
        s = south + (north - south) * row / rows
        n = south + (north - south) * (row + 1) / rows
        for col in range(cols):
            w = west + (east - west) * col / cols
            e = west + (east - west) * (col + 1) / cols
            yield (w, s, e, n)


def _split_bbox(box):
    w, s, e, n = box
    midx, midy = (w + e) / 2, (s + n) / 2
    return [(w, s, midx, midy), (midx, s, e, midy),
            (w, midy, midx, n), (midx, midy, e, n)]


def _bbox_query(box):
    w, s, e, n = box
    return '<bbox-query n="%.10f" s="%.10f" w="%.10f" e="%.10f"/>' % (n, s, w, e)


def _merge_osm_files(paths, output):
    """Merge OSM XML by (type, id), order nodes/ways/relations, atomically.

    Streaming parse avoids holding XML trees in RAM. Way->node references are
    verified: missing nodes would silently break SUMO netconvert otherwise.
    The membership of relations is preserved verbatim, even when Overpass did
    not return external members of a relation.
    """
    seen = {kind: set() for kind in ('node', 'way', 'relation')}
    node_refs = set()
    total = 0
    tmpdir = tempfile.mkdtemp(prefix='osm_merge_', dir=os.path.dirname(os.path.abspath(output)))
    streams = {}
    tmpout = output + '.' + uuid.uuid4().hex + '.tmp'
    try:
        streams = {kind: open(os.path.join(tmpdir, kind + '.xml'), 'wb')
                   for kind in seen}
        root_attrs = None
        for src in paths:
            with (gzip.open(src, 'rb') if src.endswith('.gz') else open(src, 'rb')) as inp:
                depth = 0
                document_root = None
                for event, elem in ET.iterparse(inp, events=('start', 'end')):
                    if event == 'start':
                        depth += 1
                        if depth == 1:
                            document_root = elem
                            if elem.tag != 'osm':
                                raise ValueError('Unexpected XML root in %s: %s' % (src, elem.tag))
                            if root_attrs is None:
                                root_attrs = dict(elem.attrib)
                    elif event == 'end':
                        if depth == 2 and elem.tag in seen:
                            obj_id = elem.get('id')
                            if obj_id is None:
                                raise ValueError('OSM %s without an id in %s' % (elem.tag, src))
                            if obj_id not in seen[elem.tag]:
                                seen[elem.tag].add(obj_id)
                                if elem.tag == 'way':
                                    node_refs.update(nd.get('ref') for nd in elem.findall('nd'))
                                streams[elem.tag].write(ET.tostring(elem, encoding='utf-8'))
                                streams[elem.tag].write(b'\n')
                                total += 1
                        # Do not clear nested nd/tag/member children before
                        # their enclosing OSM element has been serialized.
                        if depth == 2:
                            elem.clear()
                            # Avoid retaining millions of emptied children in the root.
                            document_root.clear()
                        depth -= 1
        for stream in streams.values():
            stream.close()
        streams = {}
        if root_attrs is None:
            raise ValueError('No valid OSM root found')
        missing = node_refs - seen['node']
        if missing:
            sample = ', '.join(sorted(missing)[:8])
            raise ValueError('Merged OSM data has %d ways-node references without nodes (e.g. %s)' %
                             (len(missing), sample))
        if not total:
            raise ValueError('Merged OSM contains no objects')
        root_attrs.setdefault('version', '0.6')
        # ElementTree quotes and escapes every root attribute safely.
        root_open = ET.tostring(ET.Element('osm', root_attrs), encoding='utf-8')
        if not root_open.endswith(b' />') and not root_open.endswith(b'/>'):
            raise AssertionError('Unexpected empty root serialization')
        root_open = root_open.rsplit(b'/>', 1)[0] + b'>'
        with (gzip.open(tmpout, 'wb') if output.endswith('.gz') else open(tmpout, 'wb')) as dest:
            dest.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            dest.write(root_open + b'\n')
            for kind in ('node', 'way', 'relation'):
                with open(os.path.join(tmpdir, kind + '.xml'), 'rb') as stream:
                    shutil.copyfileobj(stream, dest, length=1024 * 1024)
            dest.write(b'</osm>\n')
        os.replace(tmpout, output)
        print('Merged %d tiles: %d nodes, %d ways, %d relations' %
              (len(paths), len(seen['node']), len(seen['way']), len(seen['relation'])))
        return output
    finally:
        for stream in streams.values():
            stream.close()
        if os.path.exists(tmpout):
            os.remove(tmpout)
        shutil.rmtree(tmpdir, ignore_errors=True)


def _download_tiled(options, endpoint, coords, road_types, shapes, output):
    """Serial tiled downloader; report live progress as the work queue grows."""
    initial = list(_bbox_grid(*coords, options.tile_size_km))
    workdir = tempfile.mkdtemp(prefix='osm_tiles_', dir=os.path.dirname(os.path.abspath(output)))
    completed = []
    downloads = 0
    completed_count = 0
    total_count = len(initial)

    def emit(phase, current, detail=""):
        callback = getattr(options, "progress_event", None)
        if callback is not None:
            callback({"phase": phase, "current": current, "total": total_count,
                      "completed": completed_count, "detail": detail})

    try:
        emit("downloading", 1 if total_count else 0, "Preparing partitions")

        def download_box(box, depth=0):
            nonlocal downloads, completed_count, total_count
            if downloads >= MAX_TOTAL_TILES:
                raise OverpassDownloadError('Safety limit exceeded: too many Overpass requests')
            if downloads:
                time.sleep(1.0)  # strictly serial, one-second gap between HTTP requests
            downloads += 1
            path = os.path.join(workdir, 'part_%05d.osm.xml.gz' % downloads)
            current = completed_count + 1
            message = 'Downloading OSM partition %d/%d (%s)' % (
                current, total_count, ','.join('%.5f' % x for x in box))
            emit("downloading", current, "Downloading partition")
            if getattr(options, "progress", None):
                options.progress(message)
            else:
                print(message, flush=True)
            try:
                readCompressed(options, endpoint, _bbox_query(box), road_types, shapes, path)
            except OverpassDownloadError as exc:
                if exc.retryable and depth < MAX_SPLIT_DEPTH:
                    total_count += 3  # One failed leaf is replaced by four pending leaves.
                    emit("downloading", completed_count + 1, "Splitting failed partition")
                    print('Partition failed (%s); splitting into four smaller partitions' % exc,
                          file=sys.stderr, flush=True)
                    for child in _split_bbox(box):
                        download_box(child, depth + 1)
                    return
                raise OverpassDownloadError('Partition %s failed: %s' % (box, exc),
                                            status=exc.status, retryable=exc.retryable) from exc
            completed.append(path)
            completed_count += 1
            emit("downloading", completed_count, "Partition downloaded")

        for box in initial:
            download_box(box)
        emit("merging", completed_count, "Merging OSM partitions")
        result = _merge_osm_files(completed, output)
        emit("finished", completed_count, "OSM download and merge complete")
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)




def _point_in_bbox(lon, lat, bounds):
    west, south, east, north = bounds
    return west <= lon <= east and south <= lat <= north


def _segment_hits_bbox(a, b, bounds):
    """True if a straight OSM way segment crosses the bounding rectangle."""
    west, south, east, north = bounds
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for p, q in ((-dx, x0 - west), (dx, east - x0),
                 (-dy, y0 - south), (dy, north - y0)):
        if abs(p) < 1e-15:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                low = max(low, t)
            else:
                high = min(high, t)
            if low > high:
                return False
    return True


def _way_hits_bbox(way, bounds):
    last = None
    for ref in way.nodes:
        try:
            if not ref.location.valid():
                last = None
                continue
            xy = (ref.location.lon, ref.location.lat)
        except (ValueError, RuntimeError):
            last = None
            continue
        if _point_in_bbox(*xy, bounds):
            return True
        if last is not None and _segment_hits_bbox(last, xy, bounds):
            return True
        last = xy
    return False


def _clip_segment(a, b, bounds):
    """Liang-Barsky clipping; return endpoint fractions or None."""
    west, south, east, north = bounds
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for p, q in ((-dx, x0 - west), (dx, east - x0),
                 (-dy, y0 - south), (dy, north - y0)):
        if abs(p) < 1e-15:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                low = max(low, t)
            else:
                high = min(high, t)
            if low > high:
                return None
    if high - low < 1e-12:
        return None
    return low, high


def _clip_way_parts(vertices, bounds, new_node):
    """Return node-ID sequences inside bounds; boundary nodes are synthetic."""
    result = []
    current = []
    eps = 1e-12
    for a, b in zip(vertices, vertices[1:]):
        if a is None or b is None:
            if len(current) >= 2:
                result.append(current)
            current = []
            continue
        x0, y0, n0 = a
        x1, y1, n1 = b
        interval = _clip_segment((x0, y0), (x1, y1), bounds)
        if interval is None:
            if len(current) >= 2:
                result.append(current)
            current = []
            continue
        t0, t1 = interval
        if t0 <= eps:
            begin = n0
        else:
            begin = new_node(x0 + t0 * (x1 - x0), y0 + t0 * (y1 - y0))
        if t1 >= 1.0 - eps:
            end = n1
        else:
            end = new_node(x0 + t1 * (x1 - x0), y0 + t1 * (y1 - y0))
        if current and current[-1] != begin:
            if len(current) >= 2:
                result.append(current)
            current = []
        if not current:
            current = [begin]
        if current[-1] != end:
            current.append(end)
        if t1 < 1.0 - eps:
            if len(current) >= 2:
                result.append(current)
            current = []
    if len(current) >= 2:
        result.append(current)
    return result


def extract_pbf(pbf_path, coords, output, progress=None, progress_event=None):
    """Stream a *geometrically clipped* OSM XML gzip from a local PBF.

    Every way segment is clipped to the bbox, with synthetic boundary nodes.
    Closed area ways that cross the boundary are omitted rather than emitted
    as invalid open polygons. Relations are retained only when all members are
    unchanged and present. This is a strict rectangular clip, not osmium's
    smart relation-aware extract. The source PBF is still scanned sequentially.
    """
    try:
        import osmium
    except ImportError as exc:
        raise RuntimeError(
            "Local PBF mode requires 'osmium': py -3.14 -m pip install osmium"
        ) from exc
    from xml.sax.saxutils import escape, quoteattr

    source = os.path.abspath(os.path.expanduser(os.fspath(pbf_path)))
    if not os.path.isfile(source):
        raise FileNotFoundError("Local PBF not found: %s" % source)
    if not source.lower().endswith('.osm.pbf'):
        raise ValueError("Input must be a .osm.pbf file")
    bounds = tuple(float(v) for v in coords)
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid PBF cropping bounding box")
    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    nonce = uuid.uuid4().hex
    packed = os.path.join(os.path.dirname(output), '.%s.%s.osm.xml.gz' %
                          (os.path.basename(output), nonce))
    spool = os.path.join(os.path.dirname(output), '.%s.%s.ways.tmp' %
                         (os.path.basename(output), nonce))
    relations_spool = os.path.join(os.path.dirname(output), '.%s.%s.relations.tmp' %
                                   (os.path.basename(output), nonce))

    def emit(phase, detail):
        if progress:
            progress(detail)
        if progress_event:
            progress_event({'phase': phase, 'current': 0, 'total': 0,
                            'completed': 0, 'detail': detail})

    def tags_xml(tags):
        return ''.join('<tag k=%s v=%s/>\n' %
                       (quoteattr(str(t.k)), quoteattr(str(t.v))) for t in tags)

    seen_nodes = set()
    kept_ways = set()
    changed_ways = set()
    kept_relations = set()
    next_id = -1
    way_count = 0
    node_count = 0

    try:
        emit('extracting', 'Scanning PBF and clipping geometry to selected bounds')
        with gzip.open(packed, 'wt', encoding='utf-8', newline='\n') as out, \
                open(spool, 'w+', encoding='utf-8', newline='\n') as ways, \
                open(relations_spool, 'w+', encoding='utf-8', newline='\n') as relations:
            out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            out.write('<osm version="0.6" generator="V2Sim-pyosmium-clip">\n')

            def new_node(lon, lat):
                nonlocal next_id, node_count
                nid = next_id
                next_id -= 1
                lon = min(east, max(west, lon))
                lat = min(north, max(south, lat))
                out.write('<node id="%d" lon="%.10f" lat="%.10f"/>\n' %
                          (nid, lon, lat))
                node_count += 1
                return nid

            for obj in osmium.FileProcessor(source).with_locations():
                if obj.is_node():
                    if obj.location.valid() and _point_in_bbox(
                            obj.location.lon, obj.location.lat, bounds):
                        nid = int(obj.id)
                        if nid in seen_nodes:
                            continue
                        seen_nodes.add(nid)
                        out.write('<node id="%d" lon="%.10f" lat="%.10f">\n' %
                                  (nid, obj.location.lon, obj.location.lat))
                        out.write(tags_xml(obj.tags))
                        out.write('</node>\n')
                        node_count += 1
                elif obj.is_way():
                    vertices = []
                    for ref in obj.nodes:
                        if ref.location.valid():
                            vertices.append((ref.location.lon, ref.location.lat,
                                             int(ref.ref)))
                        else:
                            vertices.append(None)
                    if len(vertices) < 2:
                        continue
                    tags = {str(t.k): str(t.v) for t in obj.tags}
                    is_closed = vertices[0] is not None and vertices[-1] is not None \
                                and vertices[0][2] == vertices[-1][2]
                    is_area = is_closed and 'highway' not in tags and 'railway' not in tags
                    if is_area:
                        # A partially intersecting closed polygon cannot be
                        # represented correctly by just clipping its ring.
                        if not all(v is not None and _point_in_bbox(v[0], v[1], bounds)
                                   for v in vertices):
                            continue
                        parts = [[v[2] for v in vertices]]
                    else:
                        parts = _clip_way_parts(vertices, bounds, new_node)
                    if not parts:
                        continue
                    orig_id = int(obj.id)
                    unchanged = len(parts) == 1 and \
                                parts[0] == [v[2] for v in vertices if v is not None]
                    kept_ways.add(orig_id)
                    if not unchanged:
                        changed_ways.add(orig_id)
                    for i, part in enumerate(parts):
                        if len(part) < 2:
                            continue
                        if i == 0:
                            wid = orig_id
                        else:
                            wid = next_id
                            next_id -= 1
                        ways.write('<way id="%d">\n' % wid)
                        for nid in part:
                            ways.write('<nd ref="%d"/>\n' % nid)
                        ways.write(tags_xml(obj.tags))
                        ways.write('</way>\n')
                        way_count += 1
                elif obj.is_relation():
                    # Preserve only unaffected relations. If a way was clipped,
                    # keeping the original relation would misrepresent geometry.
                    members = list(obj.members)
                    if not members:
                        continue
                    valid = True
                    for m in members:
                        if m.type == 'n':
                            valid = int(m.ref) in seen_nodes
                        elif m.type == 'w':
                            valid = int(m.ref) in kept_ways and int(m.ref) not in changed_ways
                        elif m.type == 'r':
                            valid = int(m.ref) in kept_relations
                        else:
                            valid = False
                        if not valid:
                            break
                    if valid:
                        relations.write('<relation id="%d">\n' % int(obj.id))
                        for m in members:
                            relations.write('<member type=%s ref="%d" role=%s/>\n' %
                                            (quoteattr({'n':'node', 'w':'way', 'r':'relation'}[m.type]),
                                             int(m.ref), quoteattr(str(m.role))))
                        relations.write(tags_xml(obj.tags))
                        relations.write('</relation>\n')
                        kept_relations.add(int(obj.id))

            if not way_count and not node_count:
                raise RuntimeError('Selected map area contains no OSM objects')
            emit('writing', 'Finalizing clipped ways and relations')
            for temp in (ways, relations):
                temp.flush()
                temp.seek(0)
                shutil.copyfileobj(temp, out)
            out.write('</osm>\n')

        if not os.path.isfile(packed) or os.path.getsize(packed) == 0:
            raise RuntimeError('PBF clipping produced no output')
        os.replace(packed, output)
        emit('finished', 'PBF clipping complete: %d nodes, %d ways' %
             (node_count, way_count))
        return output
    finally:
        for temp in (packed, spool, relations_spool):
            if os.path.exists(temp):
                os.remove(temp)

def get_options(args):
    optParser = sumolib.options.ArgumentParser(description="Get network from OpenStreetMap")
    optParser.add_argument("-p", "--prefix", category="output", default="osm", help="for output file")
    optParser.add_argument("-b", "--bbox", category="input",
                           help="bounding box to retrieve in geo coordinates west,south,east,north")
    optParser.add_argument("--tile-size-km", type=float, default=DEFAULT_TILE_KM,
                           help="maximum approximate side length of each serial Overpass tile (km); 0 disables tiling")
    optParser.add_argument("-d", "--output-dir", category="output",
                           help="optional output directory (must already exist)")
    optParser.add_argument("-a", "--area", type=int, help="area id to retrieve")
    optParser.add_argument("-x", "--polygon", category="processing",
                           help="calculate bounding box from polygon data in file")
    optParser.add_argument("-u", "--url", default="www.overpass-api.de/api/interpreter",
                           help="Download from the given OpenStreetMap server")
    # alternatives: overpass.kumi.systems/api/interpreter, sumo.dlr.de/osm/api/interpreter
    optParser.add_argument("-w", "--wikidata", action="store_true",
                           default=False, help="get the corresponding wikidata")
    optParser.add_argument("-r", "--road-types", dest="roadTypes",
                           help="only delivers osm data to the specified road-types")
    optParser.add_argument("-s", "--shapes", action="store_true", default=False,
                           help="determines if polygon data (buildings, areas , etc.) is downloaded")
    optParser.add_argument("-z", "--gzip", category="output", action="store_true",
                           default=False, help="save gzipped output")
    optParser.add_argument("-q", "--query-output", category="output",
                           help="write query to the given FILE")
    optParser.add_argument("-v", "--verbose", action="store_true",
                           default=False, help="tell me what you are doing")
    options = optParser.parse_args(args=args)
    if not options.bbox and not options.area and not options.polygon:
        optParser.error("At least one of 'bbox' and 'area' and 'polygon' has to be set.")
    if not math.isfinite(options.tile_size_km) or options.tile_size_km < 0 or options.tile_size_km > 500:
        optParser.error("--tile-size-km must be between 0 and 500")
    if options.bbox:
        west, south, east, north = [float(v) for v in options.bbox.split(',')]
        if south > north or west > east or south < -90 or north > 90 or west < -180 or east > 180:
            optParser.error("Invalid geocoordinates in bbox.")
    return options


def get(args=None, progress=None, progress_event=None):
    options = get_options(args)
    options.progress = progress
    options.progress_event = progress_event
    east = None
    west = None
    if options.polygon:
        west = 1e400
        south = 1e400
        east = -1e400
        north = -1e400
        for area in sumolib.output.parse_fast(options.polygon, 'poly', ['shape']):
            for coord in area.shape.split():
                point = tuple(map(float, coord.split(',')))
                west = min(point[0], west)
                south = min(point[1], south)
                east = max(point[0], east)
                north = max(point[1], north)
    if options.bbox:
        west, south, east, north = [float(v) for v in options.bbox.split(',')]

    assert east is not None and west is not None
    
    if options.output_dir:
        options.prefix = os.path.join(options.output_dir, options.prefix)

    endpoint = options.url if options.url.startswith(("https://", "http://")) else "https://" + options.url
    parsed = urlparse.urlparse(endpoint)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid Overpass API URL")
    if not parsed.path or parsed.path == "/":
        endpoint = endpoint.rstrip("/") + "/api/interpreter"

    roadTypesJSON = json.loads(options.roadTypes.replace("\'", "\"").lower()) if options.roadTypes else {}

    suffix = ".osm.xml.gz" if options.gzip else ".osm.xml"
    if options.area:
        if options.area < 3600000000:
            options.area += 3600000000
        readCompressed(options, endpoint, '<area-query ref="%s"/>' %
                       options.area, roadTypesJSON, options.shapes, options.prefix + "_city" + suffix)
    if options.bbox or options.polygon:
        output = options.prefix + "_bbox" + suffix
        if options.tile_size_km > 0:
            _download_tiled(options, endpoint, (west, south, east, north),
                            roadTypesJSON, options.shapes, output)
        else:
            if progress_event:
                progress_event({"phase": "downloading", "current": 1, "total": 1,
                                "completed": 0, "detail": "Downloading single region"})
            readCompressed(options, endpoint, _bbox_query((west, south, east, north)),
                           roadTypesJSON, options.shapes, output)
            if progress_event:
                progress_event({"phase": "finished", "current": 1, "total": 1,
                                "completed": 1, "detail": "OSM download complete"})

    # extract the wiki data according to the wikidata-value in the extracted osm file
    if options.wikidata:
        filename = options.prefix + '.wikidata.xml.gz'
        osmFile = options.prefix + "_bbox" + suffix
        codeSet = set()
        # deal with invalid characters
        bad_chars = [';', ':', '!', "*", ')', '(', '-', '_', '%', '&', '/', '=', '?', '$', '//', '\\', '#', '<', '>']
        for line in sumolib.openz(osmFile):
            subSet = set()
            if 'wikidata' in line and line.split('"')[3][0] == 'Q':
                basicData = line.split('"')[3]
                for i in bad_chars:
                    basicData = basicData.replace(i, ' ')
                elems = basicData.split(' ')
                for e in elems:
                    if e and e[0] == 'Q':
                        subSet.add(e)
                codeSet.update(subSet)

        # make and save query results iteratively
        codeList = list(codeSet)
        interval = 50  # the maximal number of query items
        outf = gzip.open(filename, "wb")
        for i in range(0, len(codeSet), interval):
            j = i + interval
            if j > len(codeSet):
                j = len(codeSet)
            subList = codeList[i:j]
            content = urlopen("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=%s&format=json" %
                              ("|".join(subList))).read()
            if options.verbose:
                print(type(content))
            outf.write(content + b"\n")
        outf.close()


if __name__ == "__main__":
    try:
        get()
    except ssl.CertificateError:
        print("Error with SSL certificate, try 'pip install -U certifi'.", file=sys.stderr)
