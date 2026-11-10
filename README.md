# Blog con Panel de Autor

Aplicación web completa de publicación de artículos construida con **Python 3.12**, **Django 5.x** y **Bootstrap 5**. Incluye sitio público con búsqueda *full-text*, filtrado por categorías y etiquetas, páginas públicas de autor, sistema de comentarios moderados, editor enriquecido **CKEditor 5** con subida de imágenes, saneado de HTML con **Bleach**, y un **Panel de Autor** privado donde cada autor administra exclusivamente sus propios artículos y comentarios.

---

## Stack Tecnológico

- **Backend:** Python 3.12, Django 5.x
- **Base de datos:** Configurada dinámicamente con `dj-database-url` mediante `DATABASE_URL` (PostgreSQL 16 en producción y Docker; SQLite por defecto si no se define)
- **Frontend e Interacciones:** Plantillas de Django + Bootstrap 5.3 (CDN) + Bootstrap Icons + `static/js/interacciones.js` (mejora progresiva AJAX con CSRF, `aria-pressed`, Toasts de Bootstrap y modo claro/oscuro)
- **Editor WYSIWYG:** `django-ckeditor-5` con subida de imágenes restringida a usuarios autenticados (`media/uploads/`)
- **Seguridad HTML y XSS:** `bleach` mediante el filtro `|sanear_html` y escape previo en menciones `|renderizar_menciones`
- **Limitación de tasa (*Rate Limiting*):** Decorador reutilizable `@limitar_tasa` con el cache de Django (30/min en likes y votos, 5/hora en reportes)
- **Servidor y estáticos en producción:** `gunicorn` + `whitenoise`
- **Localización:** Español (`LANGUAGE_CODE = 'es'`) y zona horaria `America/Bogota`

---

## Funciones de Interacción y Moderación

### 1. Notificaciones en el sitio (`blog/notificaciones.py`)
- Modelo `Notificacion` con soporte para `COMENTARIO_NUEVO`, `COMENTARIO_APROBADO`, `MENCION`, `LIKE_POST`, `LIKE_COMENTARIO`, `SEGUIDOR_NUEVO`, `POST_NUEVO` y `REPORTE_COMENTARIO`.
- Función central `notificar(...)`: evita autonotificaciones (`actor == destinatario`) y evita duplicar la misma combinación `actor + tipo + objeto`.
- Campana en la barra de navegación con contador de no leídas (refrescado cada 60s vía `/notificaciones/contador/` cuando la pestaña está visible), desplegable con las últimas 5 y página `/notificaciones/`.

### 2. Interacción con el Post
- **Me gusta (`LikePost`):** Botón con contador en tarjetas de listado y detalle, con estado activo y precarga sin consultas N+1 (`annotate` + `Exists`).
- **¿Te fue útil? (`VotoUtil`):** Botones Sí/No al final de cada post con resumen *"X de Y lectores lo encontraron útil"* y porcentaje de utilidad por post en el Dashboard del autor.
- **Compartir:** Botones para WhatsApp, X, LinkedIn, Facebook, "Copiar enlace" (con aviso *"¡Copiado!"*) y soporte para la Web Share API en dispositivos móviles.

### 3. Interacción Avanzada con Comentarios
- **Autoría y Me gusta (`LikeComentario`):** Vincula automáticamente el usuario autenticado y precarga nombre/correo en modo lectura; permite dar "Me gusta" a comentarios aprobados.
- **Edición y borrado:** El autor de un comentario puede editarlo durante `COMENTARIO_VENTANA_EDICION_MIN = 10` minutos (queda marcado como `(editado)` y regresa a moderación `aprobado=False`) y borrarlo en cualquier momento. El autor del post y los administradores pueden eliminar cualquier comentario.
- **Reportes (`ReporteComentario`):** Los usuarios autenticados pueden reportar comentarios ajenos. Notifica en el sitio y por correo tanto al **autor del post** como a **todos los administradores activos** (sin duplicar si un usuario cumple ambos roles). Si un comentario acumula `REPORTES_PARA_OCULTAR = 3` reportes pendientes, se oculta automáticamente (`oculto_por_reportes=True`) hasta su revisión desde `/panel/reportes/` o desde el Admin de Django.
- **Menciones (`@usuario`):** Detecta hasta 5 usuarios reales por comentario, escapando primero el HTML para impedir XSS antes de enlazar al perfil público. Incluye autocompletado en `/usuarios/buscar/?q=` y envía las notificaciones `MENCION` únicamente cuando el comentario es aprobado.

