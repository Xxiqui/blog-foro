/**
 * Atajos de teclado accesibles para el Estudio de Escritura
 */

export function initAtajos(handlers) {
    document.addEventListener('keydown', (e) => {
        const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
        const mod = isMac ? e.metaKey : e.ctrlKey;
        const targetTag = (e.target.tagName || '').toLowerCase();
        const isInInput = targetTag === 'input' || targetTag === 'textarea' || e.target.isContentEditable;

        // 1. Ctrl + S / Cmd + S: Guardar cambios
        if (mod && e.key.toLowerCase() === 's' && !e.shiftKey) {
            e.preventDefault();
            if (handlers.onGuardar) handlers.onGuardar();
            return;
        }

        // 2. Ctrl + Shift + P / Cmd + Shift + P: Publicar / Programar
        if (mod && e.shiftKey && e.key.toLowerCase() === 'p') {
            e.preventDefault();
            if (handlers.onPublicar) handlers.onPublicar();
            return;
        }

        // 3. Ctrl + Shift + F / Cmd + Shift + F: Alternar modo concentración
        if (mod && e.shiftKey && e.key.toLowerCase() === 'f') {
            e.preventDefault();
            if (handlers.onAlternarEnfoque) handlers.onAlternarEnfoque();
            return;
        }

        // 4. Ctrl + Enter / Cmd + Enter: Vista previa
        if (mod && e.key === 'Enter') {
            e.preventDefault();
            if (handlers.onVistaPrevia) handlers.onVistaPrevia();
            return;
        }

        // 5. Esc: Salir de modo enfoque
        if (e.key === 'Escape') {
            if (document.body.classList.contains('focus-mode-active')) {
                e.preventDefault();
                if (handlers.onAlternarEnfoque) handlers.onAlternarEnfoque();
                return;
            }
        }

        // 6. ?: Mostrar ayuda de atajos (cuando no se está escribiendo en un campo)
        if (e.key === '?' && !isInInput) {
            e.preventDefault();
            const modalEl = document.getElementById('modalAtajos');
            if (modalEl) {
                const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.show();
            }
        }
    });
}

