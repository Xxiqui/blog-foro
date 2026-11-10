/**
 * Adaptador y sincronizador de CKEditor 5
 */
import { stripHtml, countWords, estimateReadTime } from './util.js';

let editorInstance = null;
const changeListeners = [];

export function initCKEditor(onReady) {
    // Buscar la instancia de CKEditor 5 creada por django-ckeditor-5
    const checkInterval = setInterval(() => {
        const textarea = document.querySelector('textarea[name="contenido"]') || document.querySelector('.django-ckeditor-5');
        if (!textarea) return;

        // django-ckeditor-5 vincula la instancia al elemento o a window.editors
        if (window.editors && Object.keys(window.editors).length > 0) {
            const keys = Object.keys(window.editors);
            editorInstance = window.editors[keys[0]];
        } else if (textarea.ckeditorInstance) {
            editorInstance = textarea.ckeditorInstance;
        }

        if (editorInstance) {
            clearInterval(checkInterval);
            configurarEventosEditor();
            if (onReady) onReady(editorInstance);
        }
    }, 150);

    // Timeout de seguridad por si CKEditor no carga (fallback a textarea plano)
    setTimeout(() => {
        clearInterval(checkInterval);
        if (!editorInstance) {
            const textarea = document.querySelector('textarea[name="contenido"]');
            if (textarea) {
                textarea.addEventListener('input', () => {
                    actualizarMetricas(textarea.value);
                    notificarCambios(textarea.value);
                });
                actualizarMetricas(textarea.value);
            }
        }
    }, 4000);
}

function configurarEventosEditor() {
    if (!editorInstance) return;

    editorInstance.model.document.on('change:data', () => {
        const data = editorInstance.getData();
        actualizarMetricas(data);
        notificarCambios(data);
    });

    // Actualización inicial de métricas
    actualizarMetricas(editorInstance.getData());
}

function actualizarMetricas(htmlContent) {
    const plainText = stripHtml(htmlContent);
    const words = countWords(plainText);
    const readTime = estimateReadTime(words);

    const elWords = document.getElementById('canvasWordCount');
    const elTime = document.getElementById('canvasReadingTime');

    if (elWords) elWords.innerHTML = `<i class="bi bi-file-text me-1" aria-hidden="true"></i>${words} palabras`;
    if (elTime) elTime.innerHTML = `<i class="bi bi-clock me-1" aria-hidden="true"></i>${readTime} min de lectura`;
}

function notificarCambios(content) {
    changeListeners.forEach(listener => listener(content));
}

export function onEditorChange(callback) {
    if (typeof callback === 'function') {
        changeListeners.push(callback);
    }
}

export function getEditorContent() {
    if (editorInstance) {
        return editorInstance.getData();
    }
    const textarea = document.querySelector('textarea[name="contenido"]');
    return textarea ? textarea.value : '';
}

export function setEditorContent(content) {
    if (editorInstance) {
        editorInstance.setData(content || '');
    } else {
        const textarea = document.querySelector('textarea[name="contenido"]');
        if (textarea) textarea.value = content || '';
    }
}

