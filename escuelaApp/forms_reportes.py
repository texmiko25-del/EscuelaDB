from django import forms
from django.core.exceptions import ValidationError

from .models import Estudiante
from .registro_academico import RegistroAcademico


class FiltrosReporteSistemaForm(forms.Form):
    grado = forms.ChoiceField(required=False, label='Grado')
    periodo = forms.ChoiceField(required=False, label='Período escolar')
    area = forms.ChoiceField(required=False, label='Área académica')
    fecha_desde = forms.DateField(
        required=False,
        label='Desde',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    fecha_hasta = forms.DateField(
        required=False,
        label='Hasta',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    porcentaje_min = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=100,
        max_digits=5,
        decimal_places=2,
        label='Porcentaje mínimo',
    )
    porcentaje_max = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=100,
        max_digits=5,
        decimal_places=2,
        label='Porcentaje máximo',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        grados = Estudiante.objects.order_by('grado').values_list('grado', flat=True).distinct()
        periodos = RegistroAcademico.objects.exclude(periodo='').order_by('-periodo').values_list(
            'periodo', flat=True
        ).distinct()
        areas = RegistroAcademico.objects.exclude(area='').order_by('area').values_list(
            'area', flat=True
        ).distinct()
        self.fields['grado'].choices = [('', 'Todos los grados')] + [(valor, valor) for valor in grados]
        self.fields['periodo'].choices = [('', 'Todos los períodos')] + [(valor, valor) for valor in periodos]
        self.fields['area'].choices = [('', 'Todas las áreas')] + [(valor, valor) for valor in areas]

    def clean(self):
        datos = super().clean()
        fecha_desde = datos.get('fecha_desde')
        fecha_hasta = datos.get('fecha_hasta')
        porcentaje_min = datos.get('porcentaje_min')
        porcentaje_max = datos.get('porcentaje_max')
        if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
            raise ValidationError('La fecha inicial no puede ser posterior a la fecha final.')
        if porcentaje_min is not None and porcentaje_max is not None and porcentaje_min > porcentaje_max:
            raise ValidationError('El porcentaje mínimo no puede superar el máximo.')
        return datos