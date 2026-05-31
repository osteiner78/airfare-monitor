(function () {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    canvas.style.width = "100%";
    canvas.style.height = "300px";

    if (!window.chartData || !window.chartData.length) {
        var ctx = canvas.getContext("2d");
        ctx.font = "14px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillStyle = "#888";
        ctx.textAlign = "center";
        ctx.fillText("No price data yet", 350, 150);
        return;
    }

    var ctx = canvas.getContext("2d");

    var colors = [
        "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
        "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
    ];

    var allLabels = [];

    window.chartData.forEach(function (ds, i) {
        var points = [];
        ds.data.forEach(function (point) {
            var label;
            if (typeof point.x === "string") {
                var t = point.x.replace(" ", "T");
                var d = new Date(t);
                if (!isNaN(d.getTime())) {
                    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
                    label = months[d.getMonth()] + " " + d.getDate() + " " +
                            String(d.getHours()).padStart(2,"0") + ":" +
                            String(d.getMinutes()).padStart(2,"0");
                } else {
                    label = point.x;
                }
            } else {
                label = String(point.x);
            }
            points.push({x: label, y: point.y});
            if (allLabels.indexOf(label) === -1) allLabels.push(label);
        });
        ds.data = points;
        ds.borderColor = colors[i % colors.length];
        ds.backgroundColor = colors[i % colors.length] + "20";
        ds.tension = 0.1;
        ds.pointRadius = 3;
        ds.pointHoverRadius = 5;
    });

    allLabels.sort();

    new Chart(ctx, {
        type: "line",
        data: {
            labels: allLabels,
            datasets: window.chartData,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            parsing: {
                xAxisKey: "x",
                yAxisKey: "y",
            },
            scales: {
                x: {
                    type: "category",
                },
                y: {
                    title: {
                        display: true,
                        text: "Price",
                    },
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            return ctx.dataset.label + ": " + ctx.parsed.y;
                        },
                    },
                },
            },
        },
    });
})();
