/*
 * Ventana «Transferir componentes» de un radio: abre el <dialog> del botón
 * [data-abrir-transferencia], muestra la vista previa del radio destino y
 * habilita «Confirmar». OJO: hoy ninguna plantilla carga este script, así que
 * el botón de equipos_lista.html no abre la ventana (ver docs/GUIA_DEL_CODIGO.md).
 */
(function () {
    var activadorPorModal = new WeakMap();

    function actualizarPrevia(modal) {
        var selector = modal.querySelector("[data-radio-destino]");
        var previa = modal.querySelector("[data-transferencia-previa] p");
        var lista = modal.querySelector("[data-transferencia-lista]");
        var confirmar = modal.querySelector("[data-transferencia-confirmar]");
        if (!selector || !previa || !lista || !confirmar) return;

        var opcion = selector.options[selector.selectedIndex];
        var componentes = opcion && opcion.dataset.componentes
            ? JSON.parse(opcion.dataset.componentes)
            : [];
        lista.replaceChildren();
        componentes.forEach(function (componente) {
            var elemento = document.createElement("li");
            elemento.textContent = componente.cantidad > 1
                ? componente.nombre + " · " + componente.cantidad + " unidades"
                : componente.nombre;
            lista.appendChild(elemento);
        });
        lista.hidden = componentes.length === 0;
        previa.textContent = componentes.length
            ? "Se retirarán del radio actual y quedarán registrados en el historial."
            : "Selecciona un radio destino para ver los componentes faltantes.";
        confirmar.disabled = componentes.length === 0;
    }

    document.addEventListener("click", function (evento) {
        var abrir = evento.target.closest("[data-abrir-transferencia]");
        if (abrir) {
            var modalId = abrir.getAttribute("data-abrir-transferencia");
            var modal = document.getElementById(modalId);
            if (!modal) return;
            activadorPorModal.set(modal, abrir);
            actualizarPrevia(modal);
            modal.showModal();
            var selector = modal.querySelector("[data-radio-destino]");
            if (selector) selector.focus();
            return;
        }

        var cerrar = evento.target.closest("[data-cerrar-transferencia]");
        var dialogo = cerrar
            ? cerrar.closest("dialog")
            : evento.target.matches("dialog.rd-transferencia-modal")
                ? evento.target
                : null;
        if (dialogo && dialogo.open) dialogo.close();
    });

    document.addEventListener("change", function (evento) {
        if (!evento.target.matches("[data-radio-destino]")) return;
        actualizarPrevia(evento.target.closest("dialog"));
    });

    document.addEventListener("close", function (evento) {
        var modal = evento.target;
        if (!modal.matches("dialog.rd-transferencia-modal")) return;
        var activador = activadorPorModal.get(modal);
        if (activador && activador.isConnected) activador.focus();
        actualizarPrevia(modal);
    }, true);
})();
