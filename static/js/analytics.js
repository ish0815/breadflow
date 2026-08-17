/* static/js/analytics.js -- Chart.js init for the FR-F1 Analytics page. */

document.addEventListener("DOMContentLoaded", function () {
    var data = window.BREADFLOW_ANALYTICS || {};

    new Chart(document.getElementById("monthly-revenue-chart"), {
        type: "line",
        data: {
            labels: data.monthly_labels,
            datasets: [{
                label: "Revenue",
                data: data.monthly_revenue,
                borderColor: "#2A7F7F",
                backgroundColor: "rgba(42, 127, 127, 0.25)",
                fill: true,
                tension: 0.3,
            }],
        },
        options: { plugins: { legend: { display: false } } },
    });

    new Chart(document.getElementById("top-clients-chart"), {
        type: "bar",
        data: {
            labels: data.top_client_names,
            datasets: [{
                label: "Revenue",
                data: data.top_client_revenue,
                backgroundColor: "#2A7F7F",
            }],
        },
        options: { indexAxis: "y", plugins: { legend: { display: false } } },
    });

    new Chart(document.getElementById("product-units-chart"), {
        type: "bar",
        data: {
            labels: data.product_names,
            datasets: [{
                label: "Units sold",
                data: data.product_units,
                backgroundColor: "#8B5E3C",
            }],
        },
        options: { indexAxis: "y", plugins: { legend: { display: false } } },
    });
});
