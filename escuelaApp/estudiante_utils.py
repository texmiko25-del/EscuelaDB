from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower

GRADOS_ORDENADOS = [
    ('1RO', 'Primero'),
    ('2DO', 'Segundo'),
    ('3RO', 'Tercero'),
    ('4TO', 'Cuarto'),
    ('5TO', 'Quinto'),
    ('6TO', 'Sexto'),
]


def ordenar_estudiantes(queryset):
    orden_grados = Case(
        *[
            When(grado__iexact=codigo, then=Value(indice))
            for indice, (codigo, _) in enumerate(GRADOS_ORDENADOS)
        ],
        default=Value(len(GRADOS_ORDENADOS)),
        output_field=IntegerField(),
    )
    return queryset.order_by(
        orden_grados,
        Lower('seccion'),
        Lower('apellido'),
        Lower('nombre'),
        'pk',
    )


def etiqueta_grado_seccion(estudiante):
    seccion = estudiante.seccion or 'Sin sección'
    return f'{estudiante.grado} - Sección {seccion}'


def etiqueta_estudiante(estudiante):
    grado = etiqueta_grado_seccion(estudiante) if estudiante.grado else 'Sin grado'
    return (
        f'{estudiante.nombre} {estudiante.apellido} - '
        f'{grado} - C.I.: {estudiante.cedula or "No registrada"}'
    )
