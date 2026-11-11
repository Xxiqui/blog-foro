import os
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / 'capturas_despues'
OUTPUT_DIR.mkdir(exist_ok=True)

python_bin = sys.executable

print("Iniciando servidor de desarrollo Django...")
server_proc = subprocess.Popen(
    [python_bin, 'manage.py', 'runserver', '127.0.0.1:8000', '--noreload'],
    cwd=BASE_DIR,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

time.sleep(3)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        viewports = [
            ("movil", {"width": 390, "height": 844}, True),
            ("tablet", {"width": 768, "height": 1024}, True),
            ("escritorio", {"width": 1280, "height": 800}, False)
        ]

        temas = ["light", "dark"]

        paginas = [
            ("feed", "http://127.0.0.1:8000/"),
            ("explorar", "http://127.0.0.1:8000/explorar/"),
            ("login", "http://127.0.0.1:8000/cuentas/login/"),
            ("registro", "http://127.0.0.1:8000/cuentas/registro/"),
            ("acerca", "http://127.0.0.1:8000/acerca/"),
            ("contacto", "http://127.0.0.1:8000/contacto/"),
        ]

        for vp_nombre, vp_size, is_mob in viewports:
            for tema in temas:
                context = browser.new_context(
                    viewport=vp_size,
                    is_mobile=is_mob,
                    has_touch=is_mob
                )
                page = context.new_page()

                # Establecer tema
                page.add_init_script(f"""
                    localStorage.setItem('blog_theme', '{tema}');
                    document.documentElement.setAttribute('data-bs-theme', '{tema}');
                """)

                for pag_nombre, url in paginas:
                    try:
                        page.goto(url, wait_until="networkidle", timeout=8000)
                        
                        # Comprobar overflow horizontal
                        overflow = page.evaluate("""() => {
                            const sw = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
                            const iw = window.innerWidth;
                            return sw > iw + 1;
                        }""")

                        status = "OVERFLOW DETECTADO" if overflow else "OK (sin overflow)"
                        print(f"[{vp_nombre} - {tema}] {pag_nombre}: {status}")

                        archivo_salida = OUTPUT_DIR / f"{pag_nombre}_{vp_nombre}_{tema}.png"
                        page.screenshot(path=str(archivo_salida), full_page=False)
                    except Exception as e:
                        print(f"Error en {pag_nombre} ({vp_nombre}, {tema}): {e}")

                context.close()

        browser.close()
        print("Capturas visuales guardadas en capturas_despues/")
finally:
    server_proc.terminate()
    server_proc.wait(timeout=5)
    print("Servidor Django detenido.")
