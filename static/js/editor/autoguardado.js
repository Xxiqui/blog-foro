/**
 * Módulo de Autoguardado Silencioso y Recuperación Local
 */
import { debounce, getCsrfToken, formatRelativeTime } from './util.js';

let postId = null;
let postSlug = null;
let ultimaVersionTimestamp = null;
let hayCambiosSinGuardar = false;
let timeoutMaximo = null;
let estaGuardando = false;
let config = {};

const LOCAL_STORAGE_KEY_PREFIX = 'estudio_escritura_borrador_';

export function initAutoguardado(editorConfig, getDataFn) {
    config = editorConfig || {};
    postId = config.postId || null;
    postSlug = config.postSlug || null;
    ultimaVersionTimestamp = config.actualizadoEn || new Date().toISOString();

    const indText = document.querySelector('#editorSaveIndicator .save-status-text');
    const indIcon = document.querySelector('#editorSaveIndicator i');
    const elUltimaHora = document.getElementById('editorLastSavedTime');

    // Recuperar borrador local si no tiene cambios en servidor o si falló antes
    comprobarRecuperacionLocal(getDataFn);

    // Advertencia de cierre si hay cambios pendientes
    window.addEventListener('beforeunload', (e) => {
        if (hayCambiosSinGuardar && !estaGuardando) {
            e.preventDefault();
            e.returnValue = 'Tienes cambios no guardados en el artículo.';
            return e.returnValue;
        }
    });

    // Guardado diferido de 3 segundos
    const triggerDebouncedSave = debounce(() => {
        ejecutarGuardado(getDataFn, 'auto');
    }, 3000);

    return {
        marcarModificado: () => {
            hayCambiosSinGuardar = true;
            if (indText) indText.textContent = 'Cambios sin guardar…';
            if (indIcon) indIcon.className = 'bi bi-pencil text-warning';

            // Guardar copia local de emergencia inmediatamente
            guardarEnLocalStorage(getDataFn);

            // Programar guardado al servidor
            triggerDebouncedSave();

            // Límite máximo de 30 segundos sin guardar si el usuario escribe sin pausa
            if (!timeoutMaximo) {
                timeoutMaximo = setTimeout(() => {
                    timeoutMaximo = null;
                    ejecutarGuardado(getDataFn, 'auto');
                }, 30000);
            }
        },
        guardarInmediato: (origen = 'manual') => {
            return ejecutarGuardado(getDataFn, origen);
        },
        limpiarEstadoLocal: () => {
            localStorage.removeItem(LOCAL_STORAGE_KEY_PREFIX + (postId || 'nuevo'));
        }
    };
}

async function ejecutarGuardado(getDataFn, origen = 'auto') {
    if (estaGuardando) return;
    const datos = getDataFn();
    if (!datos.titulo && !datos.contenido) return;

    estaGuardando = true;
    const indText = document.querySelector('#editorSaveIndicator .save-status-text');
    const indIcon = document.querySelector('#editorSaveIndicator i');
    const elUltimaHora = document.getElementById('editorLastSavedTime');

    if (indText) indText.textContent = 'Guardando…';
    if (indIcon) indIcon.className = 'bi bi-arrow-repeat spin text-primary';

    try {
        const payload = {
            post_id: postId,
            slug: datos.slug || postSlug,
            titulo: datos.titulo || '',
            contenido: datos.contenido || '',
            extracto: datos.extracto || '',
            categoria_id: datos.categoria_id || null,
            etiquetas: datos.etiquetas || [],
            ultima_actualizacion_conocida: ultimaVersionTimestamp,
            origen: origen
        };

        const resp = await fetch('/panel/api/autoguardar/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(payload)
        });

        const data = await resp.json();

        if (resp.status === 409) {
            // Conflicto de concurrencia
            if (indText) indText.textContent = 'Conflicto de versiones';
            if (indIcon) indIcon.className = 'bi bi-exclamation-triangle-fill text-danger';
            alert('Atención: este post fue modificado en otra pestaña o sesión. Por seguridad tus cambios se han respaldado localmente.');
            return;
        }

        if (data.ok) {
            postId = data.post_id;
            postSlug = data.slug;
            ultimaVersionTimestamp = data.guardado_en;
            hayCambiosSinGuardar = false;

            if (timeoutMaximo) {
                clearTimeout(timeoutMaximo);
                timeoutMaximo = null;
            }

            // Actualizar URL en el historial si era un post nuevo sin recargar la página
            if (window.location.pathname.includes('/panel/crear/') && postSlug) {
                const nuevaUrl = `/panel/${postSlug}/editar/`;
                window.history.replaceState({}, '', nuevaUrl);
                const btnHistorial = document.getElementById('btnAbrirHistorial');
                if (btnHistorial) btnHistorial.classList.remove('d-none');
            }

            const fecha = new Date(data.guardado_en);
            const horaStr = fecha.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

            if (indText) indText.textContent = `Guardado (${horaStr})`;
            if (indIcon) indIcon.className = 'bi bi-cloud-check text-success';
            if (elUltimaHora) elUltimaHora.textContent = `Último guardado: ${horaStr}`;

            // Limpiar respaldo local obsoleto
            localStorage.removeItem(LOCAL_STORAGE_KEY_PREFIX + (postId || 'nuevo'));
            const offlineBadge = document.getElementById('offlineBackupBadge');
            if (offlineBadge) offlineBadge.style.display = 'none';
        } else {
            throw new Error(data.error || 'Error al guardar');
        }
    } catch (err) {
        console.warn('Fallo en autoguardado:', err);
        if (indText) indText.textContent = 'Sin conexión (guardado local)';
        if (indIcon) indIcon.className = 'bi bi-cloud-slash text-warning';
        guardarEnLocalStorage(getDataFn);
    } finally {
        estaGuardando = false;
    }
}

function guardarEnLocalStorage(getDataFn) {
    try {
        const datos = getDataFn();
        const clave = LOCAL_STORAGE_KEY_PREFIX + (postId || 'nuevo');
        localStorage.setItem(clave, JSON.stringify({
            ...datos,
            guardado_local_en: new Date().toISOString()
        }));
        const offlineBadge = document.getElementById('offlineBackupBadge');
        if (offlineBadge) offlineBadge.style.display = 'inline-flex';
    } catch (_) {}
}

function comprobarRecuperacionLocal(getDataFn) {
    try {
        const clave = LOCAL_STORAGE_KEY_PREFIX + (postId || 'nuevo');
        const respaldo = localStorage.getItem(clave);
        if (!respaldo) return;

        const obj = JSON.parse(respaldo);
        const actual = getDataFn();

        // Si el respaldo tiene título o contenido y el actual está vacío
        if (obj && (!actual.titulo || actual.titulo.trim() === '') && obj.titulo) {
            const fechaStr = new Date(obj.guardado_local_en).toLocaleTimeString('es-ES');
            if (confirm(`Se encontró un borrador local no guardado de las ${fechaStr}. ¿Deseas restaurarlo?`)) {
                const tituloInput = document.getElementById('editorTitulo');
                if (tituloInput && obj.titulo) tituloInput.value = obj.titulo;
                const extractoInput = document.getElementById('inputExtracto');
                if (extractoInput && obj.extracto) extractoInput.value = obj.extracto;
            }
        }
    } catch (_) {}
}

