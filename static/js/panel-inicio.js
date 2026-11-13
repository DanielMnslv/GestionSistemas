/* Panel de inicio: mapa de equipos por sede y mapa de calor.
   Los datos llegan en <script id="pn-datos"> (ver inventario/panel.py). */
(function () {
    "use strict";
    var nodo = document.getElementById("pn-datos");
    if (!nodo) return;
    var D = JSON.parse(nodo.textContent);
    var $ = function (id) { return document.getElementById(id); };
    var NS = "http://www.w3.org/2000/svg";

    function el(tag, attrs, texto, ns) {
        var e = ns ? document.createElementNS(NS, tag) : document.createElement(tag);
        for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
        if (texto != null) e.textContent = texto;
        return e;
    }

    /* ---------- Mapa de calor: mantenimientos por tipo y semana ---------- */
    (function () {
        var g = $("pn-heat"), calor = D.calor || [];
        if (!g || !calor.length) return;
        var n = calor[0].semanas.length, sumas = new Array(n).fill(0);
        g.style.gridTemplateColumns = "92px repeat(" + n + ", 1fr)";
        calor.forEach(function (fila) {
            g.appendChild(el("span", {}, fila.nombre));
            fila.semanas.forEach(function (v, c) {
                sumas[c] += v;
                var a = v ? Math.min(4, Math.ceil(v / 2)) : 0;
                g.appendChild(el("i", { class: a ? "a" + a : "", title: fila.nombre + ": " + v + " mantenimientos" }));
            });
        });
        $("pn-min").textContent = Math.min.apply(null, sumas);
        $("pn-avg").textContent = Math.round(sumas.reduce(function (a, b) { return a + b; }, 0) / n);
        $("pn-max").textContent = Math.max.apply(null, sumas);
    })();

    /* ---------- Mapa: dónde están los equipos, por sede (Leaflet + OpenStreetMap) ---------- */
    (function () {
        var cont = $("pn-map"), M = D.mapa || { puntos: [] }, pts = M.puntos || [];
        if (!cont) return;
        var sin = M.sin_ubicar || { total: 0, puestos: 0 }, bod = M.bodega || { total: 0, malos: 0 };

        function plural(n, uno, varios) { return n + " " + (n === 1 ? uno : varios); }
        function textoTipos(tipos) {
            return (tipos || []).map(function (t) { return t.texto; }).join(", ");
        }
        function pie() {
            var t = [plural(M.total || 0, "equipo", "equipos") + " ubicados en " + plural(pts.length, "lugar", "lugares")];
            if (sin.total) t.push(sin.total + " sin sede registrada (" + textoTipos(sin.tipos) + ")");
            if (bod.total) t.push(plural(bod.total, "radio", "radios") + " en bodega sin asignar" + (bod.malos ? " (" + bod.malos + " dañado" + (bod.malos === 1 ? "" : "s") + ")" : ""));
            $("pn-mp").textContent = t.join(" · ") + ".";
        }
        pie();

        if (typeof L === "undefined") {          /* sin internet: lista simple */
            cont.className = "pn-map-lista";
            if (!pts.length) { cont.textContent = "Todavía no hay equipos con sede."; return; }
            pts.forEach(function (p) {
                cont.appendChild(el("p", {}, (p.lugar || "Ubicación exacta") + ": " + textoTipos(p.tipos) + (p.malos ? " · " + p.malos + " dañados" : "")));
            });
            return;
        }

        var map = L.map(cont, { scrollWheelZoom: false, zoomControl: true }).setView([4.6, -73.5], 6);
        /* OpenStreetMap exige el "Referer"; este sitio no lo envía por defecto, así que se pide en las imágenes. */
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19, referrerPolicy: "origin", attribution: "© OpenStreetMap"
        }).addTo(map);
        function tema() {
            cont.classList.toggle("pn-oscuro", document.documentElement.getAttribute("data-tema") === "dark");
        }
        tema();
        new MutationObserver(tema).observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });
        map.on("click", function () { map.scrollWheelZoom.enable(); });
        cont.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); });

        function popup(p) {
            var d = el("div", { class: "pn-pop" });
            d.appendChild(el("strong", {}, (p.lugar || "Ubicación exacta") + ": " + plural(p.total, "equipo", "equipos")));
            d.appendChild(el("small", {}, textoTipos(p.tipos) + (p.exacta ? "" : " · ubicación aproximada (centro del municipio)")));
            var ul = el("ul");
            p.puestos.forEach(function (x) {
                var li = el("li");
                li.appendChild(el("b", {}, x.nombre));
                li.appendChild(document.createTextNode(": " + (x.tipos.length ? textoTipos(x.tipos) : x.total) + (x.malos ? " (" + x.malos + " dañado" + (x.malos === 1 ? "" : "s") + ")" : "")));
                ul.appendChild(li);
            });
            d.appendChild(ul);
            return d;
        }

        function pin(t, m) {
            var r = Math.round(Math.min(56, 30 + Math.sqrt(t) * 3));
            var n = el("div", { class: "pn-pin" + (m ? " mal" : ""), style: "width:" + r + "px;height:" + r + "px" });
            n.appendChild(el("b", {}, t));
            if (m) n.appendChild(el("i", {}, m));
            return L.divIcon({ html: n, className: "pn-pin-w", iconSize: [r, r], iconAnchor: [r / 2, r / 2] });
        }
        /* Si hay varios lugares muy juntos se agrupan en un solo círculo (suma de equipos) al alejar el mapa. */
        var grupo = typeof L.markerClusterGroup === "function"
            ? L.markerClusterGroup({
                maxClusterRadius: 50, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
                iconCreateFunction: function (c) {
                    var t = 0, m = 0;
                    c.getAllChildMarkers().forEach(function (k) { t += k.options.p.total; m += k.options.p.malos; });
                    return pin(t, m);
                }
            })
            : L.layerGroup();

        var limites = [], marcas = [];
        pts.forEach(function (p) {
            var m = L.marker([p.lat, p.lng], {
                icon: pin(p.total, p.malos), p: p, keyboard: true,
                title: (p.lugar || "Ubicación") + ": " + textoTipos(p.tipos)
            });
            m.bindPopup(function () { return popup(p); }, { maxWidth: 320 });
            grupo.addLayer(m);
            marcas.push(m);
            limites.push([p.lat, p.lng]);
        });
        grupo.addTo(map);

        /* Lista de lugares: un clic lleva al mapa y abre el detalle. */
        var lista = $("pn-lugares"), MAX_LUGARES = 6;   /* el resto se ve en el mapa; así el panel cabe sin scroll */
        if (lista) pts.forEach(function (p, i) {
            if (i >= MAX_LUGARES) return;
            var li = el("li"), b = el("button", { type: "button" });
            b.appendChild(el("span", { class: "pn-lg-n" }, p.lugar || "Ubicación exacta"));
            b.appendChild(el("span", { class: "pn-lg-t" + (p.malos ? " mal" : ""), title: textoTipos(p.tipos) }, p.total + (p.malos ? " · " + p.malos + " dañados" : "")));
            b.addEventListener("click", function () {
                var m = marcas[i];
                if (typeof grupo.zoomToShowLayer === "function") grupo.zoomToShowLayer(m, function () { m.openPopup(); });
                else { map.setView([p.lat, p.lng], 11); m.openPopup(); }
            });
            var barra = el("span", { class: "pn-lg-b" }), rel = el("i");
            rel.style.width = Math.max(4, Math.round(p.total * 100 / (pts[0].total || 1))) + "%";
            barra.appendChild(rel);
            b.appendChild(barra);
            li.appendChild(b);
            lista.appendChild(li);
        });
        if (lista && pts.length > MAX_LUGARES) {
            lista.appendChild(el("li", { class: "pn-lg-mas" }, "+ " + (pts.length - MAX_LUGARES) + " lugares más: búsquelos en el mapa."));
        }
        if (limites.length > 1) map.fitBounds(limites, { padding: [40, 40], maxZoom: 9 });
        else if (limites.length === 1) map.setView(limites[0], 10);
        else $("pn-mp").textContent = "Todavía no hay equipos con sede. " + $("pn-mp").textContent;
        setTimeout(function () { map.invalidateSize(); }, 200);
        /* El mapa ocupa el alto libre de la pantalla: se reajusta si cambia el tamaño de la ventana. */
        var rz; window.addEventListener("resize", function () { clearTimeout(rz); rz = setTimeout(function () { map.invalidateSize(); }, 120); });
    })();
})();
