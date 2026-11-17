/*
 * SIN USO: ninguna plantilla carga este script. Agrupaba los filtros de los
 * formularios con data-lista-filtros en un panel desplegable con contador.
 */
(function () {
    var formularios = document.querySelectorAll("form[data-lista-filtros]");

    Array.prototype.forEach.call(formularios, function (formulario, indice) {
        var campos = Array.prototype.slice.call(formulario.querySelectorAll(".field"));
        var busqueda = campos.find(function (campo) {
            return campo.querySelector('input[type="search"]');
        });
        var acciones = Array.prototype.slice.call(formulario.querySelectorAll(".actions"));

        if (!campos.length && formulario.classList.contains("assignment-filter")) {
            campos = Array.prototype.filter.call(formulario.children, function (hijo) {
                return hijo.tagName === "DIV";
            });
            campos.forEach(function (campo) { campo.classList.add("field"); });
        }
        if (!campos.length) return;

        formulario.classList.add("lista-filtros-form");
        formulario.classList.add(busqueda ? "lista-filtros-con-busqueda" : "lista-filtros-solo");
        var contenedor = formulario.closest(".mant-filtros, .filter-body, .assignment-panel, .panel");
        if (contenedor) contenedor.classList.add("lista-filtros-host");

        var barra = document.createElement("div");
        barra.className = "lista-filtros-barra";
        var panel = document.createElement("div");
        panel.className = "lista-filtros-panel";
        panel.id = "lista-filtros-" + (indice + 1);
        panel.hidden = true;

        var boton = document.createElement("button");
        boton.type = "button";
        boton.className = "lista-filtros-boton";
        boton.setAttribute("aria-label", "Mostrar filtros");
        boton.setAttribute("aria-expanded", "false");
        boton.setAttribute("aria-controls", panel.id);
        boton.title = "Filtros";
        boton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4"/></svg><span class="solo-lector">Filtros</span>';

        if (busqueda) {
            busqueda.classList.add("lista-filtros-busqueda");
            var etiquetaBusqueda = busqueda.querySelector("label");
            if (etiquetaBusqueda) etiquetaBusqueda.classList.add("solo-lector");
            barra.appendChild(busqueda);

            var iconoBuscar = document.createElement("span");
            iconoBuscar.className = "lista-filtros-buscar-icono";
            iconoBuscar.setAttribute("aria-hidden", "true");
            iconoBuscar.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="m20 20-4-4"/></svg>';
            barra.appendChild(iconoBuscar);
        }
        barra.appendChild(boton);

        campos.forEach(function (campo) {
            if (campo !== busqueda) {
                var etiqueta = campo.querySelector("label");
                if (etiqueta) etiqueta.classList.remove("solo-lector");
                panel.appendChild(campo);
            }
        });

        var contenedorAcciones = document.createElement("div");
        contenedorAcciones.className = "lista-filtros-acciones";
        acciones.forEach(function (grupo) {
            while (grupo.firstChild) contenedorAcciones.appendChild(grupo.firstChild);
            grupo.remove();
        });

        if (!acciones.length && formulario.classList.contains("assignment-filter")) {
            Array.prototype.slice.call(formulario.children).forEach(function (hijo) {
                if (hijo.matches(".assignment-button")) contenedorAcciones.appendChild(hijo);
            });
        }

        if (contenedorAcciones.children.length) panel.appendChild(contenedorAcciones);

        Array.prototype.forEach.call(formulario.querySelectorAll(".mant-mas, .filters"), function (grupo) {
            if (grupo !== formulario) grupo.remove();
        });
        Array.prototype.slice.call(formulario.classList).forEach(function (nombre) {
            if (nombre === "filters" || nombre.indexOf("filters-") === 0) formulario.classList.remove(nombre);
        });

        formulario.insertBefore(panel, formulario.firstChild);
        formulario.insertBefore(barra, panel);

        function contarFiltros() {
            var cantidad = 0;
            Array.prototype.forEach.call(formulario.elements, function (campo) {
                if (campo.disabled || campo.type === "hidden" || campo.type === "submit" || campo.type === "button") return;
                if (campo.tagName === "SELECT") {
                    if (campo.selectedIndex > 0) cantidad++;
                } else if (campo.value && campo.value.trim()) {
                    cantidad++;
                }
            });

            var contador = boton.querySelector(".eq-filtro-n");
            if (cantidad && !contador) {
                contador = document.createElement("span");
                contador.className = "eq-filtro-n";
                boton.appendChild(contador);
            }
            if (contador) {
                if (cantidad) contador.textContent = cantidad;
                else contador.remove();
            }
        }

        function abrir(si) {
            panel.hidden = !si;
            boton.setAttribute("aria-expanded", si ? "true" : "false");
            boton.setAttribute("aria-label", si ? "Ocultar filtros" : "Mostrar filtros");
        }

        boton.addEventListener("click", function () { abrir(panel.hidden); });
        formulario.addEventListener("input", contarFiltros);
        formulario.addEventListener("change", contarFiltros);
        document.addEventListener("click", function (evento) {
            if (!panel.hidden && !panel.contains(evento.target) && !boton.contains(evento.target)) abrir(false);
        });
        document.addEventListener("keydown", function (evento) {
            if (evento.key === "Escape" && !panel.hidden) {
                abrir(false);
                boton.focus();
            }
        });
        contarFiltros();
    });
})();
