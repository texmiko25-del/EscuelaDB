import random
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from escuelaApp.models import Docente, Estudiante, Horario, Representante


class Command(BaseCommand):
    help = 'Crea una base demo con horarios semanales válidos para todos los grados y con estudiantes/representantes semi reales.'

    GRADE_MAP = {
        '1RO': '1ANO',
        '2DO': '2ANO',
        '3RO': '3ANO',
        '4TO': '4ANO',
        '5TO': '5ANO',
        '6TO': '6ANO',
    }
    WEEK_DAYS = [
        ('LU', 'Lunes'),
        ('MA', 'Martes'),
        ('MI', 'Miércoles'),
        ('JU', 'Jueves'),
        ('VI', 'Viernes'),
    ]
    BLOCKS = [
        ('07:30:00', '08:20:00'),
        ('08:25:00', '09:15:00'),
        ('09:30:00', '10:20:00'),
        ('10:25:00', '11:15:00'),
        ('11:30:00', '12:20:00'),
    ]
    SUBJECTS_BY_GRADE = {
        '1ANO': ['Matemáticas', 'Lengua', 'Ciencias Naturales', 'Inglés', 'Educación Física', 'Arte', 'Música'],
        '2ANO': ['Matemáticas', 'Lengua', 'Ciencias Naturales', 'Historia', 'Inglés', 'Educación Física', 'Computación'],
        '3ANO': ['Matemáticas', 'Lengua', 'Ciencias Naturales', 'Historia', 'Geografía', 'Inglés', 'Educación Física'],
        '4ANO': ['Matemáticas', 'Lengua', 'Ciencias Sociales', 'Biología', 'Geografía', 'Inglés', 'Educación Física'],
        '5ANO': ['Matemáticas', 'Lengua', 'Historia', 'Geografía', 'Biología', 'Inglés', 'Educación Física'],
        '6ANO': ['Matemáticas', 'Lengua', 'Física', 'Química', 'Historia', 'Geografía', 'Inglés', 'Educación Física'],
    }
    FIRST_NAMES = [
        'Ana', 'Luis', 'Carlos', 'María', 'José', 'Daniela', 'Andrés', 'Valeria', 'Miguel', 'Sofía',
        'Javier', 'Gabriela', 'Pedro', 'Rosa', 'Emilio', 'Nicolás', 'Camila', 'Diego', 'Fernanda', 'Samuel',
        'Elena', 'Mateo', 'Isabella', 'Dilan', 'Laura', 'Tomás', 'Renata', 'Esteban', 'Adriana', 'Sebastián',
    ]
    LAST_NAMES = [
        'Aguirre', 'Benítez', 'Cordero', 'Díaz', 'Espinoza', 'Flores', 'García', 'Hernández', 'Ibarra', 'Jaramillo',
        'López', 'Márquez', 'Núñez', 'Pérez', 'Quintero', 'Rojas', 'Sánchez', 'Torres', 'Urbina', 'Vargas',
        'Zambrano', 'Armas', 'Blanco', 'Carrero', 'Delgado', 'Figueroa', 'Mendoza', 'Rivas', 'Salazar', 'Suárez',
    ]
    PARENTAL_RELATIONSHIP = ['Madre', 'Padre', 'Tía', 'Tío', 'Abuela', 'Abuelo', 'Tutor legal']
    SEXO = ['F', 'M', 'O']
    NATIONALITIES = ['Venezolana', 'Colombiana', 'Ecuatoriana', 'Peruana', 'Dominicana']

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra datos demo previos antes de crear los nuevos.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self._reset_demo_data()

        representative_pool = self._crear_representantes()
        teacher_pool = self._crear_docentes()
        self._crear_estudiantes(representative_pool)
        self._crear_horarios(teacher_pool)

        self.stdout.write(self.style.SUCCESS(
            'Datos demo creados: 20 representantes, 40 estudiantes y horarios semanales por grado y día.'
        ))

    def _reset_demo_data(self):
        try:
            from escuelaApp.models import Asignacion, Asistencia, RegistroAcademico
        except ImportError:
            RegistroAcademico = None
            Asignacion = None
            Asistencia = None

        if RegistroAcademico is not None:
            RegistroAcademico.objects.all().delete()
        if Asistencia is not None:
            Asistencia.objects.all().delete()
        if Asignacion is not None:
            Asignacion.objects.all().delete()

        Horario.objects.all().delete()
        Estudiante.objects.all().delete()
        Representante.objects.all().delete()
        Docente.objects.all().delete()
        self.stdout.write('Datos previos eliminados antes de sembrar la demo.')

    def _crear_representantes(self):
        reps = []
        for index in range(1, 21):
            tel = f'041{(index % 10):01d}{(index * 3) % 10}{(index * 5) % 10}{(index * 7) % 10}{(index * 11) % 10}{(index * 13) % 10}{(index * 17) % 10}'
            rep = Representante.objects.create(
                nombre=self.FIRST_NAMES[(index * 3) % len(self.FIRST_NAMES)],
                apellido=self.LAST_NAMES[(index * 5) % len(self.LAST_NAMES)],
                cedula=f'V-{10000000 + index}',
                telefono=tel,
                email=f'representante{index}@escuela-demo.com',
                ocupacion=['Ingeniero', 'Abogada', 'Comerciante', 'Ama de casa', 'Docente', 'Mecánico'][index % 6],
                parentesco=self.PARENTAL_RELATIONSHIP[index % len(self.PARENTAL_RELATIONSHIP)],
                estado_civil=['SOLTERO', 'CASADO', 'UNION_LIBRE', 'DIVORCIADO'][index % 4],
                nacionalidad=self.NATIONALITIES[index % len(self.NATIONALITIES)],
                ubicacion=f'Calle {index + 10}, Urbanización San José, Valencia',
                es_tutor_legal=True,
            )
            reps.append(rep)
        return reps

    def _crear_docentes(self):
        docentes = []
        teacher_start = 30000000
        subjects = [
            'Matemáticas', 'Lengua', 'Ciencias Naturales', 'Historia', 'Geografía', 'Inglés',
            'Educación Física', 'Biología', 'Computación', 'Arte', 'Química', 'Física',
            'Educación Artística', 'Música', 'Tecnología', 'Ética', 'Valores', 'Ciencias Sociales',
        ]
        for i in range(25):
            first_name = self.FIRST_NAMES[i % len(self.FIRST_NAMES)]
            last_name = self.LAST_NAMES[(i * 2) % len(self.LAST_NAMES)]
            docente = Docente.objects.create(
                nombre=first_name,
                apellido=last_name,
                cedula=f'V-{teacher_start + i}',
                telefono=f'041{i % 9 + 2}{(i * 3) % 10}{(i * 5) % 10}{(i * 7) % 10}{(i * 11) % 10}{(i * 13) % 10}{(i * 17) % 10}',
                especialidad=subjects[i % len(subjects)],
                carga_horaria=20,
            )
            docentes.append(docente)
        return docentes

    def _crear_estudiantes(self, representantes):
        grades = [
            ('1RO', 7),
            ('2DO', 7),
            ('3RO', 7),
            ('4TO', 7),
            ('5TO', 6),
            ('6TO', 6),
        ]
        student_counter = 1
        for grado, cantidad in grades:
            for _ in range(cantidad):
                rep = representantes[(student_counter - 1) % len(representantes)]
                nombre = self.FIRST_NAMES[(student_counter * 2) % len(self.FIRST_NAMES)]
                apellido = self.LAST_NAMES[(student_counter * 3) % len(self.LAST_NAMES)]
                sexo = self.SEXO[(student_counter + 1) % len(self.SEXO)]
                birth_year = 2012 + (student_counter % 6)
                birth_day = 10 + (student_counter % 18)
                birth_month = 1 + (student_counter % 12)
                estudiante = Estudiante.objects.create(
                    nombre=nombre,
                    apellido=apellido,
                    cedula=f'V-{20000000 + student_counter}',
                    fecha_nacimiento=date(birth_year, birth_month, birth_day),
                    sexo=sexo,
                    nacionalidad=self.NATIONALITIES[(student_counter + 1) % len(self.NATIONALITIES)],
                    grado=grado,
                    seccion=('A', 'B', 'C')[(student_counter - 1) % 3],
                    matricula=f'MAT-{student_counter:03d}',
                    telefono=f'041{(student_counter % 9) + 2}{(student_counter * 3) % 10}{(student_counter * 5) % 10}{(student_counter * 7) % 10}{(student_counter * 11) % 10}{(student_counter * 13) % 10}{(student_counter * 17) % 10}',
                    ubicacion=f'Barrio La Libertad, sector {student_counter}, Valencia',
                    representante=rep,
                )
                student_counter += 1

    def _crear_horarios(self, teacher_pool):
        grade_order = list(self.GRADE_MAP.values())

        for grade_index, grado_horario in enumerate(grade_order):
            for dia_index, (dia_code, _) in enumerate(self.WEEK_DAYS):
                for bloque_idx, (hora_inicio, hora_fin) in enumerate(self.BLOCKS):
                    subject = self.SUBJECTS_BY_GRADE[grado_horario][
                        (bloque_idx + grade_index) % len(self.SUBJECTS_BY_GRADE[grado_horario])
                    ]
                    teacher_index = (dia_index * len(self.BLOCKS) + bloque_idx + grade_index) % len(teacher_pool)
                    docente = teacher_pool[teacher_index]
                    Horario.objects.create(
                        ano=grado_horario,
                        materia=subject,
                        docente=docente,
                        dia=dia_code,
                        hora_inicio=hora_inicio,
                        hora_fin=hora_fin,
                    )

        self.stdout.write(f'Horarios creados: {Horario.objects.count()} bloques.')
