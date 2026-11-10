# Sistema de Diseño y Arquitectura del Foro Adaptable

Este documento describe la arquitectura de interfaz de usuario, tokens de diseño, puntos de quiebre responsivos, especificación de componentes, presupuesto de clics y atajos de teclado implementados en **Blog con Panel de Autor**.

---

## 1. Tokens de Diseño (`static/css/tokens.css`)

El diseño utiliza tokens semánticos definidos con variables CSS nativas, compatibles con modo claro (`data-bs-theme="light"`) y modo oscuro (`data-bs-theme="dark"`).

### 1.1 Paleta Semántica
| Variable | Modo Claro | Modo Oscuro | Propósito |
|---|---|---|---|
| `--color-bg` | `#f8fafc` | `#0b0f19` | Fondo general de la aplicación |
| `--color-surface` | `#ffffff` | `#111827` | Superficie de tarjetas, filas y contenedores |
| `--color-surface-hover` | `#f1f5f9` | `#1f2937` | Estados de hover e interactivos |
| `--color-border` | `#e2e8f0` | `#1f2937` | Bordes estructurales y divisores |
| `--color-border-subtle` | `#f1f5f9` | `#1e293b` | Separadores internos sutiles |
| `--color-text` | `#0f172a` | `#f8fafc` | Texto principal (contraste AA > 14:1) |
| `--color-text-secondary` | `#475569` | `#94a3b8` | Metadatos y extractos (contraste AA > 5.5:1) |
| `--color-text-muted` | `#64748b` | `#64748b` | Fechas secundarias y placeholders |
| `--color-primary` | `#2563eb` | `#3b82f6` | Acciones primarias, botones y enlaces |
| `--color-upvote` | `#ea580c` | `#f97316` | Votos positivos (Upvote naranja Reddit) |
| `--color-downvote` | `#6366f1` | `#818cf8` | Votos negativos (Downvote índigo) |

### 1.2 Escala Espacial y Dimensiones
Basada en un múltiplo estricto de 4px:
- `--space-1`: 4px
- `--space-2`: 8px
- `--space-3`: 12px
- `--space-4`: 16px
- `--space-6`: 24px
- `--space-8`: 32px

Alturas estructurales:
- `--header-height`: 56px (barra superior global fija)
- `--bottom-bar-height`: 52px (barra inferior móvil)
- `--nav-left-width`: 220px (riel de navegación expandido)
- `--nav-rail-width`: 64px (riel colapsado en tablet)
- `--sidebar-right-width`: 320px (widgets e información comunitaria)

---

## 2. Puntos de Quiebre Reglamentarios (`static/css/layout.css`)

Se utiliza una **única base adaptable** (Mobile First) sin duplicación de plantillas ni colisión de IDs:

1. **Móvil (< 640px)**:
   - 1 columna fluida.
   - Oculta navegación izquierda pegajosa.
   - Barra de navegación inferior fija de 52px con soporte de área segura (`env(safe-area-inset-bottom)`).
   - Buscador global colapsable en icono que expande barra superior.
   - Objetivos táctiles mínimos de 44×44 px en todos los botones e iconos.

2. **Móvil amplio / Tablet chica (640px - 1023px)**:
   - Contenedor central acotado (máximo 720px).
   - Mantiene barra inferior para operación ágil con el pulgar.

3. **Tablet / Escritorio compacto (1024px - 1279px)**:
   - 2 columnas: riel de navegación lateral izquierdo colapsado a iconos (64px) + columna principal.
   - Oculta barra inferior móvil.
   - Oculta columna derecha de widgets para maximizar legibilidad.

4. **Escritorio amplio (>= 1280px)**:
   - 3 columnas completas:
     - Izquierda (220px): navegación con etiquetas de texto y lista de comunidades.
     - Central (máx. 720px / 960px): feed de publicaciones o lectura de artículo.
     - Derecha (320px): widgets de comunidad, tabla de contenidos, acerca de y enlaces legales.

5. **Modo Plano (`.app-body--plano`)**:
   - Usado en el panel de autor, estudio de escritura, páginas de cuenta y páginas estáticas (`/acerca/`, `/privacidad/`, etc.).
   - Desactiva rieles laterales y expande el área principal hasta 1200px.

---

## 3. Componentes Clave

- **`_votos.html`**:
  Riel vertical unificado con botones optimistas ▲ y ▼, conteo neto y atributo `aria-pressed`. Reversión automática en caso de error de red.

- **`_fila_post.html`**:
  Tarjeta / fila de publicación con soporte para dos modos (vista compacta o vista en tarjetas vía cookie `vista_feed`), renderizado con `content-visibility: auto; contain-intrinsic-size: 0 140px;` para acelerar el scroll a 60 fps.

- **`_comentario.html`**:
  Árbol de comentarios anidados estilo Reddit:
  - Guías visuales de indentación vertical (`.comment-tree-guide`).
  - Colapso de hilos con botón `[–]` que resume: `[+] @autor · N respuestas ocultas`.
  - Límite de profundidad a nivel 4 con botón "Continuar este hilo →".
  - Compositor en línea desplegable con atajo `Ctrl + Enter` y límite de caracteres (1000).

- **`#modalAccesoVisitante`**:
  Hoja inferior interactiva en móvil y modal centrado en escritorio que guía al lector a registrarse o iniciar sesión sin recargar la página, reteniendo la acción pretendida (voto, guardado, respuesta) para reintentarla post-login.

---

## 4. Presupuesto de Clics (Click Budget)

| Flujo | Presupuesto Máximo | Clics Reales Implementados | Mecanismo |
|---|---|---|---|
| **Leer post** | 1 clic | **1 clic** | Clic en el título o tarjeta del post |
| **Votar** | 1 clic | **1 clic** | Clic en ▲ o ▼ con AJAX optimista |
| **Guardar post** | 1 clic | **1 clic** | Clic en marcador con toast de deshacer |
| **Compartir** | 1 clic | **1 clic** | Web Share API en móvil o copia de enlace |
| **Comentar** | 1 clic | **1 clic** | Enfoque de compositor y envío con `Ctrl+Enter` |
| **Filtrar / Ordenar** | 1 clic | **1 clic** | Selector directo por pestaña |
| **Desplegar hilo** | 1 clic | **1 clic** | Alternador instantáneo `[–]` / `[+]` |

---

## 5. Atajos de Teclado Globales (`static/js/atajos.js`)

| Tecla | Acción |
|---|---|
| `/` o `Ctrl + K` | Enfocar barra de búsqueda global con sugerencias |
| `j` | Navegar al post siguiente en el feed |
| `k` | Navegar al post anterior en el feed |
| `Enter` u `o` | Abrir el post actualmente seleccionado |
| `a` | Votar positivo (Upvote) en el post enfocado |
| `s` | Guardar / Desguardar post en marcadores |
| `c` | Desplazarse a la sección de comentarios |
| `g` + `h` | Ir a Inicio (Go Home) |
| `Esc` | Cerrar modales, búsqueda o paneles flotantes |
| `Ctrl + Enter` | Enviar formulario de comentario en compositor |
