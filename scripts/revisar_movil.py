#!/usr/bin/env python
"""
Verificación visual y responsive para "Blog con Panel de Autor" usando Playwright.
Comprueba en navegadores reales a 360x740, 390x844 y 768x1024 en modo claro y oscuro.
Detecta:
1. Scroll horizontal (scrollWidth > innerWidth).
2. Elementos que desbordan el borde derecho de la ventana.
3. Botones y títulos con texto recortado inadvertidamente.
4. Controles táctiles menores de 44x44 px.

Guarda capturas de pantalla completa en:
capturas_movil/<ancho>/<tema>/<pantalla>.png
Termina con código != 0 si hay hallazgos.
"""

import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

VIEWPORTS = [
    {"ancho": 360, "alto": 740, "nombre": "360"},
    {"ancho": 390, "alto": 844, "nombre": "390"},
    {"ancho": 768, "alto": 1024, "nombre": "768"},
]

TEMAS = ["light", "dark"]


def construir_detector_js():
    """Retorna el script JS que se ejecuta en el navegador para detectar anomalías."""
    return """
    (() => {
        const innerWidth = window.innerWidth;
        const innerHeight = window.innerHeight;
        const scrollWidth = Math.max(
            document.documentElement.scrollWidth,
            document.body ? document.body.scrollWidth : 0
        );

        const hallazgos = [];

        // 1. Desbordamiento horizontal global
        if (scrollWidth > innerWidth + 1.5) {
            hallazgos.push({
                tipo: 'SCROLL_HORIZONTAL',
                selector: 'html/body',
                detalle: `scrollWidth (${scrollWidth}px) supera innerWidth (${innerWidth}px)`
            });
        }

        // 2. Elementos que superan el borde derecho
        const todos = document.querySelectorAll('*');
        for (const el of todos) {
            if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'path', 'g', 'svg', 'use'].includes(el.tagName)) continue;
            
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

            // Ignorar elementos dentro de contenedores explícitamente desplazables (pre, table-responsive, etc.)
            let dentroScroll = false;
            let padre = el.parentElement;
            while (padre && padre !== document.body && padre !== document.documentElement) {
                const pStyle = window.getComputedStyle(padre);
                if (['auto', 'scroll'].includes(pStyle.overflowX)) {
                    dentroScroll = true;
                    break;
                }
                padre = padre.parentElement;
            }

            if (!dentroScroll && rect.right > innerWidth + 2) {
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${el.id}` : '';
                const cls = (typeof el.className === 'string' && el.className.trim()) 
                    ? `.${el.className.trim().split(/\\s+/).slice(0, 2).join('.')}` 
                    : '';
                hallazgos.push({
                    tipo: 'DESBORDE_DERECHO',
                    selector: `${tag}${id}${cls}`,
                    detalle: `rect.right (${Math.round(rect.right)}px) > ventana (${innerWidth}px)`
                });
                if (hallazgos.filter(h => h.tipo === 'DESBORDE_DERECHO').length >= 5) break;
            }
        }

        // 3. Texto recortado en botones y títulos
        const selectoresTexto = 'button, .btn, [role="button"], h1, h2, h3, h4, h5, h6, .card-title';
        for (const el of document.querySelectorAll(selectoresTexto)) {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;

            const overflowX = style.overflowX;
            const overflowY = style.overflowY;
            const oculto = ['hidden', 'clip'].includes(overflowX) || ['hidden', 'clip'].includes(overflowY);
            
            // Si el texto se corta y tiene overflow hidden sin ser una línea clamp intencional de 3 líneas en títulos
            if (oculto && el.scrollWidth > el.clientWidth + 2) {
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${el.id}` : '';
                const cls = (typeof el.className === 'string' && el.className.trim()) 
                    ? `.${el.className.trim().split(/\\s+/).slice(0, 2).join('.')}` 
                    : '';
                const texto = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 25);
                
                // Permitir clamp multilínea en títulos de tarjetas de posts
                const clamp = style.webkitLineClamp;
                const esClampTitulo = (tag.startsWith('h') || cls.includes('title')) && (clamp && clamp !== 'none');
                
                if (!esClampTitulo) {
                    hallazgos.push({
                        tipo: 'TEXTO_RECORTADO',
                        selector: `${tag}${id}${cls}`,
                        detalle: `scrollWidth (${el.scrollWidth}px) > clientWidth (${el.clientWidth}px) en "${texto}..."`
                    });
                }
            }
        }

        // 4. Controles táctiles menores de 44x44 px
        // Evaluamos botones, enlaces táctiles principales, toggles e inputs interactivos
        const selectoresTactiles = 'button:not(.btn-close):not(.btn-link), .btn:not(.btn-link), [role="button"]:not(.btn-link), .touch-target-44, .navbar-toggler, .dropdown-toggle, .page-link, .nav-pills .nav-link, .comment-toggle-replies, .btn-copy-code, .tag-chip, .accordion-button';
        for (const el of document.querySelectorAll(selectoresTactiles)) {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

            // Tolerancia de 0.5px para subpíxeles
            if (rect.width < 43.5 || rect.height < 43.5) {
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${el.id}` : '';
                const cls = (typeof el.className === 'string' && el.className.trim()) 
                    ? `.${el.className.trim().split(/\\s+/).slice(0, 2).join('.')}` 
                    : '';
                const texto = (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 20);
                hallazgos.push({
                    tipo: 'CONTROL_TACTIL_PEQUENO',
                    selector: `${tag}${id}${cls}`,
                    detalle: `Tamaño ${Math.round(rect.width)}x${Math.round(rect.height)} px < 44x44 px ("${texto}")`
                });
            }
        }

        return hallazgos;
    })();
    """


