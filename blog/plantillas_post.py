"""
Definiciones de plantillas de inicio para nuevos posts en el Estudio de Escritura.
Cada plantilla incluye clave, nombre, descripción, ícono Bootstrap, título sugerido
y contenido HTML guía compatible con el saneado de bleach y CKEditor 5.
"""

PLANTILLAS_POST = {
    'en_blanco': {
        'clave': 'en_blanco',
        'nombre': 'En blanco',
        'descripcion': 'Empieza desde un lienzo limpio sin estructura predefinida.',
        'icono': 'bi-file-earmark',
        'titulo_sugerido': '',
        'contenido_html': '<p>Escribe aquí tu introducción...</p>',
    },
    'tutorial': {
        'clave': 'tutorial',
        'nombre': 'Tutorial paso a paso',
        'descripcion': 'Estructura didáctica orientada a explicar un proceso técnico de principio a fin.',
        'icono': 'bi-signpost-split-fill',
        'titulo_sugerido': 'Cómo implementar [Tecnología/Proceso] paso a paso',
        'contenido_html': (
            '<h2>Introducción</h2>'
            '<p>Explica brevemente qué aprenderá el lector en este tutorial y qué problema resuelve.</p>'
            '<h2>Requisitos previos</h2>'
            '<ul>'
            '<li>Herramienta o lenguaje necesario (con versión recomendada).</li>'
            '<li>Conocimientos básicos requeridos.</li>'
            '<li>Configuración inicial del entorno.</li>'
            '</ul>'
            '<h2>Paso 1: Configuración inicial</h2>'
            '<p>Describe el primer paso y muestra el comando o bloque de código correspondiente:</p>'
            '<pre><code class="language-bash"># Comando de instalación o inicio\n'
            'echo "Iniciando configuración"</code></pre>'
            '<h2>Paso 2: Implementación principal</h2>'
            '<p>Detalla el núcleo de la solución paso a paso con buenas prácticas.</p>'
            '<pre><code class="language-python"># Código de ejemplo principal\n'
            'def solucion():\n'
            '    return "Implementación exitosa"</code></pre>'
            '<h2>Paso 3: Verificación y pruebas</h2>'
            '<p>Muestra cómo comprobar que todo funciona correctamente mediante pruebas o comandos.</p>'
            '<h2>Conclusión y siguientes pasos</h2>'
            '<p>Resume lo aprendido y comparte recursos adicionales o ideas para continuar experimentando.</p>'
        ),
    },
    'guia_rapida': {
        'clave': 'guia_rapida',
        'nombre': 'Guía rápida',
        'descripcion': 'Referencia ágil y concisa con comandos, trucos o soluciones a problemas comunes.',
        'icono': 'bi-lightning-charge-fill',
        'titulo_sugerido': 'Guía rápida de [Tema]: Atajos y mejores prácticas',
        'contenido_html': (
            '<h2>Resumen rápido</h2>'
            '<p>Un vistazo conciso a lo más importante que necesitas saber en 2 minutos.</p>'
            '<h2>Comandos y ejemplos esenciales</h2>'
            '<pre><code class="language-bash"># Comando más utilizado\n'
            'run --quick-mode</code></pre>'
            '<h2>Errores comunes y soluciones</h2>'
            '<ul>'
            '<li><strong>Error frecuente 1:</strong> Explicación de la causa y la solución rápida.</li>'
            '<li><strong>Error frecuente 2:</strong> Parámetro o ajuste recomendado.</li>'
            '</ul>'
            '<h2>Hoja de trucos (Cheat Sheet)</h2>'
            '<p>Tabla o lista resumen para tener siempre a mano.</p>'
        ),
    },
    'analisis': {
        'clave': 'analisis',
        'nombre': 'Análisis o comparativa',
        'descripcion': 'Contrasta dos o más tecnologías, herramientas o patrones de arquitectura.',
        'icono': 'bi-bar-chart-steps',
        'titulo_sugerido': '[Opción A] vs [Opción B]: ¿Cuál elegir en [Año]?',
        'contenido_html': (
            '<h2>Contexto y motivación</h2>'
            '<p>Presenta el dilema o escenario en el que surge la necesidad de comparar estas alternativas.</p>'
            '<h2>Visión general de las opciones</h2>'
            '<h3>Opción A</h3>'
            '<p>Puntos fuertes, filosofía de diseño y casos donde brilla especialmente.</p>'
            '<h3>Opción B</h3>'
            '<p>Ventajas competitivas, ecosistema y madurez en producción.</p>'
            '<h2>Tabla comparativa de características</h2>'
            '<p>Compara rendimiento, facilidad de uso, curva de aprendizaje y soporte de la comunidad.</p>'
            '<h2>Benchmarks y pruebas prácticas</h2>'
            '<p>Resultados medibles o impresiones tras probar ambas opciones en condiciones reales.</p>'
            '<h2>Veredicto y recomendación</h2>'
            '<p>Cuándo elegir la Opción A y cuándo conviene optar por la Opción B.</p>'
        ),
    },
    'caso_estudio': {
        'clave': 'caso_estudio',
        'nombre': 'Caso de estudio',
        'descripcion': 'Narra una experiencia real de resolución de problemas, refactorización o escalado.',
        'icono': 'bi-journal-check',
        'titulo_sugerido': 'Cómo resolvimos [Problema real]: Lecciones aprendidas',
        'contenido_html': (
            '<h2>El desafío</h2>'
            '<p>Describe la situación de partida, las métricas afectadas y el impacto del problema.</p>'
            '<h2>Diagnóstico y causa raíz</h2>'
            '<p>Explica qué herramientas de monitoreo, logs o perfiles permitieron identificar el cuello de botella.</p>'
            '<h2>La solución implementada</h2>'
            '<p>Estrategia adoptada, cambios arquitectónicos y decisiones de compensación (trade-offs).</p>'
            '<pre><code class="language-python"># Fragmento representativo del cambio\n'
            '# optimizado para escala</code></pre>'
            '<h2>Resultados y métricas</h2>'
            '<ul>'
            '<li>Reducción del tiempo de respuesta o uso de recursos.</li>'
            '<li>Estabilidad y fiabilidad conseguida.</li>'
            '</ul>'
            '<h2>Lecciones aprendidas</h2>'
            '<p>Qué haríamos diferente y consejos aplicables a otros proyectos similares.</p>'
        ),
    },
}


def obtener_plantilla(clave):
    """Devuelve el diccionario de la plantilla solicitada o la plantilla en blanco por defecto."""
    return PLANTILLAS_POST.get(clave) or PLANTILLAS_POST['en_blanco']


def listar_plantillas():
    """Devuelve la lista ordenada de plantillas disponibles para selector."""
    return list(PLANTILLAS_POST.values())

