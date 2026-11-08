from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from escuelaApp.models import Asistencia, Docente, Empleado, Estudiante, Horario
from escuelaApp.registro_academico import RegistroAcademico


class Command(BaseCommand):
    help = 'Carga notas y asistencias de demostración con estudiantes y docentes existentes.'

    etiqueta_demo = 'Dato de demostración generado para pruebas.'
    grados_horario = {
        '1RO': '1ANO',
        '2DO': '2ANO',
        '3RO': '3ANO',
        '4TO': '4ANO',
        '5TO': '5ANO',
        '6TO': '6ANO',
    }
    materias_validas = {
        'Matemáticas', 'Inglés', 'Lengua', 'Castellano', 'Biología',
        'Ciencias Naturales', 'Ciencias Sociales', 'Historia', 'Geografía',
        'Educación Física', 'Educación Artística', 'Música', 'Tecnología',
        'Computación', 'Valores', 'Ética', 'Medio Ambiente',
    }
    materias_equivalentes = {
        'Lengua y Literatura': 'Lengua',
        'Educación Ambiental': 'Medio Ambiente',
        'Ética y Valores': 'Ética',
    }
    notas_demo = ('A', 'B', 'C', 'B', 'A', 'D')
    porcentajes = {
        'A': Decimal('90.00'),
        'B': Decimal('80.00'),
        'C': Decimal('70.00'),
        'D': Decimal('60.00'),
        'E': Decimal('50.00'),
        'F': Decimal('0.00'),
    }

    @transaction.atomic
    def handle(self, *args, **options):
        estudiantes = list(Estudiante.objects.order_by('pk'))
        if not estudiantes:
            raise CommandError('No hay estudiantes registrados para cargar datos.')

        horarios_por_grado = {grado: [] for grado in self.grados_horario.values()}
        for horario in Horario.objects.select_related('docente').order_by('pk'):
            materia = self.materias_equivalentes.get(horario.materia, horario.materia)
            if materia in self.materias_validas and horario.ano in horarios_por_grado:
                horarios_por_grado[horario.ano].append((materia, horario.docente))

        grados_sin_horario = sorted({
            self.grados_horario.get(estudiante.grado)
            for estudiante in estudiantes
            if not horarios_por_grado.get(self.grados_horario.get(estudiante.grado), [])
        })
        if grados_sin_horario:
            raise CommandError(
                'No hay horarios con materias válidas para estos grados: '
                + ', '.join(grado or 'sin equivalencia' for grado in grados_sin_horario)
            )

        docentes_empleados = {}
        registros_creados = 0
        asistencias_creadas = 0
        fechas = self._fechas_lectivas_recientes(5)

        for indice, estudiante in enumerate(estudiantes):
            grado_horario = self.grados_horario.get(estudiante.grado)
            if not grado_horario:
                raise CommandError(f'El grado de {estudiante} no tiene equivalencia con el horario.')

            opciones = horarios_por_grado[grado_horario]
            materia, docente = opciones[indice % len(opciones)]
            empleado = docentes_empleados.get(docente.pk)
            if empleado is None:
                empleado = self._obtener_empleado(docente)
                docentes_empleados[docente.pk] = empleado

            nota = self.notas_demo[indice % len(self.notas_demo)]
            _, creada = RegistroAcademico.objects.get_or_create(
                estudiante=estudiante,
                periodo='2026-2027',
                area=materia,
                tipo_evaluacion='Parcial',
                comentarios=self.etiqueta_demo,
                defaults={
                    'docente': empleado,
                    'nota': nota,
                    'porcentaje': self.porcentajes[nota],
                    'estado': 'Aprobado' if nota in {'A', 'B', 'C'} else 'Reprobado',
                },
            )
            registros_creados += int(creada)

            for fecha in fechas:
                estado = self._estado_asistencia(estudiante.pk, fecha)
                _, creada = Asistencia.objects.get_or_create(
                    estudiante=estudiante,
                    fecha=fecha,
                    defaults={
                        'estado': estado,
                        'observaciones': self.etiqueta_demo,
                        'registrado_por': empleado,
                    },
                )
                asistencias_creadas += int(creada)

        self.stdout.write(self.style.SUCCESS(
            f'Carga completada: {registros_creados} notas y '
            f'{asistencias_creadas} asistencias nuevas para {len(estudiantes)} estudiantes.'
        ))

    @staticmethod
    def _fechas_lectivas_recientes(cantidad):
        fecha = timezone.localdate()
        fechas = []
        while len(fechas) < cantidad:
            if fecha.weekday() < 5:
                fechas.append(fecha)
            fecha -= timedelta(days=1)
        return fechas

    @staticmethod
    def _estado_asistencia(estudiante_id, fecha):
        estados = ('PRESENTE', 'PRESENTE', 'PRESENTE', 'TARDANZA', 'AUSENTE')
        return estados[(estudiante_id + fecha.toordinal()) % len(estados)]

    @staticmethod
    def _obtener_empleado(docente):
        empleado = Empleado.objects.filter(cedula=docente.cedula).first()
        if empleado:
            return empleado

        usuario, _ = User.objects.get_or_create(
            username=docente.cedula,
            defaults={
                'first_name': docente.nombre,
                'last_name': docente.apellido,
                'email': '',
            },
        )
        empleado = Empleado.objects.filter(user=usuario).first()
        if empleado:
            if empleado.cedula != docente.cedula:
                raise CommandError(
                    f'El usuario {usuario.username} ya está vinculado a otra cédula.'
                )
            return empleado

        if not usuario.has_usable_password():
            usuario.set_unusable_password()
            usuario.save(update_fields=['password'])
        return Empleado.objects.create(
            user=usuario,
            cedula=docente.cedula,
            cargo='DOCENTE',
        )