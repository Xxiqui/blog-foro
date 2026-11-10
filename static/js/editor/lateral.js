/**
 * Barra Lateral: navegación por pestañas y sincronización de vistas previas (Google SERP y Social Card)
 */
import { slugify } from './util.js';

export function initLateral(editorConfig, onFieldChanged) {
    const tabList = document.getElementById('editorTabsList');
    const inputSlug = document.getElementById('inputSlug');
    const btnRegenerarSlug = document.getElementById('btnRegenerarSlug');
    const inputExtracto = document.getElementById('inputExtracto');
    const extractoCount = document.getElementById('extractoCharCount');

    // Restaurar pestaña activa guardada en localStorage
    const ultimaTab = localStorage.getItem('estudio_escritura_active_tab');
    if (ultimaTab && tabList) {
        const tabBtn = tabList.querySelector(`[data-bs-target="${ultimaTab}"]`);
        if (tabBtn) {
            const tabInstance = new bootstrap.Tab(tabBtn);
            tabInstance.show();
        }
    }

    if (tabList) {
        tabList.addEventListener('shown.bs.tab', (e) => {
            const target = e.target.getAttribute('data-bs-target');
            if (target) localStorage.setItem('estudio_escritura_active_tab', target);
        });
    }

    // Soporte para mover el contenido de las pestañas entre sidebar de escritorio y offcanvas móvil
    const content = document.getElementById('editorTabsContent');
    const desktopMount = document.querySelector('.editor-sidebar-content');
    const mobileMount = document.getElementById('mobileTabsMountPoint');

    function ajustarMonturaLateral() {
        if (!content || !desktopMount || !mobileMount) return;
        if (window.innerWidth < 992) {
            if (!mobileMount.contains(content)) {
                mobileMount.appendChild(content);
            }
        } else {
            if (!desktopMount.contains(content)) {
                desktopMount.appendChild(content);
            }
        }
    }
    window.addEventListener('resize', ajustarMonturaLateral);
    ajustarMonturaLateral();

    // Contador de caracteres de extracto
    if (inputExtracto && extractoCount) {
        extractoCount.textContent = inputExtracto.value.length;
        inputExtracto.addEventListener('input', () => {
            extractoCount.textContent = inputExtracto.value.length;
            if (onFieldChanged) onFieldChanged();
        });
    }

    // Regenerar slug desde el título
    if (btnRegenerarSlug && inputSlug) {
        btnRegenerarSlug.addEventListener('click', () => {
            const tituloVal = document.getElementById('editorTitulo')?.value || '';
            const nuevoSlug = slugify(tituloVal);
            if (nuevoSlug) {
                inputSlug.value = nuevoSlug;
                const serpSlug = document.getElementById('serpSlugText');
                if (serpSlug) serpSlug.textContent = nuevoSlug;
                if (onFieldChanged) onFieldChanged();
            }
        });
    }

    if (inputSlug) {
        inputSlug.addEventListener('input', () => {
            const serpSlug = document.getElementById('serpSlugText');
            if (serpSlug) serpSlug.textContent = inputSlug.value || 'tu-slug';
            if (onFieldChanged) onFieldChanged();
        });
    }
}

export function sincronizarPreviews(datos) {
    const titulo = datos.titulo || 'Título de tu artículo';
    const extracto = datos.extracto || datos.extractoFallback || 'El resumen de tu artículo aparecerá aquí tal como lo verán los usuarios en Google y redes sociales.';
    const slug = datos.slug || 'tu-slug';
    const portadaUrl = datos.portadaUrl;

    // SERP Google
    const serpTitle = document.getElementById('serpTitleText');
    const serpSnippet = document.getElementById('serpSnippetText');
    const serpSlug = document.getElementById('serpSlugText');

    if (serpTitle) serpTitle.textContent = `${titulo} - Blog`;
    if (serpSnippet) serpSnippet.textContent = extracto;
    if (serpSlug) serpSlug.textContent = slug;

    // Redes Sociales (Social Card)
    const socTitle = document.getElementById('socialCardTitle');
    const socExcerpt = document.getElementById('socialCardExcerpt');
    const socImg = document.getElementById('socialCardImg');
    const socPlaceholder = document.getElementById('socialCardImgPlaceholder');

    if (socTitle) socTitle.textContent = titulo;
    if (socExcerpt) socExcerpt.textContent = extracto;

    if (socPlaceholder) {
        if (portadaUrl) {
            socPlaceholder.innerHTML = `<img src="${portadaUrl}" alt="Portada" class="w-100 h-100 object-fit-cover" id="socialCardImg">`;
        } else {
            socPlaceholder.innerHTML = `<span class="text-muted small"><i class="bi bi-image me-1"></i>Sin portada</span>`;
        }
    }
}

