from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from escuelaApp.reportes_sistema import enviar_reporte_diario


class Command(BaseCommand):
    help = 'Genera y envía el reporte diario escolar de matrícula, asistencia y calificaciones.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fecha',
            help='Genera o reintenta el reporte de una fecha (AAAA-MM-DD). Por defecto: hoy.',
        )

    def handle(self, *args, **options):
        fecha = None
        if options['fecha']:
            try:
                fecha = date.fromisoformat(options['fecha'])
            except ValueError as error:
                raise CommandError('La fecha debe usar el formato AAAA-MM-DD.') from error

        reporte, resumen = enviar_reporte_diario(fecha)
        salida = (
            f"Reporte {reporte.fecha_reporte:%Y-%m-%d} (ID {reporte.pk}): "
            f"{resumen['enviados']} envíos correctos, {resumen['errores']} errores, "
            f"{resumen['destinos']} destinos."
        )
        if resumen['errores']:
            self.stderr.write(self.style.WARNING(salida))
        elif not resumen['destinos']:
            self.stderr.write(self.style.WARNING(f'{salida} No hay destinatarios configurados.'))
        else:
            self.stdout.write(self.style.SUCCESS(salida))