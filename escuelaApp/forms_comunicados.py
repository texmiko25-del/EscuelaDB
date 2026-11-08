from django import forms
from django.core.exceptions import ValidationError

from .models import Empleado, Representante


class ComunicadoRepresentantesForm(forms.Form):
    asunto = forms.CharField(
        max_length=200,
        label='Asunto',
        widget=forms.TextInput(attrs={'autocomplete': 'off'}),
    )
    mensaje = forms.CharField(
        label='Mensaje',
        widget=forms.Textarea(attrs={'rows': 7}),
    )
    representantes = forms.ModelMultipleChoiceField(
        label='Destinatarios',
        queryset=Representante.objects.filter(email__gt='').order_by('apellido', 'nombre'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    docentes = forms.ModelMultipleChoiceField(
        label='Docentes y profesores',
        queryset=Empleado.objects.filter(
            cargo__in=('DOCENTE', 'PROFESOR'),
            user__is_active=True,
        ).exclude(user__email='').select_related('user').order_by(
            'user__first_name', 'user__last_name', 'user__username'
        ),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['representantes'].label_from_instance = lambda representante: (
            f'{representante.nombre} {representante.apellido} · {representante.email}'
        )
        self.fields['docentes'].label_from_instance = lambda empleado: (
            f'{empleado.user.get_full_name() or empleado.user.username} · {empleado.user.email}'
        )

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('representantes') and not cleaned_data.get('docentes'):
            raise ValidationError('Selecciona al menos un representante, docente o profesor con correo.')
        return cleaned_data

    def clean_asunto(self):
        return self.cleaned_data['asunto'].strip()

    def clean_mensaje(self):
        return self.cleaned_data['mensaje'].strip()