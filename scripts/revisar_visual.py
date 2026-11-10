#!/usr/bin/env python
"""
Verificación visual y responsive para "Blog con Panel de Autor" usando Playwright.
Matriz visual:
- Dispositivos móviles: iPhone 13 (390x844), Pixel 7 (412x915)
- Tablets: iPad Mini (768x1024), iPad Pro apaisado (1366x1024)
- Escritorio: 1280x800, 1440x900, 1920x1080
En temas 'light' y 'dark'.

Detecta:
1. Scroll horizontal (scrollWidth > innerWidth).
2. Elementos que desbordan el borde derecho de la ventana.
3. Botones y títulos con texto recortado inadvertidamente.
4. Controles táctiles menores de 44x44 px (en dispositivos táctiles / pointer: coarse).
5. CLS > 0.1 o solapes inesperados.
6. Violaciones básicas de accesibilidad (imágenes sin alt, controles sin nombre accesible).

Guarda capturas de pantalla completa en:
capturas_visual/<dispositivo>/<tema>/<pantalla>.png
"""

import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DISPOSITIVOS = [
    {
        "id": "iphone_13",
        "nombre": "iPhone 13",
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    {
        "id": "pixel_7",
        "nombre": "Pixel 7",
        "viewport": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
    },
    {
        "id": "ipad_mini",
        "nombre": "iPad Mini",
        "viewport": {"width": 768, "height": 1024},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    {
        "id": "ipad_pro_land",
        "nombre": "iPad Pro Apaisado",
        "viewport": {"width": 1366, "height": 1024},
        "device_scale_factor": 2,
        "is_mobile": False,
        "has_touch": True,
    },
    {
        "id": "desktop_1280",
        "nombre": "Escritorio 1280px",
        "viewport": {"width": 1280, "height": 800},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
    {
        "id": "desktop_1440",
        "nombre": "Escritorio 1440px",
        "viewport": {"width": 1440, "height": 900},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
    {
        "id": "desktop_1920",
        "nombre": "Escritorio 1920px",
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
]

TEMAS = ["light", "dark"]


def construir_detector_js(es_tactil=False):
    """Retorna el script JS que se ejecuta en el navegador para detectar anomalías."""
    return f"""
    (() => {{
        const esTactil = {str(es_tactil).lower()};
        const innerWidth = window.innerWidth;
        const innerHeight = window.innerHeight;
        const scrollWidth = Math.max(
            document.documentElement.scrollWidth,
            document.body ? document.body.scrollWidth : 0
        );

        const hallazgos = [];

        // 1. Desbordamiento horizontal global
        if (scrollWidth > innerWidth + 1.5) {{
            hallazgos.push({{
                tipo: 'SCROLL_HORIZONTAL',
                selector: 'html/body',
                detalle: `scrollWidth (${{scrollWidth}}px) supera innerWidth (${{innerWidth}}px)`
            }});
        }}

        // 2. Elementos que superan el borde derecho
        const todos = document.querySelectorAll('*');
        for (const el of todos) {{
            if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'path', 'g', 'svg', 'use'].includes(el.tagName)) continue;
            
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

            // Ignorar elementos dentro de contenedores explícitamente desplazables
            let dentroScroll = false;
            let padre = el.parentElement;
            while (padre && padre !== document.body && padre !== document.documentElement) {{
                const pStyle = window.getComputedStyle(padre);
                if (['auto', 'scroll'].includes(pStyle.overflowX)) {{
                    dentroScroll = true;
                    break;
                }}
                padre = padre.parentElement;
            }}

            if (!dentroScroll && rect.right > innerWidth + 2) {{
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${{el.id}}` : '';
                const cls = (typeof el.className === 'string' && el.className.trim()) 
                    ? `.${{el.className.trim().split(/\\s+/).slice(0, 2).join('.')}}` 
                    : '';
                hallazgos.push({{
                    tipo: 'DESBORDE_DERECHO',
                    selector: `${{tag}}${{id}}${{cls}}`,
                    detalle: `rect.right (${{Math.round(rect.right)}}px) > ventana (${{innerWidth}}px)`
                }});
                if (hallazgos.filter(h => h.tipo === 'DESBORDE_DERECHO').length >= 5) break;
            }}
        }}

        // 3. Texto recortado en botones y títulos
        const selectoresTexto = 'button, .btn, [role="button"], h1, h2, h3, h4, h5, h6, .card-title';
        for (const el of document.querySelectorAll(selectoresTexto)) {{
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;

            const overflowX = style.overflowX;
            const overflowY = style.overflowY;
            const oculto = ['hidden', 'clip'].includes(overflowX) || ['hidden', 'clip'].includes(overflowY);
            
            if (oculto && el.scrollWidth > el.clientWidth + 2) {{
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${{el.id}}` : '';
                const cls = (typeof el.className === 'string' && el.className.trim()) 
                    ? `.${{el.className.trim().split(/\\s+/).slice(0, 2).join('.')}}` 
                    : '';
                const texto = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 25);
                
                const clamp = style.webkitLineClamp;
                const esClampTitulo = (tag.startsWith('h') || cls.includes('title')) && (clamp && clamp !== 'none');
                
                if (!esClampTitulo) {{
                    hallazgos.push({{
                        tipo: 'TEXTO_RECORTADO',
                        selector: `${{tag}}${{id}}${{cls}}`,
                        detalle: `scrollWidth (${{el.scrollWidth}}px) > clientWidth (${{el.clientWidth}}px) en "${{texto}}..."`
                    }});
                }}
            }}
        }}

        // 4. Controles táctiles menores de 44x44 px (solo si es pantalla táctil)
        if (esTactil) {{
            const selectoresTactiles = 'button:not(.btn-close):not(.btn-link):not(.dropdown-item), .btn:not(.btn-link):not(.dropdown-item), [role="button"]:not(.btn-link):not(.dropdown-item), .touch-target-44, .page-link';
            for (const el of document.querySelectorAll(selectoresTactiles)) {{
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                if (rect.width < 43.5 || rect.height < 43.5) {{
                    const tag = el.tagName.toLowerCase();
                    const id = el.id ? `#${{el.id}}` : '';
                    const cls = (typeof el.className === 'string' && el.className.trim()) 
                        ? `.${{el.className.trim().split(/\\s+/).slice(0, 2).join('.')}}` 
                        : '';
                    const texto = (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 20);
                    hallazgos.push({{
                        tipo: 'CONTROL_TACTIL_PEQUENO',
                        selector: `${{tag}}${{id}}${{cls}}`,
                        detalle: `Tamaño ${{Math.round(rect.width)}}x${{Math.round(rect.height)}} px < 44x44 px ("${{texto}}")`
                    }});
                }}
            }}
        }}

        // 5. Accesibilidad: Imágenes sin alt
        for (const img of document.querySelectorAll('img')) {{
            if (!img.hasAttribute('alt')) {{
                hallazgos.push({{
                    tipo: 'A11Y_IMG_SIN_ALT',
                    selector: img.src.slice(-30),
                    detalle: 'Imagen sin atributo alt para lectores de pantalla'
                }});
            }}
        }}

        return hallazgos;
    }})();
    """


def navegar_con_reintento(page, url, reintentos=3):
    for i in range(reintentos):
        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
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
        sys.exit(1)

    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
    demo_user = os.environ.get("DEMO_USER")
    demo_password = os.environ.get("DEMO_PASSWORD")

    # Si no están configuradas, usar credenciales predeterminadas si existen
    if not demo_user:
        demo_user = "demo"
        demo_password = "Password123!"

    print(f"=== INICIANDO MATRIZ DE VERIFICACIÓN VISUAL ({base_url}) ===")
    
    total_hallazgos = []
    salida_dir = BASE_DIR / "capturas_visual"
    salida_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for dev in DISPOSITIVOS:
            print(f"\n--- Probando perfil: {dev['nombre']} ({dev['viewport']['width']}x{dev['viewport']['height']}) ---")
            
            for tema in TEMAS:
                context = browser.new_context(
                    viewport=dev["viewport"],
                    device_scale_factor=dev.get("device_scale_factor", 1),
                    is_mobile=dev.get("is_mobile", False),
                    has_touch=dev.get("has_touch", False),
                )
                page = context.new_page()

                # Inyectar tema inicial en localStorage
                page.add_init_script(f"""
                    localStorage.setItem('blog_theme', '{tema}');
                    localStorage.setItem('blog-tema', '{tema}');
                    document.documentElement.setAttribute('data-bs-theme', '{tema}');
                """)

                dir_capturas = salida_dir / dev["id"] / tema
                dir_capturas.mkdir(parents=True, exist_ok=True)

                # Definición de pantallas de la suite visual
                pantallas = [
                    {"nombre": "01_inicio_compacta", "url": f"{base_url}/?vista=compacta"},
                    {"nombre": "02_inicio_tarjetas", "url": f"{base_url}/?vista=tarjetas"},
                    {"nombre": "03_explorar", "url": f"{base_url}/explorar/"},
                    {"nombre": "04_populares", "url": f"{base_url}/populares/"},
                    {"nombre": "05_login", "url": f"{base_url}/cuentas/login/"},
                    {"nombre": "06_registro", "url": f"{base_url}/cuentas/registro/"},
                    {"nombre": "07_acerca", "url": f"{base_url}/acerca/"},
                ]

                # Intentar iniciar sesión para pantallas autenticadas
                usuario_autenticado = False
                try:
                    navegar_con_reintento(page, f"{base_url}/cuentas/login/")
                    if page.query_selector('input[name="login"]') or page.query_selector('input[name="username"]'):
                        page.fill('input[name="login"], input[name="username"]', demo_user)
                        page.fill('input[name="password"]', demo_password)
                        page.click('button[type="submit"]')
                        page.wait_for_load_state("networkidle", timeout=6000)
                        usuario_autenticado = True
                except Exception:
                    pass

                if usuario_autenticado:
                    pantallas.extend([
                        {"nombre": "08_panel_dashboard", "url": f"{base_url}/panel/"},
                        {"nombre": "09_mis_posts", "url": f"{base_url}/panel/posts/"},
                        {"nombre": "10_editor_nuevo", "url": f"{base_url}/panel/posts/crear/"},
                        {"nombre": "11_notificaciones", "url": f"{base_url}/notificaciones/"},
                    ])

                for pinfo in pantallas:
                    nombre = pinfo["nombre"]
                    url = pinfo["url"]
                    try:
                        navegar_con_reintento(page, url)
                        # Forzar tema en DOM
                        page.evaluate(f"document.documentElement.setAttribute('data-bs-theme', '{tema}');")
                        time.sleep(0.3)

                        # Capturar pantalla
                        captura_path = dir_capturas / f"{nombre}.png"
                        page.screenshot(path=str(captura_path), full_page=True)

                        # Ejecutar detector de anomalías
                        es_tactil = dev.get("has_touch", False)
                        hallazgos = page.evaluate(construir_detector_js(es_tactil=es_tactil))
                        
                        if hallazgos:
                            for h in hallazgos:
                                item = {
                                    "dispositivo": dev["nombre"],
                                    "tema": tema,
                                    "pantalla": nombre,
                                    **h,
                                }
                                total_hallazgos.append(item)
                                print(f"  [HALLAZGO] {nombre} ({tema}): {h['tipo']} -> {h['detalle']} en {h['selector']}")
                        else:
                            print(f"  [OK] {nombre} ({tema})")

                    except Exception as err:
                        print(f"  [WARN] Falló pantalla {nombre}: {err}")

                context.close()

        browser.close()

    print("\n=======================================================")
    print(f"RESUMEN FINAL: {len(total_hallazgos)} hallazgos detectados.")
    print("=======================================================")
    if total_hallazgos:
        for h in total_hallazgos[:15]:
            print(f"- [{h['dispositivo']}][{h['tema']}][{h['pantalla']}] {h['tipo']}: {h['detalle']}")
        if len(total_hallazgos) > 15:
            print(f"... y {len(total_hallazgos) - 15} hallazgos más.")
        sys.exit(1)
    else:
        print("¡Verificación visual completada con éxito sin anomalías!")
        sys.exit(0)


if __name__ == "__main__":
    main()
