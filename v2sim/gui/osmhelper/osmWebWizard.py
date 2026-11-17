#!/usr/bin/env python
# Eclipse SUMO, Simulation of Urban MObility; see https://eclipse.dev/sumo
# Copyright (C) 2014-2025 German Aerospace Center (DLR) and others.
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# https://www.eclipse.org/legal/epl-2.0/
# This Source Code may also be made available under the following Secondary
# Licenses when the conditions for such availability set forth in the Eclipse
# Public License 2.0 are satisfied: GNU General Public License, version 2
# or later which is available at
# https://www.gnu.org/licenses/old-licenses/gpl-2.0-standalone.html
# SPDX-License-Identifier: EPL-2.0 OR GPL-2.0-or-later

# @file    osmWebWizard.py
# @author  Jakob Stigloher
# @author  Jakob Erdmann
# @author  Michael Behrisch
# @author  Mirko Barthauer
# @date    2014-14-10

import os
from pathlib import Path
import sys
import stat
import traceback
import webbrowser
import datetime
import json
import math
import threading
import subprocess
import tempfile
import shutil
from zipfile import ZipFile
import ssl
import collections
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import osmGet
from . import osmBuild
from . import ptlines2flows
from . import tileGet
import sumolib

SUMO_HOME = os.environ.get("SUMO_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
typemapdir = os.path.join(THIS_DIR, "typemap")  #os.path.join("${SUMO_HOME}" if "SUMO_HOME" in os.environ else SUMO_HOME, "data", "typemap")
typemaps = {
    "net": os.path.join(typemapdir, "osmNetconvert.typ.xml"),
    "poly": os.path.join(typemapdir, "osmPolyconvert.typ.xml"),
    "urban": os.path.join(typemapdir, "osmNetconvertUrbanDe.typ.xml"),
    "pedestrians": os.path.join(typemapdir, "osmNetconvertPedestrians.typ.xml"),
    "ships": os.path.join(typemapdir, "osmNetconvertShips.typ.xml"),
    "bicycles": os.path.join(typemapdir, "osmNetconvertBicycle.typ.xml"),
    "aerialway": os.path.join(typemapdir, "osmNetconvertAerialway.typ.xml"),
}

# common parameters
CP = ["--trip-attributes", 'departLane="best"',
      "--fringe-start-attributes", 'departSpeed="max"',
      "--validate", "--remove-loops",
      "--via-edge-types", ','.join(["highway.motorway",
                                    "highway.motorway_link",
                                    "highway.trunk_link",
                                    "highway.primary_link",
                                    "highway.secondary_link",
                                    "highway.tertiary_link"])
      ]

# pedestrian parameters
PP = ["--vehicle-class", "pedestrian", "--prefix", "ped", ]


def getParams(vClass, prefix=None):
    if prefix is None:
        prefix = vClass
    return ["--vehicle-class", vClass,  "--vclass", vClass,  "--prefix", prefix]


vehicleParameters = {
    "passenger":   CP + getParams("passenger", "veh") + ["--min-distance", "300", "--min-distance.fringe", "10",
                                                         "--allow-fringe.min-length", "1000", "--lanes"],
    "truck":       CP + getParams("truck") + ["--min-distance", "600", "--min-distance.fringe", "10"],   # noqa
    "bus":         CP + getParams("bus") + ["--min-distance", "600", "--min-distance.fringe", "10"],   # noqa
    "motorcycle":  CP + getParams("motorcycle") + ["--max-distance", "1200"],                                 # noqa
    "bicycle":     CP + getParams("bicycle", "bike") + ["--max-distance", "8000"],                                 # noqa
    "tram":        CP + getParams("tram") + ["--min-distance", "1200", "--min-distance.fringe", "10"],  # noqa
    "rail_urban":  CP + getParams("rail_urban") + ["--min-distance", "1800", "--min-distance.fringe", "10"],  # noqa
    "rail":        CP + getParams("rail") + ["--min-distance", "2400", "--min-distance.fringe", "10"],  # noqa
    "ship":             getParams("ship") + ["--fringe-start-attributes", 'departSpeed="max"', "--validate"],
    "pedestrian":  PP + ["--pedestrians", "--max-distance", "2000"],
    "persontrips": PP + ["--persontrips", "--trip-attributes", 'modes="public"'],
}

vehicleNames = {
    "passenger": "Cars",
    "truck": "Trucks",
    "bus": "Bus",
    "motorcycle": "Motorcycles",
    "bicycle": "Bicycles",
    "pedestrian": "Pedestrians",
    "tram": "Trams",
    "rail_urban": "Urban Trains",
    "rail": "Trains",
    "ship": "Ships"
}


# all can read and execute, only user can read batch files
BATCH_MODE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
BATCH_MODE |= stat.S_IWUSR
BATCH_MODE |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


def quoted_str(s):
    if isinstance(s, float):
        return "%.6f" % s
    elif not isinstance(s, str):
        return str(s)
    elif '"' in s or ' ' in s:
        return '"' + s.replace('"', '\\"') + '"'
    else:
        return s


class Builder(object):
    prefix = "osm"

    def __init__(self, data, local):
        self.files = {}
        self.files_relative = {}
        self.data = data

        self.tmp = None
        if local:
            now = data.get("outputDir", "cases/" + datetime.datetime.now().strftime("sumo_%Y%m%d_%H%M%S"))
            for base in ['', os.path.expanduser('~/Sumo')]:
                try:
                    self.tmp = os.path.abspath(os.path.join(base, now))
                    os.makedirs(self.tmp, exist_ok=data.get("outputDirExistOk", False))
                    break
                except Exception:
                    print("Cannot create directory '%s'." % self.tmp, file=sys.stderr)
                    self.tmp = None
        if self.tmp is None:
            self.tmp = tempfile.mkdtemp()

        self.origDir = os.getcwd()
        print("Building scenario in '%s'." % self.tmp)

    def report(self, message):
        pass

    def filename(self, use, name, usePrefix=True):
        prefix = self.prefix if usePrefix else ''
        self.files_relative[use] = prefix + name
        assert self.tmp is not None
        self.files[use] = os.path.join(self.tmp, prefix + name)

    def getRelative(self, options):
        result = []
        dirname = self.tmp
        assert dirname is not None
        ld = len(dirname)
        for o in options:
            if isinstance(o, str) and o[:ld] == dirname:
                remove = o[:ld+1]
                result.append(o.replace(remove, ''))
            else:
                result.append(o)
        return result

    def build(self):
        # output name for the osm file, will be used by osmBuild, can be
        # deleted after the process
        self.filename("osm", "_bbox.osm.xml.gz")
        # output name for the net file, will be used by osmBuild, randomTrips and sumo-gui
        self.filename("net", ".net.xml.gz")

        if self.data.get("coords") is None:
            # fixed input testing mode
            self.files["osm"] = self.data['osm']
        else:
            source = self.data.get("osmSource", "overpass")
            if source == "pbf":
                self.report("Extracting selected region from local OSM PBF")
                osmGet.extract_pbf(
                    self.data["pbfPath"], self.data["coords"], self.files["osm"],
                    progress=self.report,
                    progress_event=getattr(self, "partition_progress", None),
                )
            else:
                self.report("Downloading map data")
                osmArgs = ["-b=" + (",".join(map(str, self.data["coords"]))), "-p", self.prefix, "-d", self.tmp, "-z"]
                osmArgs += ["--tile-size-km", str(self.data.get("tileSizeKm", 5))]
                if self.data["poly"]:
                    osmArgs.append("--shapes")
                if 'osmMirror' in self.data:
                    osmArgs += ["-u", self.data["osmMirror"]]
                if 'roadTypes' in self.data:
                    osmArgs += ["-r", json.dumps(self.data["roadTypes"])]
                osmGet.get(osmArgs, progress=self.report,
                           progress_event=getattr(self, "partition_progress", None))

        if not os.path.isfile(self.files["osm"]) or os.path.getsize(self.files["osm"]) == 0:
            raise RuntimeError("OSM download returned no data: %s" % self.files["osm"])

        options = ["-f", self.files["osm"], "-p", self.prefix, "-d", self.tmp, "-z"]

        self.additionalFiles = []
        self.routenames = []

        if self.data["poly"]:
            # output name for the poly file, will be used by osmBuild and sumo-gui
            self.filename("poly", ".poly.xml.gz")

            options += ["-m", typemaps["poly"]]
            self.additionalFiles.append(self.files["poly"])

        typefiles = [typemaps["net"]]
        # leading space ensures that arguments starting with -- are not
        # misinterpreted as options
        netconvertOptions = " " + osmBuild.DEFAULT_NETCONVERT_OPTS
        if self.data.get("options"):
            netconvertOptions += "," + self.data["options"]
        netconvertOptions += ",--tls.default-type,actuated"
        # netconvertOptions += ",--default.spreadtype,roadCenter"
        if "pedestrian" in self.data["vehicles"]:
            # sidewalks are already included via typefile
            netconvertOptions += ",--crossings.guess"
            netconvertOptions += ",--osm.sidewalks"
            typefiles.append(typemaps["urban"])
            typefiles.append(typemaps["pedestrians"])
        if "ship" in self.data["vehicles"]:
            typefiles.append(typemaps["ships"])
        if "bicycle" in self.data["vehicles"]:
            typefiles.append(typemaps["bicycles"])
            netconvertOptions += ",--osm.bike-access"
        # special treatment for public transport
        if self.data["publicTransport"]:
            self.filename("stops", "_stops.add.xml")
            netconvertOptions += ",--ptstop-output,%s" % self.files["stops"]
            netconvertOptions += ",--ptline-clean-up"
            self.filename("ptlines", "_ptlines.xml")
            self.filename("ptroutes", "_pt.rou.xml")
            netconvertOptions += ",--ptline-output,%s" % self.files["ptlines"]
            self.additionalFiles.append(self.files["stops"])
            self.routenames.append(self.files["ptroutes"])
            netconvertOptions += ",--railway.topology.repair"
            typefiles.append(typemaps["aerialway"])
        if self.data["leftHand"]:
            netconvertOptions += ",--lefthand"
        if self.data.get("verbose"):
            netconvertOptions += ",--verbose"
        if self.data["decal"]:
            # change projection to web-mercator to match the background image projection
            netconvertOptions += ",--proj,+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +wktext +no_defs"  # noqa

        if self.data["carOnlyNetwork"]:
            if self.data["publicTransport"]:
                options += ["--vehicle-classes", "publicTransport"]
            else:
                options += ["--vehicle-classes", "passenger"]

        options += ["--netconvert-typemap", ','.join(typefiles)]
        options += ["--netconvert-options", netconvertOptions]
        options += ["--polyconvert-options", " -v,--osm.keep-full-type,--osm.merge-relations,1"]

        self.report("Converting map data")
        osmBuild.build(options)
        ptOptions = None
        begin = self.data.get("begin", 0)
        if self.data["publicTransport"]:
            self.report("Generating public transport schedule")
            self.filename("pt_stopinfos", "stopinfos.xml", False)
            self.filename("pt_vehroutes", "vehroutes.xml", False)
            self.filename("pt_trips", "trips.trips.xml", False)
            ptOptions = [
                "-n", self.files["net"],
                "-b", begin,
                "-e", begin + self.data["duration"],
                "-p", "600",
                "--random-begin",
                "--seed", "42",
                "--ptstops", self.files["stops"],
                "--ptlines", self.files["ptlines"],
                "-o", self.files["ptroutes"],
                "--ignore-errors",
                # "--no-vtypes",
                "--vtype-prefix", "pt_",
                "--stopinfos-file", self.files["pt_stopinfos"],
                "--routes-file", self.files["pt_vehroutes"],
                "--trips-file", self.files["pt_trips"],
                "--min-stops", "0",
                "--extend-to-fringe",
                "--verbose",
            ]
            ptlines2flows.main(ptlines2flows.get_options(ptOptions))

        if self.data["decal"]:
            self.report("Downloading background images")
            tileOptions = [
                "-n", self.files["net"],
                "-t", "100",
                "-d", "background_images",
                "-l", "-300",
                "-a", "Mozilla/5.0 (X11; Linux x86_64) osmWebWizard.py/1.0 (+https://github.com/eclipse-sumo/sumo)",
            ]
            assert self.tmp is not None
            try:
                os.chdir(self.tmp)
                os.mkdir("background_images")
                tileGet.get(tileOptions)
                self.report("Success.")
                self.decalError = False
            except Exception as e:
                os.chdir(self.tmp)
                shutil.rmtree("background_images", ignore_errors=True)
                self.report("Error while downloading background images: %s" % e)
                self.decalError = True

            # create a batch file for reproducing calls to randomTrips.py
            if os.name == "posix":
                SUMO_HOME_VAR = "$SUMO_HOME"
            else:
                SUMO_HOME_VAR = "%SUMO_HOME%"

            ptlines2flowsPath = os.path.join(SUMO_HOME_VAR, "tools", "ptlines2flows.py")

            self.filename("build.bat", "build.bat", False)
            batchFile = self.files["build.bat"]
            with open(batchFile, 'w') as f:
                if os.name == "posix":
                    f.write("#!/bin/bash\n")
                if ptOptions is not None:
                    f.write('python "%s" %s\n' %
                            (ptlines2flowsPath, " ".join(map(quoted_str, self.getRelative(ptOptions)))))
            os.chmod(batchFile, BATCH_MODE)

    def makeConfigFile(self):
        "Save the configuration for SUMO in a file"

        self.report("Generating configuration file")

        self.filename("guisettings", ".view.xml")
        with open(self.files["guisettings"], 'w') as f:
            if self.data["decal"] and not self.decalError:
                f.write("""
<viewsettings>
    <scheme name="real world"/>
    <delay value="20"/>
    <include href="background_images/settings.xml"/>
</viewsettings>
""")
            else:
                f.write("""
<viewsettings>
    <scheme name="real world"/>
    <delay value="20"/>
</viewsettings>
""")
        sumo = sumolib.checkBinary("sumo")

        self.filename("config", ".sumocfg")
        opts = [sumo, "-n", self.files_relative["net"], "--gui-settings-file", self.files_relative["guisettings"],
                "--duration-log.statistics",
                "--device.rerouting.adaptation-interval", "10",
                "--device.rerouting.adaptation-steps", "18",
                "--tls.actuated.jam-threshold", "30",
                "-v", "--no-step-log", "--save-configuration", self.files_relative["config"], "--ignore-route-errors"]

        if self.routenames:
            opts += ["-r", ",".join(self.getRelative(self.routenames))]

            # extra output if the scenario contains traffic
            opts += ["--tripinfo-output", "tripinfos.xml"]
            opts += ["--statistic-output", "stats.xml"]

            self.filename("outadd", "output.add.xml", False)
            with open(self.files["outadd"], 'w') as fadd:
                sumolib.writeXMLHeader(fadd, "$Id$", "additional")
                fadd.write('   <edgeData id="wizard_example" period="3600" file="edgeData.xml"/>\n')
                fadd.write("</additional>\n")
            self.additionalFiles.append(self.files["outadd"])

        if self.data["publicTransport"]:
            opts += ["--stop-output", "stopinfos.xml"]

        if len(self.additionalFiles) > 0:
            opts += ["-a", ",".join(self.getRelative(self.additionalFiles))]

        subprocess.call(opts, cwd=self.tmp)

    def openV2Sim(self):
        self.report("Create UXsim copy")
        case_dir = Path(self.files["config"]).parent
        if case_dir.name.lower().startswith("sumo_"):
            new_case_dir = case_dir.parent / ("ux_" + case_dir.name[5:])
        else:
            new_case_dir = case_dir.parent / ("ux_" + case_dir.name)
        from v2sim import ConvertCase, AddRecentProject
        try:
            ConvertCase(str(case_dir), str(new_case_dir), -1, True, True, True)
        except Exception as e:
            print(traceback.format_exc())
            self.report("Error while converting case for V2Sim: %s" % e)
            if new_case_dir.exists(): new_case_dir.rmdir()
        else:
            AddRecentProject(str(new_case_dir))
        
        self.report("Calling V2Sim")
        exec_dir = Path(__file__).parent.parent.parent / "app" / "gui_main.py"
        subprocess.run([sys.executable, exec_dir, "-d", str(case_dir)])

    def createZip(self):
        """Create a ZIP archive and return its filesystem path."""

        self.report("Building zip file")

        self.filename("zip", ".zip")

        with ZipFile(self.files["zip"], "w") as zipfile:
            files = ["net", "guisettings", "config", "run.bat"]

            if self.data["vehicles"] or self.data["publicTransport"]:
                files += ["build.bat"]

            if self.data["poly"]:
                files += ["poly"]

            # translate the pseudo file names to real file names
            files = list(map(lambda name: self.files[name], files))

            if self.data["vehicles"]:
                files += self.routenames

            # add the files to the zip
            for name in files:
                zipfile.write(name)

        return self.files["zip"]

    def finalize(self):
        assert self.tmp is not None
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass


class BuildJob:
    """State for one scenario build, read by the HTTP polling endpoint."""

    def __init__(self):
        self.id = uuid.uuid4().hex
        self.state = "running"
        self.messages = []
        self.error = None
        self.zip_path = None
        self.builder = None
        self.created = time.monotonic()
        self.thread = None
        self.lock = threading.Lock()
        self.partition = None

    def update_partition(self, event):
        """Expose a consistent snapshot of adaptive partition download progress."""
        with self.lock:
            self.partition = dict(event)

    def report(self, message):
        print(message, flush=True)
        with self.lock:
            self.messages.append(str(message))

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id,
                "state": self.state,
                "messages": list(self.messages),
                "partition": dict(self.partition) if self.partition else None,
                "error": self.error,
                "download_url": "/api/jobs/%s/download" % self.id if self.zip_path else None,
            }


