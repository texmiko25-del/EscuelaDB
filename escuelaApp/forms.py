import random
import re
import string
from datetime import date

from django import forms
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from .models import ConfiguracionDashboard, Estudiante, Docente, Representante, Empleado, Asignacion, SobreNosotros, Horario
from .models import HORARIO_JORNADA_INICIO, HORARIO_JORNADA_FIN
from .estudiante_utils import GRADOS_ORDENADOS, etiqueta_estudiante, ordenar_estudiantes


NOMBRE_RE = r"^[A-Za-zÁÉÍÓÚáéíóúÑñ\s.'-]{2,100}$"
TEXTO_RE = r"^[A-Za-zÁÉÍÓÚáéíóúÑñ\s.'-]{2,100}$"
CEDULA_RE = r"^(?:V-\d{7,8}|E-\d{6,9})$"
TELEFONO_RE = r"^\d{7,15}$"
TELEFONO_VENEZOLANO_MOVIL_RE = r"^0(?:414|424|416|426|412)\d{7}$"
AREA_RE = r"^[A-Za-zÁÉÍÓÚáéíóúÑñ0-9\s.'#/()-]{2,100}$"
PERIODO_RE = r"^\d{4}-\d{4}$"
GRADO_RE = r"^[A-Za-zÁÉÍÓÚáéíóúÑñ0-9°\.\s-]{2,50}$"
USUARIO_RE = r"^[A-Za-z0-9_]+$"


def _normalize_text(value):
    if value is None:
        return ''
    return ' '.join(str(value).strip().split())


def _validate_username(value):
    username = value or ''
    if not re.fullmatch(USUARIO_RE, username):
        raise ValidationError('El usuario solo puede contener letras y números, sin espacios ni símbolos.')
    return username


def _cedula_ocupada(cedula, modelo_actual=None, pk_actual=None):
    if not cedula:
        return None
    consultas = [
        ('representante', Representante),
        ('docente', Docente),
        ('empleado', Empleado),
        ('estudiante', Estudiante),
    ]
    for nombre, modelo in consultas:
        consulta = modelo.objects.filter(cedula__iexact=cedula)
        if modelo_actual is modelo and pk_actual:
            consulta = consulta.exclude(pk=pk_actual)
        if consulta.exists():
            return nombre
    if User.objects.filter(username__iexact=cedula).exists():
        return 'cuenta'
    return None


def _directora_admin_exists(exclude_user_id=None):
    directores = Empleado.objects.filter(cargo='DIRECTORA')
    superusuarios = User.objects.filter(is_superuser=True)
    if exclude_user_id is not None:
        directores = directores.exclude(user_id=exclude_user_id)
        superusuarios = superusuarios.exclude(pk=exclude_user_id)
    return directores.exists() or superusuarios.exists()


def generate_secure_password(length=14):
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    required = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
    ]
    chars = uppercase + lowercase + digits
    rest = ''.join(random.choice(chars) for _ in range(length - len(required)))
    password = required + list(rest)
    random.shuffle(password)
    return ''.join(password)


def validate_account_password(password):
    if len(password or '') < 8:
        raise ValidationError('La contraseña debe tener al menos 8 caracteres.')
    if not re.search(r'\d', password) or not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password):
        raise ValidationError('La contraseña debe incluir mayúscula, minúscula y número.')
    return password


def _ensure_docente_profile(empleado):
    if empleado.cargo not in ('DOCENTE', 'PROFESOR'):
        return

    Docente.objects.get_or_create(
        cedula=empleado.cedula,
        defaults={
            'nombre': empleado.user.first_name or empleado.user.username,
            'apellido': empleado.user.last_name or '',
        },
    )


