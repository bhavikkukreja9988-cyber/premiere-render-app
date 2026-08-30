/*
 * PremiereRenderAgent.jsx  --  Premiere Render App agent for Adobe Media Encoder
 * ---------------------------------------------------------------------------
 * Installed into:
 *   %APPDATA%\Adobe\Startup Scripts CC\Adobe Media Encoder\PremiereRenderAgent.jsx
 *
 * Media Encoder runs startup scripts automatically when it launches. This agent
 * polls a queue folder for job files written by the Python app, adds each job to
 * the AME batch, starts it, and reports state back through status files.
 *
 * Job and status files use a flat key=value format on purpose: ExtendScript has
 * no JSON parser, and Windows paths inside JS string literals are a
 * backslash-escaping minefield. Paths are always written with forward slashes.
 *
 * Queue file   <userData>/PremiereRenderApp/ame/queue/<job_id>.job
 *   job_id=...    project=...   sequence=...   preset=...   output=...
 *
 * Status file  <userData>/PremiereRenderApp/ame/status/<job_id>.status
 *   state=accepted|rendering|complete|error   progress=0..1
 *   output=...    message=...   updated=<ms since epoch>
 *
 * NOTE: Adobe requires "Allow Scripts to Write Files and Access Network" to be
 * enabled in Media Encoder > Preferences > General for this agent to work.
 */