### 4. Seguir Autores, Suscripciones por Correo, Rankings y Listas de Lectura (Ronda 2)
- **Seguir autores (`Seguimiento`):** Permite seguir y dejar de seguir autores (con validación que impide seguirse a uno mismo y unicidad por pareja). Incluye contador en tiempo real, feed `/siguiendo/` con artículos de los autores seguidos y notificaciones `SEGUIDOR_NUEVO` y `POST_NUEVO` (enviada solo en la primera publicación mediante `Post.notificado=True`).
- **Suscripción por correo (`Suscripcion` y `blog/emails.py`):** Suscripción opcional a un autor o a una categoría con protección *honeypot*, límite de 3 solicitudes por hora por IP y **doble confirmación** (`/suscripcion/confirmar/<token>/`). Cuando un post se publica por primera vez, se envía un boletín en HTML y texto plano a los suscriptores confirmados sin duplicar envíos a un mismo correo y con enlace único de baja sin login (`/suscripcion/baja/<token>/`).
  - **Limitación actual del envío de correos:** El envío está aislado en `blog/emails.py` y se ejecuta de forma **síncrona** reutilizando una única conexión SMTP (`get_connection(fail_silently=True)`) con registro de errores en `logging`. Para sitios con miles de suscriptores se recomienda migrar las funciones de `blog/emails.py` a una cola de tareas asíncronas con **Celery + Redis**.
- **Fórmula de Posts Más Populares (`VistaDiaria` y `blog/populares.py`):**
  - Se registra una vista diaria por sesión y día en el detalle del post (actualizada atómicamente con `F('cantidad') + 1`), ignorando al autor del post, al personal `staff`/superusuarios y a bots detectados por `User-Agent`.
  - **Fórmula de puntuación (últimos $N$ días o histórico):**
    $$\text{Puntuación Post} = (\text{vistas} \times 1) + (\text{likes nuevos} \times 3) + (\text{votos útil} \times 2) + (\text{comentarios aprobados} \times 2)$$
  - La función `posts_populares(dias=7, limite=5)` se almacena en cache durante **10 minutos** y alimenta el widget "Más populares de la semana" y la página `/populares/` (con pestañas *Semana*, *Mes* y *Siempre*).
- **Fórmula de Autores Destacados e Insignias (`blog/populares.py` y `{% insignia perfil %}`):**
  - Se calcula con `annotate` y subconsultas sin N+1 (cacheado por **30 minutos**) para autores con al menos 1 post publicado:
    $$\text{Puntuación Autor} = (\text{posts publicados} \times 2) + (\text{seguidores} \times 3) + (\text{likes recibidos} \times 1) + (\text{votos útil} \times 1)$$
  - **Insignias calculadas en tiempo de ejecución** (umbrales configurables en `config/settings.py` y variables de entorno):
    - **Nuevo:** menos de `AUTOR_INSIGNIA_NUEVO_MAX_POSTS` (por defecto `3`) posts publicados.
    - **Activo:** `AUTOR_INSIGNIA_ACTIVO_MIN_POSTS` (por defecto `5`) o más posts publicados.
    - **Destacado:** dentro del top `AUTOR_DESTACADO_TOP_N` (por defecto `3`) **y** con puntuación $\ge$ `AUTOR_DESTACADO_UMBRAL_PUNTOS` (por defecto `8`).
- **Listas de Lectura (`ListaLectura` e `ItemLista`):**
  - Todo usuario recibe automáticamente una lista privada predeterminada llamada **"Guardados"** (que no se puede borrar, renombrar ni hacer pública).
  - Permite guardar con un clic desde tarjetas y detalle, añadir artículos a listas personalizadas o crear nuevas listas al vuelo, y gestionar la privacidad en `/mis-listas/` y `/listas/<id>/`. Si un post guardado pasa a borrador, se oculta a terceros en listas públicas y muestra *"Este post ya no está disponible"* a su propietario.

