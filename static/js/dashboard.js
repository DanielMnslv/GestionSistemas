/* Dashboard de inicio: gráficos (Chart.js). Los datos llegan en <script id="pn-datos">. */
(function () {
    "use strict";
    var nodo = document.getElementById("pn-datos");
    if (!nodo || typeof Chart === "undefined") return;
    var D = JSON.parse(nodo.textContent);
    var graficos = [];

    function css(nombre) {
        return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
    }

    function dibujar() {
        graficos.forEach(function (g) { g.destroy(); });
        graficos = [];
        var texto = css("--jx-muted"), linea = css("--jx-line");
        Chart.defaults.font.family = css("--jx-font") || "sans-serif";
        Chart.defaults.color = texto;

        var t = D.tendencia;
        var lienzo = document.getElementById("g-tendencia");
        if (t && lienzo) {
            graficos.push(new Chart(lienzo, {
                type: "bar",
                data: {
                    labels: t.etiquetas,
                    datasets: [
                        { label: "Preventivos", data: t.preventivos, backgroundColor: css("--jx-primary"), borderRadius: 6, maxBarThickness: 34 },
                        { label: "Correctivos y otros", data: t.otros, backgroundColor: css("--jx-lime"), borderRadius: 6, maxBarThickness: 34 }
                    ]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: {
                        legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3 } },
                        tooltip: { callbacks: { footer: function (items) {
                            var s = items.reduce(function (a, i) { return a + i.parsed.y; }, 0);
                            return "Total: " + s;
                        } } }
                    },
                    scales: {
                        x: { stacked: true, grid: { display: false }, border: { display: false } },
                        y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: linea }, border: { display: false } }
                    }
                }
            }));
        }

        var m = D.mantenimiento;
        var dona = document.getElementById("g-semaforo");
        if (m && dona) {
            graficos.push(new Chart(dona, {
                type: "doughnut",
                data: {
                    labels: ["Vencido", "Sin mantenimiento", "Vence en 30 días", "Vigente"],
                    datasets: [{
                        data: m,
                        backgroundColor: [css("--jx-c-bad"), css("--jx-c-none"), css("--jx-c-warn"), css("--jx-c-ok")],
                        borderColor: css("--jx-surface"), borderWidth: 3, hoverOffset: 6
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, cutout: "72%",
                    plugins: { legend: { display: false } }
                }
            }));
        }
    }

    dibujar();
    /* Al cambiar entre modo claro y oscuro se vuelven a pintar con los colores nuevos. */
    new MutationObserver(dibujar).observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });
})();
