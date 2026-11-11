#!/usr/bin/env python
"""
Diagnóstico Fase 0: Verificación de hipótesis de causas raíz.
Ejecuta comprobaciones con Playwright sobre el sitio en modo producción (DEBUG=False, WhiteNoise).
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
SALIDA_DIR = BASE_DIR / "capturas_diagnostico"
SALIDA_DIR.mkdir(exist_ok=True)

def main():
    env = os.environ.copy()
    env["DEBUG"] = "False"
    env["ALLOWED_HOSTS"] = "localhost,127.0.0.1,0.0.0.0,testserver"
    env["SECURE_SSL_REDIRECT"] = "False"

    port = 8001
    server_url = f"http://127.0.0.1:{port}"

    print(f"Iniciando servidor Django local con DEBUG=False en {server_url}...")
    server_process = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=str(BASE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    time.sleep(3)

    reporte = {
        "estaticos_404": [],
        "capas_css": {},
        "container_size": {},
        "rejillas": {},
        "variables_bootstrap": {}
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            # Capturar errores de red 404
            def on_response(response):
                if response.status >= 400:
                    reporte["estaticos_404"].append({
                        "url": response.url,
                        "status": response.status
                    })
            page.on("response", on_response)

            # 1. Página de Inicio
            print("\n--- Verificando Página de Inicio ---")
            page.goto(f"{server_url}/", wait_until="networkidle")
            page.screenshot(path=str(SALIDA_DIR / "01_inicio_desktop.png"), full_page=True)

            # Evidencia A: Capas CSS y Bootstrap
            # Verificar si las reglas de Bootstrap sobreescriben las reglas de @layer
            css_info = page.evaluate("""() => {
                const body = document.body;
                const btn = document.querySelector('.btn') || document.querySelector('button');
                const card = document.querySelector('.card');
                const link = document.querySelector('a');
                
                const bodyStyle = window.getComputedStyle(body);
                const btnStyle = btn ? window.getComputedStyle(btn) : null;
                const linkStyle = link ? window.getComputedStyle(link) : null;
                
                // Inspeccionar capas CSS registradas en document.styleSheets
                const layers = [];
                for (const sheet of document.styleSheets) {
                    try {
                        for (const rule of sheet.cssRules) {
                            if (rule.constructor.name === 'CSSLayerBlockRule') {
                                layers.push(rule.name);
                            }
                        }
                    } catch (e) {}
                }

                return {
                    layers: layers,
                    bodyFont: bodyStyle.fontFamily,
                    bodyBg: bodyStyle.backgroundColor,
                    bodyColor: bodyStyle.color,
                    bsBodyBg: bodyStyle.getPropertyValue('--bs-body-bg'),
                    colorBgToken: bodyStyle.getPropertyValue('--color-background'),
                    linkTextDeco: linkStyle ? linkStyle.textDecorationLine : null,
                    btnRadius: btnStyle ? btnStyle.borderRadius : null
                };
            }""")
            reporte["capas_css"] = css_info

            # Evidencia B: container-type: inline-size
            container_info = page.evaluate("""() => {
                const feedContainer = document.querySelector('.app-feed-container');
                const feedParent = feedContainer ? feedContainer.parentElement : null;
                return {
                    feedContainerWidth: feedContainer ? feedContainer.getBoundingClientRect().width : null,
                    feedParentWidth: feedParent ? feedParent.getBoundingClientRect().width : null,
                    feedContainerComputedWidth: feedContainer ? window.getComputedStyle(feedContainer).width : null,
                    feedContainerContainerType: feedContainer ? window.getComputedStyle(feedContainer).containerType : null
                };
            }""")
            reporte["container_size"]["inicio"] = container_info

            # 2. Pantalla de Artículo (post_detail)
            print("\n--- Verificando Artículo ---")
            post_url = f"{server_url}/post/sistemas-de-diseno-accesibles-en-django-con-variables-css-y-modo-oscuro/"
            print(f"Navegando a artículo: {post_url}")
            page.goto(post_url, wait_until="networkidle")
            page.screenshot(path=str(SALIDA_DIR / "02_articulo_desktop.png"), full_page=True)

            rejillas_info = page.evaluate("""() => {
                const main = document.querySelector('.app-main');
                const sidebarRight = document.querySelector('.app-sidebar-right');
                const articleContainer = document.querySelector('.app-article-container');
                const articleLayout = document.querySelector('.article-reading-layout');
                const actionRail = document.querySelector('.article-action-rail-left');
                const readingColumn = document.querySelector('.article-reading-column');
                
                return {
                    mainWidth: main ? main.getBoundingClientRect().width : null,
                    sidebarRightDisplay: sidebarRight ? window.getComputedStyle(sidebarRight).display : null,
                    sidebarRightWidth: sidebarRight ? sidebarRight.getBoundingClientRect().width : null,
                    articleContainerWidth: articleContainer ? articleContainer.getBoundingClientRect().width : null,
                    articleLayoutWidth: articleLayout ? articleLayout.getBoundingClientRect().width : null,
                    actionRailWidth: actionRail ? actionRail.getBoundingClientRect().width : null,
                    readingColumnWidth: readingColumn ? readingColumn.getBoundingClientRect().width : null
                };
            }""")
            reporte["rejillas"]["articulo"] = rejillas_info

            # 2b. Pantalla de Comunidad (categoria_hub)
            print("\n--- Verificando Comunidad ---")
            cat_url = f"{server_url}/categoria/desarrollo-web/"
            page.goto(cat_url, wait_until="networkidle")
            page.screenshot(path=str(SALIDA_DIR / "02b_comunidad_desktop.png"), full_page=True)

            # 3. Pantalla de Login / Auth (verificar variables Bootstrap vs Tokens)
            print("\n--- Verificando Login (Paleta y Bootstrap) ---")
            page.goto(f"{server_url}/cuentas/login/", wait_until="networkidle")
            page.screenshot(path=str(SALIDA_DIR / "03_login_desktop.png"), full_page=True)

            login_vars = page.evaluate("""() => {
                const body = document.body;
                const card = document.querySelector('.card, .auth-card') || body;
                const bStyle = window.getComputedStyle(body);
                const cStyle = window.getComputedStyle(card);
                return {
                    bodyBg: bStyle.backgroundColor,
                    bsBodyBg: bStyle.getPropertyValue('--bs-body-bg'),
                    colorBgToken: bStyle.getPropertyValue('--color-background'),
                    cardBg: cStyle.backgroundColor,
                    bsCardBg: cStyle.getPropertyValue('--bs-card-bg'),
                    colorSurfaceToken: cStyle.getPropertyValue('--color-surface')
                };
            }""")
            reporte["variables_bootstrap"]["login"] = login_vars

            browser.close()

    finally:
        server_process.terminate()
        server_process.wait()

    print("\n================ RESULTADOS DEL DIAGNÓSTICO FASE 0 ================")
    print(f"Estáticos 404: {len(reporte['estaticos_404'])}")
    for err in reporte['estaticos_404']:
        print(f"  - {err['status']}: {err['url']}")

    print("\nCapas CSS:")
    for k, v in reporte["capas_css"].items():
        print(f"  {k}: {v}")

    print("\nContainer Size (Inicio):")
    for k, v in reporte["container_size"].items():
        print(f"  {k}: {v}")

    print("\nRejillas (Artículo):")
    for k, v in reporte["rejillas"].items():
        print(f"  {k}: {v}")

    print("\nVariables Bootstrap vs Tokens (Login):")
    for k, v in reporte["variables_bootstrap"].items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