### 5. Acceso Social Opcional, Comunidades, Hub de Categoría, Comentarios Anidados e Inserción (`<iframe>`)
- **Acceso con Google y GitHub (`django-allauth` en `/oauth/`):**
  - Integrado sin reemplazar las vistas propias de `/cuentas/login/`, `/cuentas/registro/` ni cambio de contraseña.
  - Inicia el flujo OAuth exclusivamente por `POST` (`SOCIALACCOUNT_LOGIN_ON_GET = False`) y vincula con una cuenta existente por correo **únicamente** si el proveedor marca ese correo como verificado.
  - Si un proveedor no tiene credenciales en el entorno, su botón no se muestra; si ninguno las tiene, el formulario tradicional queda desplegado por defecto.
  - Al registrarse con cuenta social se crea automáticamente el `Perfil`, se genera un `username` único válido para menciones (`^[A-Za-z0-9_.-]{2,30}$`) y se descarga el avatar inicial (restringido a `https://` en `lh3.googleusercontent.com` y `avatars.githubusercontent.com`, máximo 5 s y 2 MB, verificado con Pillow y redimensionado a `256x256`).
- **Categorías como Comunidades (`MiembroCategoria` y `/categoria/<slug>/`):**
  - Las categorías cuentan con `descripcion`, `avatar` (`256x256`), `banner` (`1600x400`), `creada` y reglas (`ReglaCategoria`).
  - Los usuarios pueden unirse o salir de cualquier comunidad mediante `/categoria/<slug>/unirse/` (por AJAX o formulario clásico, sin notificaciones ni correos).
  - El feed `/siguiendo/` combina artículos de autores seguidos y comunidades unidas sin duplicados y ofrece el filtro **Todo | Autores | Comunidades** (`?filtro=todo|autores|comunidades`).
  - La página `/categoria/<slug>/` funciona como un hub de comunidad con banner, avatar circular superpuesto, botón **+ Crear post** (que preselecciona `?categoria=<slug>`), hasta **3 posts fijados** (`Post.fijado_en_categoria`, con respaldo automático a los 3 más populares), selector de vista **Tarjetas | Compacta** persistido en `localStorage` (`blog_categoria_vista`), métricas semanales (**vistas esta semana** y **publicaciones esta semana**) y acordeón de reglas.
- **Menú «Compartir» con opción «Insertar» (`</>`) y `PostEmbedView`:**
  - Menú desplegable unificado en tarjetas y detalle con *Copiar enlace*, *Insertar `</>`*, *X*, *WhatsApp*, *LinkedIn* y *Más opciones…* (`navigator.share`).
  - La ruta `/post/<slug>/embed/` devuelve una tarjeta compacta autónoma exenta de `X-Frame-Options` (`@xframe_options_exempt`) para posts publicados (404 en borradores) con soporte de `?tema=claro|oscuro`.
- **Comentarios Anidados (hasta 4 niveles):**
  - Respuestas en árbol mediante `Comentario.padre` (hasta `COMENTARIO_PROFUNDIDAD_MAX = 4`), cargadas en una sola consulta SQL en `PostDetailView`.
  - Las respuestas del autor del post o de usuarios `staff` se aprueban automáticamente; el resto pasa por moderación y al aprobarse dispara la notificación `RESPUESTA_COMENTARIO`.
  - **Borrado seguro (`borrar_seguro()`):** si un comentario tiene respuestas, se marca `eliminado=True` y muestra `[comentario eliminado]` conservando el hilo; si no tiene respuestas, se elimina físicamente.

### 6. Experiencia de Autor, Autenticación Unificada y Pasada de Pulido
- **Jerarquía de insignias y marca única:**
  - En contextos compactos (tarjetas, listados y barra lateral), `{% insignia %}` muestra únicamente la insignia de mayor rango (**Destacado > Activo > Nuevo**), reservando el listado completo para el perfil público del autor.
  - La marca se centraliza en `MARCA` y `SITE_NAME` (expuesta por el context processor `blog_context`) y el modelo `Site` (`SITE_ID = 1`) se inicializa mediante la migración de datos `0006_fijar_site_marca`.
  - `nombre_mostrar` unificado en panel, tarjetas, notificaciones y correos.
- **Autenticación Consistente (`templates/base_auth.html`):**
  - Plantilla base dedicada para inicio de sesión, registro y el flujo de restablecimiento de contraseña en 4 pasos, sin elementos distractores de la cabecera.
  - Soporte de login dual por usuario o por correo (`EmailOrUsernameModelBackend`).
  - Alternador accesible de visibilidad de contraseña (`aria-label`, `aria-pressed`).
  - Sugerencia automática de nombre de usuario en registro basada en nombre y apellido, y checklist reactivo de fortaleza de contraseña.
  - Widget lateral *"Únete a la comunidad"* muestra botones *"Crear cuenta"* (primario) e *"Iniciar sesión"* (secundario) cuando no hay OAuth configurado.
