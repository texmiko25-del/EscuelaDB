from django.db.models import Q

from .estudiante_utils import ordenar_estudiantes
from .models import Asignacion, Docente, DocenteEstudiante, Empleado, Estudiante, Horario


GRADOS_POR_ANO_HORARIO = {
    '1ANO': '1RO',
    '2ANO': '2DO',
    '3ANO': '3RO',
    '4ANO': '4TO',
    '5ANO': '5TO',
    '6ANO': '6TO',
}


def perfil_docente_usuario(user):
    empleado = getattr(user, 'empleado', None)
    if not empleado or empleado.cargo not in ('DOCENTE', 'PROFESOR'):
        return None, None
    return empleado, Docente.objects.filter(cedula__iexact=empleado.cedula).first()


def estudiantes_del_docente(docente):
    anos = Horario.objects.filter(docente=docente).values_list('ano', flat=True).distinct()
    grados = [GRADOS_POR_ANO_HORARIO.get(ano, ano) for ano in anos]
    grupos_asignados = set(
        docente.estudiantes_asignados.values_list('grado', 'seccion')
    )
    alcance_horario = Q(pk__in=[])
    for grado in grados:
        grupo_grado = Q(grado=grado)
        for grado_asignado, seccion_asignada in grupos_asignados:
            if grado_asignado == grado:
                grupo_grado &= ~Q(grado=grado, seccion=seccion_asignada)
        alcance_horario |= grupo_grado
    estudiantes = Estudiante.objects.filter(
        alcance_horario
        | Q(docentes_asignados=docente)
        | Q(asignacion__docente__cedula__iexact=docente.cedula)
        | Q(asignaciones_docentes__docente=docente)
    ).distinct().select_related('representante')
    return ordenar_estudiantes(estudiantes)


def materias_del_horario(grado=None):
    horarios = Horario.objects.all()
    if grado:
        ano = next(
            (ano for ano, grado_estudiante in GRADOS_POR_ANO_HORARIO.items()
             if grado_estudiante == grado),
            grado,
        )
        horarios = horarios.filter(ano=ano)
    return list(
        horarios.order_by('materia')
        .values_list('materia', flat=True)
        .distinct()
    )


def materias_del_docente(docente):
    materias_horario = Horario.objects.filter(docente=docente).values_list('materia', flat=True)
    materias_asignadas = Asignacion.objects.filter(
        docente__cedula__iexact=docente.cedula
    ).values_list('area', flat=True)
    return sorted(set(materias_horario) | set(materias_asignadas))


def materia_programada_para_estudiante(estudiante, materia):
    ano = next(
        (ano for ano, grado in GRADOS_POR_ANO_HORARIO.items() if grado == estudiante.grado),
        estudiante.grado,
    )
    return Horario.objects.filter(ano=ano, materia=materia).exists()


def docente_puede_atender_estudiante(docente, estudiante, materia=None):
    ano = next(
        (ano for ano, grado in GRADOS_POR_ANO_HORARIO.items() if grado == estudiante.grado),
        estudiante.grado,
    )
    horarios = Horario.objects.filter(docente=docente, ano=ano)
    if materia is not None:
        horarios = horarios.filter(materia=materia)
    asignaciones = Asignacion.objects.filter(
        docente__cedula__iexact=docente.cedula,
        estudiante=estudiante,
    )
    estudiantes_asignados = DocenteEstudiante.objects.filter(
        docente=docente,
        estudiante=estudiante,
    )
    hay_seleccion_en_grupo = docente.estudiantes_asignados.filter(
        grado=estudiante.grado,
        seccion=estudiante.seccion,
    ).exists()
    if materia is not None:
        asignaciones = asignaciones.filter(area=materia)
    return (
        (horarios.exists() and not hay_seleccion_en_grupo)
        or asignaciones.exists()
        or estudiantes_asignados.exists()
    )


def filtrar_registros_docente(queryset, docente):
    alcance = Q(pk__in=[])
    grupos_asignados = set(
        docente.estudiantes_asignados.values_list('grado', 'seccion')
    )
    for ano, grado in GRADOS_POR_ANO_HORARIO.items():
        alcance_grado = Q(estudiante__grado=grado)
        for grado_asignado, seccion_asignada in grupos_asignados:
            if grado_asignado == grado:
                alcance_grado &= ~Q(
                    estudiante__grado=grado,
                    estudiante__seccion=seccion_asignada,
                )
        for materia in Horario.objects.filter(docente=docente, ano=ano).values_list(
            'materia', flat=True
        ).distinct():
            alcance |= alcance_grado & Q(area=materia)
    alcance |= Q(asignacion__docente__cedula__iexact=docente.cedula)
    alcance |= Q(estudiante__asignaciones_docentes__docente=docente)
    return queryset.filter(alcance, docente__cedula__iexact=docente.cedula).distinct()