var PRA = (function () {
    var AGENT_VERSION = "2.0.0";
    var POLL_MS = 2000;

    var base = String(Folder.userData.fsName).replace(/\\/g, "/") +
               "/PremiereRenderApp/ame";
    var queuePath = base + "/queue";
    var statusPath = base + "/status";
    var logPath = base + "/agent.log";

    var active = null;      // job object currently in the encoder
    var handled = {};       // job ids already picked up
    var listenersBound = false;

    function ensureDirs() {
        var dirs = [base, queuePath, statusPath];
        for (var i = 0; i < dirs.length; i++) {
            var folder = new Folder(dirs[i]);
            if (!folder.exists) { folder.create(); }
        }
    }

    function log(message) {
        try {
            var file = new File(logPath);
            file.encoding = "UTF-8";
            if (file.open("a")) {
                file.writeln("[" + new Date().toTimeString().substr(0, 8) + "] " +
                             message);
                file.close();
            }
        } catch (e) { /* logging must never throw */ }
    }

    function writeText(path, text) {
        try {
            var file = new File(path);
            file.encoding = "UTF-8";
            if (file.open("w")) {
                file.write(text);
                file.close();
                return true;
            }
        } catch (e) { log("write failed: " + path + " -> " + e); }
        return false;
    }

    function readText(path) {
        try {
            var file = new File(path);
            if (!file.exists) { return null; }
            file.encoding = "UTF-8";
            if (file.open("r")) {
                var content = file.read();
                file.close();
                return content;
            }
        } catch (e) { log("read failed: " + path + " -> " + e); }
        return null;
    }

    function parseKeyValues(text) {
        var result = {};
        if (!text) { return result; }
        var lines = text.split(/\r\n|\r|\n/);
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var eq = line.indexOf("=");
            if (eq <= 0) { continue; }
            var key = line.substring(0, eq);
            var value = line.substring(eq + 1);
            result[key] = value;
        }
        return result;
    }

    function setStatus(jobId, state, fields) {
        if (!jobId) { return; }
        var lines = ["job_id=" + jobId,
                     "state=" + state,
                     "agent=" + AGENT_VERSION,
                     "updated=" + new Date().getTime()];
        if (fields) {
            for (var key in fields) {
                if (fields.hasOwnProperty(key)) {
                    lines.push(key + "=" + String(fields[key]).replace(/[\r\n]/g, " "));
                }
            }
        }
        writeText(statusPath + "/" + jobId + ".status", lines.join("\n") + "\n");
    }

    function finish(state, fields) {
        if (!active) { return; }
        setStatus(active.job_id, state, fields);
        log("job " + active.job_id + " -> " + state);
        active = null;
    }

    function bindListeners() {
        if (listenersBound) { return; }
        var host = null;
        try { host = app.getEncoderHost(); } catch (e) { log("no encoder host: " + e); }
        if (!host) { return; }

        function on(eventName, handler) {
            try { host.addEventListener(eventName, handler); }
            catch (e) { log("listener " + eventName + " unavailable"); }
        }

        on("onEncodeComplete", function (event) {
            finish("complete", { output: active ? active.output : "",
                                 message: "media encoder reported completion" });
        });
        on("onEncodeError", function (event) {
            finish("error", { message: "media encoder reported an error" });
        });
        on("onEncodeProgress", function (event) {
            if (!active) { return; }
            var value = 0;
            try { value = Number(event.result) || 0; } catch (e) { value = 0; }
            if (value > 1) { value = value / 100.0; }
            setStatus(active.job_id, "rendering",
                      { progress: value, output: active.output });
        });
        on("onItemEncodingStarted", function (event) {
            if (active) {
                setStatus(active.job_id, "rendering",
                          { progress: 0, output: active.output,
                            message: "encoding started" });
            }
        });
        on("onBatchItemStatusChanged", function (event) { /* informational */ });

        listenersBound = true;
        log("agent " + AGENT_VERSION + " listeners bound");
    }

    function submit(job) {
        var frontend = null;
        try { frontend = app.getFrontend(); } catch (e) { frontend = null; }
        if (!frontend) {
            setStatus(job.job_id, "error", { message: "no AME frontend available" });
            return false;
        }

        var added = false;
        // Dynamic Link path: renders a named sequence straight out of the project.
        if (job.sequence) {
            try {
                added = frontend.addDLToBatch(job.project, job.preset,
                                              job.sequence, job.output);
            } catch (e) {
                log("addDLToBatch failed: " + e);
                added = false;
            }
        }
        // Fallback: let AME open the project and use its default sequence.
        if (!added) {
            try {
                added = frontend.addFileToBatch(job.project, job.preset, job.output);
            } catch (e) {
                log("addFileToBatch failed: " + e);
                added = false;
            }
        }
        if (!added) {
            setStatus(job.job_id, "error",
                      { message: "media encoder refused the job (check preset, " +
                                 "sequence name and project path)" });
            return false;
        }

        active = job;
        setStatus(job.job_id, "accepted", { output: job.output, progress: 0 });

        // Render unattended: kick the batch off without requiring the operator
        // to click anything, and don't pop any modal dialogs that would steal
        // their focus while they work.
        try {
            if (typeof app.enableQERenderContentMode === "function") {
                app.enableQERenderContentMode();
            }
        } catch (e) { /* not available on all builds */ }
        try {
            frontend.startBatch();
        } catch (e) {
            log("startBatch failed: " + e);
        }
        log("submitted job " + job.job_id + " -> " + job.output);
        return true;
    }

    function claim(file) {
        var text = readText(file.fsName);
        if (!text) { return; }
        var job = parseKeyValues(text);
        if (!job.job_id || !job.project || !job.output) {
            log("ignoring malformed job file: " + file.fsName);
            try { file.remove(); } catch (e) {}
            return;
        }
        handled[job.job_id] = true;
        try { file.remove(); } catch (e) { log("could not remove " + file.fsName); }
        submit(job);
    }

    function poll() {
        try {
            ensureDirs();
            bindListeners();
            if (active) { return; }
            var folder = new Folder(queuePath);
            var files = folder.getFiles("*.job");
            if (!files || files.length === 0) { return; }
            files.sort();
            claim(files[0]);
        } catch (e) {
            log("poll error: " + e);
        }
    }

    function start() {
        ensureDirs();
        log("=== agent " + AGENT_VERSION + " starting, queue=" + queuePath + " ===");
        bindListeners();
        writeText(base + "/agent.alive",
                  "version=" + AGENT_VERSION + "\nstarted=" +
                  new Date().getTime() + "\n");
        if (typeof app.scheduleTask === "function") {
            app.scheduleTask("PRA.poll();", POLL_MS, true);
            log("polling every " + POLL_MS + "ms");
        } else {
            log("app.scheduleTask unavailable - agent cannot poll on this AME build");
        }
        poll();
    }

    return { start: start, poll: poll, version: AGENT_VERSION };
})();

PRA.start();