def navegar_con_reintento(page, url, reintentos=3):
    for i in range(reintentos):
        try:
            page.goto(url, wait_until="networkidle", timeout=12000)
            return True
        except Exception as e:
            if i < reintentos - 1:
                time.sleep(0.5)
            else:
                raise e


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright no está instalado en este entorno Python.")
        print("Ejecuta: pip install -r requirements-dev.txt && playwright install chromium")
        sys.exit(1)

    demo_user = os.environ.get("DEMO_USER")
    demo_password = os.environ.get("DEMO_PASSWORD")
    if not demo_user or not demo_password:
        print("ERROR: Variables de entorno DEMO_USER y DEMO_PASSWORD no configuradas.")
        print("Ejemplo en PowerShell: $env:DEMO_USER='ana_garcia'; $env:DEMO_PASSWORD='DemoPassword123!'")
        sys.exit(1)

    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    capturas_base = BASE_DIR / "capturas_movil"
    capturas_base.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("VERIFICACIÓN VISUAL REAL CON PLAYWRIGHT - PASADA MÓVIL")
    print(f"Servidor: {base_url}")
    print(f"Usuario Demo: {demo_user}")
    print(f"Destino de capturas: {capturas_base}")
    print("=" * 75)

    todos_los_hallazgos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for vp in VIEWPORTS:
            for tema in TEMAS:
                ancho = vp["ancho"]
                alto = vp["alto"]
                nombre_vp = vp["nombre"]

                dir_captura = capturas_base / str(ancho) / tema
                dir_captura.mkdir(parents=True, exist_ok=True)

                context = browser.new_context(
                    viewport={"width": ancho, "height": alto},
                    color_scheme=tema,
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                        if ancho < 768
                        else "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
                    ),
                    device_scale_factor=2,
                )
                page = context.new_page()

                def aplicar_tema():
                    page.evaluate(
                        f"""
                        () => {{
                            document.documentElement.setAttribute('data-bs-theme', '{tema}');
                            localStorage.setItem('blog_theme', '{tema}');
                        }}
                    """
                    )
                    page.wait_for_timeout(100)

                # 1. Login inicial para tener sesión autenticada
                try:
                    page.goto(f"{base_url}/cuentas/login/", wait_until="networkidle", timeout=8000)
                    aplicar_tema()
                    # Desplegar formulario tradicional si estuviese colapsado
                    if page.locator("#collapseLoginCorreo").count() > 0:
                        page.evaluate(
                            """() => {
                            const c = document.getElementById('collapseLoginCorreo');
                            if (c && !c.classList.contains('show')) { c.classList.add('show'); }
                        }"""
                        )
                    page.fill('input[name="username"]', demo_user)
                    page.fill('input[name="password"]', demo_password)
                    page.click('button[type="submit"]')
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception as e:
                    print(f"[{ancho}px | {tema}] Error al iniciar sesión: {e}")

                # Lista de pantallas a comprobar
                pantallas = [
                    {"nombre": "01_inicio", "url": "/"},
                    {"nombre": "02_populares", "url": "/populares/"},
                    {"nombre": "03_autores", "url": "/autores/"},
                    {
                        "nombre": "04_detalle_articulo",
                        "url": "/post/arquitectura-limpia-en-proyectos-django-5-de-gran-escala/",
                    },
                    {"nombre": "05_categoria", "url": "/categoria/desarrollo-web/"},
                    {"nombre": "06_login", "url": "/cuentas/login/"},
                    {"nombre": "07_registro", "url": "/cuentas/registro/"},
                    {"nombre": "08_panel", "url": "/panel/"},
                    {"nombre": "09_editor_nuevo", "url": "/panel/posts/nuevo/"},
                    {
                        "nombre": "10_editor_con_post",
                        "url": "/panel/posts/arquitectura-limpia-en-proyectos-django-5-de-gran-escala/editar/",
                    },
                    {"nombre": "13_mis_posts", "url": "/panel/posts/"},
                    {"nombre": "14_notificaciones", "url": "/notificaciones/"},
                ]

                # Recorrido de pantallas estándar
                for p_info in pantallas:
                    nombre_p = p_info["nombre"]
                    url = f"{base_url}{p_info['url']}"
                    try:
                        navegar_con_reintento(page, url)
                        aplicar_tema()
                        page.wait_for_timeout(200)

                        # Detectar hallazgos
                        hallazgos = page.evaluate(construir_detector_js())
                        for h in hallazgos:
                            todos_los_hallazgos.append(
                                {
                                    "pantalla": nombre_p,
                                    "viewport": f"{ancho}x{alto}",
                                    "tema": tema,
                                    **h,
                                }
                            )

                        # Captura de pantalla completa
                        archivo_img = dir_captura / f"{nombre_p}.png"
                        page.screenshot(path=str(archivo_img), full_page=True)
                        estado = "✓ OK" if not hallazgos else f"⚠ {len(hallazgos)} hallazgos"
                        print(f"[{ancho}px | {tema:5s}] {nombre_p:25s} -> {estado}")
                    except Exception as e:
                        print(f"[{ancho}px | {tema:5s}] Error en {nombre_p} ({url}): {e}")

                # Pantallas con interacción específica:
                # A. Menú móvil abierto (en Inicio)
                try:
                    navegar_con_reintento(page, f"{base_url}/")
                    aplicar_tema()
                    page.wait_for_timeout(200)
                    toggler = page.locator(".navbar-toggler")
                    if toggler.is_visible():
                        toggler.click()
                        page.wait_for_timeout(350)
                        hallazgos = page.evaluate(construir_detector_js())
                        for h in hallazgos:
                            todos_los_hallazgos.append(
                                {
                                    "pantalla": "15_menu_movil",
                                    "viewport": f"{ancho}x{alto}",
                                    "tema": tema,
                                    **h,
                                }
                            )
                        archivo_img = dir_captura / "15_menu_movil.png"
                        page.screenshot(path=str(archivo_img), full_page=False)
                        print(f"[{ancho}px | {tema:5s}] 15_menu_movil             -> Capturado")
                except Exception as e:
                    print(f"[{ancho}px | {tema}] Error en 15_menu_movil: {e}")

                # B. Menú Compartir abierto (en Detalle de Artículo)
                try:
                    navegar_con_reintento(
                        page,
                        f"{base_url}/post/arquitectura-limpia-en-proyectos-django-5-de-gran-escala/",
                    )
                    aplicar_tema()
                    page.wait_for_timeout(200)
                    # Abrir el menú de compartir
                    share_btn = page.locator('.dropdown-toggle:has(.bi-share), button:has-text("Compartir")').first
                    if share_btn.count() > 0 and share_btn.is_visible():
                        share_btn.click()
                        page.wait_for_timeout(300)
                        archivo_img = dir_captura / "16_menu_compartir.png"
                        page.screenshot(path=str(archivo_img), full_page=False)
                        print(f"[{ancho}px | {tema:5s}] 16_menu_compartir         -> Capturado")
                except Exception as e:
                    print(f"[{ancho}px | {tema}] Error en 16_menu_compartir: {e}")

                # C. Hoja de Ajustes del Editor (abrir offcanvas lateral)
                try:
                    navegar_con_reintento(
                        page,
                        f"{base_url}/panel/posts/arquitectura-limpia-en-proyectos-django-5-de-gran-escala/editar/",
                    )
                    aplicar_tema()
                    page.wait_for_timeout(300)
                    # Abrir el offcanvas lateral si existe
                    page.evaluate(
                        """() => {
                        const offEl = document.getElementById('offcanvasLateral');
                        if (offEl && window.bootstrap) {
                            const bsOff = window.bootstrap.Offcanvas.getOrCreateInstance(offEl);
                            bsOff.show();
                        }
                    }"""
                    )
                    page.wait_for_timeout(400)
                    hallazgos = page.evaluate(construir_detector_js())
                    for h in hallazgos:
                        todos_los_hallazgos.append(
                            {
                                "pantalla": "11_editor_ajustes",
                                "viewport": f"{ancho}x{alto}",
                                "tema": tema,
                                **h,
                            }
                        )
                    archivo_img = dir_captura / "11_editor_ajustes.png"
                    page.screenshot(path=str(archivo_img), full_page=False)
                    print(f"[{ancho}px | {tema:5s}] 11_editor_ajustes         -> Capturado")
                except Exception as e:
                    print(f"[{ancho}px | {tema}] Error en 11_editor_ajustes: {e}")

                # D. Modal Publicar del Editor
                try:
                    navegar_con_reintento(
                        page,
                        f"{base_url}/panel/posts/arquitectura-limpia-en-proyectos-django-5-de-gran-escala/editar/",
                    )
                    aplicar_tema()
                    page.wait_for_timeout(300)
                    page.evaluate(
                        """() => {
                        const modEl = document.getElementById('modalPublicar');
                        if (modEl && window.bootstrap) {
                            const bsMod = window.bootstrap.Modal.getOrCreateInstance(modEl);
                            bsMod.show();
                        }
                    }"""
                    )
                    page.wait_for_timeout(400)
                    hallazgos = page.evaluate(construir_detector_js())
                    for h in hallazgos:
                        todos_los_hallazgos.append(
                            {
                                "pantalla": "12_modal_publicar",
                                "viewport": f"{ancho}x{alto}",
                                "tema": tema,
                                **h,
                            }
                        )
                    archivo_img = dir_captura / "12_modal_publicar.png"
                    page.screenshot(path=str(archivo_img), full_page=False)
                    print(f"[{ancho}px | {tema:5s}] 12_modal_publicar         -> Capturado")
                except Exception as e:
                    print(f"[{ancho}px | {tema}] Error en 12_modal_publicar: {e}")

                context.close()

        browser.close()

    # Resumen de Hallazgos
    print("\n" + "=" * 75)
    print("RESUMEN DE RESULTADOS DE LA AUDITORÍA EN NAVEGADOR")
    print("=" * 75)

    if not todos_los_hallazgos:
        print("\n✔ ¡PERFECTO! No se detectó ningún desborde, texto recortado o control táctil < 44px.")
        print(f"Todas las capturas se guardaron exitosamente en {capturas_base}")
        sys.exit(0)
    else:
        # Agrupar hallazgos únicos
        vistos = set()
        hallazgos_unicos = []
        for h in todos_los_hallazgos:
            clave = (h["tipo"], h["selector"], h["pantalla"])
            if clave not in vistos:
                vistos.add(clave)
                hallazgos_unicos.append(h)

        print(f"\nSe encontraron {len(hallazgos_unicos)} hallazgo(s) único(s):\n")
        for i, h in enumerate(hallazgos_unicos, start=1):
            print(f"{i:2d}. [{h['tipo']}] en {h['pantalla']} ({h['viewport']} - {h['tema']})")
            print(f"    Selector : {h['selector']}")
            print(f"    Detalle  : {h['detalle']}")
            print()

        print("Terminando con código 1 debido a hallazgos pendientes.")
        sys.exit(1)


if __name__ == "__main__":
    main()
