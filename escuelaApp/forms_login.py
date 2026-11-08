import re

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .forms import validate_account_password
from .models import Empleado


class LoginForm(forms.Form):
    username = forms.CharField(max_length=20, label='Usuario')
    password = forms.CharField(widget=forms.PasswordInput, label='Contraseña', strip=False)

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            raise forms.ValidationError('El usuario es obligatorio.')

        username = username.strip()
        if not username:
            raise forms.ValidationError('El usuario es obligatorio.')

        user = User.objects.filter(username__iexact=username).first()
        if not user and '@' in username:
            user = User.objects.filter(email__iexact=username).first()
        if user:
            return user.username

        empleado = Empleado.objects.select_related('user').filter(cedula__iexact=username).first()
        if not empleado and re.fullmatch(r'\d{5,12}', username):
            empleados = Empleado.objects.select_related('user').filter(cedula__iendswith=f'-{username}')
            if empleados.count() == 1:
                empleado = empleados.first()
        if empleado:
            return empleado.user.username

        if re.fullmatch(r'\d{5,12}', username):
            return username

        raise forms.ValidationError('El usuario debe ser una cédula válida o un usuario existente.')

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not password or not str(password).strip():
            raise forms.ValidationError('La contraseña es obligatoria.')
        return password

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)

            if user is None:
                raise forms.ValidationError('Usuario o contraseña incorrectos.')
            if not user.is_active:
                raise forms.ValidationError('Esta cuenta está desactivada.')
            cleaned_data['user'] = user

        return cleaned_data


class RecoveryEmailForm(forms.Form):
    DOMINIOS = (
        ('gmail.com', 'gmail.com'),
        ('outlook.com', 'outlook.com'),
        ('hotmail.com', 'hotmail.com'),
        ('yahoo.com', 'yahoo.com'),
        ('icloud.com', 'icloud.com'),
        ('live.com', 'live.com'),
        ('custom', 'Otro dominio'),
    )

    email_name = forms.CharField(max_length=64, label='Correo', strip=True)
    email_domain = forms.ChoiceField(choices=DOMINIOS, label='Dominio')
    email_custom_domain = forms.CharField(max_length=253, required=False, label='Otro dominio')

    def clean(self):
        cleaned_data = super().clean()
        name = (cleaned_data.get('email_name') or '').strip()
        selected_domain = cleaned_data.get('email_domain') or ''
        domain = selected_domain
        if selected_domain == 'custom':
            domain = (cleaned_data.get('email_custom_domain') or '').strip().lower()
        else:
            cleaned_data['email_custom_domain'] = ''

        if selected_domain == 'custom' and not domain:
            self.add_error('email_custom_domain', 'Escribe el dominio de tu correo.')
        elif name and domain:
            try:
                cleaned_data['email'] = forms.EmailField().clean(f'{name}@{domain}').lower()
            except ValidationError as error:
                self.add_error('email_name', error)
        return cleaned_data


class RecoveryCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r'^[A-Za-z0-9]{8}$',
        max_length=8,
        min_length=8,
        label='Código de verificación',
        error_messages={'invalid': 'Escribe el código de 8 letras y números recibido por correo.'},
        widget=forms.TextInput(attrs={
            'autocomplete': 'one-time-code',
            'inputmode': 'text',
            'maxlength': '8',
            'pattern': '[A-Za-z0-9]{8}',
            'placeholder': 'AB12CD34',
        }),
    )

    def clean_code(self):
        return self.cleaned_data['code'].upper()


class RecoveryPasswordForm(forms.Form):
    password = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        label='Confirmar contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_password(self):
        return validate_account_password(self.cleaned_data.get('password'))

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Las contraseñas no coinciden.')
        return cleaned_data
