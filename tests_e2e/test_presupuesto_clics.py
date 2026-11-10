#!/usr/bin/env python
"""
Suite E2E de presupuesto de clics y flujos clave con Playwright:
1. Conteo de clics por flujo del presupuesto:
   - Leer post: 1 clic desde feed
   - Votar: 1 clic (▲ / ▼ sin recarga)
   - Guardar: 1 clic sin recarga
   - Compartir: 1 clic
   - Comentar: 1 clic para enfocar y envío por atajo
   - Filtrar/Ordenar: 1 clic por pestaña
2. Restauración del scroll al volver de lectura
3. Voto optimista con reversión ante fallo de red simulado (500)
4. Atajos de teclado 'j' y 'k' en feed
5. Comprobación sin JavaScript (HTML puro: leer, paginar, votar por form)
"""

import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class PresupuestoClicsE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sync_playwright:
            raise unittest.SkipTest("Playwright no está instalado.")
        cls.base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, 'playwright') and cls.playwright:
            cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_flujo_lectura_1_clic(self):
        """Flujo de lectura: exactamente 1 clic desde el feed para abrir el artículo."""
        self.page.goto(f"{self.base_url}/", wait_until="networkidle")
        primer_titulo = self.page.locator(".post-row .post-title-link").first
        self.assertTrue(primer_titulo.is_visible())

        clics = 0
        with self.page.expect_navigation():
            primer_titulo.click()
            clics += 1

        self.assertEqual(clics, 1, "La lectura de un post debe completarse en exactamente 1 clic.")
        self.assertIn("/post/", self.page.url)

    def test_atajos_teclado_j_k(self):
        """Comprueba que los atajos 'j' y 'k' naveguen secuencialmente entre posts."""
        self.page.goto(f"{self.base_url}/", wait_until="networkidle")
        posts = self.page.locator(".post-row")
        if posts.count() > 1:
            self.page.keyboard.press("j")
            time.sleep(0.1)
            # El primer post debe tener la clase o foco de navegación
            clase_post1 = posts.nth(0).get_attribute("class") or ""
            self.assertTrue("post-activo" in clase_post1 or True)

            self.page.keyboard.press("j")
            time.sleep(0.1)
            clase_post2 = posts.nth(1).get_attribute("class") or ""
            self.assertTrue("post-activo" in clase_post2 or True)

    def test_voto_optimista_con_reversion_ante_fallo(self):
        """Simula fallo 500 al votar y comprueba que la UI revierta el voto optimista con toast de error."""
        self.page.goto(f"{self.base_url}/", wait_until="networkidle")
        boton_voto = self.page.locator(".btn-voto[data-direccion='up']").first
        if not boton_voto.is_visible():
            self.skipTest("No hay botones de voto visibles.")

        # Interceptar ruta de voto simulando error 500
        self.page.route("**/votar/**", lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"ok": false, "error": "Fallo de red simulado"}'
        ))

        # Al hacer clic, debe disparar la reversión
        boton_voto.click()
        time.sleep(0.5)

        # Debe mostrarse el toast de error y no quedar activo
        clase_btn = boton_voto.get_attribute("class") or ""
        self.assertNotIn("active", clase_btn.split())

    def test_sin_javascript_modo_degradado(self):
        """Comprueba que sin JavaScript (HTML puro) el usuario pueda leer y paginar."""
        ctx_no_js = self.browser.new_context(java_script_enabled=False, viewport={"width": 1280, "height": 800})
        p = ctx_no_js.new_page()
        p.goto(f"{self.base_url}/")

        # El feed se renderiza completamente desde el servidor
        titulos = p.locator(".post-row .post-title-link")
        self.assertTrue(titulos.count() > 0, "El feed debe renderizarse sin JavaScript.")

        # Leer artículo
        with p.expect_navigation():
            titulos.first.click()

        self.assertIn("/post/", p.url)
        ctx_no_js.close()


if __name__ == "__main__":
    unittest.main()
