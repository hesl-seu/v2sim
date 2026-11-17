document.addEventListener("DOMContentLoaded", function () {
    const elem = (selector, props) => {
        if (selector.startsWith("<") && selector.endsWith(">")) {
            const node = document.createElement(selector.slice(1, -1));
            if (props) Object.assign(node, props);
            return node;
        }
        return document.querySelector(selector);
    };
    const elems = selector => document.querySelectorAll(selector);
    const lequal = (...values) => values.every((value, index) => index === 0 || values[index - 1] <= value);


    class RoadTypes {
        constructor(category, typeList, checked = false) {
            this.category = category;
            this.typeList = typeList;

            const node = elem("<div>", {className: "container"});
            node.append(elem("<h4>", {textContent: category}));
            node.append(elem("<input>", {
                type: "checkbox", checked, className: "checkAll", id: category.toLowerCase()
            }));

            const types = elem("<div>", {className: "roadTypes " + category.toLowerCase()});
            for (const roadType of typeList) {
                const label = elem("<label>", {textContent: roadType});
                label.append(elem("<input>", {
                    type: "checkbox", checked, id: `${category}_${roadType}`
                }));
                types.append(label);
            }
            node.append(types);
            elem("#road-types").append(node);
        }

        getEnabledTypeList() {
            const enabled = [];
            for (const roadType of this.typeList) {
                if (document.getElementById(`${this.category}_${roadType}`).checked) {
                    enabled.push(roadType);
                    if (/^(motorway|trunk|primary|secondary|tertiary)$/.test(roadType)) {
                        enabled.push(`${roadType}_link`);
                    }
                }
            }
            return enabled;
        }
    }

    const categories = {};
    categories["Highway"] = ["motorway", "trunk", "primary","secondary", "tertiary", "unclassified", "residential",
        "living_street", "unsurfaced", "service", "raceway", "bus_guideway"];
    categories["Pedestrians"] = ["track", "footway", "pedestrian", "path", "bridleway", "cycleway", "step", "steps",
        "stairs"];              //"Pedestrians" has also the "highway" key in OSM, this will be transformed in startBuild()
    categories["Railway"] = ["preserved", "tram", "subway", "light_rail", "rail", "highspeed", "monorail"];
    categories["Aeroway"] = ["stopway", "parking_position", "taxiway", "taxilane", "runway", "highway_strip"]
    categories["Waterway"] = ["river", "canal"];
    categories["Aerialway"] = ["cable_car", "gondola"];
    categories["Route"] = ["ferry"];

    var roadClasses = [];

    for (const [key, value] of Object.entries(categories)) {
        roadClasses.push(new RoadTypes(key, value, key === "Highway"));
    }

    var activeTab = null;

    /**
     * @function
     * @param id: the id of the tab to open
     */
    function openTab(id){
        var tab = elems(".tab")[id];
        var side = elem("#side");
        var control = elems(".controls")[id];

        // clicked on the open tab, close everything
        if(activeTab === id){
            side.classList.remove("open");
            control.classList.remove("open");
            tab.classList.remove("open");
            activeTab = null;
        } else {
            // open the side and control
            side.classList.add("open");
            control.classList.add("open");
            tab.classList.add("open");

            // close the other tab, if there is one
            if(activeTab !== null){
                elems(".controls")[activeTab].classList.remove("open");
                elems(".tab")[activeTab].classList.remove("open");
            }

            activeTab = id;
        }
    }

    elems(".tab").forEach(function(tab, index){
        tab.dataset.symbol = tab.textContent;
        tab.addEventListener("click", function(){
            openTab(index);
        });
    });

    openTab(0);

    var canvas = elem("canvas");
    var canvasActive = false;
    var canvasRect = [.1, .1, .75, .9];
    var ctx = canvas.getContext("2d");

    /**
     * @function
     * sets the canvas to full page size
     */
    function setCanvasSize(){
        canvas.width = innerWidth;
        canvas.height = innerHeight;
        draw();
    }

    setCanvasSize();
    window.addEventListener("resize", setCanvasSize);

    /**
     * @function
     * draws the rect on the canvas, to select an area
     **/
    function draw(){
        var x0 = canvas.width * canvasRect[0],
            y0 = canvas.height * canvasRect[1],
            x1 = canvas.width * canvasRect[2],
            y1 = canvas.height * canvasRect[3];

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.fillStyle = "#808080";
        ctx.globalAlpha = .5;

        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.clearRect(x0, y0, x1 - x0, y1 - y0);
    }

    var mouse = {
        x: 0, // last x coordinate
        y: 0, // last y coordinates
        area: null // if mouse button is down, and in which function; move or resize
    }

    canvas.addEventListener("mousedown", function(evt){
        mouse.area = changeMousePointer(evt.clientX, evt.clientY, true);
    });
    canvas.addEventListener("mouseup", function(evt){
        mouse.area = null;
        changeMousePointer(evt.clientX, evt.clientY);
    });

    function changeMousePointer(x, y, down){
        var x0 = canvas.width * canvasRect[0],
            y0 = canvas.height * canvasRect[1],
            x1 = canvas.width * canvasRect[2],
            y1 = canvas.height * canvasRect[3];

        var cursor = "", t = 20; //tolerance

        if(lequal(x0 - t, x, x1 + t) && lequal(y0 - t, y, y1 + t)){
            if(lequal(y0 - t, y, y0 + t))
                cursor += "n";
            else if(lequal(y1 - t, y, y1 + t))
                cursor += "s";

            if(lequal(x0 - t, x, x0 + t))
                cursor += "w";
            else if(lequal(x1 - t, x, x1 + t))
                cursor += "e";

            if(cursor) cursor += "-resize";
            else if(mouse.area || down) cursor = "move";
            else cursor = "pointer";
        } else
            cursor = "auto"

        canvas.style.cursor = cursor;
        return cursor.match(/^([nsm])?([we])?/);
    }

    canvas.addEventListener("mousemove", function(evt){
        changeMousePointer(evt.clientX, evt.clientY);
        var dx = (evt.clientX - mouse.x) / canvas.width, dy = (evt.clientY - mouse.y) / canvas.height;
        mouse.x = evt.clientX;
        mouse.y = evt.clientY;
        if(mouse.area !== null){
            if(mouse.area[1] == "n"){
                if((canvasRect[1] + dy)<=canvasRect[3]){
                    canvasRect[1] += dy;
                } else if ((canvasRect[1] + dy)>canvasRect[3]){
                    [canvasRect[1], canvasRect[3]] = [canvasRect[3], canvasRect[1]];
                    canvasRect[3] += dy;
                    mouse.area[1] = "s";
                }
            }
            else if(mouse.area[1] == "s"){
                if((canvasRect[3] + dy)>=canvasRect[1]){
                    canvasRect[3] += dy;
                } else if ((canvasRect[3] + dy)<canvasRect[1]){
                    [canvasRect[1], canvasRect[3]] = [canvasRect[3], canvasRect[1]];
                    canvasRect[1] += dy;
                    mouse.area[1] = "n";
                }
            }

            if(mouse.area[2] == "w"){
                if((canvasRect[0] + dx)<=canvasRect[2]){
                    canvasRect[0] += dx;
                } else if ((canvasRect[0] + dx)>canvasRect[2]){
                    [canvasRect[0], canvasRect[2]] = [canvasRect[2], canvasRect[0]];
                    canvasRect[2] += dx;
                    mouse.area[2] = "e";
                }
            }
            else if(mouse.area[2] == "e"){
                if((canvasRect[2] + dx)>=canvasRect[0]){
                    canvasRect[2] += dx;
                } else if ((canvasRect[2] + dx)<canvasRect[0]){
                    [canvasRect[0], canvasRect[2]] = [canvasRect[2], canvasRect[0]];
                    canvasRect[0] += dx;
                    mouse.area[2] = "w";
                }
            }

            if(mouse.area[1] == "m"){
                canvasRect[0] += dx;
                canvasRect[1] += dy;
                canvasRect[2] += dx;
                canvasRect[3] += dy;
            }

            draw();
        }
    });

    /**
     * @function
     * checks if the checkbox is checked and displays the canvas in this case, else not
     **/
    function toggleCanvas(){
        if(canvasToggle.checked){
            canvasActive = true;
            canvas.style.removeProperty("display");
        } else {
            canvasActive = false;
            canvas.style.display = "none";
        }
    }

    var canvasToggle = elem("#canvas-toggle");

    canvasToggle.addEventListener("click", toggleCanvas);
    toggleCanvas();

    // function to check or uncheck all checkboxes for a certain roadType
    var checkOrUncheckAll = function() {
        Array.from(document.querySelectorAll(".roadTypes." + this.getAttribute("id") + " input[type=checkbox]")).forEach(el => el.checked = this.checked);
    };

    // listen if a roadType checkbox is selected/unselected
    var roadTypeCheckboxes = document.getElementsByClassName("checkAll");

    Array.from(roadTypeCheckboxes).forEach(function(element) {
        element.addEventListener("click", checkOrUncheckAll);
    });

    // Leaflet replaces the unsupported OpenLayers 2 API.
    // OSM tile policy: HTTPS tiles, visible attribution, browser Referer and caching.
    const map = L.map("map", {zoomControl: true, attributionControl: false})
        .setView([39.904030, 116.407526], 16);
    L.control.attribution({position: "bottomleft"}).addTo(map);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    }).addTo(map);

    function setPosition(lon, lat){
        if (typeof lon !== "number" || typeof lat !== "number") {
            const latLon = elem("#lat_lon").value.trim().split(/\s+/);
            lon = parseFloat(latLon[1]);
            lat = parseFloat(latLon[0]);
        } else {
            elem("#lat_lon").value = lat.toFixed(6) + " " + lon.toFixed(6);
        }
        if (!Number.isFinite(lat) || !Number.isFinite(lon) ||
            Math.abs(lat) > 90 || Math.abs(lon) > 180) {
            window.alert("Invalid coordinates. Use: latitude longitude");
            return;
        }

        const leftHandBounds = [
            [[50,-11],[60,1]], [[50.986099,0.774536],[53.146770,1.779785]],
            [[3,66],[30,90]], [[-45,95],[2,179]],
            [[-35,-20],[-15,40]], [[30,135],[42,150]]
        ];
        elem("#leftHand").checked = leftHandBounds.some(
            bounds => L.latLngBounds(bounds).contains([lat, lon])
        );
        map.setView([lat, lon], 16);

    }

    async function setPositionByString() {
        const query = elem("#address").value.trim();
        if (!query) return;
        try {
            const url = new URL("https://nominatim.openstreetmap.org/search");
            url.search = new URLSearchParams({q: query, format: "json", limit: "1"}).toString();
            const response = await fetch(url, {headers: {"Accept": "application/json"}});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const results = await response.json();
            if (!results.length) throw new Error("No matching location");
            setPosition(Number(results[0].lon), Number(results[0].lat));
        } catch (error) {
            window.alert("Could not locate address: " + error.message);
        }
    }

    // set default position to center Beijing
    setPosition(116.407526, 39.904030);
    /**
     * @listener
     * set the coordinates of the map to current coordinates (got from browser)
     */
    elem("#buttonCurrent").addEventListener("click", function(){
        if(!navigator.geolocation) return;

        navigator.geolocation.getCurrentPosition(function(position){
            setPosition(position.coords.longitude, position.coords.latitude);
        });
    });

    /**
     * @listener
     * whenever the input boxes changes, update the map coordinates
     */
    elem("#buttonSearch").addEventListener("click", setPositionByString);
    elem("#buttonLatLon").addEventListener("click", setPosition);

    /**
     * @listener
     * whenever the map coordinates changes, update the input boxes
     */
    map.on("moveend", function () {
        const center = map.getCenter();
        elem("#lat_lon").value = center.lat.toFixed(6) + " " + center.lng.toFixed(6);
    });

    const sourceChoice = elem("#osm-source");
    const localPbfRow = elem("#pbf-path-row");
    const partitionOption = elem("#partition-option");
    function refreshSourceOptions() {
        const isPbf = sourceChoice.value === "pbf";
        localPbfRow.hidden = !isPbf;
        partitionOption.hidden = isPbf;
    }
    sourceChoice.addEventListener("change", refreshSourceOptions);
    refreshSourceOptions();

    // Single-origin HTTP API. No WebSocket server, fixed port, or base64 ZIP.
    let activeJob = null;
    let pollController = null;
    const exportButton = elem("#export-button");
    const statusText = elem("#status-message");
    const progressBar = elem("#status-progress-fill");
    const progressTrack = elem("#status-progress-track");
    const partitionCount = elem("#partition-count");
    const progressDetail = elem("#status-detail");

    function showProgress(job) {
        const partition = job.partition;
        const complete = job.state === "completed";
        const failed = job.state === "failed";
        const downloadInProgress = partition && partition.phase === "downloading";
        const validTotal = partition && Number.isFinite(partition.total) && partition.total > 0;
        const showPartition = Boolean(validTotal);
        partitionCount.hidden = !showPartition;
        progressTrack.classList.toggle("indeterminate", !complete && !failed && !downloadInProgress);
        progressTrack.classList.toggle("failed", failed);
        progressTrack.setAttribute("aria-label", downloadInProgress ? "OSM partition download progress" : "Scenario generation progress");
        if (showPartition) {
            const total = Math.max(1, partition.total);
            const completed = Math.max(0, Math.min(total, partition.completed));
            const current = Math.max(1, Math.min(total, partition.current));
            partitionCount.textContent = `${downloadInProgress ? current : completed} / ${total}`;
            const pct = Math.round(100 * completed / total);
            progressBar.style.width = `${pct}%`;
            progressTrack.setAttribute("aria-valuenow", String(pct));
            progressDetail.textContent = downloadInProgress
                ? `${completed} completed · ${total - completed} remaining${partition.detail ? " · " + partition.detail : ""}`
                : (partition.phase === "merging" ? "Merging downloaded partitions…" :
                   partition.phase === "finished" ? "OSM data ready · generating SUMO scenario…" :
                   partition.detail || "Processing…");
        } else {
            partitionCount.textContent = "";
            progressDetail.textContent = failed ? "Task failed" :
                (partition && partition.detail ? partition.detail : "Preparing scenario…");
            progressBar.style.width = complete ? "100%" : "0%";
            progressTrack.setAttribute("aria-valuenow", complete ? "100" : "0");
        }
        if (complete) {
            progressTrack.classList.remove("indeterminate");
            progressBar.style.width = "100%";
            progressTrack.setAttribute("aria-valuenow", "100");
            progressDetail.textContent = "Scenario completed";
        } else if (failed) {
            progressDetail.textContent = "Task failed · check error above";
        }
    }

    async function apiJSON(url, options) {
        const response = await fetch(url, {cache: "no-store", ...options});
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
        return body;
    }

    function setBuildState(running, message) {
        exportButton.disabled = running;
        exportButton.textContent = running ? "Generating…" : "Generate Scenario";
        elem("#status").style.display = "block";
        if (message) statusText.textContent = message;
    }

    async function watchJob(jobId) {
        let seen = 0;
        let failures = 0;
        pollController = new AbortController();
        const signal = pollController.signal;
        while (!signal.aborted) {
            try {
                const job = await apiJSON(`/api/jobs/${encodeURIComponent(jobId)}`, {signal});
                failures = 0;
                const newMessages = job.messages.slice(seen);
                seen = job.messages.length;
                if (newMessages.length) statusText.textContent = newMessages[newMessages.length - 1];
                if (job.partition && job.partition.phase === "downloading") {
                    statusText.textContent = "Downloading OSM map";
                } else if (job.partition && job.partition.phase === "merging") {
                    statusText.textContent = "Merging OSM partitions";
                }
                showProgress(job);
                if (job.state === "completed") {
                    if (job.download_url) {
                        const link = document.createElement("a");
                        link.href = job.download_url;
                        link.download = "osm.zip";
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }
                    setBuildState(false, "Scenario completed");
                    return;
                }
                if (job.state === "failed") {
                    setBuildState(false, "Build failed: " + (job.error || "Unknown error"));
                    return;
                }
            } catch (error) {
                if (signal.aborted) return;
                if (++failures >= 5) {
                    setBuildState(false, "Cannot reach the server: " + error.message);
                    return;
                }
            }
            await new Promise(resolve => setTimeout(resolve, 1500));
        }
    }

    /**
     * @function
     * submit scenario data to the HTTP API
     */
    async function startBuild(){
        const bounds = map.getBounds();
        const cor = {
            left: bounds.getWest(), right: bounds.getEast(),
            top: bounds.getNorth(), bottom: bounds.getSouth()
        };

        var data = {
            poly: elem("#polygons").checked,
            tileSizeKm: Number(elem("#tile-size-km").value),
            osmSource: sourceChoice.value,
            ...(sourceChoice.value === "pbf" ? {pbfPath: elem("#pbf-path").value.trim()} : {}),
            duration: parseInt(elem("#duration").value),
            publicTransport: false, //elem("#publicTransport").checked,
            leftHand: elem("#leftHand").checked,
            decal: elem("#decal").checked,
            carOnlyNetwork: elem("#carOnlyNetwork").checked,
            vehicles: {},
            roadTypes:{}                                                            // sab-inf
        };

        // calculates the coordinates of the rectangle if area-picking is active
        if(canvasActive){
            var width = cor.right - cor.left;
            var height = cor.bottom - cor.top;
            data.coords = [
                cor.left + width * canvasRect[0],
                cor.top + height * canvasRect[3],
                cor.left + width * canvasRect[2],
                cor.top + height * canvasRect[1]
            ];
        } else
            data.coords = [cor.left, cor.bottom, cor.right, cor.top];
        
        roadClasses.forEach(function(roadType){
            var result = roadType.getEnabledTypeList();
            if(result){
                // in OSM "pedestrians" have also the key "highway", therefore we prepare the data accordingly
                if(roadType.category == "Pedestrians" || roadType.category == "Highway"){
                    try{
                        data.roadTypes["Highway"] = data.roadTypes["Highway"].concat(result);
                    }catch (e){
                        if (e instanceof TypeError) {
                            data.roadTypes["Highway"] = result;
                        }
                    }
                }else
                    data.roadTypes[roadType.category] = result;
            }
        });

        if (activeJob) return;
        if (data.osmSource === "pbf" && !data.pbfPath) {
            setBuildState(false, "Please enter the local .osm.pbf path on the V2Sim computer.");
            return;
        }
        setBuildState(true, "Submitting scenario…");
        progressBar.style.width = "0%";
        partitionCount.hidden = true;
        partitionCount.textContent = "";
        progressDetail.textContent = "Submitting scenario…";
        progressTrack.classList.add("indeterminate");
        progressTrack.classList.remove("failed");
        try {
            const result = await apiJSON("/api/build", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(data)
            });
            activeJob = result.job_id;
            await watchJob(result.job_id);
        } catch (error) {
            setBuildState(false, "Build request failed: " + error.message);
        } finally {
            activeJob = null;
        }
    }

    elem("#export-button").addEventListener("click", startBuild);

    // ZIP downloads now use the authenticated same-origin HTTP endpoint.
});