- **Panel de Autor Renovado (`/panel/`):**
  - Cuadrícula 4x2 con **8 métricas** clave (separando Seguidores y Me gusta).
  - Botón de reportes destacado en rojo únicamente si existen reportes pendientes (`> 0`).
  - Gráfico de lecturas actualizado con fecha actual ("Actualizado hoy") y estado vacío con 0 lecturas.
  - Checklist de *Primeros pasos* para autores nuevos con 0 artículos publicados.
  - Estado vacío inspirador en el top 5 de artículos más leídos con acceso directo a redacción.
- **Editor de Artículos Avanzado (`/panel/posts/nuevo/` y `/panel/posts/<id>/editar/`):**
  - Modo oscuro adaptado para CKEditor 5 mediante variables CSS bajo `[data-bs-theme="dark"]`.
  - Contador superior unificado de palabras y tiempo de lectura.
  - Selector de etiquetas interactivas tipo chip con filtro en vivo y modal AJAX para crear etiquetas al instante (`/panel/etiquetas/crear-ajax/`).
  - Subida de imagen de portada por arrastrar y soltar (*drag & drop*) con previsualización inmediata, validación de tipo/tamaño (5 MB) y opción para eliminarla.
  - Extracto manual opcional (hasta 160 caracteres) con contador en tiempo real y fallback automático a `extracto_plano`.
  - Barra flotante inferior de acciones fija con estado de guardado.
- **Correcciones Estéticas y de Accesibilidad:**
  - Bloques de código con padding inferior ampliado y barra de desplazamiento delgada personalizada para evitar solapamientos con la última línea.
  - Botones de respuesta colapsable en comentarios con formato de píldora redondeada sin bordes blancos toscos.
  - Botones de paginación con estado visual y semántico `aria-disabled="true"` en la primera y última página.

---

## Configuración Paso a Paso de OAuth (Google y GitHub)

El inicio de sesión social es **completamente opcional**. Para activarlo en desarrollo o en producción, define las variables en tu archivo `.env` o en el panel de Render:

```env
GOOGLE_CLIENT_ID=tu-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=tu-client-secret
GITHUB_CLIENT_ID=tu-github-client-id
GITHUB_CLIENT_SECRET=tu-github-client-secret
```

