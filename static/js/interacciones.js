/**
 * Infraestructura compartida de interacciones (Bloque 0 - Bloque 3)
 * - Helper POST AJAX con CSRF, actualización de botones/contadores, aria-pressed y Toasts de Bootstrap
 * - Redirección a login con ?next= cuando el servidor responde 401
 * - Refresco del contador de notificaciones cada 60s si la pestaña está visible
 * - Botones de compartir (Copiar enlace con "¡Copiado!" y Web Share API)
 * - Autocompletado de menciones @usuario en comentarios
 * - Conmutador de modo claro / oscuro (Bootstrap 5.3 data-bs-theme)
 */

(function () {
    'use strict';

    // 1. Obtener token CSRF desde cookies o input oculto
    function obtenerCsrfToken() {
        const inputCsrf = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (inputCsrf && inputCsrf.value) {
            return inputCsrf.value;
        }
        const nombre = 'csrftoken=';
        const cookies = document.cookie ? document.cookie.split(';') : [];
        for (let i = 0; i < cookies.length; i++) {
            const c = cookies[i].trim();
            if (c.indexOf(nombre) === 0) {
                return decodeURIComponent(c.substring(nombre.length));
            }
        }
        return '';
    }

    // 2. Mostrar avisos con Toasts de Bootstrap 5
    function mostrarToast(mensaje, variante = 'primary') {
        const contenedor = document.getElementById('toast-container');
        if (!contenedor || !mensaje) return;

        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-bg-${variante} border-0 shadow`;
        toastEl.setAttribute('role', 'status');
        toastEl.setAttribute('aria-live', 'polite');
        toastEl.setAttribute('aria-atomic', 'true');

        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body fw-semibold"></div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
            </div>
        `;
        toastEl.querySelector('.toast-body').textContent = mensaje;
        contenedor.appendChild(toastEl);

        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, { delay: 3500 });
            toast.show();
            toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
        } else {
            setTimeout(() => toastEl.remove(), 3500);
        }
    }

    // 3. Helper central para enviar POST con CSRF y recibir JSON
    async function enviarPostInteraccion(url, formData = null) {
        const headers = {
            'X-CSRFToken': obtenerCsrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
        };

        const body = formData instanceof FormData ? formData : new FormData();
        const response = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: body,
            credentials: 'same-origin',
        });

        if (response.status === 401) {
            let loginUrl = `/cuentas/login/?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
            try {
                const data401 = await response.json();
                if (data401 && data401.login_url) {
                    loginUrl = data401.login_url;
                }
            } catch (_) {
                // Usar URL por defecto
            }
            window.location.href = loginUrl;
            return null;
        }

        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = { ok: false, error: 'Respuesta inesperada del servidor.' };
        }

        if (!response.ok) {
            mostrarToast(data.error || 'No se pudo completar la acción.', 'danger');
            return null;
        }

        return data;
    }

    // 4. Manejador de formularios de "Me gusta" (posts y comentarios)
    function inicializarLikes() {
        document.querySelectorAll('form[data-ajax-like]').forEach((form) => {
            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                const btn = form.querySelector('button[type="submit"]');
                if (!btn || btn.disabled) return;

                btn.disabled = true;
                try {
                    const data = await enviarPostInteraccion(form.action, new FormData(form));
                    if (!data || !data.ok) return;

                    const activo = Boolean(data.activo);
                    btn.setAttribute('aria-pressed', activo ? 'true' : 'false');

                    const contador = btn.querySelector('[data-like-count]');
                    if (contador && typeof data.total === 'number') {
                        contador.textContent = data.total;
                    }

                    const icono = btn.querySelector('[data-like-icon]');
                    if (activo) {
                        btn.classList.remove('btn-outline-danger', 'btn-like-pop');
                        void btn.offsetWidth;
                        btn.classList.add('btn-danger', 'btn-like-pop');
                        if (icono) {
                            icono.classList.remove('bi-heart');
                            icono.classList.add('bi-heart-fill');
                        }
                        mostrarToast(data.mensaje || '¡Te gusta esto!', 'success');
                    } else {
                        btn.classList.remove('btn-danger', 'btn-like-pop');
                        btn.classList.add('btn-outline-danger');
                        if (icono) {
                            icono.classList.remove('bi-heart-fill');
                            icono.classList.add('bi-heart');
                        }
                        mostrarToast(data.mensaje || 'Has quitado tu me gusta.', 'secondary');
                    }
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    // 5. Manejador de "¿Te fue útil?" (Voto Sí / No)
    function inicializarVotosUtilidad() {
        document.querySelectorAll('form[data-ajax-voto]').forEach((form) => {
            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                const submitter = e.submitter || form.querySelector('button[type="submit"]');
                const formData = new FormData(form);
                if (submitter && submitter.name) {
                    formData.set(submitter.name, submitter.value);
                }

                const data = await enviarPostInteraccion(form.action, formData);
                if (!data || !data.ok) return;

                const contenedor = form.closest('[data-utilidad-widget]');
                if (contenedor) {
                    const btnSi = contenedor.querySelector('[data-voto-btn="si"]');
                    const btnNo = contenedor.querySelector('[data-voto-btn="no"]');
                    const resumen = contenedor.querySelector('[data-utilidad-resumen]');

                    if (btnSi) {
                        const esSi = data.voto_actual === true;
                        btnSi.setAttribute('aria-pressed', esSi ? 'true' : 'false');
                        btnSi.classList.toggle('btn-success', esSi);
                        btnSi.classList.toggle('btn-outline-success', !esSi);
                    }
                    if (btnNo) {
                        const esNo = data.voto_actual === false;
                        btnNo.setAttribute('aria-pressed', esNo ? 'true' : 'false');
                        btnNo.classList.toggle('btn-secondary', esNo);
                        btnNo.classList.toggle('btn-outline-secondary', !esNo);
                    }
                    if (resumen && typeof data.utiles === 'number' && typeof data.total === 'number') {
                        resumen.textContent = `${data.utiles} de ${data.total} lectores lo encontraron útil`;
                    }
                }

                mostrarToast(data.mensaje || '¡Gracias por tu valoración!', 'success');
            });
        });
    }

    // 5b. Manejador de botón Seguir / Siguiendo autor
    function inicializarSeguimiento() {
        document.querySelectorAll('form[data-ajax-seguir]').forEach((form) => {
            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                const btn = form.querySelector('button[type="submit"]');
                if (!btn || btn.disabled) return;

                btn.disabled = true;
                try {
                    const data = await enviarPostInteraccion(form.action, new FormData(form));
                    if (!data || !data.ok) return;

                    const activo = Boolean(data.activo);
                    btn.setAttribute('aria-pressed', activo ? 'true' : 'false');
                    btn.classList.toggle('btn-primary', activo);
                    btn.classList.toggle('btn-outline-primary', !activo);

                    const label = btn.querySelector('[data-seguir-label]');
                    if (label) {
                        label.textContent = activo ? 'Siguiendo' : 'Seguir';
                    }
                    const icono = btn.querySelector('[data-seguir-icon]');
                    if (icono) {
                        icono.className = activo ? 'bi bi-person-check-fill me-1' : 'bi bi-person-plus me-1';
                    }

                    document.querySelectorAll(`[data-seguidores-count="${form.getAttribute('data-autor-username')}"]`).forEach((el) => {
                        if (typeof data.total === 'number') {
                            el.textContent = data.total;
                        }
                    });

                    mostrarToast(data.mensaje || (activo ? 'Ahora sigues a este autor.' : 'Dejaste de seguir a este autor.'), 'info');
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    // 5c. Manejador de botón Únete / Unido en categorías (comunidades)
    function inicializarUnirseCategoria() {
        document.querySelectorAll('form[data-ajax-unirse]').forEach((form) => {
            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                const btn = form.querySelector('button[type="submit"]');
                if (!btn || btn.disabled) return;

                btn.disabled = true;
                try {
                    const data = await enviarPostInteraccion(form.action, new FormData(form));
                    if (!data || !data.ok) return;

                    const activo = Boolean(data.activo);
                    const catSlug = form.getAttribute('data-categoria-slug');

                    document.querySelectorAll(`form[data-ajax-unirse][data-categoria-slug="${catSlug}"] button[type="submit"]`).forEach((b) => {
                        b.setAttribute('aria-pressed', activo ? 'true' : 'false');
                        b.classList.toggle('btn-primary', activo);
                        b.classList.toggle('btn-outline-primary', !activo);
                        const lbl = b.querySelector('[data-unirse-label]');
                        if (lbl) lbl.textContent = activo ? 'Unido' : 'Únete';
                        const ico = b.querySelector('[data-unirse-icon]');
                        if (ico) ico.className = activo ? 'bi bi-check-lg me-1' : 'bi bi-plus-lg me-1';
                    });

                    if (catSlug && typeof data.total === 'number') {
                        document.querySelectorAll(`[data-miembros-count="${catSlug}"]`).forEach((el) => {
                            el.textContent = data.total;
                        });
                    }

                    mostrarToast(
                        data.mensaje || (activo ? 'Te has unido a la comunidad.' : 'Has salido de la comunidad.'),
                        'info'
                    );
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    // 5d. Manejador de botón Guardar en "Guardados" (marcador)
    function inicializarGuardarPost() {
        document.querySelectorAll('form[data-ajax-guardar]').forEach((form) => {
            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                const btn = form.querySelector('button[type="submit"]');
                if (!btn || btn.disabled) return;

                btn.disabled = true;
                try {
                    const data = await enviarPostInteraccion(form.action, new FormData(form));
                    if (!data || !data.ok) return;

                    const activo = Boolean(data.activo);
                    btn.setAttribute('aria-pressed', activo ? 'true' : 'false');
                    btn.classList.toggle('btn-warning', activo);
                    btn.classList.toggle('btn-outline-secondary', !activo);

                    const icono = btn.querySelector('[data-guardar-icon]');
                    if (icono) {
                        icono.className = activo ? 'bi bi-bookmark-fill' : 'bi bi-bookmark';
                    }
                    const label = btn.querySelector('[data-guardar-label]');
                    if (label) {
                        label.textContent = activo ? 'Guardado' : 'Guardar';
                    }

                    mostrarToast(data.mensaje || (activo ? 'Guardado en tu lista Guardados.' : 'Quitado de tu lista Guardados.'), 'primary');
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    // 6. Botones de compartir (Copiar enlace y Web Share API móvil)
    function inicializarCompartir() {
        document.querySelectorAll('[data-copy-url]').forEach((btn) => {
            btn.addEventListener('click', async function () {
                const url = btn.getAttribute('data-copy-url');
                if (!url) return;
                try {
                    await navigator.clipboard.writeText(url);
                } catch (_) {
                    const temp = document.createElement('input');
                    temp.value = url;
                    document.body.appendChild(temp);
                    temp.select();
                    document.execCommand('copy');
                    temp.remove();
                }
                const labelSpan = btn.querySelector('[data-copy-label]');
                const textoOriginal = labelSpan ? labelSpan.textContent : '';
                if (labelSpan) labelSpan.textContent = '¡Enlace copiado!';
                mostrarToast('¡Enlace copiado!', 'success');
                setTimeout(() => {
                    if (labelSpan) labelSpan.textContent = textoOriginal;
                }, 2000);
            });
        });

        document.querySelectorAll('[data-web-share]').forEach((btn) => {
            if (navigator.share) {
                btn.classList.remove('d-none');
                btn.addEventListener('click', async function () {
                    try {
                        await navigator.share({
                            title: btn.getAttribute('data-share-title') || document.title,
                            url: btn.getAttribute('data-share-url') || window.location.href,
                        });
                    } catch (_) {
                        // Cancelado por el usuario
                    }
                });
            }
        });

        // Modal de insertar (<iframe> embed)
        const modalEl = document.getElementById('embedPostModal');
        const textareaEmbed = document.getElementById('embed-code-textarea');
        const previewContainer = document.getElementById('embed-preview-container');
        const btnCopyEmbed = document.getElementById('btn-copy-embed-code');

        document.querySelectorAll('[data-embed-modal-trigger]').forEach((btn) => {
            btn.addEventListener('click', function () {
                const embedUrl = btn.getAttribute('data-embed-url');
                const postTitle = (btn.getAttribute('data-embed-title') || 'Artículo').replace(/"/g, '&quot;');
                if (!embedUrl) return;

                const snippet = `<iframe src="${embedUrl}" width="100%" height="260" style="border:0" loading="lazy" title="${postTitle}"></iframe>`;
                if (textareaEmbed) {
                    textareaEmbed.value = snippet;
                }
                if (previewContainer) {
                    previewContainer.innerHTML = snippet;
                }
                if (modalEl && window.bootstrap && window.bootstrap.Modal) {
                    const modalInstance = window.bootstrap.Modal.getOrCreateInstance(modalEl);
                    modalInstance.show();
                }
            });
        });

        if (btnCopyEmbed && textareaEmbed) {
            btnCopyEmbed.addEventListener('click', async function () {
                const codigo = textareaEmbed.value;
                if (!codigo) return;
                try {
                    await navigator.clipboard.writeText(codigo);
                } catch (_) {
                    textareaEmbed.select();
                    document.execCommand('copy');
                }
                mostrarToast('¡Código copiado al portapapeles!', 'success');
            });
        }
    }

    // 7. Refresco del contador de notificaciones cada 60 segundos si la pestaña es visible
    function inicializarPollingNotificaciones() {
        const badge = document.getElementById('notificaciones-badge');
        if (!badge) return;
        const urlContador = badge.getAttribute('data-contador-url');
        if (!urlContador) return;

        async function actualizarContador() {
            if (document.visibilityState !== 'visible') return;
            try {
                const resp = await fetch(urlContador, {
                    headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    credentials: 'same-origin',
                });
                if (!resp.ok) return;
                const data = await resp.json();
                if (typeof data.no_leidas === 'number') {
                    badge.textContent = data.no_leidas;
                    badge.classList.toggle('d-none', data.no_leidas === 0);
                }
            } catch (_) {
                // Silenciar errores de red transitorios
            }
        }

        setInterval(actualizarContador, 60000);
    }

    // 8. Autocompletado de menciones @usuario en textarea de comentarios
    function inicializarAutocompletadoMenciones() {
        const textarea = document.querySelector('textarea[data-mention-autocomplete]');
        if (!textarea) return;
        const endpoint = textarea.getAttribute('data-mention-url');
        if (!endpoint) return;

        const menu = document.createElement('div');
        menu.className = 'list-group position-absolute shadow-sm d-none z-3';
        menu.style.maxWidth = '280px';
        textarea.parentElement.style.position = 'relative';
        textarea.parentElement.appendChild(menu);

        let debounceTimer = null;

        function cerrarMenu() {
            menu.classList.add('d-none');
            menu.innerHTML = '';
        }

        textarea.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            const cursor = textarea.selectionStart;
            const textoHastaCursor = textarea.value.slice(0, cursor);
            const match = textoHastaCursor.match(/(?:^|\s)@([a-zA-Z0-9_.\-+]{2,30})$/);

            if (!match) {
                cerrarMenu();
                return;
            }

            const query = match[1];
            debounceTimer = setTimeout(async () => {
                try {
                    const resp = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`, {
                        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                        credentials: 'same-origin',
                    });
                    if (!resp.ok) {
                        cerrarMenu();
                        return;
                    }
                    const data = await resp.json();
                    const usuarios = data.usuarios || [];
                    if (!usuarios.length) {
                        cerrarMenu();
                        return;
                    }

                    menu.innerHTML = '';
                    usuarios.forEach((u) => {
                        const item = document.createElement('button');
                        item.type = 'button';
                        item.className = 'list-group-item list-group-item-action py-1 px-2 small d-flex justify-content-between align-items-center';
                        item.innerHTML = `<span class="fw-semibold">@${u.username}</span><span class="text-muted ms-2">${u.nombre || ''}</span>`;
                        item.addEventListener('click', () => {
                            const inicioMencion = textoHastaCursor.lastIndexOf('@' + query);
                            const antes = textarea.value.slice(0, inicioMencion);
                            const despues = textarea.value.slice(cursor);
                            textarea.value = `${antes}@${u.username} ${despues}`;
                            textarea.focus();
                            cerrarMenu();
                        });
                        menu.appendChild(item);
                    });
                    menu.classList.remove('d-none');
                } catch (_) {
                    cerrarMenu();
                }
            }, 220);
        });

        document.addEventListener('click', (e) => {
            if (!menu.contains(e.target) && e.target !== textarea) {
                cerrarMenu();
            }
        });
    }

    // 9. Modo Claro / Oscuro con soporte nativo Bootstrap 5.3 (data-bs-theme)
    function inicializarTema() {
        const btnTema = document.getElementById('theme-toggle-btn');
        const iconoTema = document.getElementById('theme-toggle-icon');

        function aplicarTema(tema) {
            document.documentElement.setAttribute('data-bs-theme', tema);
            if (iconoTema) {
                iconoTema.className = tema === 'dark' ? 'bi bi-sun-fill text-warning' : 'bi bi-moon-stars-fill';
            }
            if (btnTema) {
                btnTema.setAttribute('aria-pressed', tema === 'dark' ? 'true' : 'false');
            }
            const hljsLight = document.getElementById('hljs-theme-light');
            const hljsDark = document.getElementById('hljs-theme-dark');
            if (hljsLight && hljsDark) {
                hljsLight.disabled = (tema === 'dark');
                hljsDark.disabled = (tema !== 'dark');
            }
        }

        const guardado = localStorage.getItem('blog_theme') || 'light';
        aplicarTema(guardado);

        if (btnTema) {
            btnTema.addEventListener('click', () => {
                const actual = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light';
                const nuevo = actual === 'dark' ? 'light' : 'dark';
                localStorage.setItem('blog_theme', nuevo);
                aplicarTema(nuevo);
            });
        }
    }

    // 10. Selector de vista Tarjetas | Compacta en hub de categoría y Comentarios anidados
    function inicializarVistaCategoria() {
        const wrapper = document.getElementById('category-posts-wrapper');
        const botones = document.querySelectorAll('[data-category-view-toggle]');
        if (!wrapper || !botones.length) return;

        function aplicarModoVista(modo) {
            const modoValido = modo === 'compacta' ? 'compacta' : 'tarjetas';
            wrapper.setAttribute('data-view-mode', modoValido);
            botones.forEach((b) => {
                const activo = b.getAttribute('data-category-view-toggle') === modoValido;
                b.setAttribute('aria-pressed', activo ? 'true' : 'false');
                b.classList.toggle('btn-primary', activo);
                b.classList.toggle('btn-outline-secondary', !activo);
            });
        }

        const guardado = localStorage.getItem('blog_categoria_vista') || 'tarjetas';
        aplicarModoVista(guardado);

        botones.forEach((btn) => {
            btn.addEventListener('click', () => {
                const modo = btn.getAttribute('data-category-view-toggle');
                localStorage.setItem('blog_categoria_vista', modo);
                aplicarModoVista(modo);
            });
        });
    }

    function inicializarComentariosAnidados() {
        function alternarFormularioRespuesta(pk, forzarAbrir) {
            const formContainer = document.getElementById('reply-form-' + pk);
            if (!formContainer) return false;
            const abrir = typeof forzarAbrir === 'boolean'
                ? forzarAbrir
                : formContainer.classList.contains('d-none');
            formContainer.classList.toggle('d-none', !abrir);
            document.querySelectorAll('[data-toggle-reply="' + pk + '"]').forEach((b) => {
                b.setAttribute('aria-expanded', abrir ? 'true' : 'false');
            });
            if (abrir) {
                const ta = formContainer.querySelector('textarea');
                if (ta) ta.focus();
            }
            return true;
        }

        // Botón «Responder» (sin JS funciona con ?responder=<id>#comentario-<id>)
        document.querySelectorAll('[data-toggle-reply]').forEach((btn) => {
            btn.addEventListener('click', function (e) {
                const pk = btn.getAttribute('data-toggle-reply');
                if (alternarFormularioRespuesta(pk)) e.preventDefault();
            });
        });

        // Botón «Cancelar» del formulario inline
        document.querySelectorAll('[data-cancel-reply]').forEach((btn) => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const pk = btn.getAttribute('data-cancel-reply');
                alternarFormularioRespuesta(pk, false);
                const trigger = document.querySelector('[data-toggle-reply="' + pk + '"]');
                if (trigger) trigger.focus();
            });
        });

        // Compatibilidad con el atributo anterior data-reply-toggle="<id del contenedor>"
        document.querySelectorAll('[data-reply-toggle]').forEach((btn) => {
            btn.addEventListener('click', function (e) {
                const targetId = btn.getAttribute('data-reply-toggle');
                const formContainer = document.getElementById(targetId);
                if (!formContainer) return;
                e.preventDefault();
                const oculto = formContainer.classList.toggle('d-none');
                btn.setAttribute('aria-expanded', oculto ? 'false' : 'true');
                if (!oculto) {
                    const ta = formContainer.querySelector('textarea');
                    if (ta) ta.focus();
                }
            });
        });

        // «N respuestas más ⌄» / «Ocultar respuestas ⌃»
        document.querySelectorAll('[data-reply-collapse-btn], [data-collapse-replies]').forEach((btn) => {
            const targetSelector = btn.getAttribute('data-bs-target');
            if (!targetSelector) return;
            const collapseEl = document.querySelector(targetSelector);
            if (!collapseEl) return;
            const n = parseInt(btn.getAttribute('data-reply-count') || '0', 10);
            const textoMas = btn.getAttribute('data-label-collapsed')
                || (n === 1 ? '1 respuesta más' : n + ' respuestas más');
            const textoOcultar = btn.getAttribute('data-label-expanded') || 'Ocultar respuestas';

            function pintar(expandido) {
                btn.innerHTML = '';
                const span = document.createElement('span');
                span.textContent = expandido ? textoOcultar : textoMas;
                const icono = document.createElement('i');
                icono.className = 'bi ' + (expandido ? 'bi-chevron-up' : 'bi-chevron-down');
                icono.setAttribute('aria-hidden', 'true');
                btn.appendChild(span);
                btn.appendChild(icono);
                btn.setAttribute('aria-expanded', expandido ? 'true' : 'false');
            }

            collapseEl.addEventListener('show.bs.collapse', function (ev) {
                if (ev.target !== collapseEl) return;
                pintar(true);
            });
            collapseEl.addEventListener('hide.bs.collapse', function (ev) {
                if (ev.target !== collapseEl) return;
                pintar(false);
            });
        });
    }

    function inicializarDropdownsSobreTarjetas() {
        // Eleva la tarjeta que contiene un dropdown abierto para que el menú
        // no quede tapado por tarjetas vecinas o widgets de la barra lateral.
        document.addEventListener('show.bs.dropdown', function (ev) {
            const contenedor = ev.target.closest('.card, .post-card, article, .compact-post-row');
            if (contenedor) contenedor.classList.add('dropdown-open');
        });
        document.addEventListener('hidden.bs.dropdown', function (ev) {
            const contenedor = ev.target.closest('.card, .post-card, article, .compact-post-row');
            if (contenedor) contenedor.classList.remove('dropdown-open');
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        inicializarTema();
        inicializarLikes();
        inicializarVotosUtilidad();
        inicializarSeguimiento();
        inicializarUnirseCategoria();
        inicializarGuardarPost();
        inicializarCompartir();
        inicializarPollingNotificaciones();
        inicializarAutocompletadoMenciones();
        inicializarVistaCategoria();
        inicializarComentariosAnidados();
        inicializarDropdownsSobreTarjetas();
    });

    window.BlogInteracciones = {
        enviarPostInteraccion,
        mostrarToast,
    };
})();

