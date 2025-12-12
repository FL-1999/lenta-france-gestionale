document.addEventListener("DOMContentLoaded", function () {
  if (!window.managerDashboardData) return;

  const { reportsLast30Days = [], hoursPerSite30Days = [], reportsByStatus = [] } = window.managerDashboardData;

  const commonScaleOptions = {
    ticks: { color: "#9ca3af" },
    grid: { color: "rgba(55, 65, 81, 0.5)" },
  };

  const commonLegendOptions = {
    labels: { color: "#e5e7eb" },
  };

  const reportsCtx = document.getElementById("chartReportsLast30Days");
  if (reportsCtx) {
    const labels = reportsLast30Days.map((item) => item.date_label || item.date);
    const values = reportsLast30Days.map((item) => item.count || 0);

    new Chart(reportsCtx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Rapportini",
            data: values,
            borderColor: "rgba(129, 140, 248, 1)",
            backgroundColor: "rgba(129, 140, 248, 0.2)",
            tension: 0.25,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: commonScaleOptions,
          y: { ...commonScaleOptions, ticks: { ...commonScaleOptions.ticks, precision: 0 } },
        },
        plugins: {
          legend: commonLegendOptions,
        },
      },
    });
  }

  const hoursCtx = document.getElementById("chartHoursPerSite");
  if (hoursCtx) {
    const labels = hoursPerSite30Days.map((item) => item.site_name);
    const values = hoursPerSite30Days.map((item) => item.hours || 0);

    new Chart(hoursCtx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Ore totali",
            data: values,
            backgroundColor: "rgba(56, 189, 248, 0.7)",
            hoverBackgroundColor: "rgba(56, 189, 248, 1)",
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: commonScaleOptions,
          y: { ...commonScaleOptions, ticks: { ...commonScaleOptions.ticks, precision: 0 } },
        },
        plugins: {
          legend: commonLegendOptions,
        },
      },
    });
  }

  const statusCtx = document.getElementById("chartReportsByStatus");
  if (statusCtx) {
    const labels = reportsByStatus.map((item) => item.status);
    const values = reportsByStatus.map((item) => item.count || 0);

    new Chart(statusCtx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: [
              "rgba(248, 113, 113, 0.8)",
              "rgba(52, 211, 153, 0.8)",
              "rgba(94, 234, 212, 0.8)",
            ].slice(0, labels.length),
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: commonLegendOptions,
        },
      },
    });
  }
});
