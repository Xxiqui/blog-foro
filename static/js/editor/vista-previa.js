/**
 * Modal de Vista Previa en Vivo y Simulación Multidispositivo
 */
import { getCsrfToken } from './util.js';

let temaIframe = 'light';

export function initVistaPrevia(getDataFn) {
    const modalEl = document.getElementById('modalVistaPrevia');
    const iframe = document.getElementById('iframeVistaPrevia');
    const overlay = document.getElementById('previewSpinnerOverlay');
    const btnToggleTheme = document.getElementById('btnPreviewToggleTheme');
    const themeIcon = document.getElementById('previewThemeIcon');

    if (!modalEl || !iframe) return;

    // Viewport switcher
    const viewportBtns = modalEl.querySelectorAll('[data-viewport]');
    viewportBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            viewportBtns.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');

            const vp = btn.getAttribute('data-viewport');
            if (vp === 'mobile') {
                iframe.style.maxWidth = '375px';
            } else if (vp === 'tablet') {
                iframe.style.maxWidth = '768px';
            } else {
                iframe.style.maxWidth = '1200px';
            }
        });
    });

    // Alternador de tema en la vista previa
    if (btnToggleTheme) {
        btnToggleTheme.addEventListener('click', () => {
            temaIframe = temaIframe === 'dark' ? 'light' : 'dark';
            aplicarTemaIframe(iframe, temaIframe);
            if (themeIcon) {
                themeIcon.className = temaIframe === 'dark' ? 'bi bi-sun-fill text-warning' : 'bi bi-moon-stars';
            }
        });
    }

    // Al abrir el modal, solicitar renderizado a la API (por defecto en ancho móvil)
    modalEl.addEventListener('show.bs.modal', async () => {
        if (overlay) overlay.classList.remove('d-none');

        const btnMobile = modalEl.querySelector('[data-viewport="mobile"]');
        if (btnMobile) {
            btnMobile.click();
        }

        const datos = getDataFn();
        try {
            const resp = await fetch('/panel/api/vista-previa/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    titulo: datos.titulo || 'Artículo sin título',
                    contenido: datos.contenido || '',
                    extracto: datos.extracto || '',
                    categoria_id: datos.categoria_id || null,
                    portada_url: datos.portadaUrl || ''
                })
            });

            const data = await resp.json();
            if (data.ok && data.html) {
                renderizarEnIframe(iframe, data.html);
            } else {
                renderizarEnIframe(iframe, `<div class="p-4 text-danger">Error: ${data.error || 'No se pudo generar la vista previa.'}</div>`);
            }
        } catch (err) {
            console.error('Error generando vista previa:', err);
            renderizarEnIframe(iframe, '<div class="p-4 text-danger">Error de conexión al generar la vista previa.</div>');
        } finally {
            if (overlay) overlay.classList.add('d-none');
        }
    });
}

function renderizarEnIframe(iframe, contenidoHtml) {
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(`
        <!DOCTYPE html>
        <html lang="es" data-bs-theme="${temaIframe}">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
            <link rel="stylesheet" href="/static/css/estilos.css">
            <style>
                body { padding: 1.5rem; background-color: var(--bs-body-bg); color: var(--bs-body-color); }
            </style>
        </head>
        <body>
            <div class="container" style="max-width: 820px;">
                ${contenidoHtml}
            </div>
        </body>
        </html>
    `);
    doc.close();
}

function aplicarTemaIframe(iframe, tema) {
    try {
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        if (doc && doc.documentElement) {
            doc.documentElement.setAttribute('data-bs-theme', tema);
        }
    } catch (_) {}
}

