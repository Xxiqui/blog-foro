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
    function mostrarToast(mensaje, variante = 'primary', accion = null) {
        const contenedor = document.getElementById('toast-container');
        if (!contenedor || !mensaje) return;

        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-bg-${variante} border-0 shadow`;
        toastEl.setAttribute('role', 'status');
        toastEl.setAttribute('aria-live', 'polite');
        toastEl.setAttribute('aria-atomic', 'true');

        toastEl.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="toast-body fw-semibold py-2"></div>
                <div class="toast-actions ms-auto d-flex align-items-center gap-1 pe-2"></div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
            </div>
        `;
        toastEl.querySelector('.toast-body').textContent = mensaje;
        const actionsBox = toastEl.querySelector('.toast-actions');

        if (accion && accion.texto && typeof accion.callback === 'function') {
            const btnAccion = document.createElement('button');
            btnAccion.type = 'button';
            btnAccion.className = 'btn btn-sm btn-light py-0 px-2 fw-bold text-dark';
            btnAccion.textContent = accion.texto;
            btnAccion.addEventListener('click', () => {
                accion.callback();
                const bsToast = window.bootstrap && window.bootstrap.Toast ? window.bootstrap.Toast.getInstance(toastEl) : null;
                if (bsToast) bsToast.hide();
            });
            actionsBox.appendChild(btnAccion);
        }

        if (accion && accion.enlaceTexto && accion.enlaceUrl) {
            const link = document.createElement('a');
            link.href = accion.enlaceUrl;
            link.className = 'btn btn-sm btn-outline-light py-0 px-2 small text-decoration-none';
            link.textContent = accion.enlaceTexto;
            actionsBox.appendChild(link);
        }

        contenedor.appendChild(toastEl);

        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, { delay: 4500 });
            toast.show();
            toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
        } else {
            setTimeout(() => toastEl.remove(), 4500);
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
            const modalAuth = document.getElementById('modalAccesoVisitante');
            if (modalAuth && typeof abrirModalAcceso === 'function') {
                abrirModalAcceso();
                return null;
            }
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

    // 5d. Manejador de botón Guardar en "Guardados" (marcador con deshacer)
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

                    if (activo) {
                        mostrarToast('Guardado en tus artículos', 'primary', {
                            texto: 'Deshacer',
                            callback: () => {
                                form.dispatchEvent(new Event('submit', { cancelable: true }));
                            },
                            enlaceTexto: 'Ver guardados',
                            enlaceUrl: '/guardados/',
                        });
                    } else {
                        mostrarToast('Quitado de tus guardados', 'secondary');
                    }
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    // 6. Botones de compartir (Copiar enlace y Web Share API móvil)
    function inicializarCompartir() {
        // Manejador centralizado para botones .btn-compartir (feed, artículo y tarjetas)
        document.addEventListener('click', async function (e) {
            const btn = e.target.closest('.btn-compartir');
            if (!btn) return;
            e.preventDefault();
            const url = btn.getAttribute('data-url') || window.location.href;
            const titulo = btn.getAttribute('data-titulo') || document.title;

            if (navigator.share) {
                try {
                    await navigator.share({
                        title: titulo,
                        url: url,
                    });
                    return;
                } catch (err) {
                    if (err.name === 'AbortError') return;
                }
            }

            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(url);
                } else {
                    const temp = document.createElement('input');
                    temp.value = url;
                    document.body.appendChild(temp);
                    temp.select();
                    document.execCommand('copy');
                    temp.remove();
                }
                mostrarToast('¡Enlace copiado al portapapeles!', 'success');
            } catch (_) {
                mostrarToast('Enlace: ' + url, 'info');
            }
        });

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

    // 9. Modo Claro / Oscuro / Sistema con soporte nativo Bootstrap 5.3 (data-bs-theme)
    function inicializarTema() {
        const btnsTema = document.querySelectorAll('#theme-toggle-btn, .theme-toggle-btn, [data-action="toggle-theme"]');
        const iconosTema = document.querySelectorAll('#theme-toggle-icon, .theme-toggle-icon');
        const selectorBtns = document.querySelectorAll('[data-theme-val]');

        function getSystemTheme() {
            return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }

        function aplicarTema(modo) {
            const temaEfectivo = modo === 'system' ? getSystemTheme() : modo;
            document.documentElement.setAttribute('data-bs-theme', temaEfectivo);

            // Actualizar botones segmentados (3 opciones)
            selectorBtns.forEach(btn => {
                const val = btn.getAttribute('data-theme-val');
                const activo = val === modo;
                btn.classList.toggle('active', activo);
                btn.setAttribute('aria-pressed', activo ? 'true' : 'false');
            });

            // Actualizar íconos de conmutador simple si existen
            iconosTema.forEach(ic => {
                if (modo === 'system') {
                    ic.className = 'bi bi-laptop text-primary';
                } else if (temaEfectivo === 'dark') {
                    ic.className = 'bi bi-moon-stars-fill text-warning';
                } else {
                    ic.className = 'bi bi-sun-fill text-warning';
                }
            });

            btnsTema.forEach(btn => {
                btn.setAttribute('aria-pressed', temaEfectivo === 'dark' ? 'true' : 'false');
            });

            const hljsLight = document.getElementById('hljs-theme-light');
            const hljsDark = document.getElementById('hljs-theme-dark');
            if (hljsLight && hljsDark) {
                hljsLight.disabled = (temaEfectivo === 'dark');
                hljsDark.disabled = (temaEfectivo !== 'dark');
            }
        }

        const guardado = localStorage.getItem('blog_theme') || 'system';
        aplicarTema(guardado);

        // Click en botones segmentados
        selectorBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const nuevoModo = btn.getAttribute('data-theme-val') || 'system';
                localStorage.setItem('blog_theme', nuevoModo);
                aplicarTema(nuevoModo);
            });
        });

        // Conmutador simple (toggle rápido entre claro/oscuro)
        btnsTema.forEach(btn => {
            btn.addEventListener('click', (e) => {
                if (btn.hasAttribute('data-bs-toggle')) return; // No interceptar si abre dropdown
                e.preventDefault();
                const actual = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light';
                const nuevo = actual === 'dark' ? 'light' : 'dark';
                localStorage.setItem('blog_theme', nuevo);
                aplicarTema(nuevo);
            });
        });

        // Escuchar cambios del sistema en tiempo real
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                const modoActual = localStorage.getItem('blog_theme') || 'system';
                if (modoActual === 'system') {
                    aplicarTema('system');
                }
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
        // Colapsar hilo estilo Reddit [–]
        document.addEventListener('click', function (e) {
            const btnCollapse = e.target.closest('.btn-collapse-thread');
            if (btnCollapse) {
                e.preventDefault();
                const node = btnCollapse.closest('.comment-node');
                if (!node) return;
                const pk = node.getAttribute('data-comment-id');
                const exp = document.getElementById('expanded-content-' + pk);
                const sum = document.getElementById('collapsed-summary-' + pk);
                const hijos = document.getElementById('respuestas-' + pk);
                if (exp) exp.classList.add('d-none');
                if (sum) sum.classList.remove('d-none');
                if (hijos) hijos.classList.add('d-none');
                return;
            }

            // Expandir hilo estilo Reddit [+]
            const btnExpand = e.target.closest('.btn-expand-thread, .comment-collapsed-summary');
            if (btnExpand) {
                e.preventDefault();
                const node = btnExpand.closest('.comment-node');
                if (!node) return;
                const pk = node.getAttribute('data-comment-id');
                const exp = document.getElementById('expanded-content-' + pk);
                const sum = document.getElementById('collapsed-summary-' + pk);
                const hijos = document.getElementById('respuestas-' + pk);
                if (sum) sum.classList.add('d-none');
                if (exp) exp.classList.remove('d-none');
                if (hijos) hijos.classList.remove('d-none');
                return;
            }

            // Toggle formulario de respuesta inline
            const btnReply = e.target.closest('.btn-toggle-reply');
            if (btnReply) {
                e.preventDefault();
                const targetId = btnReply.getAttribute('data-reply-target');
                const box = document.getElementById(targetId);
                if (!box) return;
                const oculto = box.classList.toggle('d-none');
                btnReply.setAttribute('aria-expanded', oculto ? 'false' : 'true');
                if (!oculto) {
                    const ta = box.querySelector('textarea');
                    if (ta) ta.focus();
                }
                return;
            }

            // Cancelar respuesta inline
            const btnCancel = e.target.closest('.btn-cancel-reply');
            if (btnCancel) {
                e.preventDefault();
                const targetId = btnCancel.getAttribute('data-reply-target');
                const box = document.getElementById(targetId);
                if (box) {
                    box.classList.add('d-none');
                    const ta = box.querySelector('textarea');
                    if (ta) ta.value = '';
                }
                return;
            }
        });

        // Auto-crecimiento y contador de caracteres en textareas de comentarios
        document.addEventListener('input', function (e) {
            const ta = e.target.closest('.comment-composer-textarea');
            if (!ta) return;
            const container = ta.closest('.comment-form-composer') || ta.parentElement;
            const counter = container ? container.querySelector('.reply-char-counter, #main-char-counter') : null;
            if (counter) {
                counter.textContent = `${ta.value.length}/1000`;
            }
            ta.style.height = 'auto';
            ta.style.height = Math.min(320, Math.max(44, ta.scrollHeight)) + 'px';
        });

        // Atajo Ctrl+Enter / Cmd+Enter para enviar comentario
        document.addEventListener('keydown', function (e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const ta = e.target.closest('.comment-composer-textarea');
                if (!ta) return;
                e.preventDefault();
                const form = ta.closest('form');
                if (form && ta.value.trim().length > 0) {
                    form.submit();
                }
            }
        });

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

        // Compatibilidad con enlaces antiguos data-toggle-reply
        document.querySelectorAll('[data-toggle-reply]').forEach((btn) => {
            btn.addEventListener('click', function (e) {
                const pk = btn.getAttribute('data-toggle-reply');
                if (alternarFormularioRespuesta(pk)) e.preventDefault();
            });
        });

        document.querySelectorAll('[data-cancel-reply]').forEach((btn) => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const pk = btn.getAttribute('data-cancel-reply');
                alternarFormularioRespuesta(pk, false);
            });
        });
    }

    // Sondeo de comentarios nuevos cada 45s en post_detail
    function inicializarPollingNovedadesComentarios() {
        const root = document.getElementById('post-detail-root');
        if (!root) return;
        const slug = root.getAttribute('data-post-slug');
        const banner = document.getElementById('banner-nuevos-comentarios');
        const contadorTexto = document.getElementById('contador-nuevos-comentarios-texto');
        let ultimoId = parseInt(root.getAttribute('data-ultimo-comentario-id') || '0', 10);
        if (!slug || !banner) return;

        setInterval(async function () {
            if (document.visibilityState !== 'visible') return;
            try {
                const resp = await fetch(`/post/${encodeURIComponent(slug)}/comentarios/novedades/?ultimo_id=${ultimoId}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data && data.nuevos_count > 0) {
                        const n = data.nuevos_count;
                        if (contadorTexto) {
                            contadorTexto.textContent = n === 1 ? '1 comentario nuevo' : `${n} comentarios nuevos`;
                        }
                        banner.classList.remove('d-none');
                    }
                }
            } catch (_) {}
        }, 45000);
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

    // Modal de Acceso para Visitantes (Hoja inferior en móvil)
    let elementoPrevioFocoModal = null;

    function abrirModalAcceso(accion = '', ancla = '') {
        const modal = document.getElementById('modalAccesoVisitante');
        if (!modal) return;
        elementoPrevioFocoModal = document.activeElement;
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        const focusable = modal.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])');
        if (focusable.length) {
            setTimeout(() => focusable[0].focus(), 80);
        }

        const nextInput = document.getElementById('auth-modal-next');
        if (nextInput) {
            let nextVal = window.location.pathname + window.location.search;
            if (ancla) nextVal += (ancla.startsWith('#') ? ancla : '#' + ancla);
            nextInput.value = nextVal;
        }
        if (accion || ancla) {
            try {
                sessionStorage.setItem('reintentar_accion_post_login', JSON.stringify({ accion: accion, ancla: ancla }));
            } catch (_) {}
        }
    }

    function cerrarModalAcceso() {
        const modal = document.getElementById('modalAccesoVisitante');
        if (!modal) return;
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        if (elementoPrevioFocoModal && typeof elementoPrevioFocoModal.focus === 'function') {
            try { elementoPrevioFocoModal.focus(); } catch (_) {}
            elementoPrevioFocoModal = null;
        }
    }

    function verificarReintentoAccion() {
        try {
            const item = sessionStorage.getItem('reintentar_accion_post_login');
            if (item) {
                sessionStorage.removeItem('reintentar_accion_post_login');
                const data = JSON.parse(item);
                if (data && data.ancla) {
                    const el = document.querySelector(data.ancla);
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        const btn = el.querySelector('.btn-voto, .btn-guardar-post, .btn-seguir-autor, .btn-unirse-categoria') || el;
                        if (btn && btn.click) {
                            setTimeout(() => btn.click(), 400);
                        }
                    }
                }
            }
        } catch (_) {}
    }

    function inicializarModalAcceso() {
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.btn-requiere-auth');
            if (btn) {
                e.preventDefault();
                const accion = btn.getAttribute('data-action') || '';
                const ancla = btn.closest('[id]') ? '#' + btn.closest('[id]').id : '';
                abrirModalAcceso(accion, ancla);
            }
        });

        const btnCerrar = document.getElementById('btn-cerrar-modal-auth');
        if (btnCerrar) {
            btnCerrar.addEventListener('click', cerrarModalAcceso);
        }

        const modal = document.getElementById('modalAccesoVisitante');
        if (modal) {
            modal.addEventListener('click', function(e) {
                if (e.target === modal) {
                    cerrarModalAcceso();
                }
            });
            modal.addEventListener('keydown', function(e) {
                if (e.key === 'Tab') {
                    const focusable = Array.from(modal.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter(el => el.offsetParent !== null);
                    if (!focusable.length) return;
                    const first = focusable[0];
                    const last = focusable[focusable.length - 1];
                    if (e.shiftKey && document.activeElement === first) {
                        last.focus();
                        e.preventDefault();
                    } else if (!e.shiftKey && document.activeElement === last) {
                        first.focus();
                        e.preventDefault();
                    }
                }
            });
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                cerrarModalAcceso();
            }
        });

        verificarReintentoAccion();
    }

    // Buscador global con sugerencias y atajos
    function inicializarBuscadorSugerencias() {
        const searchInput = document.getElementById('header-search-input');
        const dropdown = document.getElementById('search-suggestions-dropdown');
        const searchContainer = document.getElementById('global-search-container');
        const mobileToggle = document.getElementById('mobile-search-toggle');

        if (mobileToggle && searchContainer) {
            mobileToggle.addEventListener('click', function() {
                searchContainer.classList.toggle('mobile-open');
                if (searchContainer.classList.contains('mobile-open') && searchInput) {
                    setTimeout(() => searchInput.focus(), 60);
                }
            });
        }

        // Mostrar / ocultar dropdown al recibir resultados de HTMX
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            if (evt.detail.target && evt.detail.target.id === 'search-suggestions-dropdown') {
                const dd = evt.detail.target;
                const items = dd.querySelectorAll('.suggestion-item');
                if (items.length > 0 || dd.innerText.trim().length > 0) {
                    dd.classList.add('show');
                } else {
                    dd.classList.remove('show');
                }
            }
        });

        // Navegación por teclado en el input de búsqueda (flechas, Enter, Esc)
        if (searchInput && dropdown) {
            searchInput.addEventListener('keydown', function(e) {
                const items = Array.from(dropdown.querySelectorAll('.suggestion-item'));
                let activeIdx = items.findIndex(it => it.classList.contains('active'));

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (items.length === 0) return;
                    if (activeIdx >= 0) items[activeIdx].classList.remove('active');
                    activeIdx = (activeIdx + 1) % items.length;
                    items[activeIdx].classList.add('active');
                    items[activeIdx].scrollIntoView({ block: 'nearest' });
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (items.length === 0) return;
                    if (activeIdx >= 0) items[activeIdx].classList.remove('active');
                    activeIdx = (activeIdx - 1 + items.length) % items.length;
                    items[activeIdx].classList.add('active');
                    items[activeIdx].scrollIntoView({ block: 'nearest' });
                } else if (e.key === 'Enter') {
                    if (activeIdx >= 0 && items[activeIdx]) {
                        e.preventDefault();
                        const href = items[activeIdx].getAttribute('href');
                        if (href) window.location.href = href;
                    }
                } else if (e.key === 'Escape') {
                    dropdown.classList.remove('show');
                    if (searchContainer) searchContainer.classList.remove('mobile-open');
                    searchInput.blur();
                }
            });

            // Cerrar dropdown al hacer clic fuera
            document.addEventListener('click', function(e) {
                if (searchContainer && !searchContainer.contains(e.target)) {
                    dropdown.classList.remove('show');
                    if (searchContainer.classList.contains('mobile-open') && (!mobileToggle || !mobileToggle.contains(e.target))) {
                        searchContainer.classList.remove('mobile-open');
                    }
                }
            });
        }
    }

    // Atajos de teclado del foro
    function inicializarAtajosTeclado() {
        let lastGTime = 0;
        let postIndex = -1;

        document.addEventListener('keydown', function(e) {
            // Ignorar si el usuario está escribiendo o si hay un modal abierto
            const tag = (e.target.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) {
                return;
            }
            if (document.querySelector('.modal.show, .auth-modal-backdrop.show')) {
                return;
            }

            // Atajo / o Ctrl/Cmd+K para abrir búsqueda
            if (e.key === '/' || ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K'))) {
                e.preventDefault();
                const searchContainer = document.getElementById('global-search-container');
                const searchInput = document.getElementById('header-search-input');
                if (searchContainer) searchContainer.classList.add('mobile-open');
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
                return;
            }

            // G luego H -> Ir al inicio
            if (e.key === 'g' || e.key === 'G') {
                lastGTime = Date.now();
                return;
            }
            if ((e.key === 'h' || e.key === 'H') && (Date.now() - lastGTime < 1000)) {
                e.preventDefault();
                window.location.href = '/';
                return;
            }

            // Navegación de publicaciones en el feed con j / k
            const posts = Array.from(document.querySelectorAll('.post-row, .card-post, .compact-post-row, article.card'));
            if (posts.length > 0) {
                if (e.key === 'j' || e.key === 'J') {
                    e.preventDefault();
                    if (postIndex >= 0 && postIndex < posts.length) {
                        posts[postIndex].classList.remove('keyboard-active');
                    }
                    postIndex = Math.min(posts.length - 1, postIndex + 1);
                    posts[postIndex].classList.add('keyboard-active');
                    posts[postIndex].scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return;
                }
                if (e.key === 'k' || e.key === 'K') {
                    e.preventDefault();
                    if (postIndex >= 0 && postIndex < posts.length) {
                        posts[postIndex].classList.remove('keyboard-active');
                    }
                    postIndex = Math.max(0, postIndex - 1);
                    posts[postIndex].classList.add('keyboard-active');
                    posts[postIndex].scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return;
                }

                // Acciones sobre el post activo
                if (postIndex >= 0 && postIndex < posts.length) {
                    const activePost = posts[postIndex];

                    // Enter u 'o' -> Abrir publicación
                    if (e.key === 'Enter' || e.key === 'o' || e.key === 'O') {
                        const link = activePost.querySelector('a.post-title-heading, a.post-title-link, h2 a, h3 a');
                        if (link) {
                            e.preventDefault();
                            link.click();
                        }
                        return;
                    }

                    // 'a' -> Votar
                    if (e.key === 'a' || e.key === 'A') {
                        const btnVoto = activePost.querySelector('.vote-btn, .btn-like-post, .btn-voto');
                        if (btnVoto) {
                            e.preventDefault();
                            btnVoto.click();
                        }
                        return;
                    }

                    // 's' -> Guardar
                    if (e.key === 's' || e.key === 'S') {
                        const btnGuardar = activePost.querySelector('.btn-guardar-post, [data-action="guardar"]');
                        if (btnGuardar) {
                            e.preventDefault();
                            btnGuardar.click();
                        }
                        return;
                    }

                    // 'c' -> Comentar / Saltar a comentarios
                    if (e.key === 'c' || e.key === 'C') {
                        const btnComentar = activePost.querySelector('.post-action-comment, [data-action="comentar"]');
                        if (btnComentar) {
                            e.preventDefault();
                            btnComentar.click();
                        }
                        return;
                    }
                }
            }

            // '?' -> Mostrar ayuda de atajos
            if (e.key === '?') {
                e.preventDefault();
                mostrarToast('Atajos: j/k = navegar posts, Enter/o = abrir, a = votar, s = guardar, c = comentar, / = buscar, g+h = inicio', 'dark');
            }
        });
    }

    function inicializarVotosOptimistas() {
        document.addEventListener('click', async function (e) {
            const btn = e.target.closest('.btn-voto:not(.btn-requiere-auth)');
            if (!btn || btn.disabled) return;

            const url = btn.getAttribute('data-url');
            if (!url) return;

            e.preventDefault();
            const rail = btn.closest('.vote-rail');
            const scoreEl = rail ? rail.querySelector('[data-vote-score]') : null;
            const wasActive = btn.classList.contains('active');
            const prevScore = scoreEl ? parseInt(scoreEl.textContent.trim() || '0', 10) : 0;
            const optimisticScore = wasActive ? Math.max(0, prevScore - 1) : prevScore + 1;

            // Actualización optimista
            btn.classList.toggle('active', !wasActive);
            btn.setAttribute('aria-pressed', !wasActive ? 'true' : 'false');
            if (scoreEl) scoreEl.textContent = optimisticScore;

            try {
                const data = await enviarPostInteraccion(url);
                if (data && data.ok) {
                    const finalTotal = typeof data.total === 'number' ? data.total : (typeof data.total_likes === 'number' ? data.total_likes : optimisticScore);
                    const finalActive = typeof data.activo === 'boolean' ? data.activo : (typeof data.liked === 'boolean' ? data.liked : !wasActive);
                    btn.classList.toggle('active', finalActive);
                    btn.setAttribute('aria-pressed', finalActive ? 'true' : 'false');
                    if (scoreEl) scoreEl.textContent = finalTotal;
                } else {
                    btn.classList.toggle('active', wasActive);
                    btn.setAttribute('aria-pressed', wasActive ? 'true' : 'false');
                    if (scoreEl) scoreEl.textContent = prevScore;
                    mostrarToast('No se pudo registrar el voto.', 'danger');
                }
            } catch (err) {
                btn.classList.toggle('active', wasActive);
                btn.setAttribute('aria-pressed', wasActive ? 'true' : 'false');
                if (scoreEl) scoreEl.textContent = prevScore;
                mostrarToast('Error de red al votar.', 'danger');
            }
        });
    }

    function inicializarPollingNovedadesFeed() {
        const feedRoot = document.getElementById('feed-root-container');
        if (!feedRoot) return;
        const banner = document.getElementById('banner-nuevas-publicaciones');
        const btnCargar = document.getElementById('btn-cargar-novedades');
        const contadorTexto = document.getElementById('contador-novedades-texto');
        const ultimoId = parseInt(feedRoot.getAttribute('data-ultimo-id') || '0', 10);
        if (!ultimoId || !banner) return;

        if (btnCargar) {
            btnCargar.addEventListener('click', function () {
                window.location.reload();
            });
        }

        setInterval(async function () {
            if (document.visibilityState !== 'visible') return;
            try {
                const resp = await fetch(`/feed/novedades/?ultimo_id=${ultimoId}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data && data.nuevos_count > 0) {
                        const n = data.nuevos_count;
                        if (contadorTexto) {
                            contadorTexto.textContent = n === 1 ? '1 publicación nueva' : `${n} publicaciones nuevas`;
                        }
                        banner.classList.remove('d-none');
                    }
                }
            } catch (_) {}
        }, 60000);
    }

    function inicializarRestauracionScroll() {
        const feedContainer = document.getElementById('feed-posts-container');
        if (!feedContainer) return;

        window.addEventListener('beforeunload', function () {
            try {
                sessionStorage.setItem('feed_scroll_pos', window.scrollY.toString());
                sessionStorage.setItem('feed_path', window.location.pathname + window.location.search);
            } catch (_) {}
        });

        window.addEventListener('pageshow', function () {
            try {
                const savedPath = sessionStorage.getItem('feed_path');
                const savedPos = sessionStorage.getItem('feed_scroll_pos');
                if (savedPath === (window.location.pathname + window.location.search) && savedPos) {
                    setTimeout(() => window.scrollTo({ top: parseInt(savedPos, 10), behavior: 'instant' }), 50);
                }
            } catch (_) {}
        });
    }

    function inicializarCopiarEnlaceMenu() {
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('.btn-copiar-enlace');
            if (btn) {
                e.preventDefault();
                const url = btn.getAttribute('data-url') || window.location.href;
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(url).then(() => {
                        mostrarToast('¡Enlace copiado al portapapeles!', 'success');
                    }).catch(() => {
                        mostrarToast('Enlace: ' + url, 'info');
                    });
                } else {
                    mostrarToast('Enlace: ' + url, 'info');
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        inicializarTema();
        inicializarLikes();
        inicializarVotosUtilidad();
        inicializarVotosOptimistas();
        inicializarSeguimiento();
        inicializarUnirseCategoria();
        inicializarGuardarPost();
        inicializarCompartir();
        inicializarPollingNotificaciones();
        inicializarPollingNovedadesFeed();
        inicializarRestauracionScroll();
        inicializarCopiarEnlaceMenu();
        inicializarAutocompletadoMenciones();
        inicializarVistaCategoria();
        inicializarComentariosAnidados();
        inicializarPollingNovedadesComentarios();
        inicializarDropdownsSobreTarjetas();
        inicializarModalAcceso();
        inicializarBuscadorSugerencias();
        inicializarAtajosTeclado();
    });

    window.BlogInteracciones = {
        enviarPostInteraccion,
        mostrarToast,
        abrirModalAcceso,
        cerrarModalAcceso,
    };
})();

