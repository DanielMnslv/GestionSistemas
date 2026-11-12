/* Cambio de tema claro / oscuro.
   - La preferencia se guarda en localStorage ("jano-tema": "dark" | "light").
   - Sin preferencia guardada se sigue el tema del sistema operativo.
   - El atributo data-tema de <html> también se fija antes de pintar (script en templates/_estilos.html)
     para que no haya parpadeo; este archivo solo agrega el botón y el cambio manual. */
(function () {
    "use strict";

    var CLAVE = "jano-tema";
    var raiz = document.documentElement;
    var sistema = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

    function leer() {
        try {
            var v = localStorage.getItem(CLAVE);
            return v === "dark" || v === "light" ? v : null;
        } catch (e) {
            return null;
        }
    }

    function guardar(tema) {
        try {
            localStorage.setItem(CLAVE, tema);
        } catch (e) { /* modo privado o almacenamiento bloqueado: el cambio vale solo en esta página */ }
    }

    function actual() {
        return raiz.getAttribute("data-tema") === "dark" ? "dark" : "light";
    }

    function etiquetar() {
        var oscuro = actual() === "dark";
        var texto = oscuro ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
        document.querySelectorAll("[data-tema-toggle]").forEach(function (b) {
            b.setAttribute("title", texto);
            b.setAttribute("aria-label", texto);
            b.setAttribute("aria-pressed", oscuro ? "true" : "false");
        });
    }

    function aplicar(tema) {
        raiz.setAttribute("data-tema", tema);
        etiquetar();
    }

    function alternar() {
        var nuevo = actual() === "dark" ? "light" : "dark";
        guardar(nuevo);
        aplicar(nuevo);
    }

    var ICONOS =
        '<svg class="icono-sol" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/>' +
        '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>' +
        '<svg class="icono-luna" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/></svg>';

    function iniciar() {
        // Páginas sin barra lateral (login, soporte público): botón flotante.
        if (!document.querySelector("[data-tema-toggle]")) {
            var flotante = document.createElement("button");
            flotante.type = "button";
            flotante.className = "tema-boton tema-flotante";
            flotante.setAttribute("data-tema-toggle", "");
            flotante.innerHTML = ICONOS;
            document.body.appendChild(flotante);
        }
        document.querySelectorAll("[data-tema-toggle]").forEach(function (b) {
            b.addEventListener("click", alternar);
        });
        aplicar(actual());
    }

    // Si la persona nunca eligió, seguir los cambios del sistema en vivo.
    if (sistema) {
        var alCambiarSistema = function (e) {
            if (!leer()) aplicar(e.matches ? "dark" : "light");
        };
        if (sistema.addEventListener) sistema.addEventListener("change", alCambiarSistema);
        else if (sistema.addListener) sistema.addListener(alCambiarSistema);
    }

    // Las actas y hojas de vida se imprimen siempre en claro, aunque se pida desde el tema oscuro.
    var temaAntesDeImprimir = null;
    window.addEventListener("beforeprint", function () {
        temaAntesDeImprimir = raiz.getAttribute("data-tema");
        raiz.setAttribute("data-tema", "light");
    });
    window.addEventListener("afterprint", function () {
        if (temaAntesDeImprimir) raiz.setAttribute("data-tema", temaAntesDeImprimir);
        temaAntesDeImprimir = null;
    });

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
    else iniciar();
})();
