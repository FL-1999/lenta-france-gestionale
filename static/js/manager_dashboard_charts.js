document.addEventListener("DOMContentLoaded", function () {
  if (!window.managerDashboardData || !window.ApexCharts) return;

  const { reportsLast30Days = [], hoursPerSite30Days = [], reportsByStatus = [] } = window.managerDashboardData;

  const formatNumber = (value, digits = 0) => {
    const numeric = Number(value || 0);
    return new Intl.NumberFormat("it-IT", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(numeric);
  };

  const sum = (items, mapper) => items.reduce((acc, item) => acc + Number(mapper(item) || 0), 0);

  const totalReports30 = sum(reportsLast30Days, (item) => item.count);
  const totalHours30 = sum(hoursPerSite30Days, (item) => item.hours);
  const totalStatus = sum(reportsByStatus, (item) => item.count);
  const closedCount = sum(
    reportsByStatus.filter((item) => String(item.status || "").toLowerCase().includes("chius")),
    (item) => item.count,
  );
  const closedPct = totalStatus > 0 ? (closedCount / totalStatus) * 100 : 0;

  const reportsKpi = document.getElementById("kpiReports30Days");
  const hoursKpi = document.getElementById("kpiHours30Days");
  const closedKpi = document.getElementById("kpiClosedReportsPct");

  if (reportsKpi) reportsKpi.textContent = formatNumber(totalReports30);
  if (hoursKpi) hoursKpi.textContent = `${formatNumber(totalHours30, 1)} h`;
  if (closedKpi) closedKpi.textContent = `${formatNumber(closedPct, 1)}%`;

  const palette = {
    primary: "#7c8dff",
    secondary: "#38bdf8",
    success: "#34d399",
    danger: "#fb7185",
    glow: "rgba(124, 141, 255, 0.35)",
    grid: "rgba(148, 163, 184, 0.18)",
    text: "#dbe5f5",
    muted: "#94a3b8",
  };

  const baseChartOptions = {
    chart: {
      toolbar: { show: false },
      zoom: { enabled: false },
      foreColor: palette.text,
      animations: {
        enabled: true,
        easing: "easeinout",
        speed: 700,
      },
    },
    grid: {
      borderColor: palette.grid,
      strokeDashArray: 4,
    },
    dataLabels: { enabled: false },
    legend: {
      labels: { colors: palette.text },
    },
    tooltip: {
      theme: "dark",
    },
  };

  const reportsTarget = document.getElementById("chartReportsLast30Days");
  if (reportsTarget && reportsLast30Days.length) {
    const labels = reportsLast30Days.map((item) => item.date_label || item.date);
    const values = reportsLast30Days.map((item) => Number(item.count || 0));

    const reportsChart = new ApexCharts(reportsTarget, {
      ...baseChartOptions,
      chart: {
        ...baseChartOptions.chart,
        type: "area",
        height: 290,
        dropShadow: {
          enabled: true,
          top: 6,
          left: 0,
          blur: 8,
          color: palette.primary,
          opacity: 0.26,
        },
      },
      series: [
        {
          name: "Rapportini",
          data: values,
        },
      ],
      stroke: {
        width: 4,
        curve: "smooth",
        lineCap: "round",
      },
      fill: {
        type: "gradient",
        gradient: {
          shadeIntensity: 1,
          opacityFrom: 0.5,
          opacityTo: 0.08,
          stops: [0, 100],
        },
      },
      colors: [palette.primary],
      xaxis: {
        categories: labels,
        labels: {
          rotate: -45,
          style: { colors: palette.muted },
        },
        axisBorder: { color: palette.grid },
      },
      yaxis: {
        min: 0,
        forceNiceScale: true,
        labels: {
          style: { colors: palette.muted },
          formatter: (val) => formatNumber(val),
        },
      },
      markers: {
        size: 3,
        hover: { size: 6 },
        colors: ["#0f172a"],
        strokeColors: [palette.primary],
      },
    });

    reportsChart.render();
  }

  const hoursTarget = document.getElementById("chartHoursPerSite");
  if (hoursTarget && hoursPerSite30Days.length) {
    const maxSites = 10;
    const sortedSites = [...hoursPerSite30Days]
      .sort((a, b) => Number(b.hours || 0) - Number(a.hours || 0))
      .slice(0, maxSites);

    const labels = sortedSites.map((item) => item.site_name || "Cantiere");
    const values = sortedSites.map((item) => Number(item.hours || 0));

    const hoursChart = new ApexCharts(hoursTarget, {
      ...baseChartOptions,
      chart: {
        ...baseChartOptions.chart,
        type: "bar",
        height: 290,
      },
      series: [
        {
          name: "Ore",
          data: values,
        },
      ],
      plotOptions: {
        bar: {
          horizontal: true,
          borderRadius: 7,
          borderRadiusApplication: "end",
          barHeight: "58%",
          distributed: false,
          colors: {
            backgroundBarColors: ["rgba(15, 23, 42, 0.5)"],
            backgroundBarRadius: 7,
          },
        },
      },
      fill: {
        type: "gradient",
        gradient: {
          type: "horizontal",
          shadeIntensity: 0.8,
          gradientToColors: ["#67e8f9"],
          opacityFrom: 0.95,
          opacityTo: 0.75,
          stops: [0, 100],
        },
      },
      colors: [palette.secondary],
      xaxis: {
        labels: {
          style: { colors: palette.muted },
          formatter: (val) => `${formatNumber(val)} h`,
        },
        axisBorder: { color: palette.grid },
      },
      yaxis: {
        categories: labels,
        labels: {
          style: { colors: palette.text },
          maxWidth: 220,
        },
      },
      tooltip: {
        theme: "dark",
        y: {
          formatter: (value) => `${formatNumber(value, 1)} ore`,
        },
      },
    });

    hoursChart.render();
  }

  const statusTarget = document.getElementById("chartReportsByStatus");
  if (statusTarget && reportsByStatus.length) {
    const labels = reportsByStatus.map((item) => item.status || "Stato");
    const values = reportsByStatus.map((item) => Number(item.count || 0));

    const statusChart = new ApexCharts(statusTarget, {
      ...baseChartOptions,
      chart: {
        ...baseChartOptions.chart,
        type: "donut",
        height: 290,
      },
      labels,
      series: values,
      colors: [palette.danger, palette.success, "#22d3ee"].slice(0, values.length),
      stroke: {
        width: 0,
      },
      plotOptions: {
        pie: {
          donut: {
            size: "66%",
            labels: {
              show: true,
              name: {
                show: true,
                color: palette.muted,
              },
              value: {
                show: true,
                color: palette.text,
                formatter: (value) => formatNumber(value),
              },
              total: {
                show: true,
                label: "Totale",
                color: palette.muted,
                formatter: () => formatNumber(totalStatus),
              },
            },
          },
        },
      },
      legend: {
        position: "bottom",
        fontSize: "13px",
        itemMargin: { horizontal: 12, vertical: 6 },
        labels: { colors: palette.text },
      },
      dataLabels: {
        enabled: true,
        formatter: (val) => `${val.toFixed(1)}%`,
        style: {
          fontSize: "12px",
          fontWeight: 600,
        },
      },
      tooltip: {
        y: {
          formatter: (value) => `${formatNumber(value)} rapportini`,
        },
      },
    });

    statusChart.render();
  }
});