class BuildManager:
    """Serialize builds because legacy SUMO helpers change process working directory."""

    def __init__(self, local, output_dir):
        self.local = local
        self.output_dir = output_dir
        self.current = None
        self.lock = threading.Lock()

    def start(self, data):
        with self.lock:
            if self.current and (self.current.state == "running" or
                                 (self.current.thread is not None and self.current.thread.is_alive())):
                return None
            if self.current and self.current.zip_path:
                self.current.builder.finalize()
            job = BuildJob()
            self.current = job
            thread = threading.Thread(target=self._run, args=(job, data), daemon=True)
            job.thread = thread
            thread.start()
            return job

    def get(self, job_id):
        with self.lock:
            if self.current and self.current.id == job_id:
                return self.current
        return None

    def _run(self, job, data):
        builder = None
        try:
            if self.output_dir is not None:
                data["outputDir"] = self.output_dir
                data["outputDirExistOk"] = True
            builder = Builder(data, self.local)
            job.builder = builder
            builder.report = job.report
            builder.partition_progress = job.update_partition
            builder.build()
            builder.makeConfigFile()
            if self.local:
                builder.openV2Sim()
            else:
                job.zip_path = builder.createZip()
            job.report("Scenario completed")
            with job.lock:
                job.state = "completed"
        except Exception as exc:
            traceback.print_exc()
            with job.lock:
                job.state = "failed"
                job.error = str(exc)
            job.report("Error: %s" % exc)
            if builder is not None and not self.local:
                builder.finalize()
        finally:
            # Avoid restoring cwd while another job is running; manager serializes jobs.
            if builder is not None:
                os.chdir(builder.origDir)


