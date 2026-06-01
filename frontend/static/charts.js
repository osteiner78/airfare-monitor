var colors = [
    "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
    "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
];

window.renderPriceChart = function (datasets) {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    var noDataEl = canvas.parentNode.querySelector(".no-data-msg");
    if (noDataEl) noDataEl.remove();

    if (!datasets || !datasets.length) {
        var noData = document.createElement("p");
        noData.className = "no-data-msg";
        noData.textContent = "No price data yet";
        noData.style.cssText = "text-align:center;color:#888;padding:2rem 0";
        canvas.parentNode.appendChild(noData);
        return;
    }

    var ctx = canvas.getContext("2d");

    datasets.forEach(function (ds, i) {
        ds.data.forEach(function (point) {
            if (typeof point.x === "string") {
                point.x = new Date(point.x + "Z").getTime();
            }
        });
        ds.borderColor = ds.color || colors[i % colors.length];
        ds.backgroundColor = (ds.color || colors[i % colors.length]) + "20";
        ds.tension = 0.1;
        ds.pointRadius = 3;
        ds.pointHoverRadius = 5;
    });

    new Chart(ctx, {
        type: "line",
        data: {
            datasets: datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    type: "linear",
                    afterBuildTicks: function (scale) {
                        var min = scale.min, max = scale.max;
                        var hr = 3600000;
                        var rangeHours = (max - min) / hr;
                        // Pick a "nice" step that gives roughly 6–12 ticks.
                        var niceSizes = [1, 2, 3, 6, 12, 24, 48, 72];
                        var step = niceSizes[niceSizes.length - 1];
                        for (var i = 0; i < niceSizes.length; i++) {
                            if (rangeHours / niceSizes[i] <= 12) {
                                step = niceSizes[i];
                                break;
                            }
                        }
                        var stepMs = step * hr;
                        // Align to integer UTC hours (works for whole-hour TZ offsets).
                        var first = Math.ceil(min / stepMs) * stepMs;
                        scale.ticks = [];
                        for (var t = first; t <= max; t += stepMs) {
                            scale.ticks.push({ value: t });
                        }
                    },
                    ticks: {
                        callback: function (val) {
                            var d = new Date(val);
                            var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                            return months[d.getMonth()] + " " + d.getDate() + " " +
                                   String(d.getHours()).padStart(2, "0") + ":" +
                                   String(d.getMinutes()).padStart(2, "0");
                        },
                    },
                },
                y: {},
            },
            plugins: {
                legend: {
                    position: "bottom",
                },
                tooltip: {
                    callbacks: {
                        title: function (items) {
                            var d = new Date(items[0].parsed.x);
                            return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
                                   " – " +
                                   d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
                        },
                        label: function (ctx) {
                            var currency = window.chartCurrency || "";
                            return ctx.dataset.label + ": " + currency + Math.round(ctx.parsed.y);
                        },
                    },
                },
            },
        },
    });
};

renderPriceChart(window.chartData || []);
