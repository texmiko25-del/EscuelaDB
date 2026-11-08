import logging
import re

from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect

from .contact_notifications import notify_new_contact
from .forms_subdireccion import SolicitudMatriculaForm
from .models import (
    ConfiguracionDashboard,
    InformacionEscuela,
    SobreNosotros,
    ContactoMensaje,
    Horario,
    Representante,
    SolicitudMatricula,
)

logger = logging.getLogger(__name__)


def portal_home(request):
    config, _ = ConfiguracionDashboard.objects.get_or_create(pk=1)
    info = InformacionEscuela.objects.first()
    horarios = list(Horario.objects.select_related('docente').order_by('ano', 'dia', 'hora_inicio'))
    grados_con_horario = {horario.ano for horario in horarios}
    grouped_horarios = {
        codigo: {
            'display': nombre,
            'dias': [
                {'code': dia_codigo, 'name': dia_nombre, 'items': []}
                for dia_codigo, dia_nombre in Horario.DIAS_SEMANA
            ],
        }
        for codigo, nombre in Horario.ANOS_ESCOLARES
        if codigo in grados_con_horario
    }
    dias_por_grado = {
        (codigo, dia['code']): dia
        for codigo, grupo in grouped_horarios.items()
        for dia in grupo['dias']
    }
    for horario in horarios:
        dias_por_grado[(horario.ano, horario.dia)]['items'].append(horario)

    context = {
        'config': config,
        'info': info,
        'grouped_horarios': grouped_horarios.values(),
    }
    return render(request, 'escuelaApp/portal_home.html', context)


def portal_about(request):
    info, _ = SobreNosotros.objects.get_or_create(pk=1)
    return render(request, 'escuelaApp/portal_about.html', {'info': info})


def portal_contact(request):
    info = InformacionEscuela.objects.first()
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        email = request.POST.get('email', '').strip()
        cedula_ingresada = request.POST.get('cedula', '')
        tipo_identificacion = request.POST.get('tipo_identificacion', '').strip().upper()
        cedula_valida = (
            tipo_identificacion == 'V' and bool(re.fullmatch(r'[0-9]{7,8}', cedula_ingresada))
        ) or (
            tipo_identificacion == 'E' and bool(re.fullmatch(r'[0-9]{6,9}', cedula_ingresada))
        )
        cedula = f'{tipo_identificacion}-{cedula_ingresada}' if cedula_valida else ''
        telefono = request.POST.get('telefono', '').strip()
        acepta_whatsapp = request.POST.get('acepta_whatsapp') == 'on'
        asunto = request.POST.get('asunto', '').strip()
        mensaje = request.POST.get('mensaje', '').strip()
        telefono_valido = not telefono or bool(
            re.fullmatch(r'\+58(?:412|414|416|422|424|426)[0-9]{7}', telefono)
        )
        consentimiento_valido = not acepta_whatsapp or bool(telefono)
        if nombre and email and mensaje and cedula_valida and telefono_valido and consentimiento_valido:
            representante_verificado = Representante.objects.filter(
                cedula__iexact=cedula,
                email__iexact=email,
            ).exists()
            if not representante_verificado:
                messages.error(
                    request,
                    'La cédula y el correo no coinciden con los datos de una representante registrada. Verifica la información.',
                )
                return render(request, 'escuelaApp/portal_contact.html', {'info': info})

            contacto = ContactoMensaje.objects.create(
                nombre=nombre,
                email=email,
                telefono=telefono,
                acepta_whatsapp=acepta_whatsapp,
                asunto=asunto,
                mensaje=mensaje,
            )
            resultado = notify_new_contact(contacto)
            if resultado['failures'] or not resultado['staff_count']:
                logger.warning(
                    'El contacto %s quedó guardado; destinatarios Telegram internos configurados: %s, fallos: %s.',
                    contacto.pk,
                    resultado['staff_count'],
                    resultado['failures'],
                )
            messages.success(
                request,
                'Gracias por contactarnos. Recibimos tu mensaje y te responderemos pronto.',
            )
            return redirect('portal_contact')
        elif not telefono_valido:
            messages.error(
                request,
                'Selecciona un prefijo venezolano y escribe los siete dígitos restantes.',
            )
        elif not consentimiento_valido:
            messages.error(request, 'Indica un teléfono para recibir respuesta por WhatsApp.')
        elif not cedula_valida:
            if tipo_identificacion == 'V':
                error_cedula = 'La cédula venezolana debe contener exactamente 7 u 8 dígitos.'
            elif tipo_identificacion == 'E':
                error_cedula = 'La cédula extranjera debe contener entre 6 y 9 dígitos.'
            else:
                error_cedula = 'Selecciona si la cédula es venezolana o extranjera.'
            messages.error(request, error_cedula)
        else:
            messages.error(request, 'Completa tu nombre, correo electrónico y mensaje.')
    return render(request, 'escuelaApp/portal_contact.html', {'info': info})


def portal_registro_rapido(request):
    info = InformacionEscuela.objects.first()
    if request.method == 'POST':
        form = SolicitudMatriculaForm(request.POST, request.FILES)
        if form.is_valid():
            solicitud = form.save(commit=False)
            solicitud.representante_cedula = form.cleaned_data['representante_cedula']
            solicitud.save()
            messages.success(request, 'La solicitud de matrícula fue enviada para revisión.')
            return redirect('portal_home')
    else:
        form = SolicitudMatriculaForm()
    return render(request, 'escuelaApp/portal_registro_rapido.html', {'form': form, 'info': info})
