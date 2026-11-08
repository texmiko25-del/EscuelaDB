from pathlib import Path
from docx import Document
from docx.shared import Pt

BASE_DIR = Path(__file__).resolve().parent
PROJECT_FILES = [
    'manage.py',
    'config/settings.py',
    'config/urls.py',
    'config/wsgi.py',
    'config/asgi.py',
    'escuelaApp/apps.py',
    'escuelaApp/models.py',
    'escuelaApp/forms.py',
    'escuelaApp/admin.py',
    'escuelaApp/views.py',
    'escuelaApp/urls.py',
    'templates/escuelaApp/base.html',
    'templates/escuelaApp/home.html',
    'templates/escuelaApp/login.html',
    'templates/escuelaApp/dashboard.html',
    'templates/escuelaApp/admin_dashboard.html',
    'templates/escuelaApp/admin_custom/panel_principal.html',
    'templates/escuelaApp/admin_custom/crear_usuario.html',
    'templates/escuelaApp/admin_custom/modificar_dashboard.html',
    'static/css/base.css',
    'static/css/login.css',
    'static/css/dashboard.css',
    'static/css/admin.css',
    'create_escuela_db.sql',
]


def add_heading(document, text, level=1):
    document.add_heading(text, level=level)


def add_paragraph(document, text, bold=False):
    p = document.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(11)
    return p


def add_code_block(document, title, content):
    document.add_heading(title, level=3)
    p = document.add_paragraph()
    p.style = 'Intense Quote'
    for line in content.splitlines():
        run = p.add_run(line + '\n')
        run.font.name = 'Courier New'
        run.font.size = Pt(9)


def read_file_text(path):
    target = BASE_DIR / path
    if not target.exists():
        return f'Archivo no encontrado: {path}'
    return target.read_text(encoding='utf-8', errors='replace')


def build_document():
    doc = Document()
    doc.core_properties.title = 'Documentación del proyecto Escuela'
    doc.add_heading('Documentación del proyecto Escuela', level=0)
    add_paragraph(doc, 'Este documento describe la estructura del proyecto Django, la conexión a la base de datos y los archivos de interfaz gráfica.', bold=False)

    add_heading(doc, '1. Configuración de proyecto y conexión a la base de datos', level=1)
    settings_text = read_file_text('config/settings.py')
    add_code_block(doc, 'config/settings.py', settings_text)

    add_heading(doc, '2. URLs principales del proyecto', level=1)
    urls_text = read_file_text('config/urls.py')
    add_code_block(doc, 'config/urls.py', urls_text)
    app_urls_text = read_file_text('escuelaApp/urls.py')
    add_code_block(doc, 'escuelaApp/urls.py', app_urls_text)

    add_heading(doc, '3. Archivo de administración de Django', level=1)
    manage_text = read_file_text('manage.py')
    add_code_block(doc, 'manage.py', manage_text)

    add_heading(doc, '4. Aplicación escuelaApp', level=1)
    add_code_block(doc, 'escuelaApp/apps.py', read_file_text('escuelaApp/apps.py'))
    add_code_block(doc, 'escuelaApp/models.py', read_file_text('escuelaApp/models.py'))
    add_code_block(doc, 'escuelaApp/forms.py', read_file_text('escuelaApp/forms.py'))
    add_code_block(doc, 'escuelaApp/admin.py', read_file_text('escuelaApp/admin.py'))
    add_code_block(doc, 'escuelaApp/views.py', read_file_text('escuelaApp/views.py'))

    add_heading(doc, '5. Plantillas HTML', level=1)
    add_code_block(doc, 'templates/escuelaApp/base.html', read_file_text('templates/escuelaApp/base.html'))
    add_code_block(doc, 'templates/escuelaApp/home.html', read_file_text('templates/escuelaApp/home.html'))
    add_code_block(doc, 'templates/escuelaApp/login.html', read_file_text('templates/escuelaApp/login.html'))
    add_code_block(doc, 'templates/escuelaApp/dashboard.html', read_file_text('templates/escuelaApp/dashboard.html'))
    add_code_block(doc, 'templates/escuelaApp/admin_dashboard.html', read_file_text('templates/escuelaApp/admin_dashboard.html'))
    add_code_block(doc, 'templates/escuelaApp/admin_custom/panel_principal.html', read_file_text('templates/escuelaApp/admin_custom/panel_principal.html'))
    add_code_block(doc, 'templates/escuelaApp/admin_custom/crear_usuario.html', read_file_text('templates/escuelaApp/admin_custom/crear_usuario.html'))
    add_code_block(doc, 'templates/escuelaApp/admin_custom/modificar_dashboard.html', read_file_text('templates/escuelaApp/admin_custom/modificar_dashboard.html'))

    add_heading(doc, '6. Estilos CSS', level=1)
    add_code_block(doc, 'static/css/base.css', read_file_text('static/css/base.css'))
    add_code_block(doc, 'static/css/login.css', read_file_text('static/css/login.css'))
    add_code_block(doc, 'static/css/dashboard.css', read_file_text('static/css/dashboard.css'))
    add_code_block(doc, 'static/css/admin.css', read_file_text('static/css/admin.css'))

    add_heading(doc, '7. SQL de creación de base de datos', level=1)
    add_code_block(doc, 'create_escuela_db.sql', read_file_text('create_escuela_db.sql'))

    doc.save(BASE_DIR / 'Documentacion_Escuela.docx')
    print('Documento generado en:', BASE_DIR / 'Documentacion_Escuela.docx')


if __name__ == '__main__':
    build_document()