### 1. Crear credenciales en Google Cloud Console
1. Entra en [Google Cloud Console](https://console.cloud.google.com/) y crea o selecciona un proyecto.
2. Ve a **APIs y servicios** → **Pantalla de consentimiento de OAuth**, elige tipo **Externo**, completa el nombre de la aplicación y guarda.
3. Ve a **APIs y servicios** → **Credenciales** → **Crear credenciales** → **ID de cliente de OAuth**.
4. Selecciona **Aplicación web** y agrega las siguientes **URI de redireccionamiento autorizados**:
   - **En desarrollo local:**
     ```text
     http://127.0.0.1:8000/oauth/google/login/callback/
     http://localhost:8000/oauth/google/login/callback/
     ```
   - **En producción (Render / dominio propio):**
     ```text
     https://tu-dominio.onrender.com/oauth/google/login/callback/
     ```
5. Copia el **ID de cliente** en `GOOGLE_CLIENT_ID` y el **Secreto del cliente** en `GOOGLE_CLIENT_SECRET`.

### 2. Crear una OAuth App en GitHub
1. Entra en GitHub y ve a **Settings** → **Developer settings** → **OAuth Apps** → **New OAuth App**.
2. Completa los datos de la aplicación:
   - **Homepage URL (desarrollo):** `http://127.0.0.1:8000/` (o `https://tu-dominio.onrender.com/` en producción).
   - **Authorization callback URL:**
     - **En desarrollo local:**
       ```text
       http://127.0.0.1:8000/oauth/github/login/callback/
       ```
     - **En producción (Render / dominio propio):**
       ```text
       https://tu-dominio.onrender.com/oauth/github/login/callback/
       ```
3. Registra la aplicación, genera un **Client secret** y copia los valores en `GITHUB_CLIENT_ID` y `GITHUB_CLIENT_SECRET`.

---

El proyecto cuenta con una hoja de estilos centralizada (`static/css/estilos.css`) basada en variables CSS (*design tokens*) con soporte completo para modo claro y modo oscuro (`[data-bs-theme="dark"]`), tipografía **Inter** (interfaz) y **JetBrains Mono** (código), y respeto por `prefers-reduced-motion: reduce`.

### 1. Tokens principales
| Token CSS | Modo claro (`:root`) | Modo oscuro (`[data-bs-theme="dark"]`) | Propósito |
| :--- | :--- | :--- | :--- |
| `--color-primario` | `#2563eb` | `#60a5fa` | Enlaces activos, botones e indicadores principales |
| `--superficie-fondo` | `#f8fafc` | `#0b1120` | Fondo general de la página |
| `--superficie-tarjeta` | `#ffffff` | `#111827` | Fondo de tarjetas, barra lateral y contenedores |
| `--superficie-elevada` | `#f1f5f9` | `#1e293b` | Bloques secundarios, píldoras y cabeceras sutiles |
| `--borde-color` | `#e2e8f0` | `#334155` | Bordes de tarjetas, tablas y divisores |
| `--texto-principal` | `#0f172a` | `#f8fafc` | Títulos y cuerpo principal de lectura |
| `--texto-secundario` | `#475569` | `#cbd5e1` | Extractos, fechas y metadatos (contraste $\ge 4.5:1$) |
| `--radio-tarjeta` | `12px` | `12px` | Radio de borde uniforme en tarjetas y paneles |

### 2. Componentes reutilizables
- **Píldoras de etiquetas y nube (`.tag-pill`, `.tag-size-1`..`.tag-size-4`):** Usan `--superficie-elevada`, `--texto-principal` y `--borde-color` para mantener contraste óptimo en modo claro y oscuro.
- **Portadas 16:9 y gradientes por categoría (`.post-cover-wrapper`, `.post-cover-gradient`, `{% portada_post post %}`):** Si un artículo tiene imagen se muestra en `16:9` con `object-fit: cover` y `loading="lazy"`; si no tiene imagen, genera un gradiente determinista entre 6 paletas según su categoría.
- **Avatares con inicial determinista (`{% avatar perfil tamaño %}`):** Muestra la foto del autor o un círculo con su inicial sobre un color estable calculado a partir de su `username`.
- **Extractos limpios (`{{ post.contenido|extracto_plano:160 }}`):** Ignora encabezados `h1`–`h6`, extrae el primer párrafo con contenido real, corta en límite de palabra y añade una única elipsis `…`.
- **Columna de lectura y Tabla de Contenidos (`.article-column`, `.toc-box`, `sanear_y_generar_toc`):** Columna centrada de `720px`, barra superior de progreso de lectura, resaltado de sintaxis con `highlight.js` + botón *"Copiar"* en bloques `<pre>`, e índice automático cuando el artículo tiene $\ge 3$ encabezados `h2`/`h3`.

### 3. Cómo cambiar la paleta de colores
Para personalizar la identidad visual del blog:
1. Abre `static/css/estilos.css`.
2. Modifica los valores en `:root` (modo claro) y en `[data-bs-theme="dark"]` (modo oscuro), especialmente `--color-primario`, `--color-primario-hover`, `--color-primario-suave` y los gradientes `.grad-0` a `.grad-5`.
3. Si despliegas en producción o Docker, ejecuta `python manage.py collectstatic --no-input` para actualizar los archivos servidos por WhiteNoise.

---

## Instalación y Uso Local (Sin Docker)

1. **Crear y activar el entorno virtual:**
   ```bash
   python -m venv .venv
   # En Windows (PowerShell):
   .\.venv\Scripts\Activate.ps1
   # En Linux / macOS:
   source .venv/bin/activate
   ```

2. **Instalar las dependencias:**
   ```bash
   pip install -r requirements.txt
   ```
   *Para desarrollo y pruebas visuales móviles automatizadas con Playwright:*
   ```bash
   pip install -r requirements-dev.txt
   playwright install chromium
   ```


3. **Configurar variables de entorno (opcional en desarrollo):**
   Copia `.env.example` a `.env`. Si no defines `DATABASE_URL`, el proyecto utilizará automáticamente `db.sqlite3`.
   ```bash
   cp .env.example .env
   ```

4. **Aplicar migraciones y recolectar archivos estáticos:**
   ```bash
   python manage.py migrate
   python manage.py collectstatic --no-input
   ```

5. **Cargar los datos de demostración:**
   ```bash
   python manage.py cargar_datos_demo
   ```

6. **Ejecutar las pruebas automatizadas:**
   ```bash
   python manage.py test
   ```

7. **Iniciar el servidor de desarrollo:**
   ```bash
   python manage.py runserver
   ```
   Abre `http://127.0.0.1:8000/` en tu navegador.

---

## Uso con Docker y PostgreSQL 16

El archivo `docker-compose.yml` levanta dos servicios: `db` (PostgreSQL 16 con volumen persistente) y `web` (Django + Gunicorn con usuario no-root).

1. **Construir y levantar los contenedores:**
   ```bash
   docker compose up --build
   ```

2. **Cargar datos de demostración dentro del contenedor (en otra terminal):**
   ```bash
   docker compose exec web python manage.py cargar_datos_demo
   ```

3. **Ejecutar pruebas dentro del contenedor (contra PostgreSQL):**
   ```bash
   docker compose exec web python manage.py test
   ```

4. Accede a la aplicación en `http://localhost:8000/`.

---

## Credenciales de Usuarios Demo (`cargar_datos_demo`)

Al ejecutar `python manage.py cargar_datos_demo` se crean **2 usuarios**, **3 categorías**, **6 etiquetas**, **8 posts** (6 publicados y 2 en borrador) y **6 comentarios** (4 aprobados y 2 pendientes):

| Usuario | Contraseña | Rol | Correo |
| :--- | :--- | :--- | :--- |
| `ana_garcia` | `DemoPassword123!` | Autora + Superusuaria (`/admin/` y `/panel/`) | `ana.garcia@ejemplo.com` |
| `carlos_ruiz` | `DemoPassword123!` | Autor (`/panel/`) | `carlos.ruiz@ejemplo.com` |

---

## Almacenamiento de Archivos Media y Discos Efímeros

### Limitación de los discos efímeros (Render, Railway, Heroku)
En plataformas PaaS como **Render** o **Railway**, el sistema de archivos del contenedor es **efímero**: cada vez que se realiza un nuevo despliegue (*deploy*) o el contenedor se reinicia, cualquier archivo subido al directorio local del contenedor se pierde si no está montado en un disco persistente externo.

### Solución configurada en este proyecto (Disco Persistente Montado)
- En `config/settings.py`, la ruta `MEDIA_ROOT` se lee de la variable de entorno `MEDIA_ROOT` (con valor por defecto `BASE_DIR / 'media'`).
- En `render.yaml`, el servicio web monta un **Persistent Disk** (`blog-media-disk`) en `/var/data/media` y define `MEDIA_ROOT=/var/data/media`. De esta forma, tanto los avatares (`avatares/`) como las imágenes subidas desde CKEditor 5 (`uploads/`) persisten entre despliegues.
- En `docker-compose.yml`, el volumen `media_data` se monta en `/app/media`.

### Cómo migrar a un servicio externo (Amazon S3 o Cloudinary)
Si prefieres no usar un disco persistente o necesitas escalar horizontalmente múltiples instancias web:
1. Instala `django-storages[s3]` y `boto3` (para **Amazon S3 / Cloudflare R2**) o `django-cloudinary-storage` (para **Cloudinary**).
2. En `config/settings.py`, reemplaza la clave `default` dentro de `STORAGES`:
   ```python
   # Ejemplo con Amazon S3 (django-storages)
   STORAGES = {
       "default": {
           "BACKEND": "storages.backends.s3.S3Storage",
           "OPTIONS": {
               "bucket_name": os.environ.get("AWS_STORAGE_BUCKET_NAME"),
               "region_name": os.environ.get("AWS_S3_REGION_NAME", "us-east-1"),
           },
       },
       "staticfiles": {
           "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
       },
   }
   ```

---

## Despliegue Paso a Paso en Render

El repositorio incluye `build.sh` y `render.yaml` (Blueprint de Render) listos para producción.

1. **Subir el proyecto a un repositorio en GitHub o GitLab.**
2. **Crear un Blueprint en Render:**
   - Inicia sesión en [Render](https://dashboard.render.com/).
   - Haz clic en **New +** -> **Blueprint**.
   - Conecta tu repositorio. Render detectará automáticamente el archivo `render.yaml`.
3. **Revisar los recursos que creará `render.yaml`:**
   - Base de datos PostgreSQL gestionada (`blog-db`).
   - Servicio web Python (`blog-panel-autor`) que ejecuta `./build.sh` en el build y `gunicorn config.wsgi:application` al iniciar.
   - Variables de entorno automáticas: `SECRET_KEY` autogenerada, `DEBUG=False`, `DATABASE_URL` enlazada a `blog-db`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` y `MEDIA_ROOT=/var/data/media`.
4. **Aplicar y desplegar:**
   - Haz clic en **Apply**. Una vez finalizado el despliegue, puedes poblar datos iniciales desde la pestaña *Shell* de Render ejecutando `python manage.py cargar_datos_demo`.

---

## Decisiones de Diseño

1. **Separación modular en `cuentas` y `blog`:** El modelo `Perfil` y su señal `post_save` viven en `cuentas`, mientras que `Categoria`, `Etiqueta`, `Post` y `Comentario` viven en `blog`.
2. **Compatibilidad transparente PostgreSQL / SQLite:**
   - En `blog/search.py`, la función `buscar_posts(q)` inspecciona `connection.vendor`. Si es `'postgresql'`, utiliza `SearchVector` (ponderando título `A`, etiquetas `B` y contenido `C` en configuración `spanish`), `SearchQuery`, `SearchRank` y `SearchHeadline`. Si es `'sqlite'`, utiliza `Q` con `icontains` y un generador de fragmentos resaltados en Python.
   - El índice `GinIndex` sobre `Post.buscador` se ejecuta como índice `USING gin` en PostgreSQL y degrada limpiamente a un índice estándar en SQLite para que las migraciones funcionen en cualquier entorno sin modificar código.
3. **Registro e inicio de sesión:** Al registrarse en `/cuentas/registro/`, el usuario inicia sesión automáticamente y es redirigido a su `/panel/`, donde su `Perfil` ya fue creado por la señal `post_save`.



---

## Estudio de Escritura y Servicio de Publicación

El Panel de Autor cuenta con un **Estudio de Escritura** completo para crear y editar artículos con experiencia de escritorio moderna, modo concentración y autoguardado inteligente.

### 1. Arquitectura del Servicio de Publicación (`blog/servicios/publicacion.py`)
- **Centralización e Idempotencia:** Centraliza `guardar_borrador`, `publicar`, `programar`, `despublicar` y `duplicar`. La primera publicación fija `publicado_en` y dispara notificaciones internas a seguidores y correos a suscriptores vía `transaction.on_commit`. Las publicaciones posteriores son idempotentes y no duplican notificaciones ni alteran la fecha original.
- **Inmutabilidad del Slug:** El slug del artículo es editable libremente mientras permanezca como borrador. En cuanto recibe una fecha de publicación (`publicado_en is not None`), se vuelve inmutable a nivel de modelo para proteger la integridad de enlaces públicos y SEO.
- **Control de Versiones y Revisiones (`RevisionPost`):** Cada guardado, publicación o restauración genera un punto de historial podado automáticamente a las últimas 20 revisiones por artículo.

### 2. Frontend sin Paso de Build (Módulos ES Nativos)
- Estructurado en `static/js/editor/` utilizando JavaScript modular nativo (`<script type="module">`) y CSS puro (`static/css/editor.css`), respetando variables de tema y compatibilidad completa con modo claro y oscuro:
  - `editor.js`: Punto de entrada que orquesta los componentes.
  - `autoguardado.js`: Autoguardado con debounce de 3s (máximo 30s) al endpoint `/panel/api/autoguardar/`, respaldo offline en `localStorage`, control de concurrencia HTTP 409 y alerta `beforeunload`.
  - `portada.js`: Subida por arrastrar y soltar (Drag & Drop), validación client/server (< 5 MB, formatos JPG/PNG/WebP), optimización automática a máx. 1200 px con Pillow y nombres con hash SHA-256.
  - `etiquetas.js`: Nube interactiva de chips, búsqueda en vivo y modal AJAX para crear etiquetas sin salir del editor.
  - `lateral.js`: Pestañas accesibles (`role="tablist"`), sincronización en tiempo real de tarjetas para SERP de Google y Twitter/Open Graph.
  - `checklist.js`: Barra de progreso y lista "Antes de publicar" con reglas obligatorias bloqueantes y recomendaciones con navegación "Ir".
  - `vista-previa.js`: Modal multidispositivo (Escritorio 1200px, Tableta 768px, Móvil 375px) en `iframe` aislado con alternador de tema claro/oscuro independiente.
  - `historial.js`: Timeline de revisiones históricas con visor de diferencias y restauración en un clic.
  - `atajos.js`: Manejo de atajos de teclado accesibles.

### 3. Atajos de Teclado del Estudio
| Atajo | Acción |
| --- | --- |
| <kbd>Ctrl</kbd> + <kbd>S</kbd> / <kbd>Cmd</kbd> + <kbd>S</kbd> | Guardar cambios inmediatamente |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> | Abrir modal de Publicación / Programación |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>F</kbd> | Alternar modo de concentración / enfoque |
| <kbd>Ctrl</kbd> + <kbd>Enter</kbd> | Abrir vista previa multidispositivo en vivo |
| <kbd>?</kbd> | Consultar chuleta de atajos de teclado |
| <kbd>Esc</kbd> | Salir del modo de enfoque o cerrar modal activo |

### 4. Publicación de Artículos Programados (Cron y Comando de Gestión)
Los artículos con estado `PROGRAMADO` se publican de forma automática cuando se cumple su fecha fijada mediante el comando:
```bash
python manage.py publicar_programados
```
- Admite `--dry-run` para previsualizar sin alterar la base de datos.
- Utiliza `select_for_update(skip_locked=True)` para garantizar seguridad contra condiciones de carrera si concurren múltiples instancias de cron o workers.
- Configurado en `render.yaml` como un trabajo programado (Cron Job) que se ejecuta cada 5 minutos (`*/5 * * * *`).

---

## Experiencia Pública: Foro Adaptable de Lectura y Discusión

La experiencia pública del blog funciona como un **foro de lectura y debate técnico adaptable** (referencias: Reddit, Stack Overflow, Quora, X) sobre una **única base responsive** que escala con fluidez desde 360 px en celulares hasta pantallas 4K.

### 1. Características Principales
- **Feed adaptable de 1 clic:** Acceso a lectura, orden temporal con decaimiento logarítmico (Hot / Mejores), filtros por comunidad y etiquetas, y alternador entre vista de tarjetas y vista compacta (`vista_feed`).
- **Riel de votos unificado:** Votación positiva (▲) y negativa (▼) con actualización optimista inmediata y reversión automática ante fallos de conexión.
- **Hilos de discusión anidados estilo Reddit:**
  - Guías visuales verticales indentadas (`.comment-tree-guide`).
  - Colapso instantáneo de hilos `[–]` con resumen `[+] @autor · N respuestas ocultas`.
  - Límite de indentación visual a nivel 4 con enlace a subhilos.
  - Compositor de respuestas en línea con atajo `Ctrl + Enter` y límite de 1000 caracteres.
- **Acceso para visitantes retenido:** Modal / hoja inferior sin interrupción que retiene la acción pretendida del lector (voto, guardado, respuesta) y la reintenta automáticamente tras iniciar sesión.
- **Buscador global con sugerencias en vivo:** Desplegable instantáneo con artículos, comunidades, autores y etiquetas mediante endpoint cacheado `/buscar/sugerencias/`.
- **Rendimiento y PWA:**
  - Generación de variantes WebP (192px miniatura, 640px y 1200px portadas) con `srcset` y `sizes`.
  - Cero CLS garantizado con dimensiones y `aspect-ratio` explícitos.
  - Carga diferida nativa (`loading="lazy"`, `decoding="async"`).
  - Optimización de scroll con `content-visibility: auto` en las filas fuera de pantalla.
  - PWA mínima con `manifest.webmanifest`, íconos 192 y 512, y meta etiquetas `theme-color` para modos claro y oscuro.

### 2. Atajos de Teclado Globales del Foro
- `/` o `Ctrl + K`: Enfocar buscador con sugerencias.
- `j` / `k`: Navegar al post siguiente o anterior en el feed.
- `Enter` u `o`: Abrir el post enfocado.
- `a`: Votar positivo (Upvote) en el post seleccionado.
- `s`: Guardar o desguardar post en tu lista privada.
- `c`: Saltar a los comentarios del post.
- `g` + `h`: Volver al inicio.
- `Esc`: Cerrar modales, buscador o paneles.

### 3. Scripts de Tareas y Verificación (`scripts/tareas.ps1`)
Se incluye un script unificado de automatización en PowerShell:
```powershell
# Ejecutar suite de pruebas unitarias e integración de Django (88 pruebas)
.\scripts\tareas.ps1 test

# Ejecutar pruebas E2E de presupuesto de clics (Playwright)
.\scripts\tareas.ps1 e2e

# Ejecutar matriz visual multidispositivo (iPhone 13, Pixel 7, iPad Mini, iPad Pro, Desktop)
.\scripts\tareas.ps1 visual

# Comprobar estado del sistema y configuración de producción
.\scripts\tareas.ps1 check
```
Para detalles completos sobre tokens CSS, puntos de quiebre y especificaciones de componentes, consulta [`docs/DISENO.md`](docs/DISENO.md).
