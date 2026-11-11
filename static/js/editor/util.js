/**
 * Utilidades compartidas para el Estudio de Escritura
 */

export function debounce(fn, wait = 300) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), wait);
    };
}

export function getCsrfToken() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input && input.value) {
        return input.value;
    }
    const match = document.cookie.match(/csrftoken=([\w-]+)/);
    return match ? match[1] : '';
}

export function stripHtml(html) {
    if (!html) return '';
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
}

export function countWords(text) {
    if (!text) return 0;
    const clean = text.trim();
    if (!clean) return 0;
    const words = clean.split(/\s+/);
    return words.filter(Boolean).length;
}

export function estimateReadTime(wordCount, wpm = 200) {
    if (wordCount <= 0) return 1;
    return Math.max(1, Math.ceil(wordCount / wpm));
}

export function formatReadTime(wordCount, wpm = 200) {
    if (wordCount < 200) return '< 1 min de lectura';
    const minutes = Math.ceil(wordCount / wpm);
    return `${minutes} min de lectura`;
}

export function slugify(text) {
    if (!text) return '';
    return text
        .toString()
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '') // Quita acentos
        .trim()
        .replace(/[^a-z0-9 -]/g, '')     // Quita caracteres no alfanuméricos
        .replace(/\s+/g, '-')            // Espacios a guion
        .replace(/-+/g, '-');           // Colapsa múltiples guiones
}

export function formatRelativeTime(date) {
    const now = new Date();
    const diffSec = Math.floor((now - date) / 1000);
    if (diffSec < 10) return 'hace unos segundos';
    if (diffSec < 60) return `hace ${diffSec} s`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `hace ${diffMin} min`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `hace ${diffHours} h`;
    return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

