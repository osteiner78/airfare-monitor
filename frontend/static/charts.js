(function () {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    if (!window.chartData || !window.chartData.length) {
        var noData = document.createElement("p");
        noData.textContent = "No price data yet";
        noData.style.cssText = "text-align:center;color:#888;padding:2rem 0";
        canvas.parentNode.appendChild(noData);
        return;
    }

    var ctx = canvas.getContext("2d");

    var colors = [
        "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
        "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
    ];

    window.chartData.forEach(function (ds, i) {
        ds.data.forEach(function (point) {
            point.x = new Date(point.x).getTime();
        });
        ds.borderColor = colors[i % colors.length];
        ds.backgroundColor = colors[i % colors.length] + "20";
        ds.tension = 0.1;
        ds.pointRadius = 3;
        ds.pointHoverRadius = 5;
    });

    new Chart(ctx, {
        type: "line",
        data: {
            datasets: window.chartData,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    type: "linear",
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
                y: {
                    title: {
                        display: true,
                        text: "Price",
                    },
                },
            },
            plugins: {
                legend: {
                    position: "bottom",
                },
                tooltip: {
                    callbacks: {
                        title: function (items) {
                            var d = new Date(items[0].parsed.x);
                            var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                            return months[d.getMonth()] + " " + d.getDate() + " - " +
                                   String(d.getHours()).padStart(2, "0") + ":" +
                                   String(d.getMinutes()).padStart(2, "0");
                        },
                        label: function (ctx) {
                            return ctx.dataset.label + ": " + ctx.parsed.y;
                        },
                    },
                },
            },
        },
    });
})();
