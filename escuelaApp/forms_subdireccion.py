import re

from django import forms
from django.core.exceptions import ValidationError

from .models import AsistenciaPersonal, Empleado, Estudiante, SolicitudMatricula


class SolicitudMatriculaForm(forms.ModelForm):
    tipo_identificacion_representante = forms.ChoiceField(
        choices=[('V', 'Venezolana'), ('E', 'Extranjera')],
        initial='V',
        label='Tipo de identificación del representante',
    )
    representante_cedula = forms.CharField(label='Cédula del representante')

    class Meta:
        model = SolicitudMatricula
        fields = [
            'estudiante_nombre',
            'estudiante_apellido',
            'estudiante_fecha_nacimiento',
            'estudiante_sexo',
            'estudiante_nacionalidad',
            'grado',
            'partida_nacimiento',
            'estudiante_telefono',
            'estudiante_ubicacion',
            'representante_nombre',
            'representante_apellido',
            'representante_telefono',
            'representante_email',
            'representante_parentesco',
            'representante_nacionalidad',
            'documento_representante',
            'documento_partida_nacimiento',
            'observaciones_representante',
        ]
        labels = {
            'estudiante_nombre': 'Nombres del estudiante',
            'estudiante_apellido': 'Apellidos del estudiante',
            'estudiante_fecha_nacimiento': 'Fecha de nacimiento',
            'estudiante_sexo': 'Sexo',
            'estudiante_nacionalidad': 'Nacionalidad del estudiante',
            'grado': 'Grado solicitado',
            'partida_nacimiento': 'Número de partida de nacimiento',
            'estudiante_telefono': 'Teléfono del estudiante',
            'estudiante_ubicacion': 'Dirección',
            'representante_nombre': 'Nombres del representante',
            'representante_apellido': 'Apellidos del representante',
            'representante_telefono': 'Teléfono del representante',
            'representante_email': 'Correo del representante',
            'representante_parentesco': 'Parentesco con el estudiante',
            'representante_nacionalidad': 'Nacionalidad del representante',
            'documento_representante': 'Documento de identidad del representante (PDF o imagen)',
            'documento_partida_nacimiento': 'Partida de nacimiento (PDF o imagen)',
            'observaciones_representante': 'Observaciones',
        }
        widgets = {
            'estudiante_fecha_nacimiento': forms.DateInput(attrs={'type': 'date'}),
            'observaciones_representante': forms.Textarea(attrs={'rows': 3}),
            'documento_representante': forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png'}),
            'documento_partida_nacimiento': forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields([
            'estudiante_nombre', 'estudiante_apellido', 'estudiante_fecha_nacimiento',
            'estudiante_sexo', 'estudiante_nacionalidad', 'grado', 'partida_nacimiento',
            'estudiante_telefono', 'estudiante_ubicacion', 'representante_nombre',
            'representante_apellido', 'tipo_identificacion_representante',
            'representante_cedula', 'representante_telefono', 'representante_email',
            'representante_parentesco', 'representante_nacionalidad',
            'documento_representante', 'documento_partida_nacimiento',
            'observaciones_representante',
        ])

    def clean_estudiante_fecha_nacimiento(self):
        fecha = self.cleaned_data['estudiante_fecha_nacimiento']
        if fecha.today() < fecha:
            raise ValidationError('La fecha de nacimiento no puede estar en el futuro.')
        return fecha

    def clean_representante_cedula(self):
        tipo = self.cleaned_data.get('tipo_identificacion_representante', 'V')
        valor = (self.cleaned_data.get('representante_cedula') or '').strip().upper().replace(' ', '')
        if valor.startswith(('V-', 'E-')):
            tipo, valor = valor.split('-', 1)
        digitos = re.sub(r'\D', '', valor)
        limites = (7, 8) if tipo == 'V' else (6, 9)
        if not limites[0] <= len(digitos) <= limites[1]:
            raise ValidationError('La cédula no tiene una cantidad válida de dígitos para el tipo seleccionado.')
        return f'{tipo}-{digitos}'

    def clean_representante_telefono(self):
        telefono = re.sub(r'\D', '', self.cleaned_data['representante_telefono'])
        if len(telefono) != 11:
            raise ValidationError('El teléfono del representante debe tener 11 dígitos.')
        return telefono

    def clean_documento_representante(self):
        return self._validar_archivo(self.cleaned_data['documento_representante'])

    def clean_documento_partida_nacimiento(self):
        return self._validar_archivo(self.cleaned_data['documento_partida_nacimiento'])

    @staticmethod
    def _validar_archivo(archivo):
        if archivo.size > 5 * 1024 * 1024:
            raise ValidationError('Cada documento debe pesar como máximo 5 MB.')
        return archivo


class RevisionSolicitudMatriculaForm(forms.Form):
    seccion = forms.ChoiceField(
        choices=[('', 'Seleccione una sección'), *Estudiante.SECCIONES],
        required=False,
        label='Sección asignada',
    )
    observaciones = forms.CharField(
        label='Observaciones de revisión',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def clean(self):
        cleaned_data = super().clean()
        if self.data.get('accion') == 'aprobar' and not cleaned_data.get('seccion'):
            self.add_error('seccion', 'Selecciona la sección antes de aprobar la matrícula.')
        return cleaned_data


class AsistenciaPersonalForm(forms.ModelForm):
    class Meta:
        model = AsistenciaPersonal
        fields = ['empleado', 'fecha', 'estado', 'observaciones']
        labels = {
            'empleado': 'Empleado',
            'fecha': 'Fecha',
            'estado': 'Asistencia',
            'observaciones': 'Justificación u observaciones',
        }
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'observaciones': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['empleado'].queryset = Empleado.objects.select_related('user').order_by(
            'user__last_name', 'user__first_name'
        )
        self.fields['empleado'].label_from_instance = lambda empleado: (
            f'{empleado.user.get_full_name() or empleado.user.username} - {empleado.get_cargo_display()}'
        )

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha > fecha.today():
            raise ValidationError('No se puede registrar asistencia en una fecha futura.')
        return fecha

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('estado') == 'JUSTIFICADO' and not (cleaned_data.get('observaciones') or '').strip():
            self.add_error('observaciones', 'Escribe la justificación de la inasistencia.')
        return cleaned_data