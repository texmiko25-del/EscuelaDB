import re

from django import forms
from django.utils import timezone
from .models import Asistencia, Estudiante, ResumenAsistenciaLapso
from .docente_scope import estudiantes_del_docente, perfil_docente_usuario
from .estudiante_utils import etiqueta_estudiante, ordenar_estudiantes


class AsistenciaForm(forms.ModelForm):
    estudiante_cedula = forms.ModelChoiceField(
        queryset=ordenar_estudiantes(
            Estudiante.objects.select_related('representante').all()
        ),
        required=True,
        label='Estudiante',
        empty_label='Seleccione un estudiante',
        widget=forms.Select(attrs={'class': 'form-control estudiante-select'})
    )
    fecha = forms.DateField(
        required=True,
        localize=False,
        label='Fecha',
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'data-rule': 'fecha-no-futura',
        }, format='%Y-%m-%d')
    )

    class Meta:
        model = Asistencia
        fields = ['fecha', 'estado', 'observaciones']
        labels = {
            'fecha': 'Fecha',
            'estado': 'Estado de asistencia',
            'observaciones': 'Observaciones',
        }
        widgets = {
            'estado': forms.Select(attrs={'class': 'form-control'}),
            'observaciones': forms.Textarea(attrs={
                'rows': 4,
                'maxlength': 1000,
                'class': 'form-control',
                'placeholder': 'Notas sobre la asistencia',
            }),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        empleado, docente = perfil_docente_usuario(actor) if actor else (None, None)
        if empleado:
            self.fields['estudiante_cedula'].queryset = (
                estudiantes_del_docente(docente) if docente else Estudiante.objects.none()
            )
        self.fields['fecha'].widget.attrs['max'] = timezone.localdate().isoformat()
        self.fields['estudiante_cedula'].label_from_instance = lambda obj: (
            f'{etiqueta_estudiante(obj)}'
            + (f" - Tel: {obj.telefono}" if obj.telefono else " - Tel: no registrado")
        )
        if not self.initial.get('fecha') and not self.data.get('fecha'):
            self.fields['fecha'].initial = timezone.localdate()

    def clean_estudiante_cedula(self):
        estudiante = self.cleaned_data.get('estudiante_cedula')
        if not estudiante:
            raise forms.ValidationError('Debe seleccionar un estudiante válido.')
        return estudiante

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        if fecha and fecha > timezone.now().date():
            raise forms.ValidationError('La fecha no puede ser futura.')
        return fecha

    def clean_observaciones(self):
        observaciones = self.cleaned_data.get('observaciones')
        if observaciones and len(observaciones) > 1000:
            raise forms.ValidationError('Las observaciones no pueden superar 1000 caracteres.')
        return observaciones

    def clean(self):
        cleaned_data = super().clean()
        estudiante = cleaned_data.get('estudiante_cedula')
        fecha = cleaned_data.get('fecha')
        if estudiante and fecha:
            if Asistencia.objects.filter(estudiante=estudiante, fecha=fecha).exists():
                if not self.instance or self.instance.fecha != fecha or self.instance.estudiante != estudiante:
                    raise forms.ValidationError('Ya existe un registro de asistencia para este estudiante en la fecha seleccionada.')
        return cleaned_data

    def save(self, commit=True):
        asistencia = super().save(commit=False)
        asistencia.estudiante = self.cleaned_data['estudiante_cedula']
        asistencia.fecha = self.cleaned_data['fecha']
        if commit:
            asistencia.save()
        return asistencia


class ResumenAsistenciaLapsoForm(forms.ModelForm):
    estudiante_cedula = forms.ModelChoiceField(
        queryset=ordenar_estudiantes(Estudiante.objects.all()),
        required=True,
        label='Estudiante',
        empty_label='Seleccione un estudiante',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = ResumenAsistenciaLapso
        fields = [
            'periodo', 'lapso', 'presentes', 'ausentes', 'tardanzas',
            'justificadas', 'observaciones', 'seguimiento',
        ]
        labels = {
            'periodo': 'Período escolar',
            'lapso': 'Lapso',
            'presentes': 'Presentes',
            'ausentes': 'Ausentes',
            'tardanzas': 'Tardanzas',
            'justificadas': 'Justificadas',
            'observaciones': 'Observaciones',
            'seguimiento': 'Seguimiento pedagógico',
        }
        widgets = {
            'periodo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '2026-2027',
                'maxlength': 9,
                'pattern': r'\d{4}-\d{4}',
            }),
            'lapso': forms.Select(attrs={'class': 'form-control'}),
            'presentes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'ausentes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'tardanzas': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'justificadas': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'seguimiento': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.docente_empleado, self.docente_perfil = perfil_docente_usuario(actor) if actor else (None, None)
        if self.docente_empleado:
            self.fields['estudiante_cedula'].queryset = (
                estudiantes_del_docente(self.docente_perfil)
                if self.docente_perfil else Estudiante.objects.none()
            )
        if self.instance and self.instance.pk:
            self.fields['estudiante_cedula'].initial = self.instance.estudiante
        self.fields['estudiante_cedula'].label_from_instance = etiqueta_estudiante

    def clean_periodo(self):
        periodo = self.cleaned_data['periodo']
        if not re.fullmatch(r'\d{4}-\d{4}', periodo):
            raise forms.ValidationError('El período debe tener el formato YYYY-YYYY.')
        return periodo

    def clean(self):
        cleaned_data = super().clean()
        estudiante = cleaned_data.get('estudiante_cedula')
        periodo = cleaned_data.get('periodo')
        lapso = cleaned_data.get('lapso')
        if estudiante and periodo and lapso:
            duplicados = ResumenAsistenciaLapso.objects.filter(
                estudiante=estudiante,
                periodo=periodo,
                lapso=lapso,
            )
            if self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error('lapso', 'Ya existe un resumen para este estudiante, período y lapso.')
        return cleaned_data

    def save(self, commit=True):
        resumen = super().save(commit=False)
        resumen.estudiante = self.cleaned_data['estudiante_cedula']
        if commit:
            resumen.save()
        return resumen
