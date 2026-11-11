/**
 * Punto de entrada principal para el Estudio de Escritura
 * Módulos ES nativos sin empaquetadores
 */
import { getCsrfToken, slugify } from './util.js';
import { initCKEditor, onEditorChange, getEditorContent, setEditorContent } from './ckeditor-config.js';
import { initAutoguardado } from './autoguardado.js';
import { initPortada } from './portada.js';
import { initEtiquetas, getSelectedTags } from './etiquetas.js';
import { initLateral, sincronizarPreviews } from './lateral.js';
import { initChecklist, evaluarChecklist } from './checklist.js';
import { initVistaPrevia } from './vista-previa.js';
import { initHistorial } from './historial.js';
import { initAtajos } from './atajos.js';

document.addEventListener('DOMContentLoaded', () => {
    // 1. Cargar configuración inyectada por Django
    const configEl = document.getElementById('editorConfigData');
    let config = {};
    if (configEl) {
        try {
            config = JSON.parse(configEl.textContent);
        } catch (e) {
            console.error('Error parseando configuración del editor:', e);
        }
    }

    let portadaActualUrl = config.portadaUrl || null;

    // Función unificada para obtener el estado actual del post desde el DOM
    function obtenerDatosEditor() {
        const tituloEl = document.getElementById('editorTitulo');
        const extractoEl = document.getElementById('inputExtracto');
        const slugEl = document.getElementById('inputSlug');
        const categoriaEl = document.getElementById('selectCategoria');

        return {
            postId: config.postId || null,
            titulo: tituloEl ? tituloEl.value.trim() : '',
            contenido: getEditorContent(),
            extracto: extractoEl ? extractoEl.value.trim() : '',
            slug: slugEl ? slugEl.value.trim() : (config.postSlug || ''),
            categoria_id: categoriaEl && categoriaEl.value ? categoriaEl.value : null,
            etiquetas: getSelectedTags(),
            portadaUrl: portadaActualUrl
        };
    }

    // 2. Título Autoextensible y Contador
    const textareaTitulo = document.getElementById('editorTitulo');
    const tituloCharCount = document.getElementById('tituloCharCount');
    const inputSlug = document.getElementById('inputSlug');

    function ajustarAlturaTitulo() {
        if (!textareaTitulo) return;
        textareaTitulo.style.height = 'auto';
        textareaTitulo.style.height = textareaTitulo.scrollHeight + 'px';
    }

    if (textareaTitulo) {
        ajustarAlturaTitulo();
        if (tituloCharCount) tituloCharCount.textContent = textareaTitulo.value.length;

        textareaTitulo.addEventListener('input', () => {
            ajustarAlturaTitulo();
            if (tituloCharCount) tituloCharCount.textContent = textareaTitulo.value.length;

            // Si es un post nuevo y el slug no ha sido editado a mano, sincronizarlo
            if (!config.publicadoEn && inputSlug && (!config.postSlug || inputSlug.value === slugify(config.tituloInicial || ''))) {
                inputSlug.value = slugify(textareaTitulo.value);
            }

            notificarModificacion();
        });
    }

    // 3. Inicializar Módulos del Estudio
    initChecklist();

    const autoguardado = initAutoguardado(config, obtenerDatosEditor);

    function notificarModificacion() {
        const datos = obtenerDatosEditor();
        sincronizarPreviews(datos);
        evaluarChecklist(datos);
        autoguardado.marcarModificado();
    }

    initPortada(config, (nuevaUrl) => {
        portadaActualUrl = nuevaUrl;
        notificarModificacion();
    });

    initEtiquetas(() => {
        notificarModificacion();
    });

    initLateral(config, () => {
        notificarModificacion();
    });

    initCKEditor(() => {
        onEditorChange(() => {
            notificarModificacion();
        });
        // Evaluación inicial tras cargar CKEditor
        const datos = obtenerDatosEditor();
        sincronizarPreviews(datos);
        evaluarChecklist(datos);
    });

    initVistaPrevia(obtenerDatosEditor);

    initHistorial(config, (revisionRestaurada) => {
        if (textareaTitulo) {
            textareaTitulo.value = revisionRestaurada.titulo;
            ajustarAlturaTitulo();
            if (tituloCharCount) tituloCharCount.textContent = textareaTitulo.value.length;
        }
        setEditorContent(revisionRestaurada.contenido);
        const extractoEl = document.getElementById('inputExtracto');
        if (extractoEl) extractoEl.value = revisionRestaurada.extracto || '';
        notificarModificacion();
        autoguardado.guardarInmediato('restauracion');
    });

    // 4. Modo Enfoque / Concentración
    const btnEnfoque = document.getElementById('btnAlternarEnfoque');
    const btnEnfoqueMobile = document.getElementById('btnAlternarEnfoqueMobile');
    const btnSalirEnfoque = document.getElementById('btnSalirModoEnfoque');

    function alternarModoEnfoque() {
        document.body.classList.toggle('focus-mode-active');
    }

    if (btnEnfoque) btnEnfoque.addEventListener('click', alternarModoEnfoque);
    if (btnEnfoqueMobile) btnEnfoqueMobile.addEventListener('click', alternarModoEnfoque);
    if (btnSalirEnfoque) btnSalirEnfoque.addEventListener('click', alternarModoEnfoque);

    // 4b. Manejo robusto de Configuración y SEO (desktop barra lateral + móvil offcanvas)
    const btnMenuConfigSeo = document.getElementById('btnMenuConfigSeo');
    if (btnMenuConfigSeo) {
        btnMenuConfigSeo.addEventListener('click', function(e) {
            e.preventDefault();
            // Salir de modo concentración si estaba activo para que la barra lateral sea visible
            document.body.classList.remove('focus-mode-active');

            const isDesktop = window.innerWidth >= 992;
            if (isDesktop) {
                // En escritorio: activar pestaña SEO en el panel lateral
                const tabSeo = document.getElementById('tab-seo');
                if (tabSeo && window.bootstrap && window.bootstrap.Tab) {
                    const tabInst = window.bootstrap.Tab.getOrCreateInstance(tabSeo);
                    tabInst.show();
                }
                const paneSeo = document.getElementById('pane-seo-wrap');
                if (paneSeo) {
                    paneSeo.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            } else {
                // En móvil / tablet: abrir offcanvas inferior y activar pestaña SEO
                const offcanvasEl = document.getElementById('offcanvasLateral');
                if (offcanvasEl && window.bootstrap && window.bootstrap.Offcanvas) {
                    const oc = window.bootstrap.Offcanvas.getOrCreateInstance(offcanvasEl);
                    oc.show();
                    const tabSeoMobile = offcanvasEl.querySelector('[data-bs-target="#pane-seo-wrap"]');
                    if (tabSeoMobile && window.bootstrap && window.bootstrap.Tab) {
                        window.bootstrap.Tab.getOrCreateInstance(tabSeoMobile).show();
                    }
                }
            }
        });
    }

    // Soporte para visualViewport en teclados virtuales de iOS/Android
    if (window.visualViewport) {
        const actualizarViewportTeclado = () => {
            const h = window.visualViewport.height;
            document.documentElement.style.setProperty('--visual-viewport-height', `${h}px`);
        };
        window.visualViewport.addEventListener('resize', actualizarViewportTeclado);
        window.visualViewport.addEventListener('scroll', actualizarViewportTeclado);
        actualizarViewportTeclado();
    }

    // 5. Atajos de teclado y Guardado manual
    const btnGuardarManual = document.getElementById('btnGuardarManual');
    if (btnGuardarManual) {
        btnGuardarManual.addEventListener('click', () => {
            autoguardado.guardarInmediato('manual');
        });
    }

    initAtajos({
        onGuardar: () => autoguardado.guardarInmediato('manual'),
        onPublicar: () => {
            const btnModalPub = document.getElementById('btnAbrirModalPublicar');
            if (btnModalPub) btnModalPub.click();
        },
        onAlternarEnfoque: alternarModoEnfoque,
        onVistaPrevia: () => {
            const btnVista = document.getElementById('btnAbrirVistaPrevia');
            if (btnVista) btnVista.click();
        }
    });

    // 6. Workflow Modal de Publicación y Programación
    const modalPublicarEl = document.getElementById('modalPublicar');
    const bloqueoAlert = document.getElementById('modalPublicarBloqueoAlert');
    const bloqueoList = document.getElementById('modalPublicarBloqueoList');
    const btnConfirmarPublicar = document.getElementById('btnConfirmarPublicarAccion');
    const txtConfirmarBtn = document.getElementById('txtConfirmarPublicarBtn');
    const spinnerPublicar = document.getElementById('spinnerPublicarBtn');
    const radioAhora = document.getElementById('radioPublicarAhora');
    const radioProg = document.getElementById('radioProgramar');
    const campoProg = document.getElementById('campoFechaProgramada');
    const inputFechaProg = document.getElementById('inputFechaProgramada');
    const noticeText = document.getElementById('destinatariosNoticeText');

    if (modalPublicarEl) {
        modalPublicarEl.addEventListener('show.bs.modal', async () => {
            const datos = obtenerDatosEditor();
            const { aptoParaPublicar, pendientesObligatorios } = evaluarChecklist(datos);

            if (!aptoParaPublicar) {
                bloqueoList.innerHTML = pendientesObligatorios.map(p => `<li>${p}</li>`).join('');
                bloqueoAlert.classList.remove('d-none');
                btnConfirmarPublicar.disabled = true;
            } else {
                bloqueoAlert.classList.add('d-none');
                btnConfirmarPublicar.disabled = false;
            }

            // Consultar número de destinatarios potenciales
            if (datos.categoria_id && noticeText) {
                try {
                    const resp = await fetch(`/panel/api/destinatarios-count/?categoria_id=${datos.categoria_id}`);
                    const data = await resp.json();
                    if (data.ok) {
                        noticeText.textContent = `Se notificará a ${data.seguidores} seguidores y ${data.suscriptores} suscriptores de la categoría.`;
                    }
                } catch (_) {}
            }
        });

        // Alternar campo de programación
        if (radioAhora && radioProg && campoProg) {
            radioAhora.addEventListener('change', () => {
                if (radioAhora.checked) {
                    campoProg.classList.add('d-none');
                    if (txtConfirmarBtn) txtConfirmarBtn.textContent = config.estado === 'publicado' ? 'Actualizar ahora' : 'Publicar ahora';
                }
            });

            radioProg.addEventListener('change', () => {
                if (radioProg.checked) {
                    campoProg.classList.remove('d-none');
                    if (txtConfirmarBtn) txtConfirmarBtn.textContent = 'Programar publicación';
                    // Sugerir fecha por defecto: 1 hora en el futuro
                    if (inputFechaProg && !inputFechaProg.value) {
                        const d = new Date(Date.now() + 60 * 60 * 1000);
                        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
                        inputFechaProg.value = d.toISOString().slice(0, 16);
                    }
                }
            });
        }

        // Ejecutar publicación o programación
        if (btnConfirmarPublicar) {
            btnConfirmarPublicar.addEventListener('click', async () => {
                const datos = obtenerDatosEditor();
                const esProgramado = radioProg && radioProg.checked;

                btnConfirmarPublicar.disabled = true;
                if (spinnerPublicar) spinnerPublicar.classList.remove('d-none');

                try {
                    // Primero asegurar que el último texto esté guardado
                    await autoguardado.guardarInmediato('manual');

                    let endpoint = '/panel/api/publicar/';
                    const body = {
                        post_id: config.postId,
                        slug: datos.slug,
                        titulo: datos.titulo,
                        contenido: datos.contenido,
                        extracto: datos.extracto,
                        categoria_id: datos.categoria_id,
                        etiquetas: datos.etiquetas
                    };

                    if (esProgramado) {
                        endpoint = '/panel/api/programar/';
                        body.programado_para = inputFechaProg ? inputFechaProg.value : null;
                    }

                    const resp = await fetch(endpoint, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken(),
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(body)
                    });

                    const data = await resp.json();
                    if (data.ok) {
                        autoguardado.limpiarEstadoLocal();

                        // Mostrar pantalla de éxito
                        const contenidoModal = document.getElementById('modalPublicarContenido');
                        const exitoModal = document.getElementById('modalPublicarExito');
                        const footerModal = document.getElementById('modalPublicarFooter');
                        const btnVerPost = document.getElementById('btnExitoVerPost');
                        const exitoTitulo = document.getElementById('modalPublicarExitoTitulo');
                        const exitoMsg = document.getElementById('modalPublicarExitoMsg');

                        if (contenidoModal) contenidoModal.classList.add('d-none');
                        if (footerModal) footerModal.classList.add('d-none');
                        if (exitoModal) exitoModal.classList.remove('d-none');

                        if (esProgramado) {
                            if (exitoTitulo) exitoTitulo.textContent = '¡Artículo programado con éxito!';
                            if (exitoMsg) exitoMsg.textContent = `Tu publicación se lanzará automáticamente el ${new Date(data.programado_para).toLocaleString('es-ES')}.`;
                            if (btnVerPost) btnVerPost.classList.add('d-none');
                        } else {
                            if (btnVerPost && data.url) btnVerPost.href = data.url;
                        }

                        // Actualizar badge de estado en la cabecera
                        const statusBadge = document.getElementById('editorStatusBadge');
                        if (statusBadge) {
                            if (esProgramado) {
                                statusBadge.className = 'badge rounded-pill fw-semibold editor-status-badge bg-info-subtle text-info-emphasis border border-info-subtle';
                                statusBadge.innerHTML = '<i class="bi bi-clock-fill me-1" aria-hidden="true"></i>Programado';
                            } else {
                                statusBadge.className = 'badge rounded-pill fw-semibold editor-status-badge bg-success-subtle text-success border border-success-subtle';
                                statusBadge.innerHTML = '<i class="bi bi-check-circle-fill me-1" aria-hidden="true"></i>Publicado';
                            }
                        }
                    } else {
                        alert(data.error || 'Ocurrió un error al procesar la publicación.');
                    }
                } catch (err) {
                    console.error('Error publicando:', err);
                    alert('Error de conexión.');
                } finally {
                    btnConfirmarPublicar.disabled = false;
                    if (spinnerPublicar) spinnerPublicar.classList.add('d-none');
                }
            });
        }
    }

    // 7. Acciones Secundarias: Despublicar y Duplicar
    const btnDespublicar = document.getElementById('btnAccionDespublicar');
    if (btnDespublicar) {
        btnDespublicar.addEventListener('click', async () => {
            if (!confirm('¿Deseas pasar este artículo a borrador? Dejará de ser visible públicamente.')) return;

            try {
                const resp = await fetch('/panel/api/despublicar/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ post_id: config.postId })
                });
                const data = await resp.json();
                if (data.ok) {
                    window.location.reload();
                } else {
                    alert(data.error || 'Error al despublicar.');
                }
            } catch (err) {
                console.error('Error:', err);
            }
        });
    }

    const btnsDuplicar = [document.getElementById('btnAccionDuplicar'), document.getElementById('btnDuplicarAvanzado')];
    btnsDuplicar.forEach(btn => {
        if (!btn) return;
        btn.addEventListener('click', async () => {
            if (!confirm('¿Deseas duplicar este artículo como un nuevo borrador?')) return;

            try {
                const resp = await fetch('/panel/api/duplicar/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ post_id: config.postId })
                });
                const data = await resp.json();
                if (data.ok && data.url_editor) {
                    window.location.href = data.url_editor;
                } else {
                    alert(data.error || 'Error al duplicar.');
                }
            } catch (err) {
                console.error('Error duplicando post:', err);
            }
        });
    });
});

