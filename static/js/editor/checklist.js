/**
 * Checklist interactivo "Antes de publicar"
 */
import { stripHtml } from './util.js';

export function initChecklist() {
    // Configurar botones "Ir" para saltar al campo o pestaña correspondiente
    document.querySelectorAll('.btn-checklist-jump').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabTarget = btn.getAttribute('data-jump-tab');
            const elementTarget = btn.getAttribute('data-jump-to');

            if (tabTarget) {
                const tabEl = document.getElementById(tabTarget);
                if (tabEl) {
                    const tabInstance = new bootstrap.Tab(tabEl);
                    tabInstance.show();
                }
            }

            if (elementTarget) {
                const el = document.querySelector(elementTarget);
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    setTimeout(() => {
                        if (typeof el.focus === 'function') el.focus();
                    }, 250);
                }
            }
        });
    });
}

export function evaluarChecklist(datos) {
    const titulo = (datos.titulo || '').trim();
    const contenidoPlano = stripHtml(datos.contenido || '').trim();
    const categoriaId = datos.categoria_id;
    const tienePortada = Boolean(datos.portadaUrl);
    const etiquetas = datos.etiquetas || [];
    const extracto = (datos.extracto || '').trim();

    const estado = {
        titulo: titulo.length >= 5 && titulo.length <= 120,
        contenido: contenidoPlano.length >= 100,
        categoria: Boolean(categoriaId),
        portada: tienePortada,
        etiquetas: etiquetas.length > 0,
        extracto: extracto.length > 0
    };

    let completados = 0;
    const total = 6;

    Object.entries(estado).forEach(([clave, cumple]) => {
        const itemLi = document.querySelector(`[data-check-rule="${clave}"]`);
        if (!itemLi) return;

        const icon = itemLi.querySelector('.check-icon');
        const label = itemLi.querySelector('.check-item-label');

        if (cumple) {
            completados++;
            if (icon) icon.className = 'bi bi-check-circle-fill text-success check-icon';
            if (label) label.classList.add('completado');
        } else {
            if (icon) icon.className = 'bi bi-circle text-secondary check-icon';
            if (label) label.classList.remove('completado');
        }
    });

    // Actualizar badge y barra de progreso
    const badge = document.getElementById('checklistScoreBadge');
    const progressBar = document.getElementById('checklistProgressBar');

    if (badge) badge.textContent = `${completados} / ${total}`;
    if (progressBar) {
        const pct = Math.round((completados / total) * 100);
        progressBar.style.width = `${pct}%`;
        progressBar.setAttribute('aria-valuenow', pct);

        if (pct === 100) {
            progressBar.className = 'progress-bar bg-success';
        } else if (pct >= 50) {
            progressBar.className = 'progress-bar bg-primary';
        } else {
            progressBar.className = 'progress-bar bg-warning';
        }
    }

    const pendientesObligatorios = [];
    if (!estado.titulo) pendientesObligatorios.push('Título con al menos 5 caracteres');
    if (!estado.contenido) pendientesObligatorios.push('Contenido con al menos 100 caracteres');
    if (!estado.categoria) pendientesObligatorios.push('Seleccionar una categoría');

    return {
        aptoParaPublicar: pendientesObligatorios.length === 0,
        pendientesObligatorios,
        completados,
        total
    };
}

