/**
 * Gestión de la imagen de portada: arrastrar y soltar, subida AJAX y eliminación
 */
import { getCsrfToken } from './util.js';

export function initPortada(editorConfig, onPortadaChanged) {
    const dropzone = document.getElementById('editorCoverDropzone');
    const inputArchivo = document.getElementById('inputPortadaArchivo');
    const wrapperPreview = document.getElementById('editorCoverPreviewWrapper');
    const imgPreview = document.getElementById('editorCoverImg');
    const btnCambiar = document.getElementById('btnCambiarPortada');
    const btnQuitar = document.getElementById('btnQuitarPortada');
    const uploadingState = document.getElementById('editorCoverUploading');
    const dropzoneInner = document.querySelector('.editor-cover-dropzone-inner');

    if (!dropzone || !inputArchivo) return;

    // Abrir selector al hacer clic en el dropzone
    dropzone.addEventListener('click', () => inputArchivo.click());
    if (btnCambiar) btnCambiar.addEventListener('click', () => inputArchivo.click());

    // Accesibilidad por teclado (Enter / Espacio)
    dropzone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputArchivo.click();
        }
    });

    // Eventos Drag and Drop
    ['dragenter', 'dragover'].forEach(eventType => {
        dropzone.addEventListener(eventType, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(eventType => {
        dropzone.addEventListener(eventType, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            procesarArchivo(files[0]);
        }
    });

    inputArchivo.addEventListener('change', () => {
        if (inputArchivo.files && inputArchivo.files.length > 0) {
            procesarArchivo(inputArchivo.files[0]);
        }
    });

    async function procesarArchivo(file) {
        // Validación de tipo
        const formatosValidos = ['image/jpeg', 'image/png', 'image/webp'];
        if (!formatosValidos.includes(file.type)) {
            alert('Formato no compatible. Por favor sube una imagen JPG, PNG o WebP.');
            return;
        }

        // Validación de tamaño (5 MB)
        if (file.size > 5 * 1024 * 1024) {
            alert('La imagen excede el límite máximo permitido de 5 MB.');
            return;
        }

        // Mostrar estado de carga
        if (dropzoneInner) dropzoneInner.classList.add('d-none');
        if (uploadingState) uploadingState.classList.remove('d-none');

        const formData = new FormData();
        formData.append('portada', file);
        if (editorConfig && editorConfig.postId) {
            formData.append('post_id', editorConfig.postId);
        }

        try {
            const resp = await fetch('/panel/api/portada/subir/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            });

            const data = await resp.json();
            if (data.ok && data.url) {
                mostrarPortada(data.url);
                if (onPortadaChanged) onPortadaChanged(data.url);
            } else {
                alert(data.error || 'No se pudo subir la portada.');
            }
        } catch (err) {
            console.error('Error al subir portada:', err);
            alert('Ocurrió un error al subir la imagen. Revisa tu conexión.');
        } finally {
            if (dropzoneInner) dropzoneInner.classList.remove('d-none');
            if (uploadingState) uploadingState.classList.add('d-none');
            inputArchivo.value = '';
        }
    }

    if (btnQuitar) {
        btnQuitar.addEventListener('click', async () => {
            if (!confirm('¿Deseas quitar la portada del artículo?')) return;

            try {
                const resp = await fetch('/panel/api/portada/quitar/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ post_id: editorConfig ? editorConfig.postId : null })
                });

                const data = await resp.json();
                if (data.ok) {
                    quitarPortadaUI();
                    if (onPortadaChanged) onPortadaChanged(null);
                }
            } catch (err) {
                console.error('Error al quitar portada:', err);
            }
        });
    }

    function mostrarPortada(url) {
        if (imgPreview) imgPreview.src = url;
        if (wrapperPreview) wrapperPreview.classList.remove('d-none');
        if (dropzone) dropzone.classList.add('d-none');
    }

    function quitarPortadaUI() {
        if (imgPreview) imgPreview.src = '';
        if (wrapperPreview) wrapperPreview.classList.add('d-none');
        if (dropzone) dropzone.classList.remove('d-none');
    }
}

