import re
from decimal import Decimal

from django import forms
from django.contrib.auth.models import User
from .registro_academico import RegistroAcademico
from .models import Asignacion, Estudiante, Empleado, Docente
from .docente_scope import (
    docente_puede_atender_estudiante,
    materia_programada_para_estudiante,
    materias_del_horario,
    estudiantes_del_docente,
    materias_del_docente,
    perfil_docente_usuario,
)
from .estudiante_utils import etiqueta_estudiante, ordenar_estudiantes


class RegistroAcademicoForm(forms.ModelForm):
    PORCENTAJES_POR_LETRA = {
        'A': Decimal('90.00'),
        'B': Decimal('80.00'),
        'C': Decimal('70.00'),
        'D': Decimal('60.00'),
        'E': Decimal('50.00'),
        'F': Decimal('0.00'),
    }
    TIPOS_EVALUACION = [
        ('Parcial', 'Parcial'),
        ('Final', 'Final'),
        ('Quiz', 'Quiz'),
        ('Tarea', 'Tarea'),
    ]

    ESTADOS_NOTA = [
        ('Pendiente', 'Pendiente'),
        ('Aprobado', 'Aprobado'),
        ('Reprobado', 'Reprobado'),
        ('Recuperación', 'Recuperación'),
    ]

    estudiante_cedula = forms.ModelChoiceField(
        queryset=ordenar_estudiantes(
            Estudiante.objects.select_related('representante').all()
        ),
        required=True,
        label='Estudiante',
        empty_label='Seleccione un estudiante',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    docente_cedula = forms.ChoiceField(
        required=True,
        label='Profesor',
        widget=forms.Select(attrs={'class': 'form-control docente-select'})
    )
    tipo_evaluacion = forms.ChoiceField(
        choices=[('', 'Seleccione tipo de evaluación')] + TIPOS_EVALUACION,
        required=False,
        label='Tipo de evaluación',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    estado = forms.ChoiceField(
        choices=[('', 'Seleccione estado')] + ESTADOS_NOTA,
        required=False,
        label='Estado de la nota',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    area = forms.ChoiceField(
        choices=[('', 'Seleccione una materia académica')],
        required=True,
        label='Materia académica',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    nota = forms.ChoiceField(
        choices=[('', 'Seleccione una calificación')] + [(letra, letra) for letra in 'ABCDEF'],
        required=False,
        label='Calificación (A-F)',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = RegistroAcademico
        fields = ['area', 'periodo', 'lapso', 'tipo_evaluacion', 'nota', 'estado', 'comentarios', 'seguimiento']
        labels = {
            'area': 'Materia académica',
            'periodo': 'Período escolar',
            'nota': 'Calificación (A-F)',
        }
        widgets = {
            'periodo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '2026-2027',
                'maxlength': 9,
                'pattern': r'\d{4}-\d{4}',
                'inputmode': 'numeric',
                'data-rule': 'periodo',
            }),
            'lapso': forms.Select(attrs={'class': 'form-control'}),
            'comentarios': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observaciones sobre la evaluación',
            }),
            'seguimiento': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Apoyo o seguimiento pedagógico recomendado',
            }),
        }

    def __init__(self, *args, **kwargs):
        actor = kwargs.pop('actor', None)
        super().__init__(*args, **kwargs)
        self.docente_actor, self.docente_perfil = perfil_docente_usuario(actor) if actor else (None, None)
        self.fields['lapso'].required = True
        self.fields['nota'].required = True
        self.areas_asignadas = (
            materias_del_docente(self.docente_perfil)
            if self.docente_actor and self.docente_perfil
            else ([] if self.docente_actor else materias_del_horario())
        )
        materias_disponibles = self.areas_asignadas or []
        if self.instance and self.instance.pk and self.instance.area:
            materias_disponibles = sorted(set(materias_disponibles) | {self.instance.area})
        self.fields['area'].choices = [('', 'Seleccione una materia académica')] + [
            (materia, materia) for materia in materias_disponibles
        ]
        if self.docente_actor:
            self.fields['estudiante_cedula'].queryset = (
                estudiantes_del_docente(self.docente_perfil)
                if self.docente_perfil else Estudiante.objects.none()
            )
            full_name = self.docente_actor.user.get_full_name() or self.docente_actor.cedula
        self.fields['estudiante_cedula'].label_from_instance = lambda obj: (
            etiqueta_estudiante(obj)
            + (f" - Tel: {obj.telefono}" if obj.telefono else " - Tel: no registrado")
        )
        # Build combined choices from Empleado (with user) and Docente (standalone)
        empleado_qs = Empleado.objects.select_related('user').filter(cargo__in=['DOCENTE', 'PROFESOR']).order_by('user__last_name', 'user__first_name')
        empleados = list(empleado_qs)
        empleados_cedulas = [e.cedula for e in empleados]
        docentes_extra = (
            Docente.objects.exclude(cedula__isnull=True)
            .exclude(cedula='')
            .exclude(cedula__in=empleados_cedulas)
            .order_by('apellido', 'nombre')
        )

        choices = [('', 'Seleccione un profesor')]
        for e in empleados:
            display = f"{e.user.get_full_name() or 'Sin nombre'} - C.I.: {e.cedula}"
            # try to find specialty in Docente table
            doc = Docente.objects.filter(cedula=e.cedula).first()
            if doc and doc.especialidad:
                display += f" - {doc.especialidad}"
            choices.append((f"emp:{e.pk}", display))
        for d in docentes_extra:
            display = f"{d.nombre} {d.apellido} - C.I.: {d.cedula}"
            if d.especialidad:
                display += f" - {d.especialidad}"
            choices.append((f"doc:{d.pk}", display))

        self.fields['docente_cedula'].choices = choices
        if self.docente_actor:
            self.fields['docente_cedula'].choices = [
                (f'emp:{self.docente_actor.pk}', f'{full_name} - C.I.: {self.docente_actor.cedula}')
            ]
            self.fields['docente_cedula'].initial = f'emp:{self.docente_actor.pk}'
            self.fields['docente_cedula'].disabled = True
        self.fields['estudiante_cedula'].widget.attrs.update({'class': 'form-control estudiante-select'})
        self.fields['docente_cedula'].widget.attrs.update({'class': 'form-control docente-select'})
        if self.instance and self.instance.pk:
            self.fields['estudiante_cedula'].initial = self.instance.estudiante if self.instance.estudiante else None
            if self.instance.docente:
                self.fields['docente_cedula'].initial = f"emp:{self.instance.docente.pk}"
            self.fields['tipo_evaluacion'].initial = self.instance.tipo_evaluacion
            self.fields['estado'].initial = self.instance.estado

    def clean_estudiante_cedula(self):
        estudiante = self.cleaned_data.get('estudiante_cedula')
        if not estudiante:
            raise forms.ValidationError('Debe seleccionar un estudiante.')
        return estudiante

    def clean_docente_cedula(self):
        val = self.cleaned_data.get('docente_cedula')
        if not val:
            raise forms.ValidationError('Debe seleccionar un profesor.')
        if isinstance(val, str) and val.startswith('emp:'):
            try:
                emp_pk = int(val.split(':', 1)[1])
                empleado = Empleado.objects.get(pk=emp_pk)
                if empleado.cargo not in ('DOCENTE', 'PROFESOR'):
                    raise forms.ValidationError('El empleado seleccionado no es profesor.')
                return empleado
            except (ValueError, Empleado.DoesNotExist):
                raise forms.ValidationError('Selección de profesor inválida.')
        if isinstance(val, str) and val.startswith('doc:'):
            docente_id = val.split(':', 1)[1]
            try:
                docente = Docente.objects.get(pk=int(docente_id))
            except (ValueError, Docente.DoesNotExist):
                raise forms.ValidationError('Profesor no encontrado.')
            cedula = docente.cedula
            if not cedula:
                raise forms.ValidationError('Este profesor no tiene cédula para vincular una cuenta.')
            empleado = Empleado.objects.filter(cedula=cedula).first()
            if empleado:
                return empleado
            user, created = User.objects.get_or_create(username=cedula, defaults={
                'first_name': docente.nombre,
                'last_name': docente.apellido,
                'email': ''
            })
            if created:
                user.set_unusable_password()
                user.save()
            empleado = Empleado.objects.create(user=user, cedula=cedula, cargo='DOCENTE')
            return empleado
        raise forms.ValidationError('Seleccion de docente inválida.')

    def clean_area(self):
        area = self.cleaned_data.get('area')
        if not area or len(str(area).strip()) < 2:
            raise forms.ValidationError('El área o materia es obligatoria.')
        area_text = str(area).strip()
        materias_validas = self.areas_asignadas or []
        if self.instance and self.instance.pk and self.instance.area:
            materias_validas = [*materias_validas, self.instance.area]
        if area_text not in materias_validas:
            raise forms.ValidationError('Seleccione una materia registrada en el horario o asignada al docente.')
        if not re.fullmatch(r'^[A-Za-zÁÉÍÓÚáéíóúÑñ\s./#()-]{2,100}$', area_text):
            raise forms.ValidationError('El área o materia solo puede contener texto, espacios y algunos signos básicos.')
        return area_text

    def clean_periodo(self):
        periodo = self.cleaned_data.get('periodo')
        if not re.fullmatch(r'^\d{4}-\d{4}$', str(periodo or '')):
            raise forms.ValidationError('El período debe tener el formato YYYY-YYYY.')
        return periodo

    def clean_nota(self):
        nota = self.cleaned_data.get('nota')
        if nota and nota not in self.PORCENTAJES_POR_LETRA:
            raise forms.ValidationError('La calificación debe estar entre A y F.')
        return nota

    def clean(self):
        cleaned_data = super().clean()
        estudiante = cleaned_data.get('estudiante_cedula')
        area = cleaned_data.get('area')
        periodo = cleaned_data.get('periodo')
        lapso = cleaned_data.get('lapso')
        if self.docente_actor and self.docente_perfil and estudiante and area:
            if not docente_puede_atender_estudiante(self.docente_perfil, estudiante, area):
                self.add_error('area', 'No tienes asignada esta materia para el grado del estudiante.')
        elif not self.docente_actor and estudiante and area:
            if not materia_programada_para_estudiante(estudiante, area):
                asignacion = Asignacion.objects.filter(
                    estudiante=estudiante,
                    area=area,
                    docente=cleaned_data.get('docente_cedula'),
                ).exists()
                if not asignacion:
                    self.add_error(
                        'area',
                        'La materia seleccionada no aparece en el horario de este grado.',
                    )
        if estudiante and area and periodo and lapso:
            registros = RegistroAcademico.objects.filter(
                estudiante=estudiante,
                area=area,
                periodo=periodo,
                lapso=lapso,
            )
            if self.instance.pk:
                registros = registros.exclude(pk=self.instance.pk)
            if registros.exists():
                self.add_error('lapso', 'Ya existe una nota final para este estudiante, materia y lapso.')
        return cleaned_data

    def save(self, commit=True):
        registro = super().save(commit=False)
        registro.estudiante = self.cleaned_data['estudiante_cedula']
        registro.docente = self.cleaned_data.get('docente_cedula')
        registro.porcentaje = self.PORCENTAJES_POR_LETRA.get(self.cleaned_data.get('nota'))
        registro.asignacion = Asignacion.objects.filter(
            estudiante=registro.estudiante,
            docente=registro.docente,
            area=registro.area,
            periodo=registro.periodo,
        ).first()
        if commit:
            registro.save()
        return registro
