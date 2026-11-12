/* JANO Inventario: menú lateral, menús desplegables y buscador global. */
(function () {
    "use strict";
    var raiz = document.documentElement;

    function guardar(clave, valor) {
        try { localStorage.setItem(clave, valor); } catch (e) { /* almacenamiento bloqueado */ }
    }

    function cerrarMenus(excepto) {
        document.querySelectorAll("[data-jx-drop]").forEach(function (b) {
            if (b === excepto) return;
            b.setAttribute("aria-expanded", "false");
            var m = b.parentElement.querySelector(".jx-drop-menu");
            if (m) m.hidden = true;
        });
    }

    function iniciar() {
        /* Menú lateral: cajón en celular, reducido a iconos en escritorio. */
        document.querySelectorAll("[data-jx-nav-open]").forEach(function (b) {
            b.addEventListener("click", function () { raiz.classList.add("jx-nav-open"); });
        });
        document.querySelectorAll("[data-jx-nav-close]").forEach(function (b) {
            b.addEventListener("click", function () { raiz.classList.remove("jx-nav-open"); });
        });
        document.querySelectorAll("[data-jx-mini]").forEach(function (b) {
            b.addEventListener("click", function () {
                var mini = raiz.classList.toggle("jx-mini");
                guardar("jano-menu", mini ? "mini" : "normal");
            });
        });

        /* Menús desplegables (Registrar…). */
        document.querySelectorAll("[data-jx-drop]").forEach(function (b) {
            var menu = b.parentElement.querySelector(".jx-drop-menu");
            b.addEventListener("click", function (ev) {
                ev.stopPropagation();
                var abrir = menu.hidden;
                cerrarMenus(b);
                menu.hidden = !abrir;
                b.setAttribute("aria-expanded", abrir ? "true" : "false");
                if (abrir) { var p = menu.querySelector("a,button"); if (p) p.focus(); }
            });
        });
        document.addEventListener("click", function () { cerrarMenus(null); });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") { cerrarMenus(null); raiz.classList.remove("jx-nav-open"); }
        });

        iniciarBuscador();
    }

    /* ---------- Buscador global ---------- */
    function iniciarBuscador() {
        var caja = document.querySelector("[data-jx-search]");
        if (!caja) return;
        var input = caja.querySelector("input");
        var panel = caja.querySelector(".jx-search-res");
        var url = caja.getAttribute("data-url");
        var temporizador = null, ultima = "", activo = -1, controlador = null;

        function items() { return panel.querySelectorAll(".jx-sr-item"); }
        function marcar(i) {
            var lista = items();
            lista.forEach(function (x, k) { x.classList.toggle("is-active", k === i); x.setAttribute("aria-selected", k === i ? "true" : "false"); });
            activo = i;
            if (lista[i]) lista[i].scrollIntoView({ block: "nearest" });
        }
        function mostrar(v) { panel.hidden = !v; input.setAttribute("aria-expanded", v ? "true" : "false"); }
        function el(tag, clase, texto) {
            var e = document.createElement(tag);
            if (clase) e.className = clase;
            if (texto != null) e.textContent = texto;
            return e;
        }

        function pintar(datos) {
            panel.textContent = "";
            activo = -1;
            if (!datos.grupos.length) {
                panel.appendChild(el("div", "jx-sr-empty", "Sin resultados para “" + datos.q + "”."));
            }
            datos.grupos.forEach(function (g) {
                panel.appendChild(el("div", "jx-sr-group", g.titulo));
                g.items.forEach(function (it) {
                    var a = el("a", "jx-sr-item");
                    a.href = it.url;
                    a.setAttribute("role", "option");
                    var t = el("span");
                    t.appendChild(el("b", null, it.titulo));
                    if (it.detalle) t.appendChild(el("small", null, it.detalle));
                    a.appendChild(t);
                    if (it.etiqueta) a.appendChild(el("span", "jx-badge jx-badge-bad no-dot", it.etiqueta));
                    panel.appendChild(a);
                });
            });
            if (datos.todos) {
                var todos = el("a", "jx-sr-all", "Ver todos los equipos que coinciden");
                todos.href = datos.todos;
                panel.appendChild(todos);
            }
            mostrar(true);
        }

        function buscar() {
            var q = input.value.trim();
            if (q.length < 2) { mostrar(false); ultima = ""; return; }
            if (q === ultima) { mostrar(true); return; }
            ultima = q;
            if (controlador) controlador.abort();
            controlador = window.AbortController ? new AbortController() : null;
            fetch(url + "?q=" + encodeURIComponent(q), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
                signal: controlador ? controlador.signal : undefined
            }).then(function (r) { return r.ok ? r.json() : null; })
              .then(function (d) { if (d && d.q === input.value.trim()) pintar(d); })
              .catch(function () { /* búsqueda cancelada o sin conexión */ });
        }

        input.addEventListener("input", function () {
            clearTimeout(temporizador);
            temporizador = setTimeout(buscar, 180);
        });
        input.addEventListener("focus", function () { if (panel.childNodes.length && input.value.trim().length >= 2) mostrar(true); });
        input.addEventListener("keydown", function (ev) {
            var lista = items();
            if (ev.key === "ArrowDown") { ev.preventDefault(); if (lista.length) marcar((activo + 1) % lista.length); }
            else if (ev.key === "ArrowUp") { ev.preventDefault(); if (lista.length) marcar((activo - 1 + lista.length) % lista.length); }
            else if (ev.key === "Enter") {
                ev.preventDefault();
                if (activo >= 0 && lista[activo]) { window.location = lista[activo].href; return; }
                var q = input.value.trim();
                if (q) window.location = (caja.getAttribute("data-todos") || "/inventario/equipos/") + "?estado=todos&q=" + encodeURIComponent(q);
            } else if (ev.key === "Escape") { mostrar(false); input.blur(); }
        });
        caja.addEventListener("click", function (ev) { ev.stopPropagation(); });
        document.addEventListener("click", function () { mostrar(false); });

        /* Ctrl+K o "/" enfocan el buscador desde cualquier pantalla. */
        document.addEventListener("keydown", function (ev) {
            var escribiendo = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "") || (document.activeElement && document.activeElement.isContentEditable);
            if ((ev.key === "k" || ev.key === "K") && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); input.focus(); input.select(); }
            else if (ev.key === "/" && !escribiendo) { ev.preventDefault(); input.focus(); }
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
    else iniciar();
})();