class AdminCrearUsuarioForm(forms.ModelForm):
    CARGOS_PERMITIDOS = [
        (code, label) for code, label in Empleado.CARGOS
        if code != 'DOCENTE'
    ]
    TIPOS_IDENTIFICACION = [
        ('V', 'Venezolana'),
        ('E', 'Extranjera'),
    ]

    tipo_identificacion = forms.ChoiceField(choices=TIPOS_IDENTIFICACION, initial='V', label='Tipo de identificación', required=False)
    cedula = forms.CharField(max_length=20, label='Cédula', widget=forms.TextInput(attrs={
        'inputmode': 'numeric',
        'pattern': CEDULA_RE,
        'placeholder': 'Ej. 1234567, 12345678 o E-123456',
        'title': 'Venezolana: 7 u 8 dígitos. Extranjera: de 6 a 9 dígitos.',
    }))
    username = forms.CharField(
        label='Usuario',
        max_length=150,
        strip=False,
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
            'pattern': r'[A-Za-z0-9_]+',
            'placeholder': 'Ej. AnaRojas24',
            'title': 'Solo letras y números, sin espacios ni símbolos.',
        }),
    )
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Mín. 8 caracteres, mayúscula, minúscula y número'}, render_value=True), label='Contraseña', required=False)
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Repite la contraseña'}, render_value=True), label='Confirmar contraseña', required=False)
    cargo = forms.ChoiceField(choices=CARGOS_PERMITIDOS, label='Cargo')
    email = forms.EmailField(label='Correo electrónico', required=True, widget=forms.EmailInput(attrs={'placeholder': 'usuario@escuela.com'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if _directora_admin_exists():
            self.fields['cargo'].choices = [
                choice for choice in self.fields['cargo'].choices
                if choice[0] != 'DIRECTORA'
            ]
            self.fields['cargo'].help_text = 'Ya existe una cuenta de Director/a administradora en el sistema.'
        if not self.data.get('password'):
            generated_password = generate_secure_password()
            self.initial['password'] = generated_password
            self.initial['confirm_password'] = generated_password

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']

    def clean_first_name(self):
        first_name = _normalize_text(self.cleaned_data.get('first_name'))
        if not first_name:
            raise ValidationError('El nombre es obligatorio.')
        if not re.fullmatch(NOMBRE_RE, first_name):
            raise ValidationError('El nombre solo puede contener letras, espacios, puntos y guiones.')
        return first_name

    def clean_last_name(self):
        last_name = _normalize_text(self.cleaned_data.get('last_name'))
        if not last_name:
            raise ValidationError('El apellido es obligatorio.')
        if not re.fullmatch(NOMBRE_RE, last_name):
            raise ValidationError('El apellido solo puede contener letras, espacios, puntos y guiones.')
        return last_name

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError('El correo electrónico es obligatorio.')

        if not re.fullmatch(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$', email):
            raise ValidationError('El correo debe tener un nombre y un dominio válidos, por ejemplo usuario@gmail.com.')

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Este correo ya está registrado en otra cuenta.')
        return email

    def clean_username(self):
        username = _validate_username(self.cleaned_data.get('username'))
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('Este nombre de usuario ya está registrado.')
        return username

    def clean_cedula(self):
        tipo = (self.cleaned_data.get('tipo_identificacion') or 'V').upper()
        cedula = (self.cleaned_data.get('cedula') or '').strip().upper().replace(' ', '')

        if cedula.startswith(('V-', 'E-')):
            prefijo, numero = cedula.split('-', 1)
            cedula = f'{prefijo}-{numero}'
        elif tipo in {'V', 'E'} and not cedula.startswith(f'{tipo}-'):
            cedula = f'{tipo}-{cedula}'

        if not re.fullmatch(CEDULA_RE, cedula):
            if tipo == 'V':
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')

        ocupante = _cedula_ocupada(cedula)
        if ocupante:
            raise ValidationError(f'Esta cédula ya está registrada en {ocupante}.')

        numero_base = cedula.split('-', 1)[-1] if '-' in cedula else cedula
        usernames_a_verificar = {cedula, numero_base}
        if User.objects.filter(username__in=list(usernames_a_verificar)).exists():
            raise ValidationError('Ya existe una cuenta con esta identificación.')
        return cedula

    def clean_password(self):
        return validate_account_password(self.cleaned_data.get('password'))

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if (
            self.data.get(self.add_prefix('cargo')) == 'DIRECTORA'
            and _directora_admin_exists()
        ):
            self.add_error('cargo', 'Ya existe una cuenta de Director/a administradora en el sistema.')

        if password and not confirm_password:
            self.add_error('confirm_password', 'Debes confirmar la contraseña.')
        elif password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Las contraseñas no coinciden.')

        return cleaned_data

    def save(self, commit=True):
        data = self.cleaned_data
        user = super().save(commit=False)
        user.username = data['username']
        user.set_password(data['password'])
        user.is_staff = data['cargo'] in ['DIRECTORA', 'SUBDIRECTORA', 'COORD', 'PROFESOR', 'ASISTENTE']
        user.is_superuser = data['cargo'] == 'DIRECTORA'
        if commit:
            user.save()
        grupo_nombre = dict(Empleado.CARGOS).get(data['cargo'], data['cargo'])
        grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
        user.groups.set([grupo])
        empleado = Empleado(user=user, cedula=data['cedula'], cargo=data['cargo'])
        if commit:
            empleado.save()
            _ensure_docente_profile(empleado)
        return user


class ConfirmarAccesoCuentaForm(forms.Form):
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.user.check_password(password):
            raise ValidationError('La contraseña es incorrecta.')
        return password


class AdminEditarUsuarioForm(forms.ModelForm):
    CARGO_OPCIONES = [
        (code, 'Profesor/a' if code in ('DOCENTE', 'PROFESOR') else label)
        for code, label in Empleado.CARGOS
        if code != 'DOCENTE'
    ]

    tipo_identificacion = forms.ChoiceField(choices=[('V', 'Venezolana'), ('E', 'Extranjera')], initial='V', label='Tipo de identificación', required=False)
    cedula = forms.CharField(max_length=20, label='Cédula', required=False)
    password = forms.CharField(
        label='Nueva contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        label='Confirmar contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    cargo = forms.ChoiceField(choices=CARGO_OPCIONES, label='Cargo', required=False)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            empleado = getattr(self.instance, 'empleado', None)
            if empleado and empleado.cargo == 'DOCENTE':
                self.fields['cargo'].choices = [
                    ('DOCENTE' if code == 'PROFESOR' else code, label)
                    for code, label in self.fields['cargo'].choices
                ]
            username = self.instance.username or ''
            if username.startswith(('V-', 'E-', 'P-')):
                tipo, numero = username.split('-', 1)
                self.fields['tipo_identificacion'].initial = tipo
                self.fields['cedula'].initial = numero
            elif empleado:
                self.fields['cedula'].initial = empleado.cedula
                self.fields['cargo'].initial = empleado.cargo
            else:
                self.fields['cedula'].initial = username
                self.fields['cargo'].initial = ''
            if empleado:
                self.fields['cedula'].initial = empleado.cedula
                self.fields['cargo'].initial = empleado.cargo
            elif not username.startswith(('V-', 'E-', 'P-')):
                self.fields['cedula'].initial = username
                self.fields['cargo'].initial = ''
            if actor == self.instance:
                cargo_actual = empleado.cargo if empleado else ('DIRECTORA' if self.instance.is_superuser else '')
                if cargo_actual:
                    cargo_label = dict(Empleado.CARGOS).get(cargo_actual, cargo_actual)
                    if cargo_actual in ('DOCENTE', 'PROFESOR'):
                        cargo_label = 'Profesor/a'
                    self.fields['cargo'].choices = [
                        (cargo_actual, cargo_label)
                    ]
                else:
                    self.fields['cargo'].choices = [('', 'Sin cargo')]
                self.fields['cargo'].initial = cargo_actual
            elif _directora_admin_exists(exclude_user_id=self.instance.pk):
                self.fields['cargo'].choices = [
                    choice for choice in self.fields['cargo'].choices
                    if choice[0] != 'DIRECTORA'
                ]

    def clean_cedula(self):
        tipo = (self.cleaned_data.get('tipo_identificacion') or 'V').upper()
        cedula = (self.cleaned_data.get('cedula') or '').strip().upper().replace(' ', '')

        if cedula.startswith(('V-', 'E-')):
            prefijo, numero = cedula.split('-', 1)
            cedula = f'{prefijo}-{numero}'
        elif tipo in {'V', 'E'}:
            cedula = f'{tipo}-{cedula}'

        if cedula and not re.fullmatch(CEDULA_RE, cedula):
            if tipo == 'V':
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')
        return cedula

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            return validate_account_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        cargo = cleaned_data.get('cargo')
        cedula = cleaned_data.get('cedula')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and not confirm_password:
            self.add_error('confirm_password', 'Debes confirmar la nueva contraseña.')
        elif password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Las contraseñas no coinciden.')
        elif not password and confirm_password:
            self.add_error('confirm_password', 'No has ingresado una nueva contraseña para confirmar.')

        if (
            self.data.get(self.add_prefix('cargo')) == 'DIRECTORA'
            and _directora_admin_exists(exclude_user_id=getattr(self.instance, 'pk', None))
        ):
            self.add_error('cargo', 'Ya existe una cuenta de Director/a administradora en el sistema.')

        if self.instance and getattr(self.instance, 'empleado', None):
            if not cedula:
                cleaned_data['cedula'] = self.instance.empleado.cedula

        return cleaned_data

    def save(self, commit=True):
        data = self.cleaned_data
        user = super().save(commit=False)
        if data.get('cedula'):
            user.username = data['cedula']
        if data.get('password'):
            user.set_password(data['password'])
        if data.get('cargo'):
            user.is_staff = data['cargo'] in ['DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE']
            if data['cargo'] == 'DIRECTORA':
                user.is_superuser = True
        if commit:
            user.save()

        empleado = getattr(self.instance, 'empleado', None)
        if data.get('cedula') or data.get('cargo'):
            if empleado:
                empleado.cedula = data.get('cedula') or empleado.cedula
                empleado.cargo = data.get('cargo') or empleado.cargo
                if commit:
                    empleado.save()
                    _ensure_docente_profile(empleado)
            else:
                empleado = Empleado.objects.create(
                    user=user,
                    cedula=data.get('cedula') or user.username,
                    cargo=data.get('cargo') or 'ASISTENTE'
                )
                _ensure_docente_profile(empleado)

        return user


class CuentaPropiaForm(AdminEditarUsuarioForm):
    username = forms.CharField(
        label='Usuario',
        max_length=150,
        strip=False,
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
            'pattern': r'[A-Za-z0-9_]+',
            'title': 'Solo letras y números, sin espacios ni símbolos.',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('tipo_identificacion', 'cargo'):
            self.fields.pop(field_name, None)
        self.fields['username'].initial = self.instance.username
        self.fields['cedula'].disabled = True
        self.order_fields(['cedula', 'first_name', 'last_name', 'email', 'username', 'password', 'confirm_password'])

    def clean_cedula(self):
        empleado = getattr(self.instance, 'empleado', None)
        return empleado.cedula if empleado else self.instance.username

    def clean_username(self):
        username = self.cleaned_data.get('username') or ''
        username = _validate_username(username)
        if username == self.instance.username:
            return username
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Este nombre de usuario ya está registrado.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Este correo ya está registrado en otra cuenta.')
        return email

    def save(self, commit=True):
        user = forms.ModelForm.save(self, commit=False)
        user.username = self.cleaned_data['username']
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class AdminConfiguracionForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionDashboard
        fields = '__all__'
        widgets = {
            'color_fondo': forms.TextInput(attrs={'type': 'color', 'style': 'height: 40px; padding: 0;'}),
            'fecha_inicio_clases': forms.DateInput(attrs={'type': 'date'}),
        }


class AdminSobreNosotrosForm(forms.ModelForm):
    class Meta:
        model = SobreNosotros
        fields = '__all__'
        widgets = {
            'contenido': forms.Textarea(attrs={'rows': 8, 'placeholder': 'Escribe los detalles de la institución aquí...'}),
        }


class RepresentanteSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        representante_id = getattr(value, 'value', value)
        if not representante_id:
            return option
        representante = Representante.objects.filter(pk=representante_id).first()
        if representante:
            option['attrs']['data-cedula'] = representante.cedula or ''
            option['attrs']['data-contador'] = Estudiante.objects.filter(
                representante_id=representante.pk
            ).exclude(pk=getattr(self, 'instance_pk', None)).count() + 1
        return option


class RepresentanteForm(forms.ModelForm):
    tipo_identificacion = forms.ChoiceField(choices=[('V', 'Venezolana'), ('E', 'Extranjera')], initial='V', label='Tipo de identificación', required=False)

    class Meta:
        model = Representante
        fields = ['nombre', 'apellido', 'cedula', 'telefono', 'email', 'ocupacion', 'parentesco', 'estado_civil', 'nacionalidad', 'partida_nacimiento', 'ubicacion', 'es_tutor_legal']
        widgets = {
            'cedula': forms.TextInput(attrs={
                'inputmode': 'numeric',
                'pattern': CEDULA_RE,
                'placeholder': 'Ej. V-1234567 o E-123456',
            }),
            'telefono': forms.TextInput(attrs={'inputmode': 'numeric', 'pattern': '[0-9]*', 'placeholder': 'Solo números'}),
            'email': forms.EmailInput(attrs={'placeholder': 'correo@ejemplo.com'}),
            'ocupacion': forms.TextInput(attrs={'placeholder': 'Profesión u oficio'}),
            'parentesco': forms.TextInput(attrs={'placeholder': 'Padre, madre, tutor, etc.'}),
            'estado_civil': forms.Select(attrs={'placeholder': 'Seleccione una opción'}),
            'nacionalidad': forms.TextInput(attrs={'placeholder': 'Nacionalidad'}),
            'partida_nacimiento': forms.TextInput(attrs={'placeholder': 'Número de partida de nacimiento'}),
            'ubicacion': forms.TextInput(attrs={'placeholder': 'Dirección o ubicación'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['nombre', 'apellido', 'tipo_identificacion', 'cedula'])
        if self.instance and self.instance.pk and self.instance.cedula and self.instance.cedula.startswith(('V-', 'E-')):
            self.fields['tipo_identificacion'].initial = self.instance.cedula.split('-', 1)[0]

    def clean_nombre(self):
        nombre = _normalize_text(self.cleaned_data.get('nombre'))
        if not nombre:
            return ''
        if not re.fullmatch(TEXTO_RE, nombre):
            raise ValidationError('El nombre solo puede contener letras, espacios, puntos y guiones.')
        return nombre

    def clean_apellido(self):
        apellido = _normalize_text(self.cleaned_data.get('apellido'))
        if not apellido:
            return ''
        if not re.fullmatch(TEXTO_RE, apellido):
            raise ValidationError('El apellido solo puede contener letras, espacios, puntos y guiones.')
        return apellido

    def clean_cedula(self):
        tipo = (self.cleaned_data.get('tipo_identificacion') or 'V').upper()
        cedula = (self.cleaned_data.get('cedula') or '').strip().upper().replace(' ', '')
        if not cedula:
            return None

        if cedula.startswith(('V-', 'E-')):
            prefijo, numero = cedula.split('-', 1)
            cedula = f'{prefijo}-{numero}'
        elif tipo in {'V', 'E'} and not cedula.startswith(f'{tipo}-'):
            cedula = f'{tipo}-{cedula}'

        if not re.fullmatch(CEDULA_RE, cedula):
            if tipo == 'V':
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')

        if self.instance and self.instance.pk:
            existing = Representante.objects.filter(cedula=cedula).exclude(pk=self.instance.pk).exists()
            if existing:
                raise ValidationError('Ya existe un representante con esta cédula.')

        ocupante = _cedula_ocupada(cedula, Representante, getattr(self.instance, 'pk', None))
        if ocupante:
            raise ValidationError(f'Esta cédula ya está registrada en {ocupante}.')

        return cedula

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        if telefono is not None and str(telefono).strip() != '':
            telefono_str = str(telefono).strip()
            if not re.fullmatch(r'^\d{11}$', telefono_str):
                raise ValidationError('El teléfono celular venezolano debe tener exactamente 11 dígitos.')
            if not re.fullmatch(TELEFONO_VENEZOLANO_MOVIL_RE, telefono_str):
                raise ValidationError('El teléfono celular venezolano debe comenzar con uno de estos prefijos válidos: 0414, 0424, 0416, 0426 o 0412.')
            return telefono_str
        return telefono

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and len(email) > 254:
            raise ValidationError('El correo electrónico no puede superar 254 caracteres.')
        return email or None

    def clean_ocupacion(self):
        ocupacion = _normalize_text(self.cleaned_data.get('ocupacion'))
        if ocupacion and not re.fullmatch(TEXTO_RE, ocupacion):
            raise ValidationError('La ocupación solo puede contener letras, espacios, puntos y guiones.')
        if ocupacion and len(ocupacion) > 100:
            raise ValidationError('La ocupación no puede superar 100 caracteres.')
        return ocupacion or None

    def clean_parentesco(self):
        parentesco = _normalize_text(self.cleaned_data.get('parentesco'))
        if parentesco and not re.fullmatch(TEXTO_RE, parentesco):
            raise ValidationError('El parentesco solo puede contener letras, espacios, puntos y guiones.')
        if parentesco and len(parentesco) > 50:
            raise ValidationError('El parentesco no puede superar 50 caracteres.')
        return parentesco or None

    def clean_nacionalidad(self):
        nacionalidad = _normalize_text(self.cleaned_data.get('nacionalidad'))
        if nacionalidad and not re.fullmatch(TEXTO_RE, nacionalidad):
            raise ValidationError('La nacionalidad solo puede contener letras, espacios, puntos y guiones.')
        if nacionalidad and len(nacionalidad) > 50:
            raise ValidationError('La nacionalidad no puede superar 50 caracteres.')
        return nacionalidad or None

    def clean_partida_nacimiento(self):
        partida = _normalize_text(self.cleaned_data.get('partida_nacimiento'))
        if partida and len(partida) > 50:
            raise ValidationError('La partida de nacimiento no puede superar 50 caracteres.')
        return partida or None

    def clean_ubicacion(self):
        ubicacion = _normalize_text(self.cleaned_data.get('ubicacion'))
        if ubicacion and len(ubicacion) > 200:
            raise ValidationError('La ubicación no puede superar 200 caracteres.')
        return ubicacion or None


class EstudianteForm(forms.ModelForm):
    GRADOS = GRADOS_ORDENADOS

    grado = forms.ChoiceField(
        choices=[('', 'Seleccione un grado'), *GRADOS],
        required=False,
        label='Grado',
    )
    seccion = forms.ChoiceField(
        choices=[('', 'Seleccione una sección'), *Estudiante.SECCIONES],
        required=False,
        label='Sección',
    )
    sexo = forms.ChoiceField(
        choices=[('', 'Seleccione una opción'), *Estudiante.SEXO_CHOICES],
        required=False,
        label='Sexo',
    )
    nacionalidad = forms.CharField(
        max_length=50,
        label='Nacionalidad',
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Venezolana'})
    )
    cedula = forms.CharField(
        required=False,
        label='Cédula escolar (automática)',
        widget=forms.TextInput(attrs={
            'readonly': 'readonly',
            'placeholder': 'Se genera al seleccionar representante',
        })
    )
    fecha_nacimiento = forms.DateField(
        required=False,
        label='Fecha de nacimiento',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={
            'type': 'date',
            'max': date.today().isoformat(),
            'title': 'No se permiten fechas futuras.',
        })
    )
    edad = forms.IntegerField(
        required=False,
        label='Edad (años)',
        disabled=True,
        widget=forms.NumberInput(attrs={
            'readonly': 'readonly',
            'placeholder': 'Se calcula automáticamente',
        })
    )
    matricula = forms.CharField(
        required=False,
        label='Matrícula',
        widget=forms.TextInput(attrs={'readonly': 'readonly', 'placeholder': 'Se genera automáticamente'})
    )

    class Meta:
        model = Estudiante
        fields = ['nombre', 'apellido', 'cedula', 'fecha_nacimiento', 'sexo', 'nacionalidad', 'grado', 'seccion', 'telefono', 'ubicacion', 'representante', 'matricula']
        widgets = {
            'cedula': forms.TextInput(attrs={'inputmode': 'numeric', 'pattern': '[0-9]*', 'placeholder': 'Solo números'}),
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date'}),
            'ubicacion': forms.TextInput(attrs={'placeholder': 'Dirección o ubicación'}),
            'telefono': forms.TextInput(attrs={'inputmode': 'numeric', 'pattern': '[0-9]*', 'placeholder': 'Solo números'}),
            'representante': RepresentanteSelect(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sexo'].required = False
        self.fields['nacionalidad'].required = False
        self.fields['representante'].widget.instance_pk = getattr(self.instance, 'pk', None)
        self.fields['representante'].help_text = (
            'Un representante puede tener uno o varios estudiantes. '
            'Cada estudiante recibirá su propio contador escolar.'
        )
        if self.instance and self.instance.pk and self.instance.matricula:
            self.fields['matricula'].initial = self.instance.matricula
        elif not self.instance.pk:
            self.fields['matricula'].initial = Estudiante().generar_matricula()
        if self.instance and self.instance.fecha_nacimiento:
            self.fields['edad'].initial = self.calcular_edad(self.instance.fecha_nacimiento)

    @staticmethod
    def calcular_edad(fecha_nacimiento):
        hoy = date.today()
        return hoy.year - fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day)
        )

    def clean_fecha_nacimiento(self):
        fecha_nacimiento = self.cleaned_data.get('fecha_nacimiento')
        if fecha_nacimiento and fecha_nacimiento > date.today():
            raise ValidationError('La fecha de nacimiento no puede ser una fecha futura.')
        return fecha_nacimiento

    def clean_matricula(self):
        return _normalize_text(self.cleaned_data.get('matricula')) or Estudiante().generar_matricula()

    def clean(self):
        cleaned_data = super().clean()
        representante = cleaned_data.get('representante')
        if representante:
            if self.instance and self.instance.pk and self.instance.cedula:
                cleaned_data['cedula'] = self.instance.cedula
            else:
                base = re.sub(r'\D', '', str(representante.cedula or ''))
                if base:
                    contador = Estudiante.objects.filter(
                        representante=representante
                    ).exclude(pk=getattr(self.instance, 'pk', None)).count() + 1
                    cleaned_data['cedula'] = f'{base}{contador:03d}'
        return cleaned_data

    def save(self, commit=True):
        estudiante = super().save(commit=False)

        if commit:
            estudiante.save()
        return estudiante

    def clean_nombre(self):
        nombre = _normalize_text(self.cleaned_data.get('nombre'))
        if not nombre:
            return ''
        if not re.fullmatch(TEXTO_RE, nombre):
            raise ValidationError('El nombre solo puede contener letras, espacios, puntos y guiones.')
        return nombre

    def clean_apellido(self):
        apellido = _normalize_text(self.cleaned_data.get('apellido'))
        if not apellido:
            return ''
        if not re.fullmatch(TEXTO_RE, apellido):
            raise ValidationError('El apellido solo puede contener letras, espacios, puntos y guiones.')
        return apellido

    def clean_cedula(self):
        cedula = str(self.cleaned_data.get('cedula') or '').strip().upper()
        if not cedula:
            return None

        if cedula.isdigit() and 9 <= len(cedula) <= 12:
            return cedula

        if not cedula.startswith(('V-', 'E-')):
            digits = re.sub(r'\D', '', cedula)
            if len(digits) <= 8:
                cedula = f'V-{digits}'
            elif len(digits) <= 9:
                cedula = f'E-{digits}'
            else:
                raise ValidationError('Use V- con 7 u 8 dígitos o E- con entre 6 y 9 dígitos.')

        if not re.fullmatch(CEDULA_RE, cedula):
            if cedula.startswith('V-'):
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')

        return cedula

    def clean_grado(self):
        grado = _normalize_text(self.cleaned_data.get('grado'))
        if not grado:
            return ''
        if not re.fullmatch(GRADO_RE, grado):
            raise ValidationError('El grado solo puede contener letras, números, espacios y guiones.')
        return grado

    def clean_seccion(self):
        seccion = _normalize_text(self.cleaned_data.get('seccion')).upper()
        if not seccion:
            return ''
        if seccion not in dict(Estudiante.SECCIONES):
            raise ValidationError('Selecciona una sección de la A a la F.')
        return seccion

    def clean_nacionalidad(self):
        nacionalidad = _normalize_text(self.cleaned_data.get('nacionalidad'))
        if not nacionalidad:
            return 'No especificada'
        if not re.fullmatch(TEXTO_RE, nacionalidad):
            raise ValidationError('La nacionalidad solo puede contener letras, espacios, puntos y guiones.')
        return nacionalidad

    def clean_sexo(self):
        return self.cleaned_data.get('sexo') or 'O'

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        if telefono is not None and str(telefono).strip() != '':
            telefono_str = str(telefono).strip()
            if not re.fullmatch(r'^\d{11}$', telefono_str):
                raise ValidationError('El teléfono celular venezolano debe tener exactamente 11 dígitos.')
            if not re.fullmatch(TELEFONO_VENEZOLANO_MOVIL_RE, telefono_str):
                raise ValidationError('El teléfono celular venezolano debe comenzar con uno de estos prefijos válidos: 0414, 0424, 0416, 0426 o 0412.')
            return telefono_str
        return telefono

    def clean_ubicacion(self):
        ubicacion = _normalize_text(self.cleaned_data.get('ubicacion'))
        if ubicacion and len(ubicacion) > 200:
            raise ValidationError('La ubicación no puede superar 200 caracteres.')
        return ubicacion or None


class DocenteForm(forms.ModelForm):
    MATERIAS = [
        ('Matemáticas', 'Matemáticas'),
        ('Lengua y Literatura', 'Lengua y Literatura'),
        ('Ciencias Naturales', 'Ciencias Naturales'),
        ('Ciencias Sociales', 'Ciencias Sociales'),
        ('Inglés', 'Inglés'),
        ('Educación Física', 'Educación Física'),
        ('Educación Artística', 'Educación Artística'),
        ('Computación', 'Computación'),
        ('Música', 'Música'),
        ('Tecnología', 'Tecnología'),
        ('Historia', 'Historia'),
        ('Geografía', 'Geografía'),
        ('Formación Ciudadana', 'Formación Ciudadana'),
        ('Educación Ambiental', 'Educación Ambiental'),
        ('Orientación', 'Orientación'),
    ]

    tipo_identificacion = forms.ChoiceField(
        choices=[('V', 'Venezolana'), ('E', 'Extranjera')],
        initial='V',
        label='Tipo de identificación',
        required=False,
    )

    especialidad = forms.CharField(
        max_length=100,
        label='Materia',
        widget=forms.TextInput(attrs={
            'list': 'materias-list',
            'placeholder': 'Busca o escribe una materia',
        })
    )
    telefono = forms.CharField(required=True, widget=forms.HiddenInput())

    class Meta:
        model = Docente
        fields = ['nombre', 'apellido', 'cedula', 'telefono', 'especialidad', 'carga_horaria']
        widgets = {
            'cedula': forms.TextInput(attrs={
                'inputmode': 'numeric',
                'pattern': CEDULA_RE,
                'placeholder': 'V-1234567 o E-123456',
            }),
            'especialidad': forms.TextInput(attrs={'placeholder': 'Ejemplo: Matemáticas'}),
            'carga_horaria': forms.NumberInput(attrs={'min': 1, 'max': 5, 'step': 1, 'inputmode': 'numeric'}),
        }

    def clean_nombre(self):
        nombre = _normalize_text(self.cleaned_data.get('nombre'))
        if not nombre:
            return ''
        if not re.fullmatch(TEXTO_RE, nombre):
            raise ValidationError('El nombre solo puede contener letras, espacios, puntos y guiones.')
        return nombre

    def clean_apellido(self):
        apellido = _normalize_text(self.cleaned_data.get('apellido'))
        if not apellido:
            return ''
        if not re.fullmatch(TEXTO_RE, apellido):
            raise ValidationError('El apellido solo puede contener letras, espacios, puntos y guiones.')
        return apellido

    def clean_cedula(self):
        tipo = (self.cleaned_data.get('tipo_identificacion') or 'V').upper()
        cedula = str(self.cleaned_data.get('cedula') or '').strip().upper()
        if not cedula:
            return None

        if cedula.startswith(('V-', 'E-')):
            tipo, cedula = cedula.split('-', 1)
        cedula = f'{tipo}-{re.sub(r"\D", "", cedula)}'

        if not re.fullmatch(CEDULA_RE, cedula):
            if cedula.startswith('V-'):
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')

        ocupante = _cedula_ocupada(cedula, Docente, getattr(self.instance, 'pk', None))
        if ocupante:
            raise ValidationError(f'Esta cédula ya está registrada en {ocupante}.')

        return cedula

    def clean_especialidad(self):
        especialidad = _normalize_text(self.cleaned_data.get('especialidad'))
        if especialidad and len(especialidad) > 100:
            raise ValidationError('La especialidad no puede superar 100 caracteres.')
        if especialidad and not re.fullmatch(TEXTO_RE, especialidad):
            raise ValidationError('La especialidad solo puede contener letras, espacios, puntos y guiones.')
        return especialidad or ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['telefono'].required = False
        self.fields['especialidad'].required = False
        self.fields['carga_horaria'].required = False
        if not self.is_bound and not self.instance.carga_horaria:
            self.fields['carga_horaria'].initial = None

    def clean_carga_horaria(self):
        carga_horaria = self.cleaned_data.get('carga_horaria')
        if carga_horaria is None:
            return 0
        if carga_horaria < 1 or carga_horaria > 5:
            raise ValidationError('La carga horaria debe estar entre 1 y 5 horas.')
        return carga_horaria

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        if telefono is not None and str(telefono).strip() != '':
            telefono_str = str(telefono).strip()
            if not re.fullmatch(r'^\d{11}$', telefono_str):
                raise ValidationError('El teléfono celular venezolano debe tener exactamente 11 dígitos.')
            if not re.fullmatch(TELEFONO_VENEZOLANO_MOVIL_RE, telefono_str):
                raise ValidationError('El teléfono celular venezolano debe comenzar con uno de estos prefijos válidos: 0414, 0424, 0416, 0426 o 0412.')
            return telefono_str
        return telefono


class EmpleadoForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label='Contraseña', required=False)
    first_name = forms.CharField(max_length=100, label='Nombre')
    last_name = forms.CharField(max_length=100, label='Apellido')
    email = forms.EmailField(required=False, label='Correo electrónico')

    class Meta:
        model = Empleado
        fields = [
            'cedula',
            'cargo',
            'telefono',
            'acepta_notificaciones_whatsapp',
            'telegram_chat_id',
            'notificar_contactos_telegram',
        ]
        labels = {
            'telefono': 'Teléfono para avisos de calificaciones',
            'acepta_notificaciones_whatsapp': 'Autorizo avisos de calificaciones por WhatsApp',
            'telegram_chat_id': 'Chat ID de Telegram',
            'notificar_contactos_telegram': 'Recibir avisos de nuevos contactos por Telegram',
        }
        widgets = {
            'telefono': forms.TextInput(attrs={
                'type': 'tel',
                'placeholder': '+584121234567 o 04121234567',
                'autocomplete': 'tel',
            }),
            'acepta_notificaciones_whatsapp': forms.CheckboxInput(),
            'telegram_chat_id': forms.TextInput(attrs={
                'inputmode': 'numeric',
                'placeholder': 'Chat ID obtenido después de iniciar el bot',
            }),
            'notificar_contactos_telegram': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cargo_actual = self.instance.cargo if self.instance and self.instance.pk else None
        self.fields['cargo'].choices = [
            (
                'DOCENTE' if code == 'PROFESOR' and cargo_actual == 'DOCENTE' else code,
                'Profesor/a' if code in ('DOCENTE', 'PROFESOR') else label,
            )
            for code, label in Empleado.CARGOS
            if code != 'DOCENTE'
        ]
        exclude_user_id = self.instance.user_id if self.instance and self.instance.pk else None
        current_is_directora = bool(
            self.instance and self.instance.pk and self.instance.cargo == 'DIRECTORA'
        )
        if _directora_admin_exists(exclude_user_id=exclude_user_id) and not current_is_directora:
            self.fields['cargo'].choices = [
                choice for choice in self.fields['cargo'].choices
                if choice[0] != 'DIRECTORA'
            ]
        if self.instance and self.instance.pk:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email
            self.fields['password'].required = False
        else:
            self.fields['password'].required = True

    def clean_first_name(self):
        first_name = _normalize_text(self.cleaned_data.get('first_name'))
        if not first_name:
            raise ValidationError('El nombre es obligatorio.')
        if not re.fullmatch(NOMBRE_RE, first_name):
            raise ValidationError('El nombre solo puede contener letras, espacios y puntos.')
        return first_name

    def clean_last_name(self):
        last_name = _normalize_text(self.cleaned_data.get('last_name'))
        if not last_name:
            raise ValidationError('El apellido es obligatorio.')
        if not re.fullmatch(NOMBRE_RE, last_name):
            raise ValidationError('El apellido solo puede contener letras, espacios y puntos.')
        return last_name

    def clean_telefono(self):
        telefono = (self.cleaned_data.get('telefono') or '').strip().replace(' ', '').replace('-', '')
        if telefono and not (
            re.fullmatch(r'\+[1-9]\d{7,14}', telefono)
            or re.fullmatch(TELEFONO_VENEZOLANO_MOVIL_RE, telefono)
        ):
            raise ValidationError('Usa +código de país y número, o un celular venezolano de 11 dígitos.')
        return telefono

    def clean_telegram_chat_id(self):
        chat_id = (self.cleaned_data.get('telegram_chat_id') or '').strip()
        if chat_id and (
            not re.fullmatch(r'-?[0-9]{1,20}', chat_id)
            or int(chat_id) == 0
        ):
            raise ValidationError('El chat ID de Telegram debe ser numérico.')
        return chat_id

    def clean_cedula(self):
        cedula = str(self.cleaned_data.get('cedula') or '').strip().upper()
        if not cedula:
            raise ValidationError('La cédula es obligatoria.')

        if not cedula.startswith(('V-', 'E-')):
            digits = re.sub(r'\D', '', cedula)
            if len(digits) <= 8:
                cedula = f'V-{digits}'
            elif len(digits) <= 9:
                cedula = f'E-{digits}'
            else:
                raise ValidationError('Use V- con 7 u 8 dígitos o E- con entre 6 y 9 dígitos.')

        if not re.fullmatch(CEDULA_RE, cedula):
            if cedula.startswith('V-'):
                raise ValidationError('La cédula venezolana debe tener 7 u 8 dígitos.')
            raise ValidationError('La cédula extranjera debe tener entre 6 y 9 dígitos.')

        ocupante = _cedula_ocupada(cedula, Empleado, getattr(self.instance, 'pk', None))
        if ocupante:
            raise ValidationError(f'Esta cédula ya está registrada en {ocupante}.')

        return cedula

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            if len(password) < 8:
                raise ValidationError('La contraseña debe tener al menos 8 caracteres.')
            if not re.search(r'\d', password) or not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password):
                raise ValidationError('La contraseña debe incluir mayúscula, minúscula y número.')
        return password

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('notificar_contactos_telegram') and not cleaned_data.get('telegram_chat_id'):
            self.add_error(
                'telegram_chat_id',
                'Indica el chat ID para recibir avisos por Telegram.',
            )
        exclude_user_id = self.instance.user_id if self.instance and self.instance.pk else None
        current_is_directora = bool(
            self.instance and self.instance.pk and self.instance.cargo == 'DIRECTORA'
        )
        if (
            self.data.get(self.add_prefix('cargo')) == 'DIRECTORA'
            and _directora_admin_exists(exclude_user_id=exclude_user_id)
            and not current_is_directora
        ):
            self.add_error('cargo', 'Ya existe una cuenta de Director/a administradora en el sistema.')
        if (
            self.instance and self.instance.pk
            and self.instance.user.is_superuser
            and cleaned_data.get('cargo') != 'DIRECTORA'
        ):
            self.add_error('cargo', 'La cuenta administradora debe conservar el cargo Director/a.')
        return cleaned_data

    def save(self, commit=True):
        data = self.cleaned_data
        if self.instance and self.instance.pk:
            empleado = super().save(commit=False)
            user = empleado.user
            user.username = data['cedula']
            user.first_name = data['first_name']
            user.last_name = data['last_name']
            user.email = data['email']
            if data.get('password'):
                user.set_password(data['password'])
            user.is_staff = data['cargo'] in ['DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR', 'ASISTENTE']
            if data['cargo'] == 'DIRECTORA':
                user.is_superuser = True
            user.save()
            grupo_nombre = dict(Empleado.CARGOS).get(data['cargo'], data['cargo'])
            grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
            user.groups.set([grupo])
            empleado.user = user
            if commit:
                empleado.save()
                _ensure_docente_profile(empleado)
            return empleado

        user = User(
            username=data['cedula'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            is_staff=data['cargo'] in ['DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR', 'ASISTENTE'],
        )
        user.is_superuser = data['cargo'] == 'DIRECTORA'
        user.set_password(data['password'])
        if commit:
            user.save()
        grupo_nombre = dict(Empleado.CARGOS).get(data['cargo'], data['cargo'])
        grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
        user.groups.set([grupo])

        empleado = super().save(commit=False)
        empleado.user = user
        if commit:
            empleado.save()
            _ensure_docente_profile(empleado)
        return empleado


class AsignacionForm(forms.Form):
    estudiante = forms.ModelChoiceField(
        queryset=ordenar_estudiantes(
            Estudiante.objects.select_related('representante').all()
        ),
        label='Estudiante',
        empty_label='Seleccione un estudiante',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    docente = forms.ModelChoiceField(
        queryset=Empleado.objects.select_related('user').filter(cargo__in=['DOCENTE', 'PROFESOR']),
        label='Profesor/a',
        empty_label='Seleccione un profesor',
        widget=forms.Select(attrs={'class': 'form-control docente-select'})
    )
    area = forms.CharField(
        max_length=100,
        label='Área/Materia',
        widget=forms.TextInput(attrs={
            'placeholder': 'Ejemplo: Matemáticas',
            'list': 'subject-list',
        })
    )
    periodo = forms.CharField(max_length=20, label='Período escolar', initial='2026-2027', widget=forms.TextInput(attrs={'placeholder': 'YYYY-YYYY'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['estudiante'].label_from_instance = etiqueta_estudiante
        docentes_cedulas = [doc.cedula for doc in Docente.objects.filter(cedula__in=self.fields['docente'].queryset.values_list('cedula', flat=True))]
        especialidades = {doc.cedula: doc.especialidad for doc in Docente.objects.filter(cedula__in=docentes_cedulas)}
        self.fields['docente'].label_from_instance = lambda obj: (
            f"{obj.user.get_full_name() or 'Sin nombre'} - C.I.: {obj.cedula}"
            + (f" - {especialidades.get(obj.cedula, 'Especialidad no registrada')}" if obj.cedula in especialidades else '')
        )

    def clean_area(self):
        area = _normalize_text(self.cleaned_data.get('area'))
        if not area:
            raise forms.ValidationError('El área o materia es obligatoria.')
        if not re.fullmatch(AREA_RE, area):
            raise forms.ValidationError('El área solo puede contener letras, números, espacios y algunos signos.')
        return area

    def clean_periodo(self):
        periodo = self.cleaned_data.get('periodo')
        if not re.fullmatch(PERIODO_RE, str(periodo or '')):
            raise forms.ValidationError('El período debe tener el formato YYYY-YYYY.')
        return periodo

    def clean(self):
        cleaned_data = super().clean()
        docente = cleaned_data.get('docente')

        if docente and docente.cargo not in ['DOCENTE', 'PROFESOR']:
            raise forms.ValidationError('El empleado seleccionado no tiene un cargo de profesor.')

        return cleaned_data


class DocenteEstudiantesForm(forms.Form):
    grado = forms.ChoiceField(
        choices=[('', 'Seleccione un grado'), *EstudianteForm.GRADOS],
        label='Grado',
    )
    seccion = forms.ChoiceField(
        choices=[('', 'Seleccione una sección'), *Estudiante.SECCIONES],
        label='Sección',
    )
    estudiantes = forms.ModelMultipleChoiceField(
        queryset=Estudiante.objects.none(),
        required=True,
        label='Estudiantes',
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 12}),
    )

    def __init__(self, *args, docente, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound and self.data.get(
            self.add_prefix('asignar_grupo_completo')
        ) == '1':
            self.fields['estudiantes'].required = False
        grado = (
            self.data.get(self.add_prefix('grado'), '')
            if self.is_bound
            else self.initial.get('grado', '')
        )
        seccion = (
            self.data.get(self.add_prefix('seccion'), '')
            if self.is_bound
            else self.initial.get('seccion', '')
        )
        grados_validos = {codigo for codigo, _ in EstudianteForm.GRADOS}
        if grado in grados_validos:
            self.fields['estudiantes'].queryset = ordenar_estudiantes(
                Estudiante.objects.filter(grado=grado, seccion=seccion)
            )
            self.fields['estudiantes'].label_from_instance = etiqueta_estudiante
            if not self.is_bound and docente.pk:
                self.initial['estudiantes'] = docente.estudiantes_asignados.filter(
                    grado=grado,
                    seccion=seccion,
                )


class AsignacionNotaForm(forms.ModelForm):
    class Meta:
        model = Asignacion
        fields = ['nota', 'evaluacion', 'comentarios']
        labels = {
            'nota': 'Nota',
            'evaluacion': 'Tipo de evaluación',
            'comentarios': 'Comentarios',
        }

    def clean_nota(self):
        nota = self.cleaned_data.get('nota')
        if nota is not None and (nota < 0 or nota > 100):
            raise ValidationError('La nota debe estar entre 0 y 100.')
        return nota

    def clean_evaluacion(self):
        evaluacion = _normalize_text(self.cleaned_data.get('evaluacion'))
        if evaluacion and len(evaluacion) > 100:
            raise ValidationError('La evaluación no puede superar 100 caracteres.')
        return evaluacion or ''

    def clean_comentarios(self):
        comentarios = _normalize_text(self.cleaned_data.get('comentarios'))
        if comentarios and len(comentarios) > 1000:
            raise ValidationError('Los comentarios no pueden superar 1000 caracteres.')
        return comentarios or ''


class HorarioForm(forms.ModelForm):
    class Meta:
        from .models import Horario
        model = Horario
        fields = ['ano', 'materia', 'docente', 'dia', 'hora_inicio', 'hora_fin']
        widgets = {
            'ano': forms.Select(attrs={'class': 'form-control'}),
            'materia': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ejemplo: Matemáticas',
                'list': 'subject-list',
            }),
            'docente': forms.Select(attrs={'class': 'form-control'}),
            'dia': forms.Select(attrs={'class': 'form-control'}),
            'hora_inicio': forms.TimeInput(attrs={
                'type': 'time', 'class': 'form-control', 'step': 60, 'min': '08:00', 'max': '13:00',
            }),
            'hora_fin': forms.TimeInput(attrs={
                'type': 'time', 'class': 'form-control', 'step': 60, 'min': '08:00', 'max': '13:00',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['docente'].label = 'Profesor/a'
        self.fields['docente'].label_from_instance = lambda obj: (
            f"{obj.nombre} {obj.apellido} ({obj.cedula})"
            + (f" - {obj.especialidad}" if obj.especialidad else '')
        )

    def clean_materia(self):
        materia = _normalize_text(self.cleaned_data.get('materia'))
        if not materia:
            raise forms.ValidationError('La materia es obligatoria.')
        if not re.fullmatch(AREA_RE, materia):
            raise forms.ValidationError('La materia solo puede contener letras, números, espacios y algunos signos.')
        return materia

    def clean(self):
        cleaned_data = super().clean()
        ano = cleaned_data.get('ano')
        dia = cleaned_data.get('dia')
        docente = cleaned_data.get('docente')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fin = cleaned_data.get('hora_fin')

        if hora_inicio and hora_fin and hora_inicio >= hora_fin:
            raise forms.ValidationError('La hora de inicio debe ser anterior a la hora de fin.')

        if ano and dia and hora_inicio and hora_fin:
            horarios = Horario.objects.filter(dia=dia).exclude(pk=self.instance.pk)
            horario_grado_solapado = horarios.filter(ano=ano).filter(
                hora_inicio__lt=hora_fin,
                hora_fin__gt=hora_inicio,
            ).exists()
            if horario_grado_solapado:
                raise forms.ValidationError(
                    'No se puede crear este horario porque el grado ya tiene una clase ocupando esa hora. Elige otra franja.'
                )

            if docente and horarios.filter(docente=docente).filter(
                hora_inicio__lt=hora_fin,
                hora_fin__gt=hora_inicio,
            ).exists():
                raise forms.ValidationError(
                    'No se puede crear este horario porque el profesor ya tiene una clase ocupando esa hora. Elige otra franja o un profesor distinto.'
                )

        return cleaned_data