def validate_build_request(data):
    """Validate browser input before creating files or network requests."""
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    coords = data.get("coords")
    if not isinstance(coords, list) or len(coords) != 4:
        raise ValueError("coords must be [west, south, east, north]")
    try:
        west, south, east, north = [float(v) for v in coords]
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid bounding box coordinates") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid bounding box coordinates")
    data["coords"] = [west, south, east, north]
    tile_size = data.get("tileSizeKm", 5)
    if type(tile_size) not in (int, float) or not (0 <= tile_size <= 500) or not math.isfinite(tile_size):
        raise ValueError("tileSizeKm must be between 0 and 500 km")
    data["tileSizeKm"] = tile_size
    source = data.get("osmSource", "overpass")
    if source not in ("overpass", "pbf"):
        raise ValueError("osmSource must be overpass or pbf")
    data["osmSource"] = source
    if source == "pbf":
        pbf_path = data.get("pbfPath")
        if not isinstance(pbf_path, str) or not pbf_path.strip():
            raise ValueError("Select a local .osm.pbf path")
        pbf_path = os.path.abspath(os.path.expanduser(pbf_path.strip()))
        if not pbf_path.lower().endswith(".osm.pbf"):
            raise ValueError("Local input must have .osm.pbf extension")
        if not os.path.isfile(pbf_path):
            raise ValueError("PBF file does not exist: %s" % pbf_path)
        data["pbfPath"] = pbf_path
    else:
        data.pop("pbfPath", None)
    if not isinstance(data.get("vehicles"), dict):
        raise ValueError("vehicles must be an object")
    if not isinstance(data.get("roadTypes", {}), dict):
        raise ValueError("roadTypes must be an object")
    for field in ("poly", "publicTransport", "leftHand", "decal", "carOnlyNetwork"):
        if not isinstance(data.get(field), bool):
            raise ValueError("%s must be boolean" % field)
    duration = data.get("duration")
    if type(duration) is not int or not (0 <= duration <= 31_536_000):
        raise ValueError("duration must be between 0 and 31536000 seconds")
    # The browser must not select an arbitrary filesystem output directory.
    data.pop("outputDir", None)
    data.pop("outputDirExistOk", None)
    return data


