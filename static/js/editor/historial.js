/**
 * Modal de Historial de Versiones y Restauración
 */
import { getCsrfToken, formatRelativeTime } from './util.js';

let revisionSeleccionadaId = null;

export function initHistorial(editorConfig, onRestaurarExitoso) {
    const modalEl = document.getElementById('modalHistorial');
    const listaContainer = document.getElementById('historialRevisonesList');
    const totalBadge = document.getElementById('historialTotalBadge');
    const detalleVacio = document.getElementById('historialDetalleVacio');
    const detalleContenido = document.getElementById('historialDetalleContenido');
    const btnRestaurar = document.getElementById('btnRestaurarRevision');

    if (!modalEl || !listaContainer) return;

    modalEl.addEventListener('show.bs.modal', async () => {
        const postId = editorConfig ? editorConfig.postId : null;
        if (!postId) {
            listaContainer.innerHTML = '<div class="p-3 text-muted small">Guarda el artículo primero para ver el historial.</div>';
            return;
        }

        listaContainer.innerHTML = `
            <div class="text-center py-4 text-muted small">
                <div class="spinner-border spinner-border-sm text-primary mb-2" role="status"></div>
                <div>Cargando revisiones…</div>
            </div>
        `;

        try {
            const resp = await fetch(`/panel/api/historial/${postId}/`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await resp.json();

            if (data.ok && Array.isArray(data.revisiones)) {
                if (totalBadge) totalBadge.textContent = data.revisiones.length;
                renderizarListaRevisiones(data.revisiones);
            } else {
                listaContainer.innerHTML = '<div class="p-3 text-danger small">No se pudo cargar el historial.</div>';
            }
        } catch (err) {
            console.error('Error cargando historial:', err);
            listaContainer.innerHTML = '<div class="p-3 text-danger small">Error de conexión al cargar revisiones.</div>';
        }
    });

    function renderizarListaRevisiones(revisiones) {
        if (revisiones.length === 0) {
            listaContainer.innerHTML = '<div class="p-3 text-muted small">Aún no hay revisiones registradas.</div>';
            return;
        }

        listaContainer.innerHTML = '';
        revisiones.forEach((rev, idx) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'list-group-item list-group-item-action p-2 text-start small border-bottom';
            item.setAttribute('data-rev-id', rev.id);

            const badgeClase = rev.origen === 'publicacion' ? 'bg-success-subtle text-success'
                             : (rev.origen === 'manual' ? 'bg-primary-subtle text-primary'
                             : (rev.origen === 'restauracion' ? 'bg-warning-subtle text-warning-emphasis'
                             : 'bg-secondary-subtle text-secondary'));

            const fecha = new Date(rev.creado);
            item.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="badge ${badgeClase} rounded-pill">${rev.origen}</span>
                    <span class="text-muted" style="font-size: 0.72rem;">${formatRelativeTime(fecha)}</span>
                </div>
                <div class="fw-semibold text-truncate">${rev.titulo || 'Sin título'}</div>
            `;

            item.addEventListener('click', () => {
                listaContainer.querySelectorAll('.list-group-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                cargarDetalleRevision(rev.id);
            });

            listaContainer.appendChild(item);
        });

        // Seleccionar la primera por defecto
        const primera = listaContainer.querySelector('.list-group-item');
        if (primera) primera.click();
    }

    async function cargarDetalleRevision(revId) {
        revisionSeleccionadaId = revId;
        try {
            const resp = await fetch(`/panel/api/revision/${revId}/`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await resp.json();

            if (data.ok && data.revision) {
                const rev = data.revision;
                if (detalleVacio) detalleVacio.classList.add('d-none');
                if (detalleContenido) detalleContenido.classList.remove('d-none');

                const elOrigen = document.getElementById('revisionDetalleOrigen');
                const elFecha = document.getElementById('revisionDetalleFecha');
                const elTitulo = document.getElementById('revisionDetalleTitulo');
                const elExtractoBox = document.getElementById('revisionDetalleExtractoBox');
                const elExtracto = document.getElementById('revisionDetalleExtracto');
                const elCuerpo = document.getElementById('revisionDetalleCuerpo');

                if (elOrigen) elOrigen.textContent = `Versión: ${rev.origen}`;
                if (elFecha) elFecha.textContent = new Date(rev.creado).toLocaleString('es-ES');
                if (elTitulo) elTitulo.textContent = rev.titulo;

                if (rev.extracto && elExtractoBox && elExtracto) {
                    elExtracto.textContent = rev.extracto;
                    elExtractoBox.classList.remove('d-none');
                } else if (elExtractoBox) {
                    elExtractoBox.classList.add('d-none');
                }

                if (elCuerpo) elCuerpo.innerHTML = rev.contenido;
            }
        } catch (err) {
            console.error('Error cargando detalle de revisión:', err);
        }
    }

    if (btnRestaurar) {
        btnRestaurar.addEventListener('click', async () => {
            if (!revisionSeleccionadaId) return;
            if (!confirm('¿Estás seguro de que deseas restaurar esta versión? Se creará una nueva revisión de respaldo del estado actual.')) return;

            btnRestaurar.disabled = true;
            try {
                const resp = await fetch(`/panel/api/restaurar/${revisionSeleccionadaId}/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                const data = await resp.json();

                if (data.ok && data.revision) {
                    const modalInstance = bootstrap.Modal.getInstance(modalEl);
                    if (modalInstance) modalInstance.hide();

                    if (onRestaurarExitoso) onRestaurarExitoso(data.revision);
                } else {
                    alert(data.error || 'No se pudo restaurar la versión.');
                }
            } catch (err) {
                console.error('Error restaurando versión:', err);
                alert('Error al restaurar la versión.');
            } finally {
                btnRestaurar.disabled = false;
            }
        });
    }
}

