(function () {
    var COLORS = [
        "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
        "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
    ];

    function applyFilters() {
        var allFlights = window.allFlights || [];
        var topN = window.chartTopN || 5;

        var stopsEl = document.getElementById("filter-stops");
        var durationEl = document.getElementById("filter-duration");
        if (!stopsEl || !durationEl) return;

        var maxStops = stopsEl.value === "" ? Infinity : parseInt(stopsEl.value, 10);
        var maxDuration = parseInt(durationEl.value, 10);

        var airlineCheckboxes = document.querySelectorAll(".filter-airline");
        var selectedAirlines = null;
        if (airlineCheckboxes.length > 0) {
            selectedAirlines = new Set();
            airlineCheckboxes.forEach(function (cb) {
                if (cb.checked) selectedAirlines.add(cb.value);
            });
        }

        function passes(f) {
            var stopsOk = (f.stops == null) || f.stops <= maxStops;
            var durationOk = (f.duration_min == null) || f.duration_min <= maxDuration;
            var airlineOk = (selectedAirlines === null) || selectedAirlines.has(f.airline || "");
            return stopsOk && durationOk && airlineOk;
        }

        var survivors = allFlights.filter(passes);
        survivors.sort(function (a, b) { return a.price - b.price; });
        var topSurvivors = survivors.slice(0, topN);

        var colorByKey = {};
        topSurvivors.forEach(function (f, i) {
            colorByKey[f.flight_key] = COLORS[i % COLORS.length];
        });

        var survivorSet = new Set(survivors.map(function (f) { return f.flight_key; }));

        var datasets = topSurvivors.map(function (f, i) {
            return {
                label: f.label,
                color: COLORS[i % COLORS.length],
                data: (f.data || []).map(function (pt) { return { x: pt.x, y: pt.y }; }),
            };
        });

        if (typeof window.renderPriceChart === "function") {
            window.renderPriceChart(datasets);
        }

        document.querySelectorAll("tr[data-flight-key]").forEach(function (row) {
            if (row.classList.contains("row-missing")) return;
            var key = row.getAttribute("data-flight-key");
            row.classList.remove("row-filtered", "row-colored");
            row.style.removeProperty("--row-color");

            if (!survivorSet.has(key)) {
                row.classList.add("row-filtered");
            } else if (colorByKey[key]) {
                row.style.setProperty("--row-color", colorByKey[key]);
                row.classList.add("row-colored");
            }
        });
    }

    function formatDuration(mins) {
        var h = Math.floor(mins / 60);
        var m = mins % 60;
        return h > 0 ? h + "h " + String(m).padStart(2, "0") + "m" : m + "m";
    }

    function init() {
        var stopsEl = document.getElementById("filter-stops");
        var durationEl = document.getElementById("filter-duration");
        var durationLabel = document.getElementById("filter-duration-label");
        var resetBtn = document.getElementById("filter-reset");

        if (!stopsEl || !durationEl) return;

        stopsEl.addEventListener("change", applyFilters);

        durationEl.addEventListener("input", function () {
            if (durationLabel) durationLabel.textContent = formatDuration(parseInt(this.value, 10));
            applyFilters();
        });

        document.querySelectorAll(".filter-airline").forEach(function (cb) {
            cb.addEventListener("change", applyFilters);
        });

        if (resetBtn) {
            resetBtn.addEventListener("click", function () {
                stopsEl.value = "";
                durationEl.value = durationEl.max;
                if (durationLabel) durationLabel.textContent = formatDuration(parseInt(durationEl.max, 10));
                document.querySelectorAll(".filter-airline").forEach(function (cb) {
                    cb.checked = true;
                });
                applyFilters();
            });
        }
    }

    document.addEventListener("htmx:afterSwap", init);
    init();
})();
