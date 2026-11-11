from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blog.models import (
    Categoria,
    Comentario,
    Etiqueta,
    ItemLista,
    LikeComentario,
    LikePost,
    ListaLectura,
    MiembroCategoria,
    Notificacion,
    Post,
    ReglaCategoria,
    ReporteComentario,
    Seguimiento,
    Suscripcion,
    VistaDiaria,
    VotoUtil,
)
from blog.notificaciones import notificar
from cuentas.models import Perfil

User = get_user_model()


class Command(BaseCommand):
    help = (
        'Carga datos de demostración: 2 usuarios autores, 3 categorías, '
        '6 etiquetas, 8 posts (6 publicados y 2 en borrador con HTML variado) '
        'y varios comentarios.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Cargando datos de demostración...'))

        # 1. Crear 2 usuarios con sus perfiles
        usuarios_datos = [
            {
                'username': 'ana_garcia',
                'email': 'ana.garcia@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'Ana',
                'last_name': 'García',
                'is_staff': True,
                'is_superuser': True,
                'bio': (
                    'Ingeniera de Software Senior especializada en Python, Django y '
                    'arquitecturas backend escalables con PostgreSQL.'
                ),
            },
            {
                'username': 'carlos_ruiz',
                'email': 'carlos.ruiz@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'Carlos',
                'last_name': 'Ruiz',
                'is_staff': False,
                'is_superuser': False,
                'bio': (
                    'Consultor DevOps y desarrollador full-stack apasionado por los '
                    'contenedores Docker, la seguridad web y el despliegue continuo.'
                ),
            },
            {
                'username': 'elena_torres',
                'email': 'elena.torres@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'Elena',
                'last_name': 'Torres',
                'is_staff': False,
                'is_superuser': False,
                'bio': (
                    'Desarrolladora Frontend enfocada en accesibilidad web (WCAG), '
                    'sistemas de diseño con variables CSS y experiencia de usuario.'
                ),
            },
            {
                'username': 'lucia_mendez',
                'email': 'lucia.mendez@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'Lucía',
                'last_name': 'Méndez',
                'is_staff': False,
                'is_superuser': False,
                'bio': 'Arquitecta Frontend especializada en rendimiento de aplicaciones web, React, TypeScript y microfrontends.',
            },
            {
                'username': 'miguel_sanchez',
                'email': 'miguel.sanchez@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'Miguel',
                'last_name': 'Sánchez',
                'is_staff': False,
                'is_superuser': False,
                'bio': 'Ingeniero de datos y backend enfocado en pipelines distribuidos con Celery, Redis, FastAPI y arquitecturas asíncronas.',
            },
            {
                'username': 'david_veiga',
                'email': 'david.veiga@ejemplo.com',
                'password': 'DemoPassword123!',
                'first_name': 'David',
                'last_name': 'Veiga',
                'is_staff': False,
                'is_superuser': False,
                'bio': 'Site Reliability Engineer (SRE). Especialista en observabilidad con Prometheus, Grafana y automatización con Kubernetes.',
            },
        ]

        perfiles = {}
        for u_data in usuarios_datos:
            user, created = User.objects.get_or_create(
                username=u_data['username'],
                defaults={
                    'email': u_data['email'],
                    'first_name': u_data['first_name'],
                    'last_name': u_data['last_name'],
                    'is_staff': u_data['is_staff'],
                    'is_superuser': u_data['is_superuser'],
                },
            )
            user.first_name = u_data['first_name']
            user.last_name = u_data['last_name']
            user.email = u_data['email']
            user.set_password(u_data['password'])
            user.is_staff = u_data['is_staff']
            user.is_superuser = u_data['is_superuser']
            user.save()

            perfil, _ = Perfil.objects.get_or_create(usuario=user)
            perfil.bio = u_data['bio']
            perfil.save()
            perfiles[u_data['username']] = perfil

        self.stdout.write(self.style.SUCCESS('✔ 3 usuarios y perfiles listos (ana_garcia, carlos_ruiz, elena_torres).'))

        # 2. Crear 3 categorías como comunidades con descripciones y reglas
        categorias_info = [
            {
                'nombre': 'Desarrollo Web',
                'descripcion': (
                    'Comunidad dedicada a arquitecturas backend con Django y Python, '
                    'sistemas de diseño accesibles, CSS moderno y buenas prácticas web.'
                ),
                'reglas': [
                    ('Comparte código reproducible', 'Incluye fragmentos claros y especifica la versión de Python o Django.'),
                    ('Respeto y crítica constructiva', 'Debate las ideas técnicas con amabilidad y argumentos.'),
                    ('Cuida la accesibilidad y el rendimiento', 'Prioriza soluciones semánticas y libres de consultas N+1.'),
                ],
            },
            {
                'nombre': 'Bases de Datos',
                'descripcion': (
                    'Espacio para profundizar en PostgreSQL, optimización de consultas SQL, '
                    'índices GIN/GiST, búsqueda full-text y modelado de datos relacional.'
                ),
                'reglas': [
                    ('Muestra el plan de ejecución', 'Cuando consultes sobre lentitud en SQL, acompaña tu post con EXPLAIN ANALYZE.'),
                    ('Evita capturas de texto plano', 'Publica las consultas y esquemas en bloques de código formateados.'),
                    ('Indica el motor y la versión', 'Aclara si usas PostgreSQL 16, SQLite u otro motor relacional.'),
                ],
            },
            {
                'nombre': 'DevOps y Seguridad',
                'descripcion': (
                    'Comunidad sobre contenedores Docker, despliegue continuo en la nube, '
                    'mitigación de vulnerabilidades OWASP y endurecimiento de servidores.'
                ),
                'reglas': [
                    ('No publiques secretos ni credenciales reales', 'Usa variables de entorno de ejemplo y redacta cualquier token.'),
                    ('Divulgación responsable', 'Comparte configuraciones defensivas y buenas prácticas de seguridad.'),
                    ('Infraestructura reproducible', 'Documenta los pasos de construcción en Dockerfile o scripts claros.'),
                ],
            },
            {
                'nombre': 'Arquitectura de Software',
                'descripcion': (
                    'Patrones de diseño limpios, microservicios, eventos distribuidos, '
                    'CQRS y modularidad en sistemas de alta demanda con Python.'
                ),
                'reglas': [
                    ('Justifica las decisiones de diseño', 'Explica el porqué del patrón elegido frente a alternativas más simples.'),
                    ('Diagramas y diagramación clara', 'Acompaña explicaciones complejas con esquemas o diagramas de flujo.'),
                    ('Código enfocado en la mantenibilidad', 'Prioriza la legibilidad y la facilidad de prueba en los ejemplos.'),
                ],
            },
            {
                'nombre': 'Inteligencia Artificial y ML',
                'descripcion': (
                    'Integración de modelos LLM, RAG (Retrieval-Augmented Generation), '
                    'embeddings semánticos y pipelines de inferencia en aplicaciones web.'
                ),
                'reglas': [
                    ('Seguridad y ética en IA', 'Verifica que los prompts y modelos respeten privacidad y no filtren datos sensibles.'),
                    ('Métricas y evaluación', 'Comparte benchmarks concretos sobre latencia, precisión y costo de tokens.'),
                    ('Enfócate en la integración con código real', 'Muestra cómo conectar modelos a bases de datos y APIs web.'),
                ],
            },
        ]
        categorias = {}
        for c_info in categorias_info:
            cat, _ = Categoria.objects.get_or_create(nombre=c_info['nombre'])
            cat.descripcion = c_info['descripcion']
            cat.save()
            categorias[c_info['nombre']] = cat

            for idx, (r_titulo, r_desc) in enumerate(c_info['reglas'], start=1):
                ReglaCategoria.objects.update_or_create(
                    categoria=cat,
                    orden=idx,
                    defaults={
                        'titulo': r_titulo,
                        'descripcion': r_desc,
                    },
                )

        self.stdout.write(self.style.SUCCESS(f'✔ {len(categorias)} categorías con descripción y reglas creadas.'))

        # 3. Crear etiquetas técnicas
        nombres_etiquetas = [
            'Python',
            'Django',
            'PostgreSQL',
            'Docker',
            'Seguridad',
            'Rendimiento',
            'FastAPI',
            'Redis',
            'React',
            'TypeScript',
            'Frontend',
            'Testing',
            'CleanCode',
            'Kubernetes',
            'IA',
            'Microservicios',
        ]
        etiquetas = {}
        for nombre in nombres_etiquetas:
            tag, _ = Etiqueta.objects.get_or_create(nombre=nombre)
            etiquetas[nombre] = tag

        self.stdout.write(self.style.SUCCESS('✔ 6 etiquetas creadas.'))

        # 4. Crear 8 posts (6 publicados y 2 en borrador, con HTML variado)
        posts_datos = [
            {
                'titulo': 'Arquitectura limpia en proyectos Django 5 de gran escala',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Desarrollo Web'],
                'etiquetas': ['Python', 'Django', 'Rendimiento'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Introducción a una arquitectura mantenible</h2>
                    <p>Construir aplicaciones en <strong>Django 5</strong> requiere separar responsabilidades con claridad entre modelos, vistas basadas en clases y servicios de dominio para mantener el código limpio y fácil de probar.</p>
                    <blockquote>La simplicidad y las convenciones explícitas hacen que un proyecto Django sea fácil de mantener durante años.</blockquote>
                    <h3>Buenas prácticas recomendadas en el ORM</h3>
                    <ul>
                        <li>Utilizar <code>select_related</code> y <code>prefetch_related</code> en los listados.</li>
                        <li>Encapsular consultas complejas en <em>QuerySets</em> personalizados.</li>
                        <li>Validar datos tanto en formularios como en modelos.</li>
                    </ul>
                    <h3>Ejemplo de QuerySet personalizado con anotaciones</h3>
                    <pre><code class="language-python">class PostQuerySet(models.QuerySet):
    def publicados(self):
        return self.filter(estado='publicado').select_related('autor__usuario', 'categoria')

    def con_metricas(self):
        return self.annotate(total_likes=Count('likes', distinct=True))</code></pre>
                    <h2>Separación de lógica de dominio y notificaciones</h2>
                    <p>Aislar el envío de notificaciones y correos en módulos dedicados evita acoplar las vistas HTTP con efectos secundarios y facilita las pruebas automatizadas.</p>
                """,
            },
            {
                'titulo': 'Búsqueda Full-Text en PostgreSQL con Django y SearchVector',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Bases de Datos'],
                'etiquetas': ['PostgreSQL', 'Django', 'Python'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Potenciando las búsquedas en español</h2>
                    <p>El módulo <code>django.contrib.postgres.search</code> permite implementar motores de búsqueda rápidos con soporte de lematización en español sin depender de servicios externos adicionales.</p>
                    <h3>Ponderación por niveles de relevancia</h3>
                    <ol>
                        <li><strong>Peso A:</strong> Título principal del artículo.</li>
                        <li><strong>Peso B:</strong> Etiquetas asociadas.</li>
                        <li><strong>Peso C:</strong> Cuerpo del artículo.</li>
                    </ol>
                    <h3>Tabla comparativa de pesos en SearchVector</h3>
                    <table>
                        <thead>
                            <tr><th>Nivel</th><th>Campo</th><th>Prioridad</th></tr>
                        </thead>
                        <tbody>
                            <tr><td>A</td><td>Título</td><td>Máxima (1.0)</td></tr>
                            <tr><td>B</td><td>Etiquetas</td><td>Alta (0.4)</td></tr>
                            <tr><td>C</td><td>Contenido</td><td>Media (0.2)</td></tr>
                        </tbody>
                    </table>
                    <pre><code class="language-python">vector = (
    SearchVector('titulo', weight='A', config='spanish')
    + SearchVector('contenido', weight='C', config='spanish')
)</code></pre>
                """,
            },
            {
                'titulo': 'Contenedores seguros en producción con Docker y Gunicorn',
                'autor': perfiles['carlos_ruiz'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Docker', 'Seguridad', 'Python'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Por qué nunca debes ejecutar contenedores como root</h2>
                    <p>Al empaquetar una aplicación <strong>Django</strong> en Docker con <code>python:3.12-slim</code>, es fundamental crear un usuario sin privilegios antes de iniciar <em>Gunicorn</em>.</p>
                    <h3>Configuración del Dockerfile seguro</h3>
                    <pre><code class="language-dockerfile">RUN adduser --disabled-password --gecos "" appuser
USER appuser
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]</code></pre>
                    <h3>Archivos estáticos con WhiteNoise</h3>
                    <p>Además, recuerda combinarlo con <strong>WhiteNoise</strong> para servir archivos estáticos comprimidos con cabeceras de caché eficientes.</p>
                """,
            },
            {
                'titulo': 'Prevención de ataques XSS al usar editores WYSIWYG como CKEditor 5',
                'autor': perfiles['carlos_ruiz'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Seguridad', 'Django', 'Python'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Saneado de HTML en el servidor con Bleach</h2>
                    <p>Cuando los autores redactan contenido enriquecido en <strong>CKEditor 5</strong>, nunca debemos renderizar el HTML sin antes filtrarlo contra una lista blanca estricta en el servidor.</p>
                    <blockquote>Nunca confíes únicamente en la validación del navegador; sanea siempre el HTML antes de mostrarlo al público.</blockquote>
                    <h3>Permitir resaltado de sintaxis seguro</h3>
                    <p>Con la librería <a href="https://bleach.readthedocs.io/" target="_blank" rel="noopener">Bleach</a> podemos permitir etiquetas como <code>&lt;p&gt;</code>, <code>&lt;h2&gt;</code>, <code>&lt;table&gt;</code> y validar clases <code>language-*</code> en bloques de código eliminando cualquier script malicioso.</p>
                """,
            },
            {
                'titulo': 'Optimización de consultas SQL y eliminación del problema N+1',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Bases de Datos'],
                'etiquetas': ['PostgreSQL', 'Rendimiento', 'Django'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Detectando cuellos de botella en el ORM</h2>
                    <p>El problema de las consultas <strong>N+1</strong> ocurre cuando iteramos sobre una lista de objetos y accedemos a sus relaciones foráneas sin haberlas precargado en la consulta principal.</p>
                    <h3>Comparativa de métodos del ORM</h3>
                    <table>
                        <thead>
                            <tr><th>Método</th><th>Tipo de relación</th><th>Estrategia SQL</th></tr>
                        </thead>
                        <tbody>
                            <tr><td><code>select_related</code></td><td>ForeignKey / OneToOne</td><td>Sentencias INNER/LEFT JOIN</td></tr>
                            <tr><td><code>prefetch_related</code></td><td>ManyToMany / Reverse FK</td><td>Consulta separada y unión en Python</td></tr>
                        </tbody>
                    </table>
                    <h3>Subconsultas con OuterRef y Subquery</h3>
                    <pre><code class="language-python">comentarios_sub = (
    Comentario.objects.filter(post=OuterRef('pk'), aprobado=True)
    .values('post')
    .annotate(c=Count('id'))
    .values('c')
)</code></pre>
                """,
            },
            {
                'titulo': 'Despliegue continuo en Render con PostgreSQL y WhiteNoise',
                'autor': perfiles['carlos_ruiz'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Docker', 'PostgreSQL', 'Django'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Infraestructura como código con render.yaml</h2>
                    <p>Automatizar el despliegue mediante un archivo <code>render.yaml</code> y un script <code>build.sh</code> garantiza entornos reproducibles desde el primer día en la nube.</p>
                    <h3>Pasos del script de construcción</h3>
                    <ul>
                        <li>Instalación automática de dependencias desde <code>requirements.txt</code>.</li>
                        <li>Recolección de archivos estáticos con <code>collectstatic --no-input</code>.</li>
                        <li>Aplicación automática de migraciones en la base de datos gestionada.</li>
                    </ul>
                    <h3>Ejemplo de configuración en YAML</h3>
                    <pre><code class="language-yaml">services:
  - type: web
    name: blog-panel-autor
    env: python
    buildCommand: "./build.sh"
    startCommand: "gunicorn config.wsgi:application"</code></pre>
                """,
            },
            {
                'titulo': 'Sistemas de diseño accesibles en Django con variables CSS y modo oscuro',
                'autor': perfiles['elena_torres'],
                'categoria': categorias['Desarrollo Web'],
                'etiquetas': ['Django', 'Python'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Tokens de color y contraste WCAG AA</h2>
                    <p>Definir una paleta semántica con variables CSS en <code>:root</code> y <code>[data-bs-theme="dark"]</code> permite garantizar un contraste mínimo de 4.5:1 en cualquier interfaz web.</p>
                    <h3>Estructura de variables reutilizables</h3>
                    <pre><code class="language-css">:root {
  --color-primary: #2563eb;
  --color-text-primary: #0f172a;
  --color-text-secondary: #475569;
}</code></pre>
                    <h3>Respeto a prefers-reduced-motion</h3>
                    <p>Desactivar transiciones innecesarias cuando el usuario configura reducción de movimiento mejora la accesibilidad y comodidad de lectura.</p>
                """,
            },
            {
                'titulo': 'Integración de Redis y Celery para colas asíncronas de alto rendimiento',
                'autor': perfiles['miguel_sanchez'],
                'categoria': categorias['Arquitectura de Software'],
                'etiquetas': ['Redis', 'Python', 'Rendimiento'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Procesamiento en segundo plano escalable</h2>
                    <p>Descargar tareas pesadas como envío masivo de correos, generación de PDFs y procesamiento de imágenes a <strong>Celery</strong> con broker <strong>Redis</strong> mantiene las respuestas HTTP por debajo de 50ms.</p>
                    <h3>Definición de tarea idempotente</h3>
                    <pre><code class="language-python">@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def procesar_reporte_mensual(self, usuario_id):
    try:
        generar_balance_analitico(usuario_id)
    except DatabaseError as exc:
        raise self.retry(exc=exc)</code></pre>
                    <p>Configurar <code>CELERY_TASK_ACKS_LATE = True</code> garantiza que los mensajes no se pierdan si un worker falla inesperadamente.</p>
                """,
            },
            {
                'titulo': 'Microfrontends con React y renderizado híbrido en Django',
                'autor': perfiles['lucia_mendez'],
                'categoria': categorias['Desarrollo Web'],
                'etiquetas': ['React', 'TypeScript', 'Frontend'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Uniendo lo mejor de dos mundos</h2>
                    <p>Combinar la robustez del backend de <strong>Django</strong> con componentes interactivos construidos en <strong>React 19</strong> y <strong>TypeScript</strong> permite crear experiencias tipo SPA sin perder SEO ni la seguridad del servidor.</p>
                    <h3>Incrustación sin fricción</h3>
                    <p>Utilizamos puntos de montaje mediante <code>data-*</code> attributes en las plantillas Django para hidratar islas interactivas de forma progresiva.</p>
                    <pre><code class="language-typescript">interface UserWidgetProps {
    userId: number;
    initialRole: string;
}

export const UserWidget: React.FC<UserWidgetProps> = ({ userId, initialRole }) => {
    const [role, setRole] = useState(initialRole);
    return &lt;div className="badge-pill"&gt;{role}&lt;/div&gt;;
};</code></pre>
                """,
            },
            {
                'titulo': 'Monitoreo en tiempo real con Prometheus y Grafana en Kubernetes',
                'autor': perfiles['david_veiga'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Kubernetes', 'Docker', 'Rendimiento'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Observabilidad de infraestructura y métricas RED</h2>
                    <p>En entornos de microservicios, medir <em>Rate, Errors y Duration</em> (RED) es imprescindible para detectar anomalías antes de que afecten a los usuarios finales.</p>
                    <h3>Métricas clave a instrumentar</h3>
                    <ul>
                        <li><strong>Latencia P99:</strong> Tiempo de respuesta del 99% de las peticiones HTTP.</li>
                        <li><strong>Saturación del pool de base de datos:</strong> Conexiones activas frente al límite máximo de PostgreSQL.</li>
                        <li><strong>Tasa de fallos en colas:</strong> Tareas rechazadas o enviadas al dead-letter queue.</li>
                    </ul>
                """,
            },
            {
                'titulo': 'Construcción de APIs ultra veloces con FastAPI y Pydantic v2',
                'autor': perfiles['miguel_sanchez'],
                'categoria': categorias['Desarrollo Web'],
                'etiquetas': ['FastAPI', 'Python', 'Rendimiento'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Por qué Pydantic v2 cambia las reglas del juego</h2>
                    <p>Gracias al núcleo en Rust de <strong>Pydantic v2</strong>, la serialización y validación de esquemas en <strong>FastAPI</strong> es hasta 15 veces más rápida que en versiones anteriores.</p>
                    <pre><code class="language-python">from pydantic import BaseModel, EmailStr, Field

class UsuarioSchema(BaseModel):
    id: int
    email: EmailStr
    activo: bool = True
    puntos: int = Field(ge=0, default=0)</code></pre>
                """,
            },
            {
                'titulo': 'Arquitectura RAG: Embeddings semánticos y búsqueda vectorial con pgvector',
                'autor': perfiles['elena_torres'],
                'categoria': categorias['Inteligencia Artificial y ML'],
                'etiquetas': ['IA', 'PostgreSQL', 'Python'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Búsqueda semántica integrada directamente en PostgreSQL</h2>
                    <p>La extensión <code>pgvector</code> permite almacenar y consultar vectores de alta dimensionalidad directamente en la misma base de datos relacional donde residen tus posts y usuarios.</p>
                    <h3>Índices HNSW vs IVFFlat</h3>
                    <p>Para conjuntos de datos con miles de documentos, los índices <strong>HNSW</strong> (Hierarchical Navigable Small World) ofrecen una relación óptima entre velocidad de recuperación y precisión en memoria.</p>
                """,
            },
            {
                'titulo': 'Patrones de diseño en Python: CQRS sin complicar la infraestructura',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Arquitectura de Software'],
                'etiquetas': ['CleanCode', 'Python', 'Django'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Separando operaciones de lectura y escritura</h2>
                    <p>El patrón <strong>CQRS</strong> (Command Query Responsibility Segregation) no requiere herramientas complejas ni múltiples bases de datos: en Django puede implementarse limpiamente separando servicios de mutación (Commands) y modelos de lectura optimizados (Queries).</p>
                """,
            },
            {
                'titulo': 'Estrategias avanzadas de caching para mitigar Cache Stampede',
                'autor': perfiles['carlos_ruiz'],
                'categoria': categorias['Bases de Datos'],
                'etiquetas': ['Redis', 'PostgreSQL', 'Rendimiento'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Qué ocurre cuando expira una clave con miles de lecturas por segundo</h2>
                    <p>El fenómeno <em>Cache Stampede</em> o avalancha de caché ocurre cuando una clave muy solicitada expira y cientos de hilos intentan regenerarla simultáneamente atacando la base de datos.</p>
                    <h3>Solución: Probabilistic Early Expiration (XFetch)</h3>
                    <p>Computar anticipadamente la clave antes de su expiración física con un factor delta aleatorio elimina los picos de CPU al 100%.</p>
                """,
            },
            {
                'titulo': 'Testing integral en Django: Pruebas unitarias, de integración y carga',
                'autor': perfiles['david_veiga'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Testing', 'Python', 'Django'],
                'estado': Post.Estado.PUBLICADO,
                'contenido': """
                    <h2>Pirámide de pruebas aplicada a proyectos web</h2>
                    <p>Una estrategia sólida de calidad combina pruebas de modelos rápidas en memoria con tests de integración de vistas y pruebas de carga con <strong>Locust</strong> simulando 1,000 usuarios concurrentes.</p>
                """,
            },
            {
                'titulo': 'Borrador: Guía avanzada de índices GIN y GiST en PostgreSQL 16',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Bases de Datos'],
                'etiquetas': ['PostgreSQL', 'Rendimiento'],
                'estado': Post.Estado.BORRADOR,
                'contenido': """
                    <h2>Notas en preparación sobre índices invertidos</h2>
                    <p>Este artículo se encuentra actualmente en estado de <strong>borrador</strong> y solo puede ser visto y editado por su autora desde el Panel de Autor.</p>
                """,
            },
            {
                'titulo': 'Borrador: Checklist de cabeceras HSTS y cookies seguras en producción',
                'autor': perfiles['carlos_ruiz'],
                'categoria': categorias['DevOps y Seguridad'],
                'etiquetas': ['Seguridad', 'Django'],
                'estado': Post.Estado.BORRADOR,
                'contenido': """
                    <h2>Configuración de seguridad antes de salir a producción</h2>
                    <p>Este borrador privado revisa las directivas verificadas por <code>python manage.py check --deploy</code>.</p>
                """,
            },
            {
                'titulo': 'Programado: Análisis en profundidad del compilador JIT en Python 3.13',
                'autor': perfiles['ana_garcia'],
                'categoria': categorias['Desarrollo Web'],
                'etiquetas': ['Python', 'Rendimiento'],
                'estado': Post.Estado.PROGRAMADO,
                'programado_para': timezone.now() + timedelta(days=3),
                'contenido': """
                    <h2>El futuro del rendimiento en CPython</h2>
                    <p>Python 3.13 introduce un compilador Just-In-Time (JIT) experimental que transforma el bytecode en código máquina nativo. En este artículo analizamos su impacto en servidores web Django de alta concurrencia.</p>
                """,
            },
        ]

        posts_creados = []
        for p_data in posts_datos:
            post, created = Post.objects.get_or_create(
                titulo=p_data['titulo'],
                defaults={
                    'autor': p_data['autor'],
                    'categoria': p_data['categoria'],
                    'contenido': p_data['contenido'].strip(),
                    'estado': p_data['estado'],
                    'programado_para': p_data.get('programado_para'),
                },
            )
            if not created:
                post.autor = p_data['autor']
                post.categoria = p_data['categoria']
                post.contenido = p_data['contenido'].strip()
                post.estado = p_data['estado']
                if 'programado_para' in p_data:
                    post.programado_para = p_data['programado_para']
                post.save()

            post.etiquetas.set([etiquetas[nombre] for nombre in p_data['etiquetas']])
            posts_creados.append(post)

        # Crear algunas revisiones de ejemplo en el primer post
        from blog.models import RevisionPost
        if posts_creados:
            primer_post = posts_creados[0]
            if not RevisionPost.objects.filter(post=primer_post).exists():
                RevisionPost.objects.create(
                    post=primer_post,
                    titulo='Arquitectura inicial en Django 5',
                    contenido='<p>Versión borrador inicial de la estructura.</p>',
                    extracto='Estructura preliminar.',
                    origen=RevisionPost.Origen.AUTO
                )
                RevisionPost.objects.create(
                    post=primer_post,
                    titulo=primer_post.titulo,
                    contenido=primer_post.contenido,
                    extracto='Construir aplicaciones en Django 5 requiere separar responsabilidades con claridad.',
                    origen=RevisionPost.Origen.PUBLICACION
                )

        self.stdout.write(self.style.SUCCESS(f'✔ {len(posts_creados)} posts creados o sincronizados con plantillas y revisiones.'))

        # 5. Crear comentarios (aprobados y pendientes de moderación)
        comentarios_datos = [
            {
                'post': posts_creados[0],
                'nombre': 'Laura Méndez',
                'email': 'laura@ejemplo.com',
                'texto': 'Excelente explicación sobre cómo estructurar los QuerySets en Django 5. ¡Muy útil!',
                'aprobado': True,
            },
            {
                'post': posts_creados[0],
                'nombre': 'Diego Vargas',
                'email': 'diego@ejemplo.com',
                'texto': '¿Recomiendas usar vistas basadas en clases también para paneles administrativos a medida?',
                'aprobado': False,
            },
            {
                'post': posts_creados[1],
                'nombre': 'Sofía Castro',
                'email': 'sofia@ejemplo.com',
                'texto': 'La tabla con los pesos A, B y C de SearchVector me aclaró muchísimo cómo ordenar por relevancia.',
                'aprobado': True,
            },
            {
                'post': posts_creados[2],
                'nombre': 'Andrés Morales',
                'email': 'andres@ejemplo.com',
                'texto': 'Gran detalle el de usar un usuario no root en el Dockerfile para producción.',
                'aprobado': True,
            },
            {
                'post': posts_creados[3],
                'nombre': 'Valeria Ríos',
                'email': 'valeria@ejemplo.com',
                'texto': 'Acabo de integrar Bleach siguiendo este enfoque y funciona de maravilla con CKEditor 5.',
                'aprobado': False,
            },
            {
                'post': posts_creados[4],
                'nombre': 'Mateo Gómez',
                'email': 'mateo@ejemplo.com',
                'texto': 'Desde que aplicamos select_related y prefetch_related redujimos las consultas de 50 a solo 3.',
                'aprobado': True,
            },
            {
                'post': posts_creados[7],
                'nombre': 'David Veiga',
                'email': 'david.veiga@ejemplo.com',
                'texto': 'Gran artículo @miguel_sanchez. En producción con Kubernetes, Redis Sentinel nos ha dado una estabilidad impecable.',
                'aprobado': True,
            },
            {
                'post': posts_creados[8],
                'nombre': 'Elena Torres',
                'email': 'elena.torres@ejemplo.com',
                'texto': 'El enfoque de islas en Django es perfecto para no tener que migrar toda la app a una SPA compleja.',
                'aprobado': True,
            },
            {
                'post': posts_creados[9],
                'nombre': 'Carlos Ruiz',
                'email': 'carlos.ruiz@ejemplo.com',
                'texto': 'Las métricas RED nos salvaron en el último despliegue. Configurar alertas sobre el P99 de latencia es clave.',
                'aprobado': True,
            },
            {
                'post': posts_creados[10],
                'nombre': 'Ana García',
                'email': 'ana.garcia@ejemplo.com',
                'texto': 'Pydantic v2 es impresionante en velocidad. La validación con Rust en FastAPI se siente casi instantánea.',
                'aprobado': True,
            },
            {
                'post': posts_creados[11],
                'nombre': 'Miguel Sánchez',
                'email': 'miguel.sanchez@ejemplo.com',
                'texto': 'Tener pgvector dentro del mismo PostgreSQL nos ahorró levantar una base de datos vectorial dedicada.',
                'aprobado': True,
            },
            {
                'post': posts_creados[12],
                'nombre': 'Lucía Méndez',
                'email': 'lucia.mendez@ejemplo.com',
                'texto': 'Separar Commands de Queries hace que los tests unitarios no tengan efectos secundarios en la base de datos.',
                'aprobado': True,
            },
            {
                'post': posts_creados[13],
                'nombre': 'David Veiga',
                'email': 'david.veiga@ejemplo.com',
                'texto': 'El algoritmo probabilístico XFetch es una maravilla para evitar caídas cuando expira un cálculo pesado.',
                'aprobado': True,
            },
            {
                'post': posts_creados[14],
                'nombre': 'Carlos Ruiz',
                'email': 'carlos.ruiz@ejemplo.com',
                'texto': 'Las pruebas con Locust nos permitieron simular 2,000 conexiones concurrentes y ajustar los workers de Gunicorn.',
                'aprobado': True,
            },
        ]

        comentarios_creados = []
        for c_data in comentarios_datos:
            com, _ = Comentario.objects.get_or_create(
                post=c_data['post'],
                nombre=c_data['nombre'],
                email=c_data['email'],
                defaults={
                    'texto': c_data['texto'],
                    'aprobado': c_data['aprobado'],
                },
            )
            comentarios_creados.append(com)

        self.stdout.write(self.style.SUCCESS('✔ 6 comentarios creados (4 aprobados y 2 pendientes).'))

        # 6. Likes en posts, votos de utilidad, likes en comentarios, reportes y notificaciones
        ana_user = perfiles['ana_garcia'].usuario
        carlos_user = perfiles['carlos_ruiz'].usuario

        # Likes cruzados entre autores
        LikePost.objects.get_or_create(usuario=carlos_user, post=posts_creados[0])
        LikePost.objects.get_or_create(usuario=carlos_user, post=posts_creados[1])
        LikePost.objects.get_or_create(usuario=ana_user, post=posts_creados[2])
        LikePost.objects.get_or_create(usuario=ana_user, post=posts_creados[3])

        notificar(
            destinatario=ana_user,
            tipo=Notificacion.Tipo.LIKE_POST,
            actor=carlos_user,
            post=posts_creados[0],
        )
        notificar(
            destinatario=carlos_user,
            tipo=Notificacion.Tipo.LIKE_POST,
            actor=ana_user,
            post=posts_creados[2],
        )

        # Votos de utilidad (¿Te fue útil?)
        VotoUtil.objects.update_or_create(
            usuario=carlos_user,
            post=posts_creados[0],
            defaults={'util': True},
        )
        VotoUtil.objects.update_or_create(
            usuario=ana_user,
            post=posts_creados[0],
            defaults={'util': True},
        )
        VotoUtil.objects.update_or_create(
            usuario=carlos_user,
            post=posts_creados[1],
            defaults={'util': True},
        )
        VotoUtil.objects.update_or_create(
            usuario=ana_user,
            post=posts_creados[2],
            defaults={'util': True},
        )

        # Likes en comentarios aprobados
        LikeComentario.objects.get_or_create(usuario=ana_user, comentario=comentarios_creados[0])
        LikeComentario.objects.get_or_create(usuario=carlos_user, comentario=comentarios_creados[2])

        # Reportes de ejemplo sobre comentarios
        ReporteComentario.objects.get_or_create(
            comentario=comentarios_creados[0],
            reportante=carlos_user,
            defaults={
                'motivo': ReporteComentario.Motivo.SPAM,
                'detalle': 'Reporte de demostración para probar el panel de moderación de reportes.',
                'estado': ReporteComentario.Estado.PENDIENTE,
            },
        )
        ReporteComentario.objects.get_or_create(
            comentario=comentarios_creados[3],
            reportante=ana_user,
            defaults={
                'motivo': ReporteComentario.Motivo.OTRO,
                'detalle': 'Segundo reporte de demostración en un post de Carlos.',
                'estado': ReporteComentario.Estado.PENDIENTE,
            },
        )

        self.stdout.write(
            self.style.SUCCESS('✔ Likes, votos de utilidad, notificaciones y reportes demo cargados.')
        )

        # 7. Ronda 2: Seguidores, Suscripciones confirmadas, Vistas diarias y Listas de lectura
        # Carlos sigue a Ana para que Ana supere el umbral de autora Destacada (>= 8 pts),
        # mientras Carlos mantiene una puntuación menor al umbral para diferenciar insignias.
        Seguimiento.objects.get_or_create(seguidor=carlos_user, autor=perfiles['ana_garcia'])
        Seguimiento.objects.filter(seguidor=ana_user, autor=perfiles['carlos_ruiz']).delete()
        LikePost.objects.filter(usuario=ana_user, post__autor=perfiles['carlos_ruiz']).delete()
        VotoUtil.objects.filter(usuario=ana_user, post__autor=perfiles['carlos_ruiz']).delete()

        notificar(
            destinatario=ana_user,
            tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
            actor=carlos_user,
        )

        # Suscripciones por correo confirmadas (autor y categoría)
        Suscripcion.objects.update_or_create(
            email=carlos_user.email,
            autor=perfiles['ana_garcia'],
            defaults={
                'usuario': carlos_user,
                'confirmada': True,
                'activa': True,
            },
        )
        Suscripcion.objects.update_or_create(
            email=ana_user.email,
            categoria=categorias['DevOps y Seguridad'],
            defaults={
                'usuario': ana_user,
                'confirmada': True,
                'activa': True,
            },
        )

        # Vistas diarias de los últimos días en los posts publicados
        hoy = timezone.localdate()
        vistas_demo = [
            (posts_creados[0], 0, 18),
            (posts_creados[0], 1, 12),
            (posts_creados[1], 0, 14),
            (posts_creados[1], 2, 9),
            (posts_creados[2], 0, 15),
            (posts_creados[3], 1, 11),
            (posts_creados[4], 0, 8),
            (posts_creados[5], 3, 7),
        ]
        for post_obj, dias_atras, cantidad in vistas_demo:
            VistaDiaria.objects.update_or_create(
                post=post_obj,
                fecha=hoy - timedelta(days=dias_atras),
                defaults={'cantidad': cantidad},
            )

        # Listas de lectura ("Guardados" y lista pública personalizada)
        lista_guardados_ana, _ = ListaLectura.objects.get_or_create(
            usuario=ana_user,
            nombre=ListaLectura.NOMBRE_GUARDADOS,
            defaults={
                'descripcion': 'Artículos guardados para leer más tarde.',
                'publica': False,
                'es_predeterminada': True,
            },
        )
        ItemLista.objects.get_or_create(lista=lista_guardados_ana, post=posts_creados[2])
        ItemLista.objects.get_or_create(lista=lista_guardados_ana, post=posts_creados[3])

        lista_publica_ana, _ = ListaLectura.objects.update_or_create(
            usuario=ana_user,
            nombre='Lecturas Recomendadas de Arquitectura y DevOps',
            defaults={
                'descripcion': 'Colección pública de guías prácticas sobre Django 5, PostgreSQL y Docker.',
                'publica': True,
                'es_predeterminada': False,
            },
        )
        ItemLista.objects.get_or_create(lista=lista_publica_ana, post=posts_creados[0])
        ItemLista.objects.get_or_create(lista=lista_publica_ana, post=posts_creados[1])
        ItemLista.objects.get_or_create(lista=lista_publica_ana, post=posts_creados[2])

        self.stdout.write(
            self.style.SUCCESS('✔ Seguidores, suscripciones confirmadas, vistas diarias y listas de lectura cargados.')
        )

        # 8. Comunidades (MiembroCategoria), posts fijados en categoría y árbol de comentarios anidados
        elena_user = perfiles['elena_torres'].usuario

        lucia_user = perfiles['lucia_mendez'].usuario
        miguel_user = perfiles['miguel_sanchez'].usuario
        david_user = perfiles['david_veiga'].usuario

        # Membresías a comunidades
        MiembroCategoria.objects.get_or_create(usuario=ana_user, categoria=categorias['Desarrollo Web'])
        MiembroCategoria.objects.get_or_create(usuario=ana_user, categoria=categorias['Bases de Datos'])
        MiembroCategoria.objects.get_or_create(usuario=carlos_user, categoria=categorias['Desarrollo Web'])
        MiembroCategoria.objects.get_or_create(usuario=carlos_user, categoria=categorias['DevOps y Seguridad'])
        MiembroCategoria.objects.get_or_create(usuario=elena_user, categoria=categorias['Desarrollo Web'])
        MiembroCategoria.objects.get_or_create(usuario=elena_user, categoria=categorias['Inteligencia Artificial y ML'])
        MiembroCategoria.objects.get_or_create(usuario=lucia_user, categoria=categorias['Desarrollo Web'])
        MiembroCategoria.objects.get_or_create(usuario=lucia_user, categoria=categorias['Arquitectura de Software'])
        MiembroCategoria.objects.get_or_create(usuario=miguel_user, categoria=categorias['Arquitectura de Software'])
        MiembroCategoria.objects.get_or_create(usuario=miguel_user, categoria=categorias['Bases de Datos'])
        MiembroCategoria.objects.get_or_create(usuario=david_user, categoria=categorias['DevOps y Seguridad'])
        MiembroCategoria.objects.get_or_create(usuario=david_user, categoria=categorias['Arquitectura de Software'])

        # Likes y votos cruzados en posts adicionales
        for idx, u in enumerate([lucia_user, miguel_user, david_user, elena_user]):
            if idx + 7 < len(posts_creados):
                p = posts_creados[idx + 7]
                LikePost.objects.get_or_create(usuario=u, post=p)
                VotoUtil.objects.update_or_create(usuario=u, post=p, defaults={'util': True})
                VistaDiaria.objects.update_or_create(post=p, fecha=hoy, defaults={'cantidad': 25 + idx * 8})

        # Seguimientos cruzados
        Seguimiento.objects.get_or_create(seguidor=lucia_user, autor=perfiles['elena_torres'])
        Seguimiento.objects.get_or_create(seguidor=miguel_user, autor=perfiles['ana_garcia'])
        Seguimiento.objects.get_or_create(seguidor=david_user, autor=perfiles['carlos_ruiz'])

        # Fijar posts destacados en sus categorías (máximo 3 por categoría)
        for p_fijo in (posts_creados[0], posts_creados[6]):
            p_fijo.fijado_en_categoria = True
            p_fijo.save(update_fields=['fijado_en_categoria'])

        posts_creados[1].fijado_en_categoria = True
        posts_creados[1].save(update_fields=['fijado_en_categoria'])

        posts_creados[2].fijado_en_categoria = True
        posts_creados[2].save(update_fields=['fijado_en_categoria'])

        # Hilos de comentarios anidados en varios niveles (1 -> 2 -> 3 -> 4)
        # La raíz es el comentario de la visitante Laura Méndez (sin cuenta registrada)
        raiz_hilo = comentarios_creados[0]  # Comentario de Laura Méndez en posts_creados[0]
        if raiz_hilo.autor_id:
            raiz_hilo.autor = None
            raiz_hilo.save(update_fields=['autor'])

        nivel_2, _ = Comentario.objects.update_or_create(
            post=posts_creados[0],
            padre=raiz_hilo,
            autor=ana_user,
            nombre='Ana García',
            email=ana_user.email,
            defaults={
                'texto': '¡Gracias, Laura! Encapsular en QuerySets hace que las vistas queden muy limpias.',
                'aprobado': True,
            },
        )
        nivel_3, _ = Comentario.objects.update_or_create(
            post=posts_creados[0],
            padre=nivel_2,
            autor=carlos_user,
            nombre='Carlos Ruiz',
            email=carlos_user.email,
            defaults={
                'texto': 'Totalmente de acuerdo @ana_garcia, además facilita probar cada filtro por separado.',
                'aprobado': True,
            },
        )
        Comentario.objects.update_or_create(
            post=posts_creados[0],
            padre=nivel_3,
            autor=elena_user,
            nombre='Elena Torres',
            email=elena_user.email,
            defaults={
                'texto': 'Exacto, y combinado con annotate() evitamos por completo las consultas N+1.',
                'aprobado': True,
            },
        )

        # Un comentario eliminado con respuestas activas ([comentario eliminado])
        padre_eliminado, _ = Comentario.objects.update_or_create(
            post=posts_creados[0],
            padre=None,
            nombre='Usuario Anterior',
            email='anterior@ejemplo.com',
            defaults={
                'texto': 'Este comentario fue eliminado por su autor pero conserva su hilo.',
                'aprobado': True,
                'eliminado': True,
            },
        )
        Comentario.objects.update_or_create(
            post=posts_creados[0],
            padre=padre_eliminado,
            autor=carlos_user,
            nombre='Carlos Ruiz',
            email=carlos_user.email,
            defaults={
                'texto': 'Aunque el comentario original se eliminó, esta respuesta sigue visible para mantener el contexto de la conversación.',
                'aprobado': True,
            },
        )

        self.stdout.write(
            self.style.SUCCESS('✔ Membresías de comunidades, posts fijados e hilos anidados de comentarios cargados.')
        )
        self.stdout.write(self.style.SUCCESS('¡Datos de demostración cargados exitosamente!'))

