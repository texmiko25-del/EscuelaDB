from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from escuelaApp.models import Docente, Empleado, Estudiante, Representante
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Crea estudiantes y representantes ficticios DEMO en un entorno de desarrollo.'

    GRADOS = ('1RO', '2DO', '3RO', '4TO', '5TO', '6TO')
    SECCIONES = ('A', 'B', 'C')

    def add_arguments(self, parser):
        parser.add_argument(
            '--cantidad',
            type=int,
            default=10,
            help='Cantidad de estudiantes DEMO que se crearán (por defecto: 10).',
        )
        parser.add_argument(
            '--confirmar-demo',
            action='store_true',
            help='Confirma que se crearán datos ficticios DEMO.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando solo se permite con DJANGO_DEBUG=true.')
        if not options['confirmar_demo']:
            raise CommandError('Confirma la creación de datos ficticios con --confirmar-demo.')

        cantidad = options['cantidad']
        if cantidad < 1 or cantidad > 100:
            raise CommandError('La cantidad debe estar entre 1 y 100 estudiantes.')

        creados = 0
        for numero in range(1, cantidad + 1):
            nombre_representante = f'DEMO Representante {numero:02d}'
            apellido_representante = 'Prueba'
            representante = Representante.objects.filter(
                nombre=nombre_representante,
                apellido=apellido_representante,
            ).first()
            if representante is None:
                cedula_representante = self._cedula_disponible(numero)
                representante = Representante.objects.create(
                    nombre=nombre_representante,
                    apellido=apellido_representante,
                    cedula=cedula_representante,
                    email=f'demo-representante-{numero:02d}@example.invalid',
                    parentesco='Representante DEMO',
                    nacionalidad='DEMO',
                )

            nombre_estudiante = f'DEMO Estudiante {numero:02d}'
            estudiante, fue_creado = Estudiante.objects.get_or_create(
                nombre=nombre_estudiante,
                apellido='Prueba',
                representante=representante,
                defaults={
                    'cedula': f'DEMO-EST-{numero:04d}',
                    'sexo': 'O',
                    'nacionalidad': 'DEMO',
                    'grado': self.GRADOS[(numero - 1) % len(self.GRADOS)],
                    'seccion': self.SECCIONES[(numero - 1) % len(self.SECCIONES)],
                    'matricula': f'DEMO-MAT-{numero:04d}',
                    'fecha_nacimiento': date(2012 + ((numero - 1) % 6), 1, 15),
                },
            )
            if fue_creado:
                creados += 1

        self.stdout.write(self.style.SUCCESS(
            f'Estudiantes DEMO creados: {creados}; representantes DEMO disponibles: '
            f'{Representante.objects.filter(nombre__startswith="DEMO Representante ").count()}.'
        ))

    @staticmethod
    def _cedula_disponible(numero):
        for consecutivo in range(990000000 + numero, 990001000):
            cedula = f'E-{consecutivo}'
            ocupada = (
                Representante.objects.filter(cedula__iexact=cedula).exists()
                or Docente.objects.filter(cedula__iexact=cedula).exists()
                or Empleado.objects.filter(cedula__iexact=cedula).exists()
                or Estudiante.objects.filter(cedula__iexact=cedula).exists()
                or User.objects.filter(username__iexact=cedula).exists()
            )
            if not ocupada:
                return cedula
        raise CommandError('No hay cédulas disponibles en el rango DEMO reservado.')
