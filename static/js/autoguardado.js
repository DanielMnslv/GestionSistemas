/* Conserva borradores del formulario en este navegador mientras se trabaja. */
(function () {
    "use strict";

    var PREFIJO = "jano-borrador-v1:";
    var VIGENCIA_MS = 7 * 24 * 60 * 60 * 1000;
    var EXCLUIDOS = /(password|contrase|clave|secret|token|credential|licencia|firma|csrf|api[_-]?key)/i;
    var TIPOS = ["text", "search", "email", "tel", "url", "number", "date", "datetime-local", "time", "checkbox", "radio"];
    var temporizadorAviso;

    function mostrarAviso(texto) {
        var aviso = document.getElementById("jano-autoguardado-aviso");
        if (!aviso) {
            aviso = document.createElement("div");
            aviso.id = "jano-autoguardado-aviso";
            aviso.className = "jx-autoguardado-aviso";
            aviso.setAttribute("role", "status");
            aviso.setAttribute("aria-live", "polite");
            document.body.appendChild(aviso);
        }
        aviso.textContent = texto;
        aviso.hidden = false;
        window.clearTimeout(temporizadorAviso);
        temporizadorAviso = window.setTimeout(function () {
            aviso.hidden = true;
        }, 2800);
    }

    function esGuardable(campo) {
        if (!campo.name || campo.disabled || EXCLUIDOS.test(campo.name)) return false;
        if (campo.matches('input[type="hidden"], input[type="password"], input[type="file"], input[type="submit"], input[type="button"], input[type="reset"]')) return false;
        if (campo.matches("input") && TIPOS.indexOf(campo.type) < 0) return false;
        return campo.matches("input, textarea, select");
    }

    function controles(formulario) {
        return Array.prototype.slice.call(formulario.querySelectorAll("input, textarea, select")).filter(esGuardable);
    }

    function claveFormulario(formulario) {
        var accion = new URL(formulario.action || window.location.href, window.location.href);
        var usuario = document.body.getAttribute("data-draft-user") || "anon";
        var identificador = formulario.getAttribute("data-borrador") || formulario.id || formulario.name || formulario.className || "formulario";
        return PREFIJO + usuario + ":" + accion.pathname + accion.search + ":" + identificador;
    }

    function leerValores(formulario) {
        var agrupados = {};
        controles(formulario).forEach(function (campo) {
            if (!agrupados[campo.name]) agrupados[campo.name] = [];
            if (campo.type === "checkbox" || campo.type === "radio") {
                if (campo.checked) agrupados[campo.name].push(campo.value);
            } else if (campo.tagName === "SELECT" && campo.multiple) {
                agrupados[campo.name] = Array.prototype.slice.call(campo.selectedOptions).map(function (opcion) { return opcion.value; });
            } else {
                agrupados[campo.name].push(campo.value.slice(0, 20000));
            }
        });
        return agrupados;
    }

    function guardar(formulario, clave, pendiente) {
        try {
            var registro = {
                guardado: Date.now(),
                pendiente: !!pendiente,
                valores: leerValores(formulario),
            };
            var serializado = JSON.stringify(registro);
            if (serializado.length <= 180000) {
                window.localStorage.setItem(clave, serializado);
                return true;
            }
        } catch (error) {
            /* Navegadores privados o almacenamiento lleno: el formulario sigue funcionando. */
        }
        return false;
    }

    function restaurar(formulario, valores) {
        var porNombre = {};
        controles(formulario).forEach(function (campo) {
            if (!porNombre[campo.name]) porNombre[campo.name] = [];
            porNombre[campo.name].push(campo);
        });
        Object.keys(valores || {}).forEach(function (nombre) {
            var lista = porNombre[nombre];
            var guardados = valores[nombre];
            if (!lista || !Array.isArray(guardados)) return;
            lista.forEach(function (campo) {
                if (campo.type === "checkbox" || campo.type === "radio") {
                    campo.checked = guardados.indexOf(campo.value) >= 0;
                } else if (campo.tagName === "SELECT" && campo.multiple) {
                    Array.prototype.forEach.call(campo.options, function (opcion) {
                        opcion.selected = guardados.indexOf(opcion.value) >= 0;
                    });
                } else {
                    campo.value = guardados.length ? guardados[0] : "";
                }
                campo.dispatchEvent(new Event("change", { bubbles: true }));
            });
        });
    }

    function tieneErrores(formulario) {
        return !!formulario.querySelector(".ficha-field-error, .maintenance-form-errors, .errorlist, [aria-invalid='true']");
    }

    function configurar(formulario) {
        if (!formulario || formulario.dataset.autoguardado === "1") return;
        var campos = controles(formulario);
        if (!campos.length) return;
        formulario.dataset.autoguardado = "1";
        var clave = claveFormulario(formulario);
        var borrador = null;

        try {
            borrador = JSON.parse(window.localStorage.getItem(clave) || "null");
        } catch (error) {
            borrador = null;
        }

        if (borrador && Date.now() - borrador.guardado > VIGENCIA_MS) {
            window.localStorage.removeItem(clave);
            borrador = null;
        }

        if (borrador && borrador.pendiente) {
            if (tieneErrores(formulario)) {
                guardar(formulario, clave, false);
            } else {
                window.localStorage.removeItem(clave);
            }
            borrador = null;
        } else if (borrador && borrador.valores) {
            restaurar(formulario, borrador.valores);
            mostrarAviso("Se restauró el borrador guardado en este navegador.");
        }

        var espera;
        function programarGuardado() {
            window.clearTimeout(espera);
            espera = window.setTimeout(function () {
                if (guardar(formulario, clave, false)) {
                    mostrarAviso("Borrador guardado automáticamente.");
                }
            }, 350);
        }

        formulario.addEventListener("input", programarGuardado);
        formulario.addEventListener("change", programarGuardado);
        formulario.addEventListener("submit", function () {
            window.clearTimeout(espera);
            guardar(formulario, clave, true);
        }, true);
    }

    function revisar() {
        document.querySelectorAll("form").forEach(configurar);
    }

    document.addEventListener("DOMContentLoaded", revisar);
    new MutationObserver(revisar).observe(document.documentElement, {
        childList: true,
        subtree: true,
    });
})();