class WizardHTTPHandler(SimpleHTTPRequestHandler):
    """Single-origin HTTP API and static frontend, no WebSocket dependency."""

    server_version = "V2SimWizard/2.0"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(THIS_DIR, "webWizard"), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return False
        expected = "http://" + self.headers.get("Host", "")
        return origin == expected

    def do_POST(self):
        if self.path != "/api/build":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
        if not self._same_origin():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "Same-origin request required"})
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Expected application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid body size"})
        if not 0 < length <= 65536:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request must be 1-65536 bytes"})
        try:
            data = validate_build_request(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if data.get("osmSource") == "pbf" and not self.server.build_manager.local:
            return self._json(HTTPStatus.FORBIDDEN, {"error": "Local PBF is available only in local wizard mode"})
        job = self.server.build_manager.start(data)
        if job is None:
            return self._json(HTTPStatus.CONFLICT, {"error": "A build is already running"})
        return self._json(HTTPStatus.ACCEPTED, {"job_id": job.id, "status_url": "/api/jobs/" + job.id})

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(HTTPStatus.OK, {"status": "ok", "version": 2})
        if self.path.startswith("/api/jobs/"):
            parts = self.path.split("/")
            if len(parts) not in (4, 5):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
            job = self.server.build_manager.get(parts[3])
            if job is None:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown job"})
            if len(parts) == 4:
                return self._json(HTTPStatus.OK, job.snapshot())
            if parts[4] == "download" and len(parts) == 5:
                return self._download(job)
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
        if self.path.startswith("/api/"):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def _download(self, job):
        with job.lock:
            if job.state != "completed" or not job.zip_path:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Archive unavailable"})
            path = job.zip_path
        if not os.path.isfile(path):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Archive missing"})
        size = os.path.getsize(path)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="osm.zip"')
        self.send_header("Content-Length", str(size))
        self.end_headers()
        try:
            with open(path, "rb") as src:
                shutil.copyfileobj(src, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass


def get_options(args=None):
    parser = sumolib.options.ArgumentParser(description="V2Sim OSM Web Wizard HTTP API")
    parser.add_argument("--remote", action="store_true",
                        help="In remote mode, SUMO GUI will not be automatically opened instead a zip file " +
                        "will be generated.")
    parser.add_argument("--osm-file", default="osm_bbox.osm.xml", dest="osmFile", help="use input file from path.")
    parser.add_argument("--test-output", dest="testOutputDir",
                        help="Run with pre-defined options on file 'osm_bbox.osm.xml' and " +
                        "write output to the given directory.")
    parser.add_argument("--bbox", help="bounding box to retrieve in geo coordinates west,south,east,north.")
    parser.add_argument("-o", "--output", dest="outputDir",
                        help="Write output to the given folder rather than creating a name based on the timestamp")
    parser.add_argument("--address", default="", help="HTTP bind address (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8010,
                        help="HTTP server port (default 8010, use 0 for an available port).")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="tell me what you are doing")
    parser.add_argument("-b", "--begin", default=0, type=sumolib.miscutils.parseTime,
                        help="Defines the begin time for the scenario.")
    parser.add_argument("-e", "--end", default=900, type=sumolib.miscutils.parseTime,
                        help="Defines the end time for the scenario.")
    parser.add_argument("-n", "--netconvert-options", help="additional comma-separated options for netconvert")
    parser.add_argument("--demand", default="passenger:6f5,bicycle:2f2,pedestrian:4,ship:1f40",
                        help="Traffic demand definition for non-interactive mode.")
    return parser.parse_args(args)


def main(options):
    if options.testOutputDir is not None:
        demand = collections.defaultdict(dict)
        for mode in options.demand.split(","):
            k, v = mode.split(":")
            if "f" in v:
                demand[k]['count'], demand[k]['fringeFactor'] = v.split("f")
            else:
                demand[k]['count'] = v
        data = {u'begin': options.begin,
                u'duration': options.end - options.begin,
                u'vehicles': demand,
                u'osm': os.path.abspath(options.osmFile),
                u'poly': options.bbox is None,  # reduce download size
                u'publicTransport': True,
                u'leftHand': False,
                u'decal': False,
                u'verbose': options.verbose,
                u'carOnlyNetwork': False,
                u'outputDir': options.testOutputDir,
                u'coords': options.bbox.split(",") if options.bbox else None,
                u'options': options.netconvert_options
                }
        builder = Builder(data, True)
        builder.build()
        builder.makeConfigFile()
        if not options.remote:
            subprocess.call([sumolib.checkBinary("sumo"), "-c", builder.files["config"]])
    else:
        address = options.address or "127.0.0.1"
        if address not in ("127.0.0.1", "localhost", "::1"):
            print("WARNING: HTTP API exposed beyond loopback; use a trusted network only.", file=sys.stderr)
        manager = BuildManager(local=not options.remote, output_dir=options.outputDir)
        httpd = ThreadingHTTPServer((address, options.port), WizardHTTPHandler)
        httpd.daemon_threads = True
        httpd.build_manager = manager
        host = "127.0.0.1" if address in ("127.0.0.1", "localhost", "0.0.0.0") else address
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        url = "http://%s:%s/" % (host, httpd.server_port)
        print("OSM Web Wizard: %s" % url, flush=True)
        if not options.remote:
            webbrowser.open(url)
        try:
            httpd.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


if __name__ == "__main__":
    main(get_options())
