(function () {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    if (!window.chartData || !window.chartData.length) return;

    var ctx = canvas.getContext("2d");

    var colors = [
        "#4a90d9", "#e67e22", "#2ecc71", "#e74c3c", "#9b59b6",
        "#1abc9c", "#f39c12", "#3498db", "#e91e63", "#00bcd4",
    ];

    window.chartData.forEach(function (ds, i) {
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
                    type: "time",
                    time: {
                        unit: "hour",
                        displayFormats: {
                            hour: "MMM d HH:mm",
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
                        label: function (ctx) {
                            return ctx.dataset.label + ": " + ctx.parsed.y;
                        },
                    },
                },
            },
        },
    });
})();
