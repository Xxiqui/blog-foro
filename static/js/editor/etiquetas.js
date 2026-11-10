/**
 * Gestión de Etiquetas: selección por chips, filtrado dinámico y creación AJAX
 */
import { getCsrfToken } from './util.js';

let selectedTagIds = new Set();
let onEtiquetasChangedCallback = null;

export function initEtiquetas(onTagsChanged) {
    onEtiquetasChangedCallback = onTagsChanged;
    const cloud = document.getElementById('editorTagsCloud');
    const inputFiltro = document.getElementById('inputFiltroEtiquetas');
    const btnGuardarModal = document.getElementById('btnGuardarNuevaEtiqueta');
    const inputNuevoNombre = document.getElementById('inputNuevaEtiquetaNombre');
    const errorMsg = document.getElementById('errorNuevaEtiqueta');

    // Inicializar etiquetas que ya están marcadas como activas
    if (cloud) {
        cloud.querySelectorAll('.tag-chip.active').forEach(chip => {
            const id = chip.getAttribute('data-tag-id');
            if (id) selectedTagIds.add(id);
        });
        actualizarContadorEtiquetas();

        cloud.addEventListener('click', (e) => {
            const chip = e.target.closest('.tag-chip');
            if (!chip) return;

            const id = chip.getAttribute('data-tag-id');
            if (!id) return;

            if (selectedTagIds.has(id)) {
                selectedTagIds.delete(id);
                chip.classList.remove('bg-primary', 'text-white', 'border-primary', 'active');
                chip.classList.add('bg-body-secondary', 'text-body', 'border-secondary-subtle');
                chip.setAttribute('aria-pressed', 'false');
            } else {
                selectedTagIds.add(id);
                chip.classList.add('bg-primary', 'text-white', 'border-primary', 'active');
                chip.classList.remove('bg-body-secondary', 'text-body', 'border-secondary-subtle');
                chip.setAttribute('aria-pressed', 'true');
            }

            actualizarContadorEtiquetas();
            if (onEtiquetasChangedCallback) onEtiquetasChangedCallback(Array.from(selectedTagIds));
        });
    }

    // Filtrado en vivo de etiquetas
    if (inputFiltro && cloud) {
        inputFiltro.addEventListener('input', () => {
            const query = inputFiltro.value.trim().toLowerCase();
            cloud.querySelectorAll('.tag-chip').forEach(chip => {
                const name = chip.getAttribute('data-tag-name')?.toLowerCase() || '';
                if (!query || name.includes(query)) {
                    chip.style.display = 'inline-block';
                } else {
                    chip.style.display = 'none';
                }
            });
        });
    }

    // Creación de nueva etiqueta vía AJAX
    if (btnGuardarModal && inputNuevoNombre) {
        btnGuardarModal.addEventListener('click', async () => {
            const nombre = inputNuevoNombre.value.trim();
            if (!nombre) {
                inputNuevoNombre.focus();
                return;
            }

            if (errorMsg) errorMsg.classList.add('d-none');
            btnGuardarModal.disabled = true;

            try {
                const resp = await fetch('/panel/api/etiqueta/crear/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ nombre: nombre })
                });

                const data = await resp.json();
                if (data.ok && data.etiqueta) {
                    const tag = data.etiqueta;
                    agregarChipAlCloud(tag.id, tag.nombre, true);
                    inputNuevoNombre.value = '';

                    // Cerrar modal
                    const modalEl = document.getElementById('modalNuevaEtiqueta');
                    const modalInstance = bootstrap.Modal.getInstance(modalEl);
                    if (modalInstance) modalInstance.hide();
                } else {
                    if (errorMsg) {
                        errorMsg.textContent = data.error || 'No se pudo crear la etiqueta.';
                        errorMsg.classList.remove('d-none');
                    }
                }
            } catch (err) {
                console.error('Error al crear etiqueta:', err);
                if (errorMsg) {
                    errorMsg.textContent = 'Error de conexión.';
                    errorMsg.classList.remove('d-none');
                }
            } finally {
                btnGuardarModal.disabled = false;
            }
        });
    }
}

function agregarChipAlCloud(id, nombre, seleccionar = true) {
    const cloud = document.getElementById('editorTagsCloud');
    if (!cloud) return;

    let chip = cloud.querySelector(`[data-tag-id="${id}"]`);
    if (!chip) {
        chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'badge rounded-pill border tag-chip transition-all bg-body-secondary text-body border-secondary-subtle';
        chip.setAttribute('data-tag-id', id);
        chip.setAttribute('data-tag-name', nombre);
        chip.textContent = `#${nombre}`;
        cloud.prepend(chip);
    }

    if (seleccionar) {
        selectedTagIds.add(String(id));
        chip.classList.add('bg-primary', 'text-white', 'border-primary', 'active');
        chip.classList.remove('bg-body-secondary', 'text-body', 'border-secondary-subtle');
        chip.setAttribute('aria-pressed', 'true');
        actualizarContadorEtiquetas();
        if (onEtiquetasChangedCallback) onEtiquetasChangedCallback(Array.from(selectedTagIds));
    }
}

function actualizarContadorEtiquetas() {
    const countEl = document.getElementById('etiquetasSeleccionadasCount');
    if (countEl) countEl.textContent = selectedTagIds.size;
}

export function getSelectedTags() {
    return Array.from(selectedTagIds);
}

