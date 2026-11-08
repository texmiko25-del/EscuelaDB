from datetime import date, timedelta
from decimal import Decimal
import inspect
import json
import re
import time
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

from django.contrib.auth.models import User
from django.conf import settings
from django.core import mail
from django.core.management import call_command, CommandError
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from .models import (
    ComunicadoRepresentantes,
    ConstanciaCalificacion,
    DestinatarioAvisoCalificacion,
    Empleado,
    EntregaReporteSistema,
    EntregaComunicadoRepresentante,
    Estudiante,
    NotificacionCalificacion,
    Representante,
    ReporteSistemaDiario,
)

from .forms import AdminCrearUsuarioForm, AsignacionForm, RepresentanteForm, EstudianteForm, DocenteForm
from .forms_asistencia import AsistenciaForm
from .forms_login import LoginForm
from .forms_registro_academico import RegistroAcademicoForm
from .registro_academico import RegistroAcademico


class PortalAboutTests(TestCase):
    def test_pagina_sobre_nosotros_incluye_enlace_para_volver_al_portal(self):
        response = self.client.get(reverse('portal_about'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("portal_home")}"')
        self.assertContains(response, 'Volver al portal')


class StudentRegistrationNavigationTests(TestCase):
    def test_muestra_barras_de_navegacion_al_registrar_estudiante(self):
        from django.template.loader import render_to_string

        usuario = User.objects.create_user(
            username='directora-registro-nav',
            is_staff=True,
        )
        Empleado.objects.create(
            user=usuario,
            cedula='V-76543218',
            cargo='DIRECTORA',
        )
        factory = RequestFactory()

        solicitud_registro = factory.get(reverse('admin_crear_estudiante'))
        solicitud_registro.user = usuario
        solicitud_registro.resolver_match = resolve(reverse('admin_crear_estudiante'))
        pagina_registro = render_to_string(
            'escuelaApp/base.html',
            request=solicitud_registro,
        )

        self.assertIn('class="site-header"', pagina_registro)
        self.assertIn('id="sidebar"', pagina_registro)
        self.assertIn('sidebar-active', pagina_registro)

        solicitud_lista = factory.get(reverse('admin_estudiantes'))
        solicitud_lista.user = usuario
        solicitud_lista.resolver_match = resolve(reverse('admin_estudiantes'))
        pagina_lista = render_to_string(
            'escuelaApp/base.html',
            request=solicitud_lista,
        )

        self.assertIn('class="site-header"', pagina_lista)
        self.assertIn('id="sidebar"', pagina_lista)


class FilteredRegistrySearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='directora-busqueda-registros',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=self.user,
            cedula='V-99887766',
            cargo='DIRECTORA',
        )
        self.representante = Representante.objects.create(
            nombre='Ana',
            apellido='Pérez',
            cedula='V-12345678',
            email='ana@example.com',
        )
        Estudiante.objects.create(
            nombre='Luis',
            apellido='Pérez',
            cedula='V-22334455',
            grado='1RO',
            representante=self.representante,
        )
        from .models import Docente

        Docente.objects.create(
            nombre='Marta',
            apellido='Rojas',
            cedula='V-33445566',
            especialidad='Matemáticas',
        )
        self.client.force_login(self.user)

    def _assert_results_follow_filter(self, route, query, result):
        response = self.client.get(reverse(route), {'q': query})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="filter-results"')
        self.assertContains(response, result)
        html = response.content.decode()
        self.assertLess(html.index('name="q"'), html.index('id="filter-results"'))

    def _assert_paginated_results(self, route, query, second_page_name):
        first_page = self.client.get(reverse(route), {'q': query})
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.context['page_obj']), 5)
        self.assertContains(first_page, 'Página 1 de 2')
        self.assertContains(first_page, f'href="?page=2&q={query}"')

        second_page = self.client.get(reverse(route), {'q': query, 'page': 2})
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.context['page_obj']), 1)
        self.assertContains(second_page, second_page_name)
        self.assertContains(second_page, 'Página 2 de 2')

    def test_busqueda_por_cedula_de_representante_muestra_resultado_bajo_filtro(self):
        self._assert_results_follow_filter(
            'admin_representantes',
            '12345678',
            'Ana Pérez',
        )

    def test_busqueda_de_estudiante_muestra_resultado_bajo_filtro(self):
        self._assert_results_follow_filter(
            'admin_estudiantes',
            '22334455',
            'Luis Pérez',
        )

    def test_busqueda_dinamica_de_estudiante_incluye_su_representante(self):
        response = self.client.get(
            reverse('admin_estudiantes'),
            {'q': '22334455', 'format': 'json'},
        )

        self.assertEqual(response.status_code, 200)
        resultados = response.json()
        self.assertEqual(resultados['total'], 1)
        self.assertEqual(len(resultados['estudiantes']), 1)
        self.assertEqual(resultados['estudiantes'][0]['nombre'], 'Luis Pérez')
        self.assertEqual(
            resultados['estudiantes'][0]['representante'],
            'Ana Pérez',
        )

    def test_busqueda_dinamica_de_docente_devuelve_datos_de_lista(self):
        response = self.client.get(
            reverse('admin_docentes'),
            {'q': '33445566', 'format': 'json'},
        )

        self.assertEqual(response.status_code, 200)
        resultados = response.json()
        self.assertEqual(resultados['total'], 1)
        self.assertEqual(resultados['docentes'][0]['nombre'], 'Marta Rojas')
        self.assertEqual(
            resultados['docentes'][0]['especialidad'],
            'Matemáticas',
        )

    def test_listados_permiten_gestionar_registros_sin_cedula(self):
        from .models import Docente

        estudiante = Estudiante.objects.create(
            nombre='',
            apellido='',
            cedula=None,
            grado='',
            seccion='',
        )
        docente = Docente.objects.create(
            nombre='',
            apellido='',
            cedula=None,
        )
        representante = Representante.objects.create(
            nombre='',
            apellido='',
            cedula=None,
        )

        casos = (
            ('admin_estudiantes', 'admin_editar_estudiante_por_id', estudiante),
            ('admin_docentes', 'admin_editar_docente_por_id', docente),
            ('admin_representantes', 'admin_editar_representante_por_id', representante),
        )
        for listado, editar, registro in casos:
            with self.subTest(listado=listado):
                response = self.client.get(reverse(listado))
                self.assertEqual(response.status_code, 200)
                url_editar = reverse(editar, args=[registro.pk])
                self.assertContains(response, url_editar)
                self.assertEqual(self.client.get(url_editar).status_code, 200)

    def test_busqueda_dinamica_de_representante_devuelve_datos_de_lista(self):
        response = self.client.get(
            reverse('admin_representantes'),
            {'q': '12345678', 'format': 'json'},
        )

        self.assertEqual(response.status_code, 200)
        resultados = response.json()
        self.assertEqual(resultados['total'], 1)
        self.assertEqual(
            resultados['representantes'][0]['nombre'],
            'Ana Pérez',
        )
        self.assertEqual(
            resultados['representantes'][0]['email'],
            'ana@example.com',
        )

    def test_busquedas_de_registros_no_muestran_boton_filtrar(self):
        for ruta in (
            'admin_estudiantes',
            'admin_docentes',
            'admin_representantes',
        ):
            response = self.client.get(reverse(ruta))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'data-registry-search')
            self.assertContains(response, 'type="search"')
            self.assertNotContains(response, '>Filtrar</button>')

    def test_busqueda_de_docente_muestra_resultado_bajo_filtro(self):
        self._assert_results_follow_filter(
            'admin_docentes',
            '33445566',
            'Marta Rojas',
        )

    def test_lista_de_estudiantes_pagina_cada_cinco_resultados(self):
        for numero in range(2, 8):
            Estudiante.objects.create(
                nombre=f'Estudiante {numero}',
                apellido='Prueba',
                cedula=f'V-223344{numero:02d}',
                grado='1RO',
                representante=self.representante,
            )

        self._assert_paginated_results(
            'admin_estudiantes',
            'Prueba',
            'Estudiante 7 Prueba',
        )

    def test_lista_de_docentes_pagina_cada_cinco_resultados(self):
        from .models import Docente

        for numero in range(2, 8):
            Docente.objects.create(
                nombre=f'Docente {numero}',
                apellido='Prueba',
                cedula=f'V-334455{numero:02d}',
            )

        self._assert_paginated_results(
            'admin_docentes',
            'Prueba',
            'Docente 7 Prueba',
        )

    def test_lista_de_representantes_pagina_cada_cinco_resultados(self):
        for numero in range(2, 8):
            Representante.objects.create(
                nombre=f'Representante {numero}',
                apellido='Prueba',
                cedula=f'V-123456{numero:02d}',
            )

        self._assert_paginated_results(
            'admin_representantes',
            'Prueba',
            'Representante 7 Prueba',
        )


class DemoStudentsCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_comando_demo_rechaza_entornos_no_debug(self):
        with self.assertRaises(CommandError):
            call_command('crear_estudiantes_demo', '--confirmar-demo')

    @override_settings(DEBUG=True)
    def test_comando_crea_diez_estudiantes_y_representantes_demo_con_grado_y_seccion(self):
        call_command('crear_estudiantes_demo', '--confirmar-demo', stdout=StringIO())
        call_command('crear_estudiantes_demo', '--confirmar-demo', stdout=StringIO())

        estudiantes = Estudiante.objects.filter(nombre__startswith='DEMO Estudiante ')
        representantes = Representante.objects.filter(nombre__startswith='DEMO Representante ')
        self.assertEqual(estudiantes.count(), 10)
        self.assertEqual(representantes.count(), 10)
        self.assertTrue(all(estudiante.grado and estudiante.seccion for estudiante in estudiantes))
        self.assertEqual(set(estudiantes.values_list('grado', flat=True)), {
            '1RO', '2DO', '3RO', '4TO', '5TO', '6TO',
        })
        self.assertEqual(set(estudiantes.values_list('seccion', flat=True)), {'A', 'B', 'C'})
        self.assertTrue(all(
            representante.email.endswith('@example.invalid')
            for representante in representantes
        ))
        self.assertTrue(all(
            estudiante.cedula.startswith('DEMO-EST-')
            and estudiante.matricula.startswith('DEMO-MAT-')
            for estudiante in estudiantes
        ))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='recuperar-cuenta',
            email='usuario@gmail.com',
            password='Password123',
        )
        self.url = reverse('forgot_password')

    def _solicitar_codigo(self):
        response = self.client.post(self.url, {
            'action': 'send_code',
            'email_name': 'usuario',
            'email_domain': 'gmail.com',
            'email_custom_domain': '',
        })
        codigo = re.search(r'es ([A-Z0-9]{8})\.', mail.outbox[-1].body).group(1)
        self.assertRegex(codigo, r'[A-Z]')
        self.assertRegex(codigo, r'\d')
        return response, codigo

    def test_dominio_personalizado_es_obligatorio(self):
        from .forms_login import RecoveryEmailForm

        form = RecoveryEmailForm(data={
            'email_name': 'usuario',
            'email_domain': 'custom',
            'email_custom_domain': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('email_custom_domain', form.errors)

    def test_recuperacion_envia_codigo_verifica_y_actualiza_password(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Recuperación segura')
        response, codigo = self._solicitar_codigo()
        self.assertContains(response, 'Ingresa el código')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['usuario@gmail.com'])

        response = self.client.post(self.url, {'action': 'verify_code', 'code': codigo})
        self.assertContains(response, 'Nueva contraseña')
        session = self.client.session
        self.assertNotIn('password_reset_code_hash', session)

        response = self.client.post(self.url, {
            'action': 'verify_code',
            'code': codigo,
        })
        self.assertContains(response, 'Nueva contraseña')
        self.assertNotContains(response, 'Ingresa el código')

        response = self.client.post(self.url, {
            'action': 'reset_password',
            'password': 'weak',
            'confirm_password': 'weak',
        })
        self.assertContains(response, 'al menos 8 caracteres')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Password123'))

        response = self.client.post(self.url, {
            'action': 'reset_password',
            'password': 'NewPassword456',
            'confirm_password': 'NewPassword456',
        })
        self.assertContains(response, 'Contraseña actualizada')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPassword456'))
        self.assertFalse(self.user.check_password('Password123'))
        self.assertNotIn('password_reset_stage', self.client.session)

    def test_codigo_deja_de_servir_si_el_correo_se_desafilia_de_la_cuenta(self):
        _, codigo = self._solicitar_codigo()
        self.user.email = 'otro@gmail.com'
        self.user.save(update_fields=['email'])

        response = self.client.post(self.url, {'action': 'verify_code', 'code': codigo})

        self.assertContains(response, 'El código no es correcto')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Password123'))

    def test_codigo_expirado_habilita_reenvio_y_codigo_nuevo_funciona(self):
        self._solicitar_codigo()
        session = self.client.session
        session['password_reset_code_expires_at'] = time.time() - 1
        session.save()

        response = self.client.post(self.url, {'action': 'verify_code', 'code': 'AB12CD34'})
        contenido = response.content.decode()
        self.assertIn('El código venció', contenido)
        self.assertIn('id="verify-code-button" type="submit" disabled', contenido)
        self.assertIn('id="resend-code-button" type="submit" >Reenviar código', contenido)

        response = self.client.post(self.url, {'action': 'resend_code'})
        self.assertContains(response, 'Ingresa el código')
        self.assertEqual(len(mail.outbox), 2)
        nuevo_codigo = re.search(r'es ([A-Z0-9]{8})\.', mail.outbox[-1].body).group(1)
        response = self.client.post(self.url, {'action': 'verify_code', 'code': nuevo_codigo})
        self.assertContains(response, 'Crea una contraseña')

    def test_expiracion_del_cambio_reinicia_en_correo_y_no_cambia_clave(self):
        _, codigo = self._solicitar_codigo()
        self.client.post(self.url, {'action': 'verify_code', 'code': codigo})
        session = self.client.session
        session['password_reset_verified_expires_at'] = time.time() - 1
        session.save()

        response = self.client.post(self.url, {
            'action': 'reset_password',
            'password': 'NewPassword456',
            'confirm_password': 'NewPassword456',
        })
        self.assertContains(response, 'Ingresa tu correo para comenzar de nuevo')
        self.assertContains(response, 'Correo electrónico')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Password123'))

    def test_acceso_directo_al_enlace_reinicia_siempre_en_correo(self):
        self._solicitar_codigo()
        response = self.client.get(self.url)
        self.assertContains(response, 'Recupera tu acceso')
        self.assertNotContains(response, 'Ingresa el código')
        self.assertNotIn('password_reset_stage', self.client.session)


@override_settings(SYSTEM_NOTIFICATION_EMAIL='')
class ConstanciasCalificacionTests(TestCase):
    def setUp(self):
        self.directora_user = User.objects.create_superuser(
            username='directora-constancias',
            email='directora@example.com',
            password='PasswordSegura123!',
            first_name='Ana',
            last_name='Directora',
        )
        self.directora = Empleado.objects.create(
            user=self.directora_user,
            cedula='V-12345678',
            cargo='DIRECTORA',
            telefono='04121234567',
            acepta_notificaciones_whatsapp=True,
        )
        self.estudiante = Estudiante.objects.create(
            nombre='Luis', apellido='Pérez', cedula='V-88776655', grado='4TO'
        )
        self.registro = RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Lengua',
            periodo='2026-2027',
            nota='C',
            porcentaje=Decimal('55.00'),
            tipo_evaluacion='Parcial',
            estado='Reprobado',
        )
        self.client.force_login(self.directora_user)

    def test_pdf_contiene_constancia_y_resumen_critico_de_tres_fuentes(self):
        from .constancias import construir_pdf_constancia
        from .models import Asistencia, ResumenAsistenciaLapso

        for dias in range(3):
            Asistencia.objects.create(
                estudiante=self.estudiante,
                fecha=date.today() - timedelta(days=dias),
                estado='AUSENTE',
            )

        contenido, resumen = construir_pdf_constancia(self.registro)

        self.assertTrue(contenido.startswith(b'%PDF'))
        self.assertEqual(resumen['asistencia']['ausencias'], 3)
        self.assertEqual(resumen['calificaciones']['bajas'], 1)
        self.assertEqual(resumen['nivel'], 'CRÍTICO')

    def test_constancia_se_guarda_y_avisa_por_correo_y_whatsapp(self):
        from .constancias import generar_constancia_y_notificar

        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo') as correo:
                with patch('escuelaApp.constancias._enviar_whatsapp') as whatsapp:
                    constancia, resultados, _ = generar_constancia_y_notificar(self.registro)

        self.assertTrue(constancia.archivo.name.endswith('.pdf'))
        self.assertEqual({resultado[1] for resultado in resultados}, {'EMAIL', 'WHATSAPP'})
        self.assertTrue(all(resultado[3] == 'ENVIADO' for resultado in resultados))
        self.assertEqual(NotificacionCalificacion.objects.filter(estado='ENVIADO').count(), 2)
        correo.assert_called_once()
        whatsapp.assert_called_once()

    def test_adaptador_smtp_adjunta_el_pdf(self):
        from .constancias import _enviar_correo

        archivo = MagicMock()
        archivo.name = 'constancias/calificacion.pdf'
        archivo.open.return_value = BytesIO(b'%PDF-test')
        constancia = SimpleNamespace(archivo=archivo)
        with override_settings(
            EMAIL_HOST_USER='hectorluis.pc25@gmail.com',
            EMAIL_HOST_PASSWORD='local-test-password',
            DEFAULT_FROM_EMAIL='hectorluis.pc25@gmail.com',
        ):
            with patch('escuelaApp.constancias.EmailMessage') as email_class:
                email_class.return_value.send.return_value = 1
                _enviar_correo('directora@example.com', 'Nota cargada', 'Aviso', constancia)

        email_class.assert_called_once_with(
            'Nota cargada', 'Aviso', 'hectorluis.pc25@gmail.com', ['directora@example.com']
        )
        email_class.return_value.attach.assert_called_once_with(
            'calificacion.pdf', b'%PDF-test', 'application/pdf'
        )

    @override_settings(SYSTEM_NOTIFICATION_EMAIL='hectorluis.pc25@gmail.com')
    def test_envia_aviso_al_correo_institucional_configurado(self):
        from .constancias import generar_constancia_y_notificar

        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo') as enviar_correo:
                with patch('escuelaApp.constancias._enviar_whatsapp'):
                    _, resultados, _ = generar_constancia_y_notificar(self.registro)

        correo = 'hectorluis.pc25@gmail.com'
        self.assertTrue(any(resultado[1:3] == ('EMAIL', correo) for resultado in resultados))
        self.assertTrue(any(call.args[0] == correo for call in enviar_correo.call_args_list))

    def test_adaptador_twilio_usa_plantilla_aprobada(self):
        from .constancias import _enviar_whatsapp

        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'sid': 'SM123'}).encode('utf-8')
        environment = {
            'TWILIO_ACCOUNT_SID': 'AC123',
            'TWILIO_AUTH_TOKEN': 'auth-token',
            'TWILIO_WHATSAPP_FROM': 'whatsapp:+14155238886',
            'TWILIO_WHATSAPP_CONTENT_SID': 'HX123',
        }
        with patch.dict('os.environ', environment):
            with patch('escuelaApp.constancias.urlopen', return_value=response) as solicitar:
                _enviar_whatsapp('+584121234567', 'Nota cargada')

        payload = parse_qs(solicitar.call_args.args[0].data.decode('utf-8'))
        self.assertEqual(payload['ContentSid'], ['HX123'])
        self.assertEqual(payload['To'], ['whatsapp:+584121234567'])
        self.assertEqual(json.loads(payload['ContentVariables'][0]), {'1': 'Nota cargada'})

    def test_no_envia_whatsapp_sin_consentimiento(self):
        from .constancias import generar_constancia_y_notificar

        self.directora.acepta_notificaciones_whatsapp = False
        self.directora.save(update_fields=['acepta_notificaciones_whatsapp'])
        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo'):
                with patch('escuelaApp.constancias._enviar_whatsapp') as whatsapp:
                    _, resultados, _ = generar_constancia_y_notificar(self.registro)

        whatsapp.assert_not_called()
        self.assertEqual([resultado[1] for resultado in resultados], ['EMAIL'])

    def test_envia_a_destinatario_adicional_activo(self):
        from .constancias import generar_constancia_y_notificar

        correo = 'hectorluis.pc25@gmail.com'
        DestinatarioAvisoCalificacion.objects.create(correo=correo)
        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo') as enviar_correo:
                with patch('escuelaApp.constancias._enviar_whatsapp'):
                    _, resultados, _ = generar_constancia_y_notificar(self.registro)

        self.assertTrue(any(resultado[1:3] == ('EMAIL', correo) for resultado in resultados))
        self.assertTrue(any(call.args[0] == correo for call in enviar_correo.call_args_list))
        self.assertTrue(NotificacionCalificacion.objects.filter(destinatario=correo).exists())

    def test_constancia_llega_solo_al_representante_asociado(self):
        from .constancias import generar_constancia_y_notificar

        representante_asociado = Representante.objects.create(
            nombre='Marta', apellido='Pérez', cedula='V-23456789',
            email='madre@example.com',
        )
        representante_ajeno = Representante.objects.create(
            nombre='Luis', apellido='Rojas', cedula='V-34567890',
            email='otro@example.com',
        )
        self.estudiante.representante = representante_asociado
        self.estudiante.save(update_fields=['representante'])

        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo') as enviar_correo:
                with patch('escuelaApp.constancias._enviar_whatsapp'):
                    generar_constancia_y_notificar(self.registro)

        correos = [call.args[0] for call in enviar_correo.call_args_list]
        self.assertIn('madre@example.com', correos)
        self.assertNotIn('otro@example.com', correos)

    def test_fallo_del_proveedor_se_registra_sin_perder_la_calificacion(self):
        from .constancias import generar_constancia_y_notificar

        with patch('escuelaApp.models.PrivateDocumentsStorage.save', return_value='constancia.pdf'):
            with patch('escuelaApp.constancias._enviar_correo', side_effect=OSError('SMTP no disponible')):
                constancia, resultados, _ = generar_constancia_y_notificar(self.registro)

        self.registro.refresh_from_db()
        self.assertEqual(self.registro.porcentaje, Decimal('55.00'))
        self.assertTrue(constancia.archivo.name)
        self.assertTrue(any(resultado[3] == 'ERROR' for resultado in resultados))
        self.assertTrue(NotificacionCalificacion.objects.filter(estado='ERROR').exists())

    def test_vista_crea_nota_y_llama_al_generador_de_constancia(self):
        from .models import Docente, Horario

        profesor_user = User.objects.create_user(
            username='profesor-constancia',
            password='PasswordSegura123!',
        )
        profesor = Empleado.objects.create(
            user=profesor_user,
            cedula='V-87654321',
            cargo='DOCENTE',
        )
        docente = Docente.objects.create(
            nombre='Profesor',
            apellido='Constancia',
            cedula=profesor.cedula,
        )
        Horario.objects.create(
            ano='4ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        with patch(
            'escuelaApp.views_registro_academico.generar_constancia_y_notificar',
            return_value=(None, [], None),
        ) as generar:
            respuesta = self.client.post(reverse('admin_crear_registro_academico'), {
                'estudiante_cedula': str(self.estudiante.pk),
                'docente_cedula': f'emp:{profesor.pk}',
                'area': 'Matemáticas',
                'periodo': '2026-2027',
                'lapso': 'LAPSO_1',
                'tipo_evaluacion': 'Parcial',
                'nota': 'B',
                'estado': 'Aprobado',
            })

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta['Location'], reverse('admin_registro_academico'))
        self.assertEqual(RegistroAcademico.objects.filter(estudiante=self.estudiante).count(), 2)
        generar.assert_called_once()


class ComunicadosRepresentantesTests(TestCase):
    def setUp(self):
        self.representantes = [
            Representante.objects.create(
                nombre='Ana', apellido='Pérez', cedula='V-45678901', email='ana@example.com'
            ),
            Representante.objects.create(
                nombre='Luis', apellido='Rojas', cedula='V-56789012', email='luis@example.com'
            ),
        ]
        self.usuario = User.objects.create_superuser(
            username='directora-comunicados',
            email='directora-comunicados@example.com',
            password='PasswordSegura123!',
        )

    def test_envia_un_correo_independiente_a_cada_representante(self):
        from .comunicados import enviar_comunicado_representantes

        with override_settings(
            EMAIL_HOST_USER='remitente@example.com',
            EMAIL_HOST_PASSWORD='test-secret',
            DEFAULT_FROM_EMAIL='remitente@example.com',
        ):
            with patch('escuelaApp.comunicados.send_mail', return_value=1) as enviar:
                comunicado, entregas = enviar_comunicado_representantes(
                    'Reunión escolar', 'La reunión será el viernes.', self.representantes, self.usuario
                )

        self.assertEqual(comunicado.entregas.count(), 2)
        self.assertEqual(len(entregas), 2)
        self.assertEqual(enviar.call_count, 2)
        destinos = [call.args[3] for call in enviar.call_args_list]
        self.assertEqual(destinos, [['ana@example.com'], ['luis@example.com']])
        self.assertTrue(all(len(destino) == 1 for destino in destinos))
        self.assertEqual(EntregaComunicadoRepresentante.objects.filter(estado='ENVIADO').count(), 2)

    def test_envia_comunicado_a_representantes_y_docentes_individualmente(self):
        from .comunicados import enviar_comunicado_representantes

        usuario_docente = User.objects.create_user(
            username='docente-comunicado', email='docente@example.com', is_active=True
        )
        docente = Empleado.objects.create(
            user=usuario_docente, cedula='V-87654321', cargo='DOCENTE'
        )
        with override_settings(
            EMAIL_HOST_USER='remitente@example.com',
            EMAIL_HOST_PASSWORD='test-secret',
            DEFAULT_FROM_EMAIL='remitente@example.com',
        ):
            with patch('escuelaApp.comunicados.send_mail', return_value=1) as enviar:
                _, entregas = enviar_comunicado_representantes(
                    'Cambio de horario', 'El horario fue actualizado.',
                    self.representantes, self.usuario, docentes=[docente],
                )

        destinos = [llamada.args[3] for llamada in enviar.call_args_list]
        self.assertEqual(destinos, [
            ['ana@example.com'], ['luis@example.com'], ['docente@example.com'],
        ])
        self.assertEqual(len(entregas), 3)
        entrega_docente = EntregaComunicadoRepresentante.objects.get(correo='docente@example.com')
        self.assertIsNone(entrega_docente.representante)
        self.assertEqual(entrega_docente.estado, 'ENVIADO')

    def test_interfaz_directiva_acepta_representantes_y_docentes(self):
        from types import SimpleNamespace

        docente_user = User.objects.create_user(
            username='profesor-interfaz-comunicado', email='profesor@example.com'
        )
        docente = Empleado.objects.create(
            user=docente_user, cedula='V-87654322', cargo='PROFESOR'
        )
        from django.contrib.messages.storage.fallback import FallbackStorage

        path = reverse('comunicados_representantes')
        request = RequestFactory().get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'directora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        pagina = resolve(path).func(request)
        self.assertContains(pagina, 'Comunicados a representantes y docentes')
        self.assertContains(pagina, 'Docentes y profesores')
        self.client.force_login(self.usuario)
        with patch(
            'escuelaApp.views_comunicados.enviar_comunicado_representantes',
            return_value=(SimpleNamespace(pk=12), [SimpleNamespace(estado='ENVIADO')]),
        ) as enviar:
            respuesta = self.client.post(reverse('comunicados_representantes'), {
                'asunto': 'Cambio de horario',
                'mensaje': 'El horario fue actualizado.',
                'representantes': [str(self.representantes[0].pk)],
                'docentes': [str(docente.pk)],
            })

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta['Location'], reverse('comunicados_representantes'))
        self.assertEqual(enviar.call_args.args[0:2], ('Cambio de horario', 'El horario fue actualizado.'))
        self.assertEqual(list(enviar.call_args.args[2]), [self.representantes[0]])
        self.assertEqual(enviar.call_args.kwargs['docentes'].get(), docente)

    def test_comunicado_no_se_guarda_si_smtp_no_esta_configurado(self):
        from .comunicados import enviar_comunicado_representantes

        with override_settings(EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD=''):
            with self.assertRaises(RuntimeError):
                enviar_comunicado_representantes(
                    'Aviso', 'Mensaje general', self.representantes, self.usuario
                )

        self.assertEqual(ComunicadoRepresentantes.objects.count(), 0)


@override_settings(SYSTEM_NOTIFICATION_EMAIL='')
class ReportesSistemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin-reporte-sistema',
            email='admin-reportes@example.com',
            password='PasswordSegura123!',
        )
        self.client.force_login(self.user)
        self.estudiante = Estudiante.objects.create(
            nombre='Rosa', apellido='Mora', cedula='V-67890123', grado='5TO'
        )

    def test_filtros_reporte_validan_rangos_y_aceptan_valores(self):
        from .forms_reportes import FiltrosReporteSistemaForm

        form = FiltrosReporteSistemaForm(data={
            'grado': '5TO',
            'fecha_desde': '2026-01-01',
            'fecha_hasta': '2026-12-31',
            'porcentaje_min': '40',
            'porcentaje_max': '80',
        })
        self.assertTrue(form.is_valid(), form.errors)

        form_invalido = FiltrosReporteSistemaForm(data={
            'fecha_desde': '2026-12-31',
            'fecha_hasta': '2026-01-01',
            'porcentaje_min': '90',
            'porcentaje_max': '40',
        })
        self.assertFalse(form_invalido.is_valid())
        self.assertTrue(form_invalido.non_field_errors())

    def test_cinco_tipos_de_reporte_generan_datos_con_propositos_distintos(self):
        from .models import Asistencia, ResumenAsistenciaLapso
        from .reportes_sistema import datos_reporte_interactivo

        RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Matemáticas',
            periodo='2026-2027',
            nota='B',
            porcentaje=Decimal('82.00'),
        )
        Asistencia.objects.create(
            estudiante=self.estudiante,
            fecha=date.today(),
            estado='AUSENTE',
        )
        filtros = {
            'grado': '5TO',
            'periodo': '2026-2027',
            'area': 'Matemáticas',
            'fecha_desde': date.today() - timedelta(days=2),
            'fecha_hasta': date.today(),
            'porcentaje_min': Decimal('80'),
            'porcentaje_max': Decimal('90'),
        }

        detalle = datos_reporte_interactivo('detalle', filtros)
        resumen = datos_reporte_interactivo('resumen', filtros)
        con_filtros = datos_reporte_interactivo('filtros', filtros)
        historico = datos_reporte_interactivo('historico', filtros)
        estadistico = datos_reporte_interactivo('estadistico', filtros)

        self.assertEqual(detalle['total_resultados'], 1)
        self.assertEqual(detalle['estudiantes'][0]['estudiante'], self.estudiante)
        self.assertEqual(detalle['estudiantes'][0]['registros'], 1)
        self.assertIn({'etiqueta': 'Calificaciones bajo 60%', 'valor': 0}, resumen['indicadores'])
        self.assertEqual(con_filtros['registros'][0].area, 'Matemáticas')
        self.assertEqual(historico['meses'][-1]['registros'], 1)
        self.assertEqual(estadistico['total_resultados'], 1)
        self.assertEqual(estadistico['distribucion'][1]['etiqueta'], 'B')
        self.assertEqual(estadistico['distribucion'][1]['cantidad'], 1)

    def test_filtros_multiples_exportan_excel_con_estilo_institucional(self):
        from openpyxl import load_workbook

        from .views_reportes_sistema import historial_reportes_sistema

        RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Matemáticas',
            periodo='2026-2027',
            nota='A',
            porcentaje=Decimal('95.00'),
        )
        path = reverse('historial_reportes_sistema')
        request = RequestFactory().get(path, {
            'tipo': 'filtros',
            'grado': '5TO',
            'periodo': '2026-2027',
            'area': 'Matemáticas',
            'porcentaje_min': '90',
            'porcentaje_max': '100',
            'exportar': 'xlsx',
        })
        request.user = self.user
        request.session = {'staff_session_token': 'reportes-csv-test'}

        respuesta = historial_reportes_sistema(request)
        libro = load_workbook(BytesIO(respuesta.content))
        hoja = libro['Reporte']

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('attachment; filename="reporte-filtros.xlsx"', respuesta['Content-Disposition'])
        self.assertIn('E.B. Elba Rosa de Acevedo', hoja['B1'].value)
        self.assertEqual(hoja['A11'].value, 'Estudiante')
        self.assertEqual(hoja['A12'].value, 'Rosa Mora')
        self.assertIn('ReporteFiltros', hoja.tables)
        self.assertEqual(len(hoja._images), 1)

    def test_reporte_estadistico_excel_incluye_grafico(self):
        from openpyxl import load_workbook

        from .views_reportes_sistema import historial_reportes_sistema

        RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Matemáticas',
            periodo='2026-2027',
            nota='A',
            porcentaje=Decimal('95.00'),
        )
        path = reverse('historial_reportes_sistema')
        request = RequestFactory().get(path, {'tipo': 'estadistico', 'exportar': 'xlsx'})
        request.user = self.user
        request.session = {'staff_session_token': 'reporte-estadistico-test'}

        respuesta = historial_reportes_sistema(request)
        libro = load_workbook(BytesIO(respuesta.content))

        self.assertEqual(len(libro['Reporte']._charts), 1)

    def test_archivo_generado_se_envia_al_correo_de_la_directora_activa(self):
        from .report_delivery import enviar_reporte_a_directora

        directora = User.objects.create_user(
            username='directora-correo-reportes',
            email='directora@example.com',
            is_staff=True,
        )
        Empleado.objects.create(user=directora, cedula='V-76543213', cargo='DIRECTORA')
        subdirectora = User.objects.create_user(
            username='subdirectora-no-destino',
            email='subdirectora@example.com',
            is_staff=True,
        )
        Empleado.objects.create(user=subdirectora, cedula='V-76543214', cargo='SUBDIRECTORA')

        with override_settings(
            EMAIL_HOST_USER='remitente@example.com',
            EMAIL_HOST_PASSWORD='test-secret',
            DEFAULT_FROM_EMAIL='remitente@example.com',
        ):
            with patch('escuelaApp.report_delivery.EmailMessage') as email_class:
                email_class.return_value.send.return_value = 1
                enviado = enviar_reporte_a_directora(
                    'reporte-prueba.pdf', b'%PDF-prueba', 'application/pdf'
                )

        self.assertTrue(enviado)
        email_class.assert_called_once_with(
            'Reporte generado: reporte-prueba.pdf',
            'Se adjunta el reporte generado desde el sistema escolar.',
            'remitente@example.com',
            ['directora@example.com'],
        )
        email_class.return_value.attach.assert_called_once_with(
            'reporte-prueba.pdf', b'%PDF-prueba', 'application/pdf'
        )

    def test_reporte_critico_cruza_las_tres_tablas_en_30_dias(self):
        from .models import Asistencia
        from .reportes_sistema import _datos_reporte

        hoy = date.today()
        for dias in range(3):
            Asistencia.objects.create(
                estudiante=self.estudiante,
                fecha=hoy - timedelta(days=dias),
                estado='AUSENTE',
            )
        RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Matemáticas',
            periodo='2026-2027',
            nota='F',
            porcentaje=Decimal('45.00'),
        )

        datos = _datos_reporte(hoy)

        self.assertEqual(datos['estudiantes'], 1)
        self.assertEqual(datos['ausencias'], 3)
        self.assertEqual(datos['calificaciones_bajas'], 1)
        self.assertEqual(len(datos['estudiantes_criticos']), 1)
        self.assertIn('Estudiantes en situación crítica: 1', datos['resumen'])

    def test_reporte_pdf_y_entrega_diaria_no_se_duplican(self):
        from .reportes_sistema import enviar_reporte_diario

        DestinatarioAvisoCalificacion.objects.create(correo='reporte@example.com')
        fecha = date.today()
        with patch('escuelaApp.reportes_sistema._enviar_reporte') as enviar:
            reporte, primer_resultado = enviar_reporte_diario(fecha)
            mismo_reporte, segundo_resultado = enviar_reporte_diario(fecha)

        self.assertTrue(reporte.archivo.name.endswith('.pdf'))
        self.assertEqual(reporte.pk, mismo_reporte.pk)
        self.assertEqual(ReporteSistemaDiario.objects.count(), 1)
        self.assertEqual(primer_resultado['enviados'], 2)
        self.assertEqual(segundo_resultado['enviados'], 0)
        self.assertEqual(enviar.call_count, 2)
        self.assertEqual(EntregaReporteSistema.objects.filter(estado='ENVIADO').count(), 2)

    @override_settings(SYSTEM_NOTIFICATION_EMAIL='hectorluis.pc25@gmail.com')
    def test_reporte_diario_incluye_correo_institucional(self):
        from .reportes_sistema import enviar_reporte_diario

        with patch('escuelaApp.reportes_sistema._enviar_reporte') as enviar:
            _, resultado = enviar_reporte_diario(date.today())

        self.assertEqual(resultado['destinos'], 2)
        self.assertTrue(any(
            llamada.args[:2] == ('EMAIL', 'hectorluis.pc25@gmail.com')
            for llamada in enviar.call_args_list
        ))

    def test_historial_restringido_a_personal_directivo(self):
        from django.contrib.messages.storage.fallback import FallbackStorage

        from .views_reportes_sistema import historial_reportes_sistema

        path = reverse('historial_reportes_sistema')
        request = RequestFactory().get(path)
        request.user = self.user
        request.session = {'staff_session_token': 'reportes-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        respuesta = historial_reportes_sistema(request)

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.content.decode()
        for nombre in ('Detalle', 'Resumen', 'Filtros múltiples', 'Histórico', 'Estadístico / gráfico'):
            with self.subTest(reporte=nombre):
                self.assertIn(nombre, contenido)

    def test_reportes_sistema_restringidos_a_roles_directivos(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.shortcuts import resolve_url

        from .views_reportes_sistema import historial_reportes_sistema

        coordinador = User.objects.create_user(
            username='coordinador-sin-reportes', is_staff=True
        )
        Empleado.objects.create(
            user=coordinador, cedula='V-76543212', cargo='COORD'
        )
        path = reverse('historial_reportes_sistema')
        request = RequestFactory().get(path)
        request.user = coordinador
        request.session = {'staff_session_token': 'coordinador-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)

        respuesta = historial_reportes_sistema(request)

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, resolve_url('admin_panel'))

class ValidacionFormsTests(TestCase):
    def test_generar_password_segura_cumple_requisitos(self):
        from .forms import generate_secure_password

        password = generate_secure_password()

        self.assertGreaterEqual(len(password), 12)
        self.assertRegex(password, r'[A-Z]')
        self.assertRegex(password, r'[a-z]')
        self.assertRegex(password, r'\d')

    def test_representante_acepta_vacios_en_datos_opcionales(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'tipo_identificacion': 'V',
            'cedula': '12345678',
            'telefono': '',
            'email': '',
            'ocupacion': '',
            'parentesco': '',
            'estado_civil': '',
            'nacionalidad': '',
            'partida_nacimiento': '',
            'ubicacion': '',
        })

        self.assertTrue(form.is_valid(), form.errors)

    def test_representante_acepta_datos_basicos_vacios_y_cedulas_repetidas_nulas(self):
        for _ in range(2):
            form = RepresentanteForm(data={
                'nombre': '',
                'apellido': '',
                'tipo_identificacion': '',
                'cedula': '',
            })
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.save().cedula)

    def test_estudiante_acepta_vacios_en_datos_opcionales(self):
        representante = Representante.objects.create(
            nombre='Luis',
            apellido='Pérez',
            cedula='V-12345678',
        )
        form = EstudianteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'cedula': '',
            'fecha_nacimiento': '',
            'sexo': '',
            'nacionalidad': '',
            'grado': '4TO',
            'seccion': 'A',
            'telefono': '',
            'ubicacion': '',
            'representante': representante.pk,
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['sexo'], 'O')
        self.assertEqual(form.cleaned_data['nacionalidad'], 'No especificada')

    def test_estudiante_acepta_datos_basicos_vacios_y_cedulas_repetidas_nulas(self):
        for _ in range(2):
            form = EstudianteForm(data={
                'nombre': '',
                'apellido': '',
                'cedula': '',
                'fecha_nacimiento': '',
                'sexo': '',
                'nacionalidad': '',
                'grado': '',
                'seccion': '',
                'telefono': '',
                'ubicacion': '',
                'representante': '',
            })
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.save().cedula)

    def test_docente_acepta_vacios_en_datos_opcionales(self):
        form = DocenteForm(data={
            'nombre': 'Carlos',
            'apellido': 'Mendoza',
            'tipo_identificacion': 'V',
            'cedula': '12345678',
            'telefono': '',
            'especialidad': '',
            'carga_horaria': '',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['carga_horaria'], 0)

    def test_docente_acepta_datos_basicos_vacios_y_cedulas_repetidas_nulas(self):
        for _ in range(2):
            form = DocenteForm(data={
                'nombre': '',
                'apellido': '',
                'tipo_identificacion': '',
                'cedula': '',
                'telefono': '',
                'especialidad': '',
                'carga_horaria': '',
            })
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.save().cedula)

    def test_representante_form_incluye_datos_adicionales(self):
        form = RepresentanteForm()

        self.assertIn('email', form.fields)
        self.assertIn('ocupacion', form.fields)
        self.assertIn('parentesco', form.fields)
        self.assertIn('estado_civil', form.fields)
        self.assertIn('nacionalidad', form.fields)

    def test_representante_form_permite_cedula_venezolana_o_extranjera(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'tipo_identificacion': 'E',
            'cedula': '12345678',
            'telefono': '04121234567',
            'email': 'ana@example.com',
            'ocupacion': 'Abogada',
            'parentesco': 'Madre',
            'estado_civil': 'CASADO',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '12345',
            'ubicacion': 'Caracas',
            'es_tutor_legal': True,
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['cedula'], 'E-12345678')
        representante = form.save()
        form_edicion = RepresentanteForm(instance=representante)
        self.assertEqual(form_edicion['tipo_identificacion'].value(), 'E')

    def test_representante_form_rechaza_cedula_y_telefono_invalidos(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'cedula': 'abc123',
            'telefono': 'abc-123',
            'partida_nacimiento': '12345',
            'ubicacion': 'Caracas',
            'es_tutor_legal': True,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('cedula', form.errors)
        self.assertIn('telefono', form.errors)

    def test_estudiante_form_rechaza_datos_incorrectos(self):
        form = EstudianteForm(data={
            'nombre': 'Ana1',
            'apellido': 'García',
            'cedula': '12345678',
            'grado': '4TO',
            'partida_nacimiento': '12345',
            'telefono': 'telefono',
            'ubicacion': 'Caracas',
            'representante': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('nombre', form.errors)
        self.assertIn('telefono', form.errors)

    def test_estudiante_form_acepta_grado_y_seccion_vacios(self):
        datos = {
            'nombre': 'Ana',
            'apellido': 'García',
            'cedula': 'V-12345678',
            'fecha_nacimiento': '2015-06-15',
            'sexo': 'F',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '12345',
            'telefono': '04141234567',
            'ubicacion': 'Caracas',
            'representante': '',
        }

        for campo in ('grado', 'seccion'):
            with self.subTest(campo=campo):
                form = EstudianteForm(data={**datos, campo: ''})
                self.assertTrue(form.is_valid(), form.errors)

    def test_estudiante_form_permite_cedula_venezolana_o_extranjera(self):
        form = EstudianteForm(data={
            'nombre': 'Ana',
            'apellido': 'García',
            'cedula': 'E-123456789',
            'grado': '4TO',
            'seccion': 'A',
            'fecha_nacimiento': '2015-06-15',
            'sexo': 'F',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '12345',
            'telefono': '04141234567',
            'ubicacion': 'Caracas',
            'representante': '',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['cedula'], 'E-123456789')

    def test_estudiante_form_rechaza_fecha_nacimiento_futura(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        form = EstudianteForm(data={
            'nombre': 'Ana',
            'apellido': 'García',
            'cedula': 'V-12345678',
            'grado': '4TO',
            'seccion': 'A',
            'fecha_nacimiento': tomorrow,
            'sexo': 'F',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '12345',
            'telefono': '04141234567',
            'ubicacion': 'Caracas',
            'representante': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_nacimiento', form.errors)

    def test_estudiante_form_generates_cedula_escolar_and_matricula_independiente(self):
        representante = Representante.objects.create(
            nombre='Luis',
            apellido='Pérez',
            cedula='V-12345678',
            telefono='04141234567',
            ubicacion='Caracas',
            es_tutor_legal=True,
        )

        form = EstudianteForm(data={
            'nombre': 'María',
            'apellido': 'Pérez',
            'cedula': 'V-87654321',
            'grado': '5TO',
            'seccion': 'B',
            'fecha_nacimiento': '2014-05-10',
            'sexo': 'F',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '54321',
            'telefono': '04141234568',
            'ubicacion': 'Caracas',
            'representante': representante.pk,
        })

        self.assertTrue(form.is_valid(), form.errors)
        estudiante = form.save()
        self.assertEqual(estudiante.cedula, '12345678001')
        self.assertEqual(estudiante.matricula, 'MAT-001')
        self.assertEqual(estudiante.seccion, 'B')

    def test_representante_form_permite_telefono_celular_venezolano(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'cedula': '12345678',
            'telefono': '04141234567',
            'email': 'ana@example.com',
            'ocupacion': 'Abogada',
            'parentesco': 'Madre',
            'estado_civil': 'CASADO',
            'nacionalidad': 'Venezolana',
            'partida_nacimiento': '12345',
            'ubicacion': 'Caracas',
            'es_tutor_legal': True,
        })

        self.assertTrue(form.is_valid(), form.errors)

    def test_representante_form_rechaza_telefono_con_prefijo_no_venezolano(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'cedula': '12345678',
            'telefono': '02121234567',
            'partida_nacimiento': '12345',
            'ubicacion': 'Caracas',
            'es_tutor_legal': True,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('telefono', form.errors)

    def test_representante_form_rechaza_telefono_con_simbolos(self):
        form = RepresentanteForm(data={
            'nombre': 'Ana',
            'apellido': 'Pérez',
            'cedula': '12345678',
            'telefono': '0212-1234567',
            'partida_nacimiento': '12345',
            'ubicacion': 'Caracas',
            'es_tutor_legal': True,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('telefono', form.errors)

    def test_docente_form_rechaza_especialidad_con_numeros(self):
        form = DocenteForm(data={
            'nombre': 'Carlos',
            'apellido': 'Mendoza',
            'cedula': '12345678',
            'especialidad': 'Matemáticas 2',
            'carga_horaria': '20',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('especialidad', form.errors)

    def test_admin_crear_usuario_permite_cedula_venezolana_o_extranjera(self):
        form = AdminCrearUsuarioForm(data={
            'email': 'nuevo_extranjero@example.com',
            'username': 'AnaRojas24',
            'first_name': 'Ana',
            'last_name': 'Rojas',
            'cedula': 'E-12345678',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, 'AnaRojas24')
        self.assertEqual(user.empleado.cedula, 'E-12345678')

    def test_admin_crear_usuario_acepta_limites_de_cedula_por_nacionalidad(self):
        casos_validos = (
            ('V-1234567', 'V'),
            ('V-12345678', 'V'),
            ('E-123456', 'E'),
            ('E-123456789', 'E'),
        )
        for index, (cedula, tipo) in enumerate(casos_validos):
            with self.subTest(cedula=cedula):
                form = AdminCrearUsuarioForm(data={
                    'email': f'valida{index}@example.com',
                    'username': f'CuentaValida{index}',
                    'first_name': 'Ana',
                    'last_name': 'Rojas',
                    'tipo_identificacion': tipo,
                    'cedula': cedula,
                    'password': 'Password123',
                    'confirm_password': 'Password123',
                    'cargo': 'ASISTENTE',
                })

                self.assertTrue(form.is_valid(), form.errors)

    def test_admin_crear_usuario_rechaza_cedulas_fuera_de_limites(self):
        casos_invalidos = (
            ('V-123456', 'V'),
            ('V-123456789', 'V'),
            ('E-12345', 'E'),
            ('E-1234567890', 'E'),
        )
        for index, (cedula, tipo) in enumerate(casos_invalidos):
            with self.subTest(cedula=cedula):
                form = AdminCrearUsuarioForm(data={
                    'email': f'invalida{index}@example.com',
                    'username': f'CuentaInvalida{index}',
                    'first_name': 'Ana',
                    'last_name': 'Rojas',
                    'tipo_identificacion': tipo,
                    'cedula': cedula,
                    'password': 'Password123',
                    'confirm_password': 'Password123',
                    'cargo': 'ASISTENTE',
                })

                self.assertFalse(form.is_valid())
                self.assertIn('cedula', form.errors)

    def test_campo_cedula_acepta_prefijos_en_patrón_html(self):
        field = AdminCrearUsuarioForm().fields['cedula']

        self.assertEqual(field.widget.attrs['pattern'], r'^(?:V-\d{7,8}|E-\d{6,9})$')

    def test_formulario_nuevo_confirma_la_password_generada(self):
        form = AdminCrearUsuarioForm()

        self.assertTrue(form.initial['password'])
        self.assertEqual(form.initial['password'], form.initial['confirm_password'])
        self.assertIn(f'value="{form.initial["password"]}"', form['password'].as_widget())
        self.assertIn(f'value="{form.initial["password"]}"', form['confirm_password'].as_widget())

    def test_formulario_crear_cuenta_carga_css_actualizado(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.urls import resolve
        from .views import admin_crear_usuario

        usuario = User.objects.create_superuser(
            username='directora-css-form', password='Password123'
        )
        path = reverse('admin_crear_usuario')
        request = RequestFactory().get(path)
        request.user = usuario
        request.session = {'staff_session_token': 'directora-css-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)

        response = admin_crear_usuario(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn('css/admin.css?v=28', response.content.decode())

    def test_crear_primera_directora_asigna_superusuario_y_oculta_siguiente(self):
        form = AdminCrearUsuarioForm(data={
            'email': 'directora@example.com',
            'username': 'DirectoraNueva',
            'first_name': 'Laura',
            'last_name': 'Garcia',
            'cedula': 'V-22334455',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'DIRECTORA',
        })

        self.assertIn('DIRECTORA', [value for value, _ in form.fields['cargo'].choices])
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.empleado.cargo, 'DIRECTORA')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertNotIn('DIRECTORA', [value for value, _ in AdminCrearUsuarioForm().fields['cargo'].choices])

    def test_admin_crear_usuario_rechaza_usuario_fuera_del_formato(self):
        datos = {
            'email': 'nuevo@example.com',
            'first_name': 'Ana',
            'last_name': 'Rojas',
            'cedula': 'V-12345678',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        }
        for username in ('Ana Rojas24', ' AnaRojas24', 'AnaRojas24 ', 'Ana.Rojas24', 'Ana-Rojas24'):
            with self.subTest(username=username):
                form = AdminCrearUsuarioForm(data={**datos, 'username': username})
                self.assertFalse(form.is_valid())
                self.assertIn('username', form.errors)

    def test_admin_crear_usuario_permite_cualquier_combinacion_de_letras_y_numeros(self):
        datos = {
            'email': 'nuevo@example.com',
            'first_name': 'Ana',
            'last_name': 'Rojas',
            'cedula': 'V-12345678',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        }
        for username in ('ana', 'ANAROjas24', '12345678', 'ana_rojas24'):
            with self.subTest(username=username):
                form = AdminCrearUsuarioForm(data={**datos, 'username': username})
                self.assertTrue(form.is_valid(), form.errors)

    def test_admin_crear_usuario_requiere_confirmacion_igual(self):
        form = AdminCrearUsuarioForm(data={
            'email': 'confirmacion@example.com',
            'username': 'LuisGuerrero24',
            'first_name': 'Luis',
            'last_name': 'Guerrero',
            'cedula': 'V-12345678',
            'password': 'Password123',
            'confirm_password': 'Password321',
            'cargo': 'ASISTENTE',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('confirm_password', form.errors)

    def _solicitar_edicion_cuenta(self, user, method='get', data=None, session=None, confirmar=False, target=None):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .views import admin_editar_usuario

        target = target or user
        request_factory = RequestFactory()
        url = reverse('admin_editar_usuario', args=[target.pk])
        if confirmar:
            url = f'{url}?confirm=1'
        request = getattr(request_factory, method)(url, data=data or {})
        request.user = user
        request.session = session if session is not None else {'staff_session_token': 'test'}
        request._messages = FallbackStorage(request)
        return admin_editar_usuario(request, target.pk), request.session

    def _solicitar_mi_cuenta(self, user, url_name, method='get', data=None, session=None):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        from django.urls import resolve
        from .views import mi_cuenta_editar_view, mi_cuenta_view

        request_factory = RequestFactory()
        path = reverse(url_name)
        request = getattr(request_factory, method)(path, data=data or {})
        request.user = user
        if session is None:
            session = SessionStore()
            session['staff_session_token'] = 'test'
        request.session = session
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        view = mi_cuenta_editar_view if url_name == 'mi_cuenta_editar' else mi_cuenta_view
        return view(request), request.session

    def test_usuario_staff_no_puede_editar_otra_cuenta(self):
        actor = User.objects.create_user(username='docente-editor', is_staff=True)
        target = User.objects.create_user(username='otra-cuenta')

        with self.assertRaises(PermissionDenied):
            self._solicitar_edicion_cuenta(actor, target=target)

    def test_panel_staff_solo_muestra_su_propia_cuenta(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .views import admin_panel_view

        actor = User.objects.create_user(username='docente-visible', is_staff=True)
        target = User.objects.create_user(username='cuenta-privada')
        request = RequestFactory().get(reverse('admin_panel'))
        request.user = actor
        request.session = {'staff_session_token': 'test'}
        request._messages = FallbackStorage(request)

        response = admin_panel_view(request)
        content = response.content.decode()

        self.assertIn(actor.username, content)
        self.assertNotIn(target.username, content)

    def test_directora_es_administradora_y_admin_no_es_un_cargo(self):
        from .forms import AdminEditarUsuarioForm, EmpleadoForm

        admin = User.objects.create_user(
            username='admin-editor', password='Password123', is_staff=True, is_superuser=True
        )
        Empleado.objects.create(user=admin, cedula='V-12345678', cargo='DIRECTORA')
        form_propio = AdminEditarUsuarioForm(instance=admin, actor=admin)
        otra_cuenta = User.objects.create_user(username='cuenta-asistente')
        form_otra = AdminEditarUsuarioForm(instance=otra_cuenta, actor=admin)
        formulario_nuevo_usuario = AdminCrearUsuarioForm()
        formulario_nuevo_empleado = EmpleadoForm()

        self.assertEqual(list(form_propio.fields['cargo'].choices), [('DIRECTORA', 'Director/a')])
        self.assertNotIn('DIRECTORA', [value for value, _ in form_otra.fields['cargo'].choices])
        self.assertNotIn('DIRECTORA', [value for value, _ in formulario_nuevo_usuario.fields['cargo'].choices])
        self.assertNotIn('DIRECTORA', [value for value, _ in formulario_nuevo_empleado.fields['cargo'].choices])
        self.assertNotIn('ADMIN', [value for value, _ in form_otra.fields['cargo'].choices])

        intento_degradar_admin = AdminEditarUsuarioForm(
            data={'cargo': 'ASISTENTE'}, instance=admin, actor=admin
        )
        intento_asignar_cargo_inexistente = AdminEditarUsuarioForm(
            data={'cargo': 'ADMIN'}, instance=otra_cuenta, actor=admin
        )

        self.assertFalse(intento_degradar_admin.is_valid())
        self.assertIn('cargo', intento_degradar_admin.errors)
        self.assertFalse(intento_asignar_cargo_inexistente.is_valid())
        self.assertIn('cargo', intento_asignar_cargo_inexistente.errors)
        intento_asignar_directora = AdminEditarUsuarioForm(
            data={'cargo': 'DIRECTORA'}, instance=otra_cuenta, actor=admin
        )
        self.assertFalse(intento_asignar_directora.is_valid())
        self.assertIn('cargo', intento_asignar_directora.errors)

    def test_cargos_administrativos_se_muestran_en_forma_unisex(self):
        self.assertEqual(
            dict(Empleado.CARGOS),
            {
                'DIRECTORA': 'Director/a',
                'SUBDIRECTORA': 'Subdirector/a',
                'COORD': 'Coordinador/a Pedagógico/a',
                'DOCENTE': 'Docente',
                'PROFESOR': 'Profesor/a',
                'ASISTENTE': 'Asistente',
            },
        )

    def test_cargo_profesor_aparece_una_sola_vez_en_formularios(self):
        from .forms import AdminEditarUsuarioForm, EmpleadoForm

        actor = User.objects.create_user(username='editor-profesores', is_staff=True)
        user = User.objects.create_user(username='profesor-antiguo')
        empleado = Empleado.objects.create(
            user=user, cedula='V-12345678', cargo='DOCENTE'
        )

        editar_usuario = AdminEditarUsuarioForm(instance=user, actor=actor)
        editar_empleado = EmpleadoForm(instance=empleado)
        nuevo_empleado = EmpleadoForm()
        nueva_cuenta = AdminCrearUsuarioForm()

        for form in (editar_usuario, editar_empleado):
            self.assertEqual(
                [(value, label) for value, label in form.fields['cargo'].choices if label == 'Profesor/a'],
                [('DOCENTE', 'Profesor/a')],
            )
        self.assertEqual(
            [(value, label) for value, label in nuevo_empleado.fields['cargo'].choices if label == 'Profesor/a'],
            [('PROFESOR', 'Profesor/a')],
        )
        self.assertEqual(
            [(value, label) for value, label in nueva_cuenta.fields['cargo'].choices if label == 'Profesor/a'],
            [('PROFESOR', 'Profesor/a')],
        )
        self.assertEqual(editar_usuario.fields['cargo'].initial, 'DOCENTE')

    def test_formulario_personal_no_quita_cargo_directora_al_superusuario(self):
        from .forms import EmpleadoForm

        admin = User.objects.create_user(
            username='directora-protegida', is_staff=True, is_superuser=True
        )
        empleado = Empleado.objects.create(
            user=admin, cedula='V-12345678', cargo='DIRECTORA'
        )
        form = EmpleadoForm(
            data={
                'cedula': '12345678',
                'cargo': 'ASISTENTE',
                'first_name': 'Directora',
                'last_name': 'Protegida',
                'email': '',
                'password': '',
            },
            instance=empleado,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('cargo', form.errors)

    def test_editar_cuenta_no_permite_asignar_segunda_directora(self):
        from .forms import AdminEditarUsuarioForm

        admin_actual = User.objects.create_user(
            username='directora-actual', is_staff=True, is_superuser=True
        )
        Empleado.objects.create(user=admin_actual, cedula='V-12345678', cargo='DIRECTORA')
        nueva_directora = User.objects.create_user(username='directora-nueva')
        Empleado.objects.create(user=nueva_directora, cedula='V-87654321', cargo='ASISTENTE')
        form = AdminEditarUsuarioForm(
            data={
                'email': '',
                'first_name': '',
                'last_name': '',
                'cargo': 'DIRECTORA',
                'cedula': '87654321',
            },
            instance=nueva_directora,
            actor=admin_actual,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('cargo', form.errors)
        admin_actual.refresh_from_db()
        nueva_directora.refresh_from_db()

        self.assertTrue(admin_actual.is_superuser)
        self.assertTrue(admin_actual.is_staff)
        self.assertEqual(admin_actual.empleado.cargo, 'DIRECTORA')
        self.assertFalse(nueva_directora.is_superuser)
        self.assertFalse(nueva_directora.is_staff)
        self.assertEqual(nueva_directora.empleado.cargo, 'ASISTENTE')

    def test_editar_mi_cuenta_pide_password_antes_de_mostrar_el_formulario(self):
        user = User.objects.create_user(
            username='usuario-editar', password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(user=user, cedula='V-73456781', cargo='SUBDIRECTORA')

        response, _ = self._solicitar_edicion_cuenta(user)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Confirma tu identidad', content)
        self.assertIn('name="password"', content)
        self.assertNotIn('name="first_name"', content)

    def test_editar_otra_cuenta_pide_password_del_actor(self):
        actor = User.objects.create_user(
            username='admin-editor-cuenta', password='Password123',
            is_staff=True, is_superuser=True,
        )
        target = User.objects.create_user(username='cuenta-objetivo')

        response, session = self._solicitar_edicion_cuenta(actor, target=target)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Ingresa la contraseña de tu cuenta', content)
        self.assertIn(target.username, content)
        self.assertNotIn('name="first_name"', content)

        response, _ = self._solicitar_edicion_cuenta(
            actor, 'post', {'password': 'Incorrecta123'}, target=target, session=session
        )
        self.assertIn('La contraseña es incorrecta.', response.content.decode())

        response, session = self._solicitar_edicion_cuenta(
            actor, 'post', {'password': 'Password123'}, target=target, session=session
        )
        self.assertEqual(response.status_code, 302)
        response, _ = self._solicitar_edicion_cuenta(actor, target=target, session=session)
        self.assertIn('name="first_name"', response.content.decode())

    def test_editar_mi_cuenta_rechaza_password_incorrecta(self):
        user = User.objects.create_user(
            username='usuario-editar', password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(user=user, cedula='V-73456782', cargo='SUBDIRECTORA')

        response, _ = self._solicitar_edicion_cuenta(user, 'post', {'password': 'Incorrecta123'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('La contraseña es incorrecta.', content)
        self.assertNotIn('name="first_name"', content)

    def test_editar_cuenta_rechaza_confirmacion_de_password_distinta(self):
        from .forms import AdminEditarUsuarioForm

        user = User.objects.create_user(username='usuario-editar', password='Password123')
        form = AdminEditarUsuarioForm(data={
            'password': 'NuevaClave123',
            'confirm_password': 'OtraClave123',
        }, instance=user)

        self.assertFalse(form.is_valid())
        self.assertIn('confirm_password', form.errors)

    def test_editar_mi_cuenta_muestra_formulario_solo_despues_de_confirmar_password(self):
        user = User.objects.create_user(
            username='V-12345678', password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(user=user, cedula='V-73456783', cargo='SUBDIRECTORA')

        response, session = self._solicitar_edicion_cuenta(user, 'post', {'password': 'Password123'})

        self.assertEqual(response.status_code, 302)
        response, _ = self._solicitar_edicion_cuenta(user, session=session, confirmar=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirma tu identidad', response.content.decode())
        response, session = self._solicitar_edicion_cuenta(
            user, 'post', {'password': 'Password123'}, session=session
        )
        self.assertEqual(response.status_code, 302)
        response, _ = self._solicitar_edicion_cuenta(user, session=session)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Editar datos de V-12345678', content)
        self.assertIn('name="first_name"', content)
        self.assertEqual(content.count('type="password"'), 2)

        response, _ = self._solicitar_edicion_cuenta(user, 'post', {
            'tipo_identificacion': 'V',
            'cedula': '12345678',
            'first_name': 'Luis',
            'last_name': 'Perez',
            'password': 'NuevaClave123',
            'confirm_password': 'NuevaClave123',
        }, session=session)

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaClave123'))

    def test_superusuario_puede_acceder_y_modificar_su_propia_cuenta(self):
        directora = User.objects.create_superuser(
            username='directorasololec',
            email='directora@example.com',
            password='Password123',
        )
        Empleado.objects.create(user=directora, cedula='V-73456784', cargo='DIRECTORA')

        response, _ = self._solicitar_mi_cuenta(directora, 'mi_cuenta')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirma tu identidad', response.content.decode())

        response, session = self._solicitar_mi_cuenta(
            directora,
            'mi_cuenta',
            method='post',
            data={'password': 'Password123'},
        )
        self.assertEqual(response.url, reverse('mi_cuenta_editar'))
        response, session = self._solicitar_mi_cuenta(
            directora, 'mi_cuenta_editar', session=session
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="first_name"', response.content.decode())
        response, _ = self._solicitar_mi_cuenta(directora, 'mi_cuenta_editar', 'post', {
            'username': 'directorasololec',
            'cedula': 'V-73456784',
            'email': 'cambiado@example.com',
            'first_name': 'Nombre cambiado',
            'last_name': 'Directora',
            'password': '',
            'confirm_password': '',
        }, session)
        directora.refresh_from_db()
        self.assertEqual(response.url, reverse('mi_cuenta'))
        self.assertEqual(directora.first_name, 'Nombre cambiado')
        self.assertEqual(directora.email, 'cambiado@example.com')
        self.assertTrue(directora.check_password('Password123'))

    def test_cuenta_superusuario_rechaza_edicion_directa(self):
        directora = User.objects.create_superuser(
            username='directora-bloqueada', password='Password123'
        )

        with self.assertRaises(PermissionDenied):
            self._solicitar_edicion_cuenta(directora)

    def test_listado_muestra_cuenta_protegida_sin_acciones_de_cambio(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.urls import resolve

        from .views import admin_cuentas_view

        directora = User.objects.create_superuser(
            username='directora-lectura', email='directora@example.com', password='Password123'
        )
        cuenta_protegida = User.objects.create_superuser(
            username='cuenta-protegida-lista', email='protegida@example.com', password='Password123'
        )
        Empleado.objects.create(user=directora, cedula='V-73456785', cargo='DIRECTORA')
        Empleado.objects.create(user=cuenta_protegida, cedula='V-73456787', cargo='DIRECTORA')
        path = reverse('admin_cuentas')
        request = RequestFactory().get(path)
        request.user = directora
        request.session = {'staff_session_token': 'directora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)

        response = admin_cuentas_view(request)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(reverse('mi_cuenta'), contenido)
        self.assertIn('Solo lectura', contenido)
        self.assertNotIn(reverse('admin_editar_usuario', args=[directora.pk]), contenido)
        self.assertNotIn(reverse('admin_eliminar_usuario', args=[directora.pk]), contenido)
        self.assertNotIn(reverse('admin_editar_usuario', args=[cuenta_protegida.pk]), contenido)

    def test_docente_puede_entrar_a_su_cuenta(self):
        user = User.objects.create_user(
            username='docente-cuenta-propia', password='Password123', is_staff=True
        )
        Empleado.objects.create(user=user, cedula='V-73456786', cargo='DOCENTE')

        response, _ = self._solicitar_mi_cuenta(user, 'mi_cuenta')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirma tu identidad', response.content.decode())

    def test_navegacion_superior_agrupa_secciones_y_deja_cuentas_visible(self):
        directora = User.objects.create_superuser(
            username='directora-nav', password='Password123',
        )
        Empleado.objects.create(user=directora, cedula='V-73456792', cargo='DIRECTORA')
        self.client.force_login(directora)

        response = self.client.get(reverse('admin_cuentas'))

        self.assertContains(response, '<summary>Académico')
        self.assertContains(response, reverse('admin_representantes'))
        self.assertContains(response, 'Matrículas')
        self.assertContains(response, '<summary>Personal y cuenta')
        self.assertContains(response, reverse('admin_cuentas'))
        self.assertContains(response, 'class="site-nav__actions"')
        self.assertContains(response, 'class="site-logout"')

    def test_directora_no_aparece_en_listado_de_personal(self):
        directora = User.objects.create_superuser(
            username='directora-personal', password='Password123',
        )
        User.objects.create_user(
            username='asistente-personal-lista', password='Password123', is_staff=True,
            first_name='Ana', last_name='Asistente',
        )
        Empleado.objects.create(user=directora, cedula='V-73456788', cargo='DIRECTORA')
        empleado = User.objects.get(username='asistente-personal-lista')
        Empleado.objects.create(user=empleado, cedula='V-73456789', cargo='ASISTENTE')
        self.client.force_login(directora)

        response = self.client.get(reverse('admin_personal'))

        self.assertEqual(response.status_code, 200)
        contenido_tabla = response.content.decode().split('<tbody>', 1)[1].split('</tbody>', 1)[0]
        self.assertNotIn('directora-personal', contenido_tabla)
        self.assertIn('Ana Asistente', contenido_tabla)

    def test_directora_puede_habilitar_y_restringir_cuenta_desde_cuentas(self):
        directora = User.objects.create_superuser(
            username='directora-estados', password='Password123',
        )
        objetivo = User.objects.create_user(
            username='cuenta-estados', password='Password123', is_staff=True,
        )
        self.client.force_login(directora)

        response = self.client.get(reverse('admin_cuentas'))

        self.assertContains(response, 'Estado de la cuenta')
        self.assertContains(response, 'Restringir cuenta')
        response = self.client.post(reverse('admin_toggle_usuario', args=[objetivo.pk]))

        self.assertRedirects(response, reverse('admin_cuentas'))
        objetivo.refresh_from_db()
        self.assertFalse(objetivo.is_active)
        response = self.client.get(reverse('admin_cuentas'))
        self.assertContains(response, 'Restringida')
        self.assertContains(response, 'Habilitar cuenta')

        response = self.client.post(reverse('admin_toggle_usuario', args=[objetivo.pk]))

        self.assertRedirects(response, reverse('admin_cuentas'))
        objetivo.refresh_from_db()
        self.assertTrue(objetivo.is_active)

    def test_no_se_puede_restringir_la_cuenta_propia_ni_la_directora_principal(self):
        directora = User.objects.create_superuser(
            username='directora-proteccion', password='Password123',
        )
        Empleado.objects.create(user=directora, cedula='V-73456790', cargo='DIRECTORA')
        cuenta_directora = User.objects.create_user(
            username='directora-no-superuser', password='Password123', is_staff=True,
        )
        Empleado.objects.create(user=cuenta_directora, cedula='V-73456791', cargo='DIRECTORA')
        self.client.force_login(directora)

        self.client.post(reverse('admin_toggle_usuario', args=[directora.pk]))
        self.client.post(reverse('admin_toggle_usuario', args=[cuenta_directora.pk]))

        directora.refresh_from_db()
        cuenta_directora.refresh_from_db()
        self.assertTrue(directora.is_active)
        self.assertTrue(cuenta_directora.is_active)

    def test_acceso_mi_cuenta_exige_password_y_abre_formulario_propio(self):
        user = User.objects.create_user(
            username='docente-cuenta', password='Password123', is_staff=True
        )
        Empleado.objects.create(user=user, cedula='V-12345678', cargo='DOCENTE')

        response, session = self._solicitar_mi_cuenta(user, 'mi_cuenta')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirma tu identidad', response.content.decode())
        self.assertNotIn('name="first_name"', response.content.decode())

        response, _ = self._solicitar_mi_cuenta(
            user, 'mi_cuenta', 'post', {'password': 'Incorrecta123'}, session
        )
        self.assertIn('La contraseña es incorrecta.', response.content.decode())

        response, session = self._solicitar_mi_cuenta(
            user, 'mi_cuenta', 'post', {'password': 'Password123'}, session
        )
        self.assertEqual(response.url, reverse('mi_cuenta_editar'))
        response, session = self._solicitar_mi_cuenta(
            user, 'mi_cuenta_editar', session=session
        )
        content = response.content.decode()
        self.assertIn('Editar mi cuenta', content)
        self.assertIn('name="first_name"', content)
        self.assertIn('name="username"', content)
        cedula_input = next(tag for tag in content.split('>') if 'name="cedula"' in tag)
        self.assertIn('V-12345678', cedula_input)
        self.assertIn('disabled', cedula_input)
        self.assertNotIn('name="cargo"', content)

        response, _ = self._solicitar_mi_cuenta(user, 'mi_cuenta_editar', 'post', {
            'username': 'AnaPerez24',
            'cedula': 'V-87654321',
            'email': 'docente@example.com',
            'first_name': 'Ana',
            'last_name': 'Pérez',
            'password': '',
            'confirm_password': '',
        }, session)
        self.assertEqual(response.url, reverse('mi_cuenta'))
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Ana')
        self.assertEqual(user.email, 'docente@example.com')
        self.assertEqual(user.username, 'AnaPerez24')
        self.assertEqual(user.empleado.cedula, 'V-12345678')
        self.assertTrue(user.check_password('Password123'))

    def test_cambiar_contrasena_cierra_sesion_y_pide_iniciar_de_nuevo(self):
        user = User.objects.create_user(
            username='docenteclave', password='Password123', is_staff=True
        )
        Empleado.objects.create(user=user, cedula='V-23456789', cargo='DOCENTE')
        response, session = self._solicitar_mi_cuenta(
            user, 'mi_cuenta', 'post', {'password': 'Password123'}
        )
        self.assertEqual(response.url, reverse('mi_cuenta_editar'))

        response, session = self._solicitar_mi_cuenta(user, 'mi_cuenta_editar', 'post', {
            'username': 'docenteclave',
            'cedula': 'V-23456789',
            'email': '',
            'first_name': '',
            'last_name': '',
            'password': 'NuevaClave123',
            'confirm_password': 'NuevaClave123',
        }, session)

        self.assertEqual(response.url, reverse('login'))
        self.assertNotIn('_auth_user_id', session)
        self.assertIn('session_message', session)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaClave123'))

    def test_editar_cuenta_rechaza_usuario_con_espacios_o_simbolos_no_permitidos(self):
        from .forms import CuentaPropiaForm

        user = User.objects.create_user(username='usuario-viejo', is_staff=True)
        form = CuentaPropiaForm(data={
            'cedula': 'V-12345678',
            'username': 'ana.rojas24',
            'first_name': 'Ana',
            'last_name': 'Rojas',
            'email': '',
            'password': '',
            'confirm_password': '',
        }, instance=user)

        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

        form = CuentaPropiaForm(data={
            'cedula': 'V-12345678',
            'username': 'AnaRojas24',
            'first_name': 'Ana',
            'last_name': 'Rojas',
            'email': '',
            'password': '',
            'confirm_password': '',
        }, instance=user)

        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_crear_usuario_rechaza_email_sin_nombre_y_dominio_validos(self):
        form = AdminCrearUsuarioForm(data={
            'email': 'usuario@dominio',
            'username': 'MariaTorres24',
            'first_name': 'María',
            'last_name': 'Torres',
            'cedula': 'V-87654321',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_admin_crear_usuario_rechaza_nombre_con_numeros(self):
        form = AdminCrearUsuarioForm(data={
            'email': 'nuevo@example.com',
            'username': 'JuanPerez24',
            'first_name': 'Juan123',
            'last_name': 'Pérez',
            'cedula': '12345678',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('first_name', form.errors)

    def test_admin_crear_usuario_rechaza_cedula_y_email_duplicados(self):
        User.objects.create_user(username='12345678', email='duplicado@example.com', password='Password123')
        form = AdminCrearUsuarioForm(data={
            'email': 'duplicado@example.com',
            'username': 'LauraPerez24',
            'first_name': 'Laura',
            'last_name': 'Pérez',
            'cedula': '12345678',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('cedula', form.errors)
        self.assertIn('email', form.errors)

    def test_asignacion_form_muestra_estudiantes_y_docentes_disponibles(self):
        representante = Representante.objects.create(nombre='Luis', apellido='Pérez', cedula='22222222', telefono='04121234567')
        estudiante = Estudiante.objects.create(nombre='Ana', apellido='Gómez', cedula='33333333', grado='4to', representante=representante)
        user = User.objects.create_user(username='docente1', email='docente1@example.com', password='Password123', first_name='Carlos', last_name='Mendoza')
        empleado = Empleado.objects.create(user=user, cedula='44444444', cargo='DOCENTE')

        form = AsignacionForm()
        choices = [choice[1] for choice in form.fields['estudiante'].choices if choice[0]]
        docente_choices = [choice[1] for choice in form.fields['docente'].choices if choice[0]]

        self.assertTrue(any('Ana Gómez' in choice and '33333333' in choice for choice in choices))
        self.assertTrue(any('Carlos Mendoza' in choice and '44444444' in choice for choice in docente_choices))

    def test_registro_academico_form_rechaza_area_con_numeros(self):
        form = RegistroAcademicoForm(data={
            'estudiante_cedula': '99999999',
            'docente_cedula': '',
            'asignacion_id': '',
            'area': 'Matemáticas 2',
            'periodo': '2026-2027',
            'tipo_evaluacion': 'Parcial',
            'nota': '85',
            'estado': 'Aprobado',
            'comentarios': 'Prueba',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('area', form.errors)

    def test_registro_academico_form_muestra_todas_las_materias_en_selector(self):
        from .models import Docente, Horario

        docente = Docente.objects.create(
            nombre='Docente', apellido='Horario', cedula='DOC-HORARIO-001'
        )
        materias_horario = [
            'Lengua y Literatura',
            'Formación Ciudadana',
            'Educación Ambiental',
            'Orientación',
            'Robótica',
        ]
        for indice, materia in enumerate(materias_horario):
            Horario.objects.create(
                ano='1ANO',
                materia=materia,
                docente=docente,
                dia='LU',
                hora_inicio=f'{8 + indice:02d}:00',
                hora_fin=f'{9 + indice:02d}:00',
            )

        form = RegistroAcademicoForm()
        materias = {value for value, _ in form.fields['area'].choices if value}

        self.assertEqual(
            materias,
            set(Horario.objects.values_list('materia', flat=True).distinct()),
        )
        self.assertIn('Robótica', materias)

    def test_registro_academico_form_rechaza_calificacion_invalida(self):
        form = RegistroAcademicoForm(data={
            'estudiante_cedula': '99999999',
            'docente_cedula': '',
            'asignacion_id': '',
            'area': 'Matemáticas',
            'periodo': '2026-2027',
            'tipo_evaluacion': 'Parcial',
            'nota': 'G',
            'estado': 'Pendiente',
            'comentarios': 'Prueba',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('nota', form.errors)

    def test_registro_academico_form_calcula_porcentaje_desde_calificacion(self):
        from .models import Docente, Horario

        representante = Representante.objects.create(nombre='Luis', apellido='Pérez', cedula='55555555')
        estudiante = Estudiante.objects.create(nombre='Ana', apellido='Gómez', cedula='66666666', grado='4TO', representante=representante)
        profesor_user = User.objects.create_user(username='profesor-nota', first_name='Carlos', last_name='Mendoza')
        profesor = Empleado.objects.create(user=profesor_user, cedula='77777777', cargo='DOCENTE')
        docente = Docente.objects.create(
            nombre='Carlos',
            apellido='Mendoza',
            cedula=profesor.cedula,
        )
        Horario.objects.create(
            ano='4ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        form = RegistroAcademicoForm(data={
            'estudiante_cedula': str(estudiante.pk),
            'docente_cedula': f'emp:{profesor.pk}',
            'area': 'Matemáticas',
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'tipo_evaluacion': 'Final',
            'nota': 'B',
            'estado': 'Aprobado',
        })

        self.assertTrue(form.is_valid(), form.errors)
        registro = form.save()

        self.assertEqual(registro.nota, 'B')
        self.assertEqual(registro.porcentaje, 80)

    def test_asistencia_form_rechaza_fecha_futura(self):
        form = AsistenciaForm(data={
            'estudiante_cedula': '99999999',
            'fecha': (date.today() + timedelta(days=1)).strftime('%Y-%m-%d'),
            'estado': 'PRESENTE',
            'observaciones': 'Prueba',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('fecha', form.errors)

    def test_asistencia_form_renderiza_fecha_inicial_en_formato_iso(self):
        from django.utils import timezone

        form = AsistenciaForm()

        self.assertEqual(
            form['fecha'].value().isoformat(),
            timezone.localdate().isoformat(),
        )
        self.assertIn(
            f'value="{timezone.localdate().isoformat()}"',
            str(form['fecha']),
        )

    def test_asistencia_form_guarda_y_recupera_el_registro(self):
        from .models import Asistencia

        estudiante = Estudiante.objects.create(
            nombre='Ana', apellido='Gómez', cedula='V-78787878', grado='1RO'
        )
        fecha = date.today().isoformat()
        form = AsistenciaForm(data={
            'estudiante_cedula': str(estudiante.pk),
            'fecha': fecha,
            'estado': 'PRESENTE',
            'observaciones': 'Prueba aislada de guardado.',
        })

        self.assertTrue(form.is_valid(), form.errors)
        asistencia = form.save()
        guardada = Asistencia.objects.get(pk=asistencia.pk)

        self.assertEqual(guardada.estudiante_id, estudiante.pk)
        self.assertEqual(guardada.fecha.isoformat(), fecha)
        self.assertEqual(guardada.estado, 'PRESENTE')
        self.assertEqual(guardada.observaciones, 'Prueba aislada de guardado.')

    def test_login_form_rechaza_usuario_no_cedula(self):
        form = LoginForm(data={
            'username': 'usuario123',
            'password': 'Password123',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_login_form_rechaza_password_vacio(self):
        form = LoginForm(data={
            'username': '12345678',
            'password': '   ',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)

    def test_login_form_permite_usuario_existente(self):
        User.objects.create_user(username='Lord12', password='Password123')
        form = LoginForm(data={
            'username': 'Lord12',
            'password': 'Password123',
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['user'].username, 'Lord12')

    def test_login_form_permite_cedula_asociada_a_usuario_personalizado(self):
        user = User.objects.create_user(username='AnaRojas24', password='Password123')
        Empleado.objects.create(user=user, cedula='V-12345678', cargo='ASISTENTE')
        form = LoginForm(data={
            'username': 'V-12345678',
            'password': 'Password123',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['user'].username, 'AnaRojas24')

    def test_login_incluye_boton_mostrar_y_ocultar_contrasena(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'id="toggle-password-visibility"')
        self.assertContains(response, 'aria-pressed="false"')
        self.assertContains(response, 'class="login-form" autocomplete="off"')
        self.assertContains(response, 'name="password" autocomplete="off"')
        self.assertContains(response, "passwordInput.type = shouldShow ? 'text' : 'password'")

    def test_login_ignora_redireccion_next_a_host_externo(self):
        User.objects.create_user(username='login-next', password='Password123')

        response = self.client.post(reverse('login'), {
            'username': 'login-next',
            'password': 'Password123',
            'next': 'https://example.org/',
        })

        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_login_conserva_redireccion_next_relativa(self):
        User.objects.create_user(username='login-next-local', password='Password123')
        next_path = reverse('portal_about')

        response = self.client.post(reverse('login'), {
            'username': 'login-next-local',
            'password': 'Password123',
            'next': next_path,
        })

        self.assertRedirects(response, next_path, fetch_redirect_response=False)

    def test_usuario_inactivo_no_puede_acceder_al_panel(self):
        user = User.objects.create_user(username='inactivo', password='Password123', is_active=False, is_staff=True)
        self.client.force_login(user)

        response = self.client.get(reverse('admin_panel'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))

    def test_sesion_staff_avisa_a_30_segundos_del_limite_de_dos_minutos(self):
        user = User.objects.create_user(
            username='temporizador-sesion', password='Password123', is_staff=True
        )
        self.client.force_login(user)

        response = self.client.get(reverse('mi_cuenta'))

        self.assertContains(response, 'id="session-timeout-modal"')
        self.assertContains(response, 'data-idle-timeout="120"')
        self.assertContains(response, 'data-warning-seconds="30"')
        self.assertContains(response, f'data-logout-url="{reverse("logout")}"')
        self.assertContains(response, 'Continuar en la sesión')
        self.assertContains(response, 'session_timeout.js')
        self.assertContains(response, 'role="alertdialog" aria-modal="true"')

    def test_boton_continuar_renueva_sesion_de_personal(self):
        user = User.objects.create_user(
            username='continuar-sesion', password='Password123', is_staff=True
        )
        self.client.force_login(user)

        response = self.client.post(reverse('refresh_staff_session'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})
        self.assertEqual(
            self.client.session.get_expiry_age(),
            settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS,
        )

    def test_boton_continuar_renueva_sesion_al_final_del_contador(self):
        user = User.objects.create_user(
            username='reanudar-al-limite', password='Password123', is_staff=True
        )
        self.client.force_login(user)
        session = self.client.session
        session['last_staff_activity'] = time.time() - (
            settings.SESSION_IDLE_TIMEOUT_SECONDS + 2
        )
        session.save()

        response = self.client.post(reverse('refresh_staff_session'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})
        self.assertLess(
            time.time() - self.client.session['last_staff_activity'],
            2,
        )

    def test_boton_continuar_renueva_sesion_mientras_queda_un_segundo(self):
        user = User.objects.create_user(
            username='reanudar-un-segundo', password='Password123', is_staff=True
        )
        self.client.force_login(user)
        session = self.client.session
        session['last_staff_activity'] = time.time() - (
            settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS - 1
        )
        session.set_expiry(
            settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
        )
        session.save()

        response = self.client.post(reverse('refresh_staff_session'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})
        self.assertLess(
            time.time() - self.client.session['last_staff_activity'],
            2,
        )

    def test_boton_continuar_no_renueva_despues_de_terminar_los_30_segundos(self):
        user = User.objects.create_user(
            username='reanudar-despues-del-limite', password='Password123', is_staff=True
        )
        self.client.force_login(user)
        session = self.client.session
        session['last_staff_activity'] = time.time() - (
            settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
        )
        session.set_expiry(
            settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
        )
        session.save()

        response = self.client.post(reverse('refresh_staff_session'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('portal_home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sesion_inactiva_dos_minutos_vuelve_al_portal(self):
        user = User.objects.create_user(
            username='sesion-expirada', password='Password123', is_staff=True
        )
        self.client.force_login(user)
        session = self.client.session
        session['last_staff_activity'] = time.time() - 121
        session.save()

        response = self.client.get(reverse('mi_cuenta'))

        self.assertRedirects(response, reverse('portal_home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotIn('session_message', self.client.session)
        portal_response = self.client.get(reverse('portal_home'))
        self.assertEqual(portal_response.status_code, 200)
        self.assertNotContains(portal_response, 'Tu sesión se cerró automáticamente por inactividad')

    def test_cerrar_sesion_por_tiempo_carga_el_portal_sin_panel(self):
        user = User.objects.create_user(
            username='cierre-por-tiempo', password='Password123', is_staff=True
        )
        self.client.force_login(user)

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, reverse('portal_home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        portal_response = self.client.get(reverse('portal_home'))
        self.assertEqual(portal_response.status_code, 200)
        self.assertNotContains(portal_response, reverse('admin_panel'))
        self.assertNotContains(portal_response, 'session-timeout-modal')

    def test_portal_no_muestra_aviso_de_sesion_por_parametro(self):
        response = self.client.get(reverse('portal_home'), {
            'session_message': 'Tu sesión se cerró automáticamente por inactividad.'
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Tu sesión se cerró automáticamente por inactividad')

    def test_docente_se_crea_como_staff_para_acceder_al_panel(self):
        from .models import Docente

        form = AdminCrearUsuarioForm(data={
            'email': 'docente@example.com',
            'username': 'LauraGarcia24',
            'first_name': 'Laura',
            'last_name': 'García',
            'cedula': 'V-22334455',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'PROFESOR',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertTrue(user.is_staff)
        self.assertEqual(user.empleado.cargo, 'PROFESOR')
        self.assertTrue(Docente.objects.filter(cedula=user.empleado.cedula).exists())

    def test_asistente_se_crea_como_staff_en_los_formularios_de_cuenta_y_personal(self):
        from .forms import EmpleadoForm

        user_form = AdminCrearUsuarioForm(data={
            'email': 'asistente-form@example.com',
            'username': 'AsistentePrueba',
            'first_name': 'Ana',
            'last_name': 'Prueba',
            'cedula': 'V-88776655',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'ASISTENTE',
        })
        self.assertTrue(user_form.is_valid(), user_form.errors)
        user = user_form.save()
        self.assertTrue(user.is_staff)
        self.assertEqual(user.empleado.cargo, 'ASISTENTE')

        employee_form = EmpleadoForm(data={
            'email': 'asistente-personal@example.com',
            'first_name': 'Bea',
            'last_name': 'Prueba',
            'cedula': 'V-88776656',
            'password': 'Password123',
            'cargo': 'ASISTENTE',
            'telegram_chat_id': '1122334455',
            'notificar_contactos_telegram': 'on',
        })
        self.assertTrue(employee_form.is_valid(), employee_form.errors)
        empleado = employee_form.save()
        self.assertTrue(empleado.user.is_staff)
        self.assertEqual(empleado.cargo, 'ASISTENTE')
        self.assertEqual(empleado.telegram_chat_id, '1122334455')
        self.assertTrue(empleado.notificar_contactos_telegram)

    def test_editar_personal_sin_password_actualiza_datos_y_conserva_clave(self):
        from .forms import EmpleadoForm

        user = User.objects.create_user(
            username='personal-editable',
            password='Password123',
            first_name='Nombre',
            last_name='Anterior',
            is_staff=True,
        )
        empleado = Empleado.objects.create(
            user=user,
            cedula='V-88776657',
            cargo='ASISTENTE',
        )
        form = EmpleadoForm(data={
            'email': 'personal-actualizado@example.com',
            'first_name': 'Nombre',
            'last_name': 'Actualizado',
            'cedula': 'V-88776657',
            'password': '',
            'cargo': 'ASISTENTE',
        }, instance=empleado)

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()

        self.assertEqual(user.last_name, 'Actualizado')
        self.assertEqual(user.email, 'personal-actualizado@example.com')
        self.assertTrue(user.check_password('Password123'))

    def test_docente_puede_ver_los_estudiantes_de_su_grado(self):
        from .models import Docente, Horario

        user = User.objects.create_user(
            username='docente-seccion',
            email='docente-seccion@example.com',
            password='Password123',
            first_name='Miguel',
            last_name='Sánchez',
            is_staff=True,
        )
        Empleado.objects.create(user=user, cedula='V-99887766', cargo='DOCENTE')
        docente_db = Docente.objects.create(nombre='Miguel', apellido='Sánchez', cedula='V-99887766', especialidad='Matemáticas')
        Horario.objects.create(ano='1ANO', materia='Matemáticas', docente=docente_db, dia='LU', hora_inicio='08:00:00', hora_fin='09:00:00')

        representante = Representante.objects.create(
            nombre='Pedro', apellido='Pérez', cedula='V-32165498', telefono='04141234567', es_tutor_legal=True
        )
        Estudiante.objects.create(nombre='Ana', apellido='Gómez', cedula='V-10101010', grado='1RO', representante=representante)
        Estudiante.objects.create(nombre='Luis', apellido='Rojas', cedula='V-20202020', grado='2DO', representante=representante)

        self.client.force_login(user)
        response = self.client.get(reverse('docente_mis_estudiantes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ana Gómez')
        self.assertNotContains(response, 'Luis Rojas')

    def test_pagina_404_personalizada(self):
        from django.test.utils import override_settings

        with override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver']):
            response = self.client.get('/ruta-que-no-existe-xyz/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Página no encontrada', status_code=404)
        self.assertContains(response, 'Volver', status_code=404)


class ProfesorPermisosTests(TestCase):
    def setUp(self):
        from .models import Docente

        self.usuario = User.objects.create_user(
            username='profesor-permisos', password='Password123', is_staff=True,
        )
        Empleado.objects.create(
            user=self.usuario, cedula='V-44556677', cargo='PROFESOR',
        )
        Docente.objects.create(
            nombre='Ana', apellido='Rojas', cedula='V-44556677',
        )
        self.client.force_login(self.usuario)
        self.factory = RequestFactory()

    def _solicitar_ruta(self, nombre):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.urls import resolve

        path = reverse(nombre)
        request = self.factory.get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'profesor-test'}
        request._messages = FallbackStorage(request)
        return resolve(path).func(request)

    def test_profesor_llega_a_sus_estudiantes_en_vez_del_dashboard(self):
        response = self._solicitar_ruta('admin_panel')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('docente_mis_estudiantes'))

    def test_profesor_puede_abrir_estudiantes_notas_y_asistencia(self):
        rutas_permitidas = (
            ('docente_mis_estudiantes', 'escuelaApp.views'),
            ('admin_registro_academico', 'escuelaApp.views_registro_academico'),
            ('admin_crear_registro_academico', 'escuelaApp.views_registro_academico'),
            ('admin_asistencias', 'escuelaApp.views_asistencia'),
            ('admin_crear_asistencia', 'escuelaApp.views_asistencia'),
            ('gestionar_horarios', 'escuelaApp.views'),
        )
        from unittest.mock import patch

        for ruta, modulo in rutas_permitidas:
            with self.subTest(ruta=ruta):
                with patch(f'{modulo}.render', return_value=HttpResponse(status=200)):
                    response = self._solicitar_ruta(ruta)
                self.assertEqual(response.status_code, 200)

    def test_profesor_no_puede_abrir_modulos_administrativos(self):
        rutas_restringidas = (
            'admin_estudiantes',
            'admin_docentes',
            'admin_representantes',
            'admin_cuentas',
            'admin_personal',
            'validar_cedula',
        )
        for ruta in rutas_restringidas:
            with self.subTest(ruta=ruta):
                response = self._solicitar_ruta(ruta)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('admin_panel'))

    def test_profesor_solo_consulta_horarios_sin_controles_de_edicion(self):
        from .models import Docente, Horario

        docente = Docente.objects.get(cedula=self.usuario.empleado.cedula)
        Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        response = self.client.get(reverse('gestionar_horarios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Matemáticas')
        self.assertNotContains(response, 'Asignar Nuevo Bloque')
        self.assertNotContains(response, 'Editar bloque')
        self.assertNotContains(response, 'Eliminar bloque')

    def test_profesor_puede_descargar_pdf_de_horarios_sin_notificar_directora(self):
        from unittest.mock import patch

        from .models import Docente, Horario

        docente = Docente.objects.get(cedula=self.usuario.empleado.cedula)
        Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        with patch('escuelaApp.views.enviar_reporte_a_directora') as enviar:
            response = self.client.get(reverse('exportar_horarios_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        enviar.assert_not_called()

    def test_profesor_no_puede_crear_editar_ni_eliminar_horarios(self):
        from .models import Docente, Horario

        docente = Docente.objects.get(cedula=self.usuario.empleado.cedula)
        horario = Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )

        crear = self.client.get(reverse('crear_horario'))
        editar = self.client.get(reverse('editar_horario', args=[horario.pk]))
        eliminar = self.client.post(reverse('eliminar_horario', args=[horario.pk]))

        self.assertEqual(crear.status_code, 302)
        self.assertEqual(crear.url, reverse('admin_panel'))
        self.assertEqual(editar.status_code, 302)
        self.assertEqual(editar.url, reverse('admin_panel'))
        self.assertEqual(eliminar.status_code, 302)
        self.assertEqual(eliminar.url, reverse('admin_panel'))
        self.assertTrue(Horario.objects.filter(pk=horario.pk).exists())


class AsistentePermisosTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(
            username='asistente-permisos', password='Password123', is_staff=True,
        )
        Empleado.objects.create(
            user=self.usuario, cedula='V-55667788', cargo='ASISTENTE',
        )
        self.estudiante = Estudiante.objects.create(
            nombre='Estudiante', apellido='Lectura', cedula='V-55667789', grado='1ANO',
        )
        self.factory = RequestFactory()

    def _solicitar_ruta(self, nombre, argumentos=None):
        from django.contrib.messages.storage.fallback import FallbackStorage

        path = reverse(nombre, args=argumentos or [])
        request = self.factory.get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'asistente-test'}
        request._messages = FallbackStorage(request)
        return resolve(path).func(request)

    def test_asistente_puede_abrir_sus_modulos_autorizados(self):
        modulos = {
            'admin_estudiantes': 'escuelaApp.views',
            'admin_asistencias': 'escuelaApp.views_asistencia',
            'admin_resumenes_asistencia_lapso': 'escuelaApp.views_asistencia',
            'admin_registro_academico': 'escuelaApp.views_registro_academico',
        }
        for ruta, modulo in modulos.items():
            with self.subTest(ruta=ruta):
                with patch(f'{modulo}.render', return_value=HttpResponse(status=200)):
                    response = self._solicitar_ruta(ruta)
                self.assertEqual(response.status_code, 200)

    def test_asistente_solo_ve_previsualizacion_y_exportacion_en_vistas_academicas(self):
        from django.template.loader import render_to_string

        from . import views, views_asistencia, views_registro_academico

        rutas = (
            ('admin_estudiantes', views, 'admin_crear_estudiante', 'admin_editar_estudiante'),
            ('admin_asistencias', views_asistencia, 'admin_crear_asistencia', None),
            ('admin_registro_academico', views_registro_academico, 'admin_crear_registro_academico', 'admin_editar_registro_academico'),
            ('admin_resumenes_asistencia_lapso', views_asistencia, 'admin_crear_resumen_asistencia_lapso', 'admin_editar_resumen_asistencia_lapso'),
        )
        for ruta, modulo, crear, editar in rutas:
            with self.subTest(ruta=ruta):
                path = reverse(ruta)
                request = self.factory.get(path)
                request.user = self.usuario
                request.session = {'staff_session_token': 'asistente-test'}
                request.resolver_match = resolve(path)
                with patch(
                    f'{modulo.__name__}.render',
                    return_value=HttpResponse(status=200),
                ) as render_page:
                    response = resolve(path).func(request)
                contenido = render_to_string(
                    render_page.call_args.args[1],
                    render_page.call_args.args[2],
                    request=request,
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(reverse(crear), contenido)
                if editar:
                    self.assertNotIn(reverse(editar, args=[999999]), contenido)
                if ruta == 'admin_estudiantes':
                    self.assertIn(reverse('admin_exportar_registros_academicos_pdf'), contenido)
                    self.assertIn(reverse('admin_exportar_asistencias_pdf'), contenido)
                    self.assertIn('aria-label="Descargar notas en PDF de Estudiante Lectura"', contenido)
                    self.assertIn('aria-label="Descargar asistencia en PDF de Estudiante Lectura"', contenido)
                    self.assertNotIn('PDF notas</a>', contenido)
                    self.assertNotIn('PDF asistencia</a>', contenido)
                elif ruta == 'admin_asistencias':
                    self.assertIn(reverse('admin_exportar_asistencias_pdf'), contenido)
                elif ruta == 'admin_registro_academico':
                    self.assertIn(reverse('admin_exportar_registros_academicos_pdf'), contenido)
                else:
                    self.assertIn(reverse('admin_exportar_resumenes_asistencia_lapso_pdf'), contenido)

    def test_resumen_de_asistencia_muestra_modal_detallado_y_reportes_con_iconos(self):
        from django.template.loader import render_to_string
        from .models import Asistencia, ResumenAsistenciaLapso

        resumen = ResumenAsistenciaLapso.objects.create(
            estudiante=self.estudiante,
            registrado_por=self.usuario.empleado,
            periodo='2026-2027',
            lapso='LAPSO_1',
            presentes=35,
            ausentes=2,
            tardanzas=1,
            justificadas=1,
            observaciones='Observación de prueba',
            seguimiento='Seguimiento de prueba',
        )
        request = self.factory.get(reverse('admin_resumenes_asistencia_lapso'))
        request.user = self.usuario
        resumen_html = render_to_string(
            'escuelaApp/admin_custom/gestionar_resumenes_asistencia.html',
            {
                'request': request,
                'resumenes': [resumen],
                'periodo': '',
                'lapso': '',
                'grado': '',
                'grados': [],
                'periodos': [],
                'lapsos': [],
            },
            request=request,
        )

        self.assertIn('Presentes', resumen_html)
        self.assertIn('Ausentes', resumen_html)
        self.assertNotIn('Observaciones / seguimiento</th>', resumen_html)
        self.assertIn('data-tardanzas="1"', resumen_html)
        self.assertIn('data-observaciones="Observación de prueba"', resumen_html)
        self.assertIn('data-seguimiento="Seguimiento de prueba"', resumen_html)
        self.assertIn('aria-label="Ver resumen completo de asistencia de Estudiante Lectura"', resumen_html)
        self.assertIn('id="closeAttendanceSummary">Cerrar</button>', resumen_html)
        self.assertIn("event.key === 'Escape'", resumen_html)
        self.assertIn('aria-label="Descargar reporte de asistencia por lapso en PDF de Estudiante Lectura"', resumen_html)
        self.assertNotIn('PDF del estudiante</a>', resumen_html)
        self.assertNotIn(reverse('admin_editar_resumen_asistencia_lapso', args=[resumen.pk]), resumen_html)
        self.assertNotIn('Editar resumen', resumen_html)

        asistencia = Asistencia.objects.create(
            estudiante=self.estudiante,
            fecha=date(2026, 10, 20),
            estado='PRESENTE',
        )
        asistencia_html = render_to_string(
            'escuelaApp/admin_custom/gestionar_asistencias.html',
            {
                'request': request,
                'asistencias': [asistencia],
                'query': '',
                'grado': '',
                'fecha': '',
                'grados': [],
                'resumen': {},
            },
            request=request,
        )
        self.assertIn('aria-label="Descargar reporte de asistencia en PDF de Estudiante Lectura"', asistencia_html)
        self.assertNotIn('PDF del estudiante</a>', asistencia_html)

    def test_resumen_de_asistencia_guardado_no_se_puede_editar(self):
        from django.contrib.messages import get_messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .models import ResumenAsistenciaLapso

        directora = User.objects.create_user(
            username='directora-resumen-inmutable',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=directora,
            cedula='V-55667790',
            cargo='DIRECTORA',
        )
        resumen = ResumenAsistenciaLapso.objects.create(
            estudiante=self.estudiante,
            periodo='2026-2027',
            lapso='LAPSO_1',
            presentes=35,
            ausentes=2,
            observaciones='No modificar',
        )
        path = reverse('admin_editar_resumen_asistencia_lapso', args=[resumen.pk])
        request = self.factory.post(path, {'presentes': 0, 'observaciones': 'Cambio'})
        request.user = directora
        request.session = {'staff_session_token': 'directora-test'}
        request._messages = FallbackStorage(request)

        response = resolve(path).func(request, resumen_id=resumen.pk)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_resumenes_asistencia_lapso'))
        resumen.refresh_from_db()
        self.assertEqual(resumen.presentes, 35)
        self.assertEqual(resumen.ausentes, 2)
        self.assertEqual(resumen.observaciones, 'No modificar')
        self.assertIn('no se pueden editar', str(list(get_messages(request))[0]))

    def test_asistente_puede_exportar_reportes_individuales_y_grupales_pdf(self):
        from .models import Asistencia, ResumenAsistenciaLapso
        from .registro_academico import RegistroAcademico

        Asistencia.objects.create(estudiante=self.estudiante, fecha=date(2026, 10, 20))
        ResumenAsistenciaLapso.objects.create(
            estudiante=self.estudiante,
            periodo='2026-2027',
            lapso='LAPSO_1',
        )
        RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            area='Matemáticas',
            periodo='2026-2027',
            nota='A',
        )
        reportes = (
            ('admin_exportar_asistencias_pdf', []),
            ('admin_exportar_asistencias_pdf', [self.estudiante.cedula]),
            ('admin_exportar_resumenes_asistencia_lapso_pdf', []),
            ('admin_exportar_resumenes_asistencia_lapso_pdf', [self.estudiante.cedula]),
            ('admin_exportar_registros_academicos_pdf', []),
            ('admin_exportar_registros_academicos_pdf', [self.estudiante.cedula]),
        )
        for ruta, argumentos in reportes:
            with self.subTest(ruta=ruta, individual=bool(argumentos)):
                path = reverse(ruta)
                request = self.factory.get(
                    path,
                    {'estudiante': argumentos[0]} if argumentos else {},
                )
                request.user = self.usuario
                request.session = {'staff_session_token': 'asistente-test'}
                response = resolve(path).func(request)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'application/pdf')
                self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_asistente_no_puede_modificar_datos_academicos_o_estudiantes(self):
        rutas_restringidas = (
            'admin_crear_estudiante',
            'admin_editar_estudiante',
            'admin_eliminar_estudiante',
            'admin_crear_representante',
            'admin_representantes',
            'admin_editar_representante',
            'admin_eliminar_representante',
            'admin_crear_asistencia',
            'admin_crear_registro_academico',
            'admin_editar_registro_academico',
            'admin_crear_resumen_asistencia_lapso',
            'admin_editar_resumen_asistencia_lapso',
            'admin_docentes',
            'gestionar_horarios',
            'crear_horario',
            'admin_mensajes',
            'admin_cuentas',
            'admin_personal',
        )
        for ruta in rutas_restringidas:
            with self.subTest(ruta=ruta):
                argumentos = (
                    [self.estudiante.cedula]
                    if ruta in (
                        'admin_editar_estudiante',
                        'admin_eliminar_estudiante',
                        'admin_editar_representante',
                        'admin_eliminar_representante',
                    )
                    else [999999]
                    if ruta in ('admin_editar_registro_academico', 'admin_editar_resumen_asistencia_lapso')
                    else []
                )
                response = self._solicitar_ruta(ruta, argumentos)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('admin_panel'))

    def test_panel_asistente_no_muestra_enlaces_restringidos(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.template.loader import render_to_string
        from .views import admin_panel_view

        path = reverse('admin_panel')
        request = self.factory.get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'asistente-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        with patch('escuelaApp.views.render') as render_page:
            admin_panel_view(request)

        pagina = render_to_string(
            'escuelaApp/admin_custom/panel_principal.html',
            render_page.call_args.args[2],
            request=request,
        )
        self.assertIn(reverse('admin_estudiantes'), pagina)
        self.assertIn(reverse('admin_asistencias'), pagina)
        self.assertIn(reverse('admin_registro_academico'), pagina)
        self.assertNotIn(reverse('admin_crear_estudiante'), pagina)
        self.assertNotIn(reverse('admin_representantes'), pagina)
        self.assertNotIn('Modificar configuración', pagina)


class DirectoraSidebarTests(TestCase):
    def test_barra_lateral_muestra_estudiantes_y_configuracion(self):
        from django.template.loader import render_to_string

        usuario = User.objects.create_user(
            username='directora-sidebar',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=usuario,
            cedula='V-45678901',
            cargo='DIRECTORA',
        )

        pagina = render_to_string(
            'escuelaApp/includes/sidebar_admin.html',
            {
                'request': SimpleNamespace(
                    user=usuario,
                    resolver_match=SimpleNamespace(url_name='admin_crear_estudiante'),
                ),
            },
        )

        self.assertIn(reverse('admin_estudiantes'), pagina)
        self.assertIn('>Estudiantes</span>', pagina)
        self.assertIn('>Gestión académica</h2>', pagina)
        self.assertIn('>Configuración</h2>', pagina)
        self.assertIn(reverse('admin_modificar_dashboard'), pagina)
        self.assertIn(reverse('admin_modificar_sobre_nosotros'), pagina)
        self.assertIn('sidebar-active', pagina)


class CoordinadorPermisosTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(
            username='coordinador-panel',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=self.usuario,
            cedula='V-34567890',
            cargo='COORD',
        )
        self.factory = RequestFactory()

    def _solicitar_ruta(self, nombre, argumentos=None):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.urls import resolve

        path = reverse(nombre, args=argumentos or [])
        request = self.factory.get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'coordinator-test'}
        request._messages = FallbackStorage(request)
        return resolve(path).func(request)

    def test_coordinador_no_puede_abrir_secciones_administrativas(self):
        rutas_restringidas = (
            'admin_asignaciones',
            'registrar_asignacion',
            'gestionar_horarios',
            'dashboard_pedagogico',
            'admin_representantes',
            'admin_crear_representante',
            'admin_mensajes',
            'admin_personal',
            'admin_cuentas',
            'admin_crear_usuario',
            'admin_modificar_dashboard',
            'admin_modificar_sobre_nosotros',
            'sistema_administrativo',
        )
        for ruta in rutas_restringidas:
            with self.subTest(ruta=ruta):
                response = self._solicitar_ruta(ruta)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('admin_panel'))

        response = self._solicitar_ruta('admin_eliminar_usuario', [self.usuario.pk])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_panel'))
        for ruta in ('admin_editar_representante', 'admin_eliminar_representante'):
            with self.subTest(ruta=ruta):
                response = self._solicitar_ruta(ruta, ['V-34567890'])
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('admin_panel'))

    def test_navegacion_de_coordinacion_no_muestra_representantes(self):
        from django.template.loader import render_to_string

        page = render_to_string(
            'escuelaApp/includes/sidebar_admin.html',
            {'request': SimpleNamespace(user=self.usuario, resolver_match=SimpleNamespace(url_name='admin_panel'))},
        )
        self.assertNotIn(reverse('admin_representantes'), page)

    def test_coordinador_no_puede_abrir_el_admin_de_django(self):
        from django.contrib.sessions.backends.db import SessionStore
        from django.utils import timezone
        from .middleware import ActiveStaffAccessMiddleware

        request = self.factory.get('/admin/')
        request.user = self.usuario
        request.session = SessionStore()
        request.session['staff_session_token'] = 'coordinator-test'
        request.session['last_staff_activity'] = timezone.now().timestamp()

        response = ActiveStaffAccessMiddleware(lambda current_request: HttpResponse(status=200))(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_panel'))

    def test_coordinador_conserva_sus_cuatro_secciones(self):
        from . import views, views_asistencia, views_registro_academico

        rutas_permitidas = (
            ('admin_estudiantes', views),
            ('admin_docentes', views),
            ('admin_registro_academico', views_registro_academico),
            ('admin_asistencias', views_asistencia),
        )
        for ruta, modulo in rutas_permitidas:
            with self.subTest(ruta=ruta):
                path = reverse(ruta)
                request = self.factory.get(path)
                request.user = self.usuario
                request.session = {'staff_session_token': 'coordinator-test'}
                with patch(f'{modulo.__name__}.render', return_value=HttpResponse(status=200)):
                    response = resolve(path).func(request)
                self.assertEqual(response.status_code, 200)


class DashboardPedagogicoTests(TestCase):
    def setUp(self):
        usuario = User.objects.create_superuser(
            username='admin-dashboard',
            email='admin-dashboard@example.com',
            password='Password123',
        )
        self.client.force_login(usuario)

    def test_dashboard_muestra_alumno_en_recuperacion_sin_porcentaje(self):
        from .views import dashboard_pedagogico

        estudiante = Estudiante.objects.create(
            nombre='Ana', apellido='Pérez', cedula='V-12345678', grado='1RO'
        )
        RegistroAcademico.objects.create(
            estudiante=estudiante,
            area='Lengua',
            periodo='2026-2027',
            estado='Recuperación',
        )
        request = RequestFactory().get('/admin-panel/coordinacion/pedagogico/', {'periodo': '2026-2027'})
        request.user = User.objects.get(username='admin-dashboard')

        with patch('escuelaApp.views.render') as render_page:
            inspect.unwrap(dashboard_pedagogico)(request)

        context = render_page.call_args.args[2]
        self.assertEqual(render_page.call_args.args[1], 'escuelaApp/admin_custom/dashboard_pedagogico.html')
        self.assertEqual(context['total_alumnos_en_riesgo'], 1)
        self.assertEqual(context['resumen_por_grado'][0]['en_riesgo'], 1)
        self.assertIsNone(context['alumnos_en_riesgo'][0]['promedio'])

    def test_panel_directora_muestra_enlaces_a_modulos_autorizados(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.template.loader import render_to_string
        from .views import admin_panel_view

        directora = User.objects.get(username='admin-dashboard')
        Empleado.objects.create(user=directora, cedula='V-76543210', cargo='DIRECTORA')
        path = reverse('admin_panel')
        request = RequestFactory().get(path)
        request.user = directora
        request.session = {'staff_session_token': 'directora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        with patch('escuelaApp.views.render') as render_page:
            admin_panel_view(request)

        pagina = render_to_string(
            'escuelaApp/admin_custom/panel_principal.html',
            render_page.call_args.args[2],
            request=request,
        )
        self.assertNotIn('Próximos horarios', pagina)
        for ruta in (
            'subdireccion_solicitudes_matricula',
            'subdireccion_asistencia_personal',
            'admin_cuentas',
            'admin_personal',
            'historial_reportes_sistema',
        ):
            with self.subTest(ruta=ruta):
                self.assertIn(reverse(ruta), pagina)

    def test_cuentas_y_exportacion_de_horarios_responden_correctamente(self):
        from .views import admin_cuentas_view

        request = RequestFactory().get('/admin-panel/cuentas/')
        request.user = User.objects.get(username='admin-dashboard')
        with patch('escuelaApp.views.render') as render_page:
            inspect.unwrap(admin_cuentas_view)(request)
        with patch('escuelaApp.views.enviar_reporte_a_directora') as enviar:
            pdf = self.client.get(reverse('exportar_horarios_pdf'))

        context = render_page.call_args.args[2]
        self.assertEqual(render_page.call_args.args[1], 'escuelaApp/admin_custom/gestionar_cuentas.html')
        self.assertEqual(context['total_cuentas'], 1)
        self.assertEqual(context['resultados'], 1)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        enviar.assert_called_once_with('horarios.pdf', pdf.content, 'application/pdf')


class ExportarEstudiantesPdfTests(TestCase):
    def setUp(self):
        user = User.objects.create_superuser(
            username='admin-pdf',
            email='admin-pdf@example.com',
            password='Password123',
        )
        self.client.force_login(user)

    def test_exportacion_pdf_devuelve_un_documento_pdf(self):
        with patch('escuelaApp.views.enviar_reporte_a_directora') as enviar:
            response = self.client.get(reverse('admin_exportar_estudiantes_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        enviar.assert_called_once_with('lista_estudiantes.pdf', response.content, 'application/pdf')

    def test_exportacion_pdf_filtra_por_periodo_y_rango_de_grados(self):
        primero = Estudiante.objects.create(nombre='Ana', apellido='Alvarez', cedula='V-11111111', grado='1RO')
        segundo = Estudiante.objects.create(nombre='Bea', apellido='Bravo', cedula='V-22222222', grado='2DO')
        tercero = Estudiante.objects.create(nombre='Ciro', apellido='Castro', cedula='V-33333333', grado='3RO')
        RegistroAcademico.objects.create(estudiante=primero, area='Lengua', periodo='2025-2026')
        RegistroAcademico.objects.create(estudiante=segundo, area='Lengua', periodo='2026-2027')
        RegistroAcademico.objects.create(estudiante=tercero, area='Lengua', periodo='2025-2026')

        with patch('reportlab.platypus.SimpleDocTemplate.build') as build_pdf:
            response = self.client.get(reverse('admin_exportar_estudiantes_pdf'), {
                'periodo': '2025-2026',
                'desde_grado': '1RO',
                'hasta_grado': '2DO',
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        tabla = build_pdf.call_args.args[0][-1]
        nombres_exportados = [fila[0].getPlainText() for fila in tabla._cellvalues[1:]]
        self.assertEqual(nombres_exportados, ['Ana Alvarez'])

    def test_exportacion_pdf_rechaza_rango_de_grados_invertido(self):
        response = self.client.get(reverse('admin_exportar_estudiantes_pdf'), {
            'desde_grado': '4TO',
            'hasta_grado': '2DO',
        })

        self.assertEqual(response.status_code, 400)


class RegistrosDocentesPorLapsoTests(TestCase):
    def setUp(self):
        from .models import Docente, Horario

        self.estudiante = Estudiante.objects.create(
            nombre='Ana', apellido='Alvarez', cedula='V-80000001', grado='1RO'
        )
        self.otro_estudiante = Estudiante.objects.create(
            nombre='Bea', apellido='Bravo', cedula='V-80000002', grado='2DO'
        )
        self.user = User.objects.create_user(
            username='docente-lapso',
            password='Password123',
            first_name='Carlos',
            last_name='Mendoza',
            is_staff=True,
        )
        self.empleado = Empleado.objects.create(
            user=self.user,
            cedula='V-80000003',
            cargo='DOCENTE',
        )
        self.docente = Docente.objects.create(
            nombre='Carlos',
            apellido='Mendoza',
            cedula=self.empleado.cedula,
        )
        Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=self.docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )

    def test_nota_requiere_lapso_y_no_admite_duplicado(self):
        datos = {
            'estudiante_cedula': str(self.estudiante.pk),
            'docente_cedula': f'emp:{self.empleado.pk}',
            'area': 'Matemáticas',
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'tipo_evaluacion': 'Final',
            'nota': 'B',
            'estado': 'Aprobado',
        }
        form = RegistroAcademicoForm(data=datos)
        self.assertTrue(form.is_valid(), form.errors)
        registro = form.save()
        self.assertEqual(registro.porcentaje, Decimal('80.00'))
        self.assertEqual(registro.lapso, 'LAPSO_1')

        duplicado = RegistroAcademicoForm(data=datos)
        self.assertFalse(duplicado.is_valid())
        self.assertIn('lapso', duplicado.errors)

        datos['lapso'] = 'LAPSO_2'
        otra_nota = RegistroAcademicoForm(data=datos)
        self.assertTrue(otra_nota.is_valid(), otra_nota.errors)

    def test_docente_solo_puede_registrar_sus_estudiantes_y_materias(self):
        datos = {
            'estudiante_cedula': str(self.estudiante.pk),
            'docente_cedula': f'emp:{self.empleado.pk}',
            'area': 'Matemáticas',
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'tipo_evaluacion': 'Final',
            'nota': 'A',
            'estado': 'Aprobado',
        }
        form = RegistroAcademicoForm(data=datos, actor=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().docente, self.empleado)
        materias_disponibles = {
            value for value, _ in form.fields['area'].choices if value
        }
        self.assertEqual(materias_disponibles, {'Matemáticas'})

        datos['estudiante_cedula'] = str(self.otro_estudiante.pk)
        form = RegistroAcademicoForm(data=datos, actor=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('estudiante_cedula', form.errors)

    def test_directivo_no_puede_registrar_materia_que_no_esta_en_horario_del_grado(self):
        datos = {
            'estudiante_cedula': str(self.otro_estudiante.pk),
            'docente_cedula': f'emp:{self.empleado.pk}',
            'area': 'Lengua',
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'tipo_evaluacion': 'Final',
            'nota': 'A',
            'estado': 'Aprobado',
        }
        form = RegistroAcademicoForm(data=datos)

        self.assertFalse(form.is_valid())
        self.assertIn('area', form.errors)

    def test_asignacion_expresa_habilita_registro_para_docente_sin_horario(self):
        from .models import Asignacion, Docente
        from .docente_scope import (
            docente_puede_atender_estudiante,
            estudiantes_del_docente,
            filtrar_registros_docente,
            materias_del_docente,
        )
        from .views import _datos_estudiantes_docente

        asignado = Estudiante.objects.create(
            nombre='Estudiante', apellido='Asignado', cedula='V-80000005', grado='4TO'
        )
        user_sin_horario = User.objects.create_user(
            username='docente-sin-horario',
            first_name='Docente',
            last_name='Sin Horario',
            is_staff=True,
        )
        empleado_sin_horario = Empleado.objects.create(
            user=user_sin_horario,
            cedula='V-80000006',
            cargo='DOCENTE',
        )
        docente_sin_horario = Docente.objects.create(
            nombre='Docente',
            apellido='Sin Horario',
            cedula=empleado_sin_horario.cedula,
        )
        Asignacion.objects.create(
            estudiante=asignado,
            docente=empleado_sin_horario,
            area='Ciencias Naturales',
            periodo='2026-2027',
        )
        datos = {
            'estudiante_cedula': str(asignado.pk),
            'docente_cedula': f'emp:{empleado_sin_horario.pk}',
            'area': 'Ciencias Naturales',
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'tipo_evaluacion': 'Final',
            'nota': 'A',
            'estado': 'Aprobado',
        }
        form = RegistroAcademicoForm(data=datos, actor=user_sin_horario)
        self.assertTrue(form.is_valid(), form.errors)
        registro = form.save()

        self.assertIn(asignado, estudiantes_del_docente(docente_sin_horario))
        self.assertEqual(materias_del_docente(docente_sin_horario), ['Ciencias Naturales'])
        self.assertTrue(docente_puede_atender_estudiante(
            docente_sin_horario, asignado, 'Ciencias Naturales'
        ))
        self.assertTrue(filtrar_registros_docente(
            RegistroAcademico.objects.all(), docente_sin_horario
        ).filter(pk=registro.pk).exists())
        self.assertEqual(registro.asignacion.docente, empleado_sin_horario)
        _, grupos = _datos_estudiantes_docente(docente_sin_horario)
        self.assertEqual(len(grupos), 1)
        self.assertIn(asignado, grupos[0]['estudiantes'])
        self.assertIn('Ciencias Naturales', grupos[0]['materias'])

    def test_docente_no_puede_editar_nota_de_otro_grado(self):
        from .docente_scope import filtrar_registros_docente

        otro_user = User.objects.create_user(username='otro-docente')
        otro_empleado = Empleado.objects.create(
            user=otro_user,
            cedula='V-80000004',
            cargo='DOCENTE',
        )
        registro = RegistroAcademico.objects.create(
            estudiante=self.otro_estudiante,
            docente=otro_empleado,
            area='Matemáticas',
            periodo='2026-2027',
            lapso='LAPSO_1',
            nota='A',
        )
        registro_mismo_grado = RegistroAcademico.objects.create(
            estudiante=self.estudiante,
            docente=otro_empleado,
            area='Matemáticas',
            periodo='2026-2027',
            lapso='LAPSO_1',
            nota='A',
        )
        registros_del_docente = filtrar_registros_docente(
            RegistroAcademico.objects.all(),
            self.docente,
        )
        self.assertFalse(registros_del_docente.filter(pk=registro.pk).exists())
        self.assertFalse(registros_del_docente.filter(pk=registro_mismo_grado.pk).exists())

    def test_resumen_asistencia_es_unico_por_estudiante_periodo_y_lapso(self):
        from .forms_asistencia import ResumenAsistenciaLapsoForm

        datos = {
            'estudiante_cedula': str(self.estudiante.pk),
            'periodo': '2026-2027',
            'lapso': 'LAPSO_1',
            'presentes': '35',
            'ausentes': '2',
            'tardanzas': '1',
            'justificadas': '1',
            'observaciones': 'Seguimiento regular.',
            'seguimiento': 'Contactar representante si persisten las ausencias.',
        }
        form = ResumenAsistenciaLapsoForm(data=datos, actor=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        resumen = form.save()
        self.assertEqual(resumen.estudiante, self.estudiante)
        self.assertEqual(resumen.ausentes, 2)

        duplicado = ResumenAsistenciaLapsoForm(data=datos, actor=self.user)
        self.assertFalse(duplicado.is_valid())
        self.assertIn('lapso', duplicado.errors)

        datos['lapso'] = 'LAPSO_2'
        otro_lapso = ResumenAsistenciaLapsoForm(data=datos, actor=self.user)
        self.assertTrue(otro_lapso.is_valid(), otro_lapso.errors)


@override_settings(
    WHATSAPP_ACCESS_TOKEN='test-meta-token',
    WHATSAPP_PHONE_NUMBER_ID='123456789',
    WHATSAPP_RECIPIENT='+58041282848237',
    WHATSAPP_TEMPLATE_NAME='escuela_contacto_nuevo',
    WHATSAPP_TEMPLATE_LANGUAGE='es',
    WHATSAPP_API_VERSION='v23.0',
)
class WhatsAppCloudApiTests(TestCase):
    def _create_contact_representative(self):
        return Representante.objects.get_or_create(
            cedula='V-12345678',
            defaults={
                'nombre': 'Familia',
                'apellido': 'de prueba',
                'email': 'familia@example.com',
            },
        )

    def _post_contact(self, **overrides):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from .views_portal import portal_contact

        self._create_contact_representative()
        data = {
            'nombre': 'Familia de prueba',
            'cedula': '12345678',
            'tipo_identificacion': 'V',
            'email': 'familia@example.com',
            'asunto': 'Consulta escolar',
            'mensaje': 'Quisiera información.',
        }
        data.update(overrides)
        request = RequestFactory().post(reverse('portal_contact'), data)
        request.session = {}
        request._messages = FallbackStorage(request)
        return portal_contact(request), request

    def test_meta_envia_plantilla_aprobada_al_numero_en_formato_internacional(self):
        import json

        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"messages":[{"id":"wamid.test-message"}]}'
        )
        with patch('escuelaApp.whatsapp.urlopen', return_value=response) as urlopen:
            from .whatsapp import send_contact_notification

            resultado = send_contact_notification()

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v23.0/123456789/messages')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-meta-token')
        self.assertEqual(payload, {
            'messaging_product': 'whatsapp',
            'to': '5841282848237',
            'type': 'template',
            'template': {
                'name': 'escuela_contacto_nuevo',
                'language': {'code': 'es'},
            },
        })
        self.assertEqual(resultado['messages'][0]['id'], 'wamid.test-message')

    def test_meta_http_error_se_reporta_como_error_de_entrega(self):
        from urllib.error import HTTPError

        from .whatsapp import WhatsAppDeliveryError, send_contact_notification

        error = HTTPError(
            'https://graph.facebook.com',
            400,
            'Bad Request',
            {},
            BytesIO(b''),
        )
        with patch('escuelaApp.whatsapp.urlopen', side_effect=error):
            with self.assertRaises(WhatsAppDeliveryError):
                send_contact_notification()

    @override_settings(WHATSAPP_ACCESS_TOKEN='')
    def test_meta_requiere_credenciales(self):
        from .whatsapp import WhatsAppConfigurationError, send_contact_notification

        with self.assertRaises(WhatsAppConfigurationError):
            send_contact_notification()

    def test_formulario_guarda_contacto_sin_destinatarios_configurados(self):
        from django.contrib.messages import get_messages
        from .models import ContactoMensaje

        response, request = self._post_contact()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('portal_contact'))
        self.assertEqual(ContactoMensaje.objects.count(), 1)
        notification = str(list(get_messages(request))[0])
        self.assertIn('Recibimos tu mensaje', notification)
        self.assertNotIn('notificaciones', notification)

    def test_formulario_notifica_a_personal_configurado_y_contacto(self):
        from django.contrib.messages import get_messages
        from .models import ContactoMensaje

        with patch(
            'escuelaApp.views_portal.notify_new_contact',
            return_value={'staff_count': 2, 'failures': 0},
        ) as notify:
            response, request = self._post_contact()

        self.assertEqual(response.status_code, 302)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], ContactoMensaje.objects.get())
        self.assertIn('Recibimos tu mensaje', str(list(get_messages(request))[0]))

    def test_formulario_bloquea_envio_si_cedula_y_correo_no_coinciden(self):
        from .models import ContactoMensaje

        response, request = self._post_contact(cedula='87654321')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La cédula y el correo no coinciden')
        self.assertEqual(ContactoMensaje.objects.count(), 0)
        self.assertEqual(list(request._messages)[0].level_tag, 'error')

    def test_formulario_compara_correo_sin_distinguir_mayusculas(self):
        from .models import ContactoMensaje

        response, _ = self._post_contact(email='FAMILIA@EXAMPLE.COM')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactoMensaje.objects.count(), 1)

    def test_formulario_acepta_cedula_de_representante_extranjera(self):
        from .models import ContactoMensaje

        Representante.objects.create(
            nombre='Familia',
            apellido='extranjera',
            cedula='E-123456',
            email='familia@example.com',
        )
        response, _ = self._post_contact(
            cedula='123456',
            tipo_identificacion='E',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactoMensaje.objects.count(), 1)

    def test_formulario_acepta_limites_validos_de_cedulas(self):
        from .models import ContactoMensaje

        Representante.objects.create(
            nombre='Familia',
            apellido='venezolana',
            cedula='V-1234567',
            email='familia@example.com',
        )
        response, _ = self._post_contact(cedula='1234567')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactoMensaje.objects.count(), 1)

        Representante.objects.create(
            nombre='Familia',
            apellido='extranjera',
            cedula='E-123456789',
            email='familia@example.com',
        )
        response, _ = self._post_contact(
            cedula='123456789',
            tipo_identificacion='E',
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactoMensaje.objects.count(), 2)

    def test_formulario_rechaza_cedula_que_no_cumple_formato_seleccionado(self):
        from .models import ContactoMensaje

        response, _ = self._post_contact(
            cedula='123456',
            tipo_identificacion='V',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La cédula venezolana debe contener exactamente 7 u 8 dígitos')
        self.assertEqual(ContactoMensaje.objects.count(), 0)

    def test_formulario_exige_tipo_y_numero_de_cedula_estricto(self):
        from .models import ContactoMensaje

        response, _ = self._post_contact(tipo_identificacion='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecciona si la cédula es venezolana o extranjera')
        self.assertEqual(ContactoMensaje.objects.count(), 0)

        response, _ = self._post_contact(cedula='1234 5678')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactoMensaje.objects.count(), 0)

    def test_formulario_guarda_telefono_internacional_y_consentimiento(self):
        from .models import ContactoMensaje
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from .views_portal import portal_contact

        self._create_contact_representative()
        request = RequestFactory().post(reverse('portal_contact'), {
            'nombre': 'Familia de prueba',
            'cedula': '12345678',
            'tipo_identificacion': 'V',
            'email': 'familia@example.com',
            'telefono': '+584121234567',
            'acepta_whatsapp': 'on',
            'asunto': 'Consulta escolar',
            'mensaje': 'Quisiera información.',
        })
        request.session = {}
        request._messages = FallbackStorage(request)

        with patch(
            'escuelaApp.views_portal.notify_new_contact',
            return_value={'staff_count': 1, 'failures': 0},
        ):
            response = portal_contact(request)

        contacto = ContactoMensaje.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(contacto.telefono, '+584121234567')
        self.assertTrue(contacto.acepta_whatsapp)

    def test_formulario_rechaza_telefono_que_no_sea_prefijo_venezolano_y_siete_digitos(self):
        from .models import ContactoMensaje
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from .views_portal import portal_contact

        self._create_contact_representative()
        request = RequestFactory().post(reverse('portal_contact'), {
            'nombre': 'Familia de prueba',
            'cedula': '12345678',
            'tipo_identificacion': 'V',
            'email': 'familia@example.com',
            'telefono': '+58412123ABCD',
            'acepta_whatsapp': 'on',
            'asunto': 'Consulta escolar',
            'mensaje': 'Quisiera información.',
        })
        request.session = {}
        request._messages = FallbackStorage(request)

        response = portal_contact(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactoMensaje.objects.count(), 0)

    def test_notifica_solo_a_personal_activo_seleccionado(self):
        from django.contrib.auth.models import User
        from .contact_notifications import notify_new_contact
        from .models import ContactoMensaje, Empleado

        seleccionado = User.objects.create_user(
            username='personal-telegram',
            password='test-password',
            is_staff=True,
        )
        Empleado.objects.create(
            user=seleccionado,
            cedula='V-76543210',
            cargo='ASISTENTE',
            telegram_chat_id='111222333',
            notificar_contactos_telegram=True,
        )
        no_seleccionado = User.objects.create_user(
            username='personal-no-telegram',
            password='test-password',
            is_staff=True,
        )
        Empleado.objects.create(
            user=no_seleccionado,
            cedula='V-76543211',
            cargo='ASISTENTE',
            telegram_chat_id='444555666',
        )
        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            mensaje='Consulta',
        )

        with patch('escuelaApp.contact_notifications.send_telegram_message') as send_message:
            resultado = notify_new_contact(contacto)

        self.assertEqual(resultado, {'staff_count': 1, 'failures': 0})
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], '111222333')

    def test_notifica_al_contacto_por_whatsapp_con_consentimiento(self):
        from .contact_notifications import notify_new_contact
        from .models import ContactoMensaje

        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            telefono='+584121234567',
            acepta_whatsapp=True,
            mensaje='Consulta',
        )

        with patch('escuelaApp.contact_notifications.send_telegram_message') as telegram:
            with patch('escuelaApp.contact_notifications.send_contact_whatsapp') as whatsapp:
                resultado = notify_new_contact(contacto)

        self.assertEqual(resultado, {'staff_count': 0, 'failures': 0})
        telegram.assert_not_called()
        whatsapp.assert_called_once_with(
            '+584121234567',
            'Recibimos tu mensaje de contacto. Gracias por escribirnos; '
            'la escuela te responderá pronto.',
        )


@override_settings(TELEGRAM_BOT_TOKEN='123456:example-token')
class TelegramBotApiTests(TestCase):
    def test_envia_respuesta_al_chat_id_del_contacto(self):
        import json

        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"ok":true,"result":{"message_id":123}}'
        )
        with patch('escuelaApp.telegram.urlopen', return_value=response) as urlopen:
            from .telegram import send_telegram_message

            resultado = send_telegram_message('987654321', 'Hola, recibimos tu mensaje.')

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            'https://api.telegram.org/bot123456:example-token/sendMessage',
        )
        self.assertEqual(json.loads(request.data.decode('utf-8')), {
            'chat_id': '987654321',
            'text': 'Hola, recibimos tu mensaje.',
        })
        self.assertTrue(resultado['ok'])

    def test_formulario_ya_no_acepta_chat_id_de_telegram(self):
        from .models import ContactoMensaje
        from .views_portal import portal_contact
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        Representante.objects.get_or_create(
            cedula='V-12345678',
            defaults={
                'nombre': 'Familia',
                'apellido': 'de prueba',
                'email': 'familia@example.com',
            },
        )
        request = RequestFactory().post(reverse('portal_contact'), {
            'nombre': 'Familia de prueba',
            'cedula': '12345678',
            'tipo_identificacion': 'V',
            'email': 'familia@example.com',
            'asunto': 'Consulta escolar',
            'mensaje': 'Quisiera información.',
            'telegram_chat_id': '987654321',
        })
        request.session = {}
        request._messages = FallbackStorage(request)

        with patch(
            'escuelaApp.views_portal.notify_new_contact',
            return_value={'staff_count': 1, 'failures': 0},
        ):
            response = portal_contact(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactoMensaje.objects.get().telegram_chat_id, '')

    def test_formulario_de_contacto_no_muestra_chat_id_de_telegram(self):
        from .views_portal import portal_contact

        response = self.client.get(reverse('portal_contact'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Chat ID de Telegram')
        self.assertNotContains(response, 'telegram_chat_id')
        self.assertContains(response, 'minlength="7" maxlength="8" pattern="[0-9]{7,8}"')
        self.assertContains(response, "cedula.minLength = venezolana ? 7 : 6")
        self.assertContains(response, "cedula.maxLength = venezolana ? 8 : 9")
        self.assertContains(response, "slice(0, cedula.maxLength)")
        self.assertContains(response, "cedula.setCustomValidity(cedula.value && !cedulaCompleta ? error : '')")
        self.assertContains(response, "wrapper.classList.toggle('has-error', isCedula && !isValid)")
        self.assertContains(response, "badge.textContent = isCedula")

    def test_admin_puede_enviar_respuesta_al_chat_guardado(self):
        from django.contrib.auth.models import User
        from django.test import Client
        from .models import ContactoMensaje

        usuario = User.objects.create_superuser(
            username='directora-telegram',
            email='directora@example.com',
            password='test-password',
        )
        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            telegram_chat_id='987654321',
            mensaje='Quisiera información.',
        )
        client = Client()
        client.force_login(usuario)

        with patch('escuelaApp.views.send_telegram_message') as send_message:
            response = client.post(
                reverse('admin_responder_mensaje_telegram', args=[contacto.pk]),
                {'respuesta': 'Claro, con gusto.'},
            )

        self.assertEqual(response.status_code, 302)
        send_message.assert_called_once_with('987654321', 'Claro, con gusto.')

    @override_settings(TELEGRAM_BOT_TOKEN='')
    def test_requiere_token_de_bot(self):
        from .telegram import TelegramConfigurationError, send_telegram_message

        with self.assertRaises(TelegramConfigurationError):
            send_telegram_message('987654321', 'Respuesta')

    def test_http_error_se_reporta_como_error_de_entrega(self):
        from urllib.error import HTTPError
        from .telegram import TelegramDeliveryError, send_telegram_message

        error = HTTPError(
            'https://api.telegram.org',
            400,
            'Bad Request',
            {},
            BytesIO(b''),
        )
        with patch('escuelaApp.telegram.urlopen', side_effect=error):
            with self.assertRaises(TelegramDeliveryError):
                send_telegram_message('987654321', 'Respuesta')


@override_settings(
    WHATSAPP_ACCESS_TOKEN='test-meta-token',
    WHATSAPP_PHONE_NUMBER_ID='123456789',
    WHATSAPP_API_VERSION='v23.0',
    WHATSAPP_CONTACT_REPLY_TEMPLATE_NAME='escuela_respuesta_contacto',
    WHATSAPP_CONTACT_REPLY_TEMPLATE_LANGUAGE='es',
)
class WhatsAppContactReplyTests(TestCase):
    def test_meta_envia_respuesta_plantilla_al_numero_consentido(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {'messages': [{'id': 'wamid.response123'}]}
        ).encode('utf-8')

        with patch('escuelaApp.whatsapp.urlopen', return_value=response) as urlopen:
            from .whatsapp import send_contact_whatsapp

            resultado = send_contact_whatsapp('04121234567', 'Recibimos tu mensaje.')

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(
            request.full_url,
            'https://graph.facebook.com/v23.0/123456789/messages',
        )
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-meta-token')
        self.assertEqual(payload, {
            'messaging_product': 'whatsapp',
            'to': '584121234567',
            'type': 'template',
            'template': {
                'name': 'escuela_respuesta_contacto',
                'language': {'code': 'es'},
                'components': [{
                    'type': 'body',
                    'parameters': [{
                        'type': 'text',
                        'text': 'Recibimos tu mensaje.',
                    }],
                }],
            },
        })
        self.assertEqual(resultado['messages'][0]['id'], 'wamid.response123')

    def test_meta_rechaza_respuestas_fuera_del_limite_de_plantilla(self):
        from .whatsapp import WhatsAppDeliveryError, send_contact_whatsapp

        with self.assertRaises(WhatsAppDeliveryError):
            send_contact_whatsapp('04121234567', 'x' * 1025)

    def test_admin_responde_por_whatsapp_solo_con_consentimiento(self):
        from django.test import Client
        from .models import ContactoMensaje

        usuario = User.objects.create_superuser(
            username='directora-whatsapp',
            email='directora-whatsapp@example.com',
            password='test-password',
        )
        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            telefono='+584121234567',
            acepta_whatsapp=True,
            mensaje='Consulta',
        )
        client = Client()
        client.force_login(usuario)

        with patch('escuelaApp.views.send_contact_whatsapp') as send_message:
            response = client.post(
                reverse('admin_responder_mensaje', args=[contacto.pk]),
                {
                    'canal': 'whatsapp',
                    'respuesta': 'Recibimos tu consulta.',
                    'confirmar_destinatario': 'on',
                },
            )

        self.assertEqual(response.status_code, 302)
        send_message.assert_called_once_with(
            '+584121234567',
            'Recibimos tu consulta.',
        )

        contacto.acepta_whatsapp = False
        contacto.save(update_fields=['acepta_whatsapp'])
        with patch('escuelaApp.views.send_contact_whatsapp') as send_message:
            response = client.post(
                reverse('admin_responder_mensaje_whatsapp', args=[contacto.pk]),
                {'respuesta': 'Otro mensaje.'},
            )

        self.assertEqual(response.status_code, 302)
        send_message.assert_not_called()

    def test_admin_puede_responder_por_correo(self):
        from django.test import Client
        from .models import ContactoMensaje

        usuario = User.objects.create_superuser(
            username='directora-correo-contacto',
            email='directora-correo@example.com',
            password='test-password',
        )
        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            asunto='Información escolar',
            mensaje='Consulta sobre el estudiante.',
        )
        client = Client()
        client.force_login(usuario)

        with patch('escuelaApp.views.send_mail', return_value=1) as send_email:
            response = client.post(
                reverse('admin_responder_mensaje', args=[contacto.pk]),
                {
                    'canal': 'correo',
                    'respuesta': 'Información solicitada.',
                    'confirmar_destinatario': 'on',
                },
            )

        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once_with(
            subject='Respuesta: Información escolar',
            message='Información solicitada.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=['familia@example.com'],
            fail_silently=False,
        )

    def test_respuesta_se_bloquea_si_no_confirma_destinatario(self):
        from django.test import Client
        from .models import ContactoMensaje

        usuario = User.objects.create_superuser(
            username='directora-sin-confirmacion',
            email='directora-confirmacion@example.com',
            password='test-password',
        )
        contacto = ContactoMensaje.objects.create(
            nombre='Familia de prueba',
            email='familia@example.com',
            mensaje='Consulta.',
        )
        client = Client()
        client.force_login(usuario)

        with patch('escuelaApp.views.send_mail') as send_email:
            response = client.post(
                reverse('admin_responder_mensaje', args=[contacto.pk]),
                {'canal': 'correo', 'respuesta': 'Información solicitada.'},
            )

        self.assertEqual(response.status_code, 302)
        send_email.assert_not_called()

    def test_detalle_muestra_solo_estudiantes_del_representante_coincidente(self):
        from django.http import HttpResponse
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory
        from .models import ContactoMensaje, Estudiante, Representante
        from .views import admin_mensajes_view

        usuario = User.objects.create_superuser(
            username='directora-detalle-contacto',
            email='directora-detalle@example.com',
            password='test-password',
        )
        representante = Representante.objects.create(
            nombre='María',
            apellido='Familia',
            cedula='V-81818181',
            email='familia@example.com',
        )
        Estudiante.objects.create(
            nombre='Daniel',
            apellido='Familia',
            cedula='V-91919191',
            grado='3ER GRADO',
            representante=representante,
        )
        otro_representante = Representante.objects.create(
            nombre='Otro',
            apellido='Representante',
            cedula='V-71717171',
            email='otro@example.com',
        )
        Estudiante.objects.create(
            nombre='Estudiante',
            apellido='Ajeno',
            cedula='V-61616161',
            grado='6TO GRADO',
            representante=otro_representante,
        )
        ContactoMensaje.objects.create(
            nombre='María Familia',
            email='familia@example.com',
            mensaje='Consulta de prueba.',
        )
        request = RequestFactory().get('/admin-panel/mensajes/')
        request.user = usuario
        request.session = SessionStore()

        with patch('escuelaApp.views.render', return_value=HttpResponse()) as render_view:
            response = admin_mensajes_view(request)

        self.assertEqual(response.status_code, 200)
        mensajes = render_view.call_args.args[2]['mensajes']
        self.assertEqual(len(mensajes[0].estudiantes_relacionados), 1)
        self.assertEqual(
            mensajes[0].estudiantes_relacionados[0].nombre,
            'Daniel',
        )


class HorariosPortalTests(TestCase):
    def test_portal_agrupa_horarios_por_grado_y_dia_en_orden_semanal(self):
        from django.test import RequestFactory

        from .models import Docente, Horario
        from .views_portal import portal_home

        docente = Docente.objects.create(nombre='Laura', apellido='Pérez', cedula='V-55443322')
        Horario.objects.create(
            ano='2ANO',
            materia='Ciencias',
            docente=docente,
            dia='MI',
            hora_inicio='09:00',
            hora_fin='10:00',
        )
        request = RequestFactory().get('/portal/')
        request.session = {}

        with patch('escuelaApp.views_portal.render') as render_portal:
            portal_home(request)

        context = render_portal.call_args.args[2]
        grupos = list(context['grouped_horarios'])
        grupo_segundo = next(grupo for grupo in grupos if grupo['display'] == '2do Grado')
        self.assertEqual(
            [dia['name'] for dia in grupo_segundo['dias']],
            ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes'],
        )
        miercoles = next(dia for dia in grupo_segundo['dias'] if dia['code'] == 'MI')
        self.assertIn('Ciencias', [horario.materia for horario in miercoles['items']])

    def test_horario_rechaza_solapamiento_de_grado_y_docente(self):
        from django.core.exceptions import ValidationError

        from .models import Docente, Horario

        docente = Docente.objects.create(nombre='Ana', apellido='Rojas', cedula='V-11223344')
        Horario.objects.create(
            ano='3ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00:00',
            hora_fin='09:00:00',
        )

        con_mismo_grado = Horario(
            ano='3ANO',
            materia='Historia',
            docente=docente,
            dia='LU',
            hora_inicio='08:30:00',
            hora_fin='09:30:00',
        )
        with self.assertRaisesMessage(
            ValidationError,
            'el grado ya tiene una clase ocupando esa hora',
        ):
            con_mismo_grado.full_clean()

        con_mismo_docente = Horario(
            ano='4ANO',
            materia='Lengua',
            docente=docente,
            dia='LU',
            hora_inicio='08:30:00',
            hora_fin='09:30:00',
        )
        with self.assertRaisesMessage(
            ValidationError,
            'el profesor ya tiene una clase ocupando esa hora',
        ):
            con_mismo_docente.full_clean()

    def test_contexto_de_edicion_incluye_detalles_del_bloque_ocupado(self):
        from .models import Docente, Horario
        from .views import _horario_form_context

        docente = Docente.objects.create(nombre='Ana', apellido='Rojas', cedula='V-11223346')
        Horario.objects.create(
            ano='3ANO',
            materia='Matemáticas',
            docente=docente,
            dia='LU',
            hora_inicio='08:00:00',
            hora_fin='09:00:00',
        )

        horario_existente = next(
            horario for horario in _horario_form_context()['existing_schedules']
            if horario['docente_id'] == docente.pk
        )

        self.assertEqual(horario_existente['materia'], 'Matemáticas')
        self.assertEqual(horario_existente['docente__nombre'], 'Ana')
        self.assertEqual(horario_existente['docente__apellido'], 'Rojas')

    def test_formulario_horario_rechaza_horas_fuera_de_la_jornada(self):
        from django.core.exceptions import ValidationError

        from .forms import HorarioForm
        from .models import Docente, Horario

        docente = Docente.objects.create(nombre='Ana', apellido='Rojas', cedula='V-11223345')
        for hora_inicio, hora_fin in [('07:45', '08:30'), ('12:30', '13:15')]:
            with self.subTest(hora_inicio=hora_inicio, hora_fin=hora_fin):
                form = HorarioForm(data={
                    'ano': '1ANO',
                    'materia': 'Matemáticas',
                    'docente': docente.pk,
                    'dia': 'LU',
                    'hora_inicio': hora_inicio,
                    'hora_fin': hora_fin,
                })

                self.assertFalse(form.is_valid())
                self.assertIn('Verifique el horario', str(form.non_field_errors()))

                horario = Horario(
                    ano='1ANO',
                    materia='Matemáticas',
                    docente=docente,
                    dia='LU',
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
                with self.assertRaisesMessage(ValidationError, 'Verifique el horario'):
                    horario.full_clean()


class SubdireccionWorkflowTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(
            username='subdirectora-pruebas',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=self.usuario,
            cedula='V-33557799',
            cargo='SUBDIRECTORA',
        )
        self.factory = RequestFactory()

    def _solicitud(self, **cambios):
        from datetime import date

        from .models import SolicitudMatricula

        valores = {
            'estudiante_nombre': 'Ana',
            'estudiante_apellido': 'Pérez',
            'estudiante_fecha_nacimiento': date(2015, 5, 10),
            'estudiante_sexo': 'F',
            'estudiante_nacionalidad': 'Venezolana',
            'grado': '1RO',
            'partida_nacimiento': 'PN-123',
            'representante_nombre': 'Luis',
            'representante_apellido': 'Pérez',
            'representante_cedula': 'V-12345678',
            'representante_telefono': '04141234567',
            'representante_parentesco': 'Padre',
            'representante_nacionalidad': 'Venezolana',
            'documento_representante': '',
            'documento_partida_nacimiento': '',
        }
        valores.update(cambios)
        return SolicitudMatricula.objects.create(**valores)

    def _request(self, nombre, argumentos=None, data=None):
        from django.contrib.messages.storage.fallback import FallbackStorage

        path = reverse(nombre, args=argumentos or [])
        request = self.factory.post(path, data=data or {})
        request.user = self.usuario
        request.session = {'staff_session_token': 'subdirectora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        return request

    def _get_request(self, nombre, argumentos=None):
        from django.contrib.messages.storage.fallback import FallbackStorage

        path = reverse(nombre, args=argumentos or [])
        request = self.factory.get(path)
        request.user = self.usuario
        request.session = {'staff_session_token': 'subdirectora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)
        return request

    def test_subdirectora_puede_gestionar_roles_y_personal_sin_cargo_directora(self):
        from unittest.mock import patch

        from django.http import HttpResponse

        from .views import admin_crear_empleado, admin_crear_usuario

        with patch('escuelaApp.views.render', return_value=HttpResponse()) as render_page:
            admin_crear_usuario(self._get_request('admin_crear_usuario'))
        form_usuario = render_page.call_args.args[2]['form']
        self.assertIn('SUBDIRECTORA', dict(form_usuario.fields['cargo'].choices))
        self.assertNotIn('DIRECTORA', dict(form_usuario.fields['cargo'].choices))

        with patch('escuelaApp.views.render', return_value=HttpResponse()) as render_page:
            admin_crear_empleado(self._get_request('admin_crear_empleado'))
        form_empleado = render_page.call_args.args[2]['form']
        self.assertEqual(
            [(value, label) for value, label in form_empleado.fields['cargo'].choices if label == 'Profesor/a'],
            [('PROFESOR', 'Profesor/a')],
        )
        self.assertNotIn('DOCENTE', dict(form_empleado.fields['cargo'].choices))
        self.assertNotIn('DIRECTORA', dict(form_empleado.fields['cargo'].choices))

    def test_subdirectora_no_puede_asignar_cargo_directora_por_post(self):
        from unittest.mock import patch

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.http import HttpResponse

        from .views import admin_crear_empleado, admin_crear_usuario

        datos_usuario = {
            'email': 'directora-nueva@example.com',
            'username': 'DirectoraNueva',
            'first_name': 'Laura',
            'last_name': 'Pérez',
            'cedula': 'V-22334455',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'cargo': 'DIRECTORA',
        }
        request = self.factory.post(reverse('admin_crear_usuario'), data=datos_usuario)
        request.user = self.usuario
        request.session = {'staff_session_token': 'subdirectora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(reverse('admin_crear_usuario'))
        with patch('escuelaApp.views.render', return_value=HttpResponse()) as render_page:
            admin_crear_usuario(request)
        self.assertIn('cargo', render_page.call_args.args[2]['form'].errors)
        self.assertFalse(User.objects.filter(username='DirectoraNueva').exists())

        datos_empleado = {
            'first_name': 'Marta',
            'last_name': 'Pérez',
            'cedula': 'V-22334456',
            'email': 'empleada-directora@example.com',
            'password': 'Password123',
            'cargo': 'DIRECTORA',
        }
        request = self.factory.post(reverse('admin_crear_empleado'), data=datos_empleado)
        request.user = self.usuario
        request.session = {'staff_session_token': 'subdirectora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(reverse('admin_crear_empleado'))
        with patch('escuelaApp.views.render', return_value=HttpResponse()) as render_page:
            admin_crear_empleado(request)
        self.assertIn('cargo', render_page.call_args.args[2]['form'].errors)
        self.assertFalse(User.objects.filter(email='empleada-directora@example.com').exists())

    def test_subdirectora_no_puede_editar_ni_borrar_a_la_directora(self):
        from .views import admin_editar_usuario, admin_eliminar_usuario

        directora = User.objects.create_superuser(
            username='directora-protegida',
            email='directora-protegida@example.com',
            password='Password123',
        )
        Empleado.objects.create(
            user=directora,
            cedula='V-66778899',
            cargo='DIRECTORA',
        )

        with self.assertRaises(PermissionDenied):
            admin_editar_usuario(self._get_request('admin_editar_usuario', [directora.pk]), directora.pk)

        response = admin_eliminar_usuario(
            self._request('admin_eliminar_usuario', [directora.pk]), directora.pk
        )
        directora.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(directora.is_superuser)

    def test_panel_subdirectora_muestra_sus_tareas_administrativas(self):
        from unittest.mock import patch

        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.template.loader import render_to_string
        from django.urls import resolve

        from .views import admin_panel_view

        request = self.factory.get(reverse('admin_panel'))
        request.user = self.usuario
        request.session = {'staff_session_token': 'subdirectora-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(reverse('admin_panel'))

        with patch('escuelaApp.views.render') as render_page:
            admin_panel_view(request)
        contexto = render_page.call_args.args[2]
        pagina = render_to_string(
            'escuelaApp/admin_custom/panel_principal.html',
            contexto,
            request=request,
        )

        for contenido in (
            'Solicitudes de matrícula',
            'Asistencia del personal',
            'Cuentas y permisos',
            'Personal',
        ):
            with self.subTest(contenido=contenido):
                self.assertIn(contenido, pagina)
        self.assertIn('/admin-panel/subdireccion/matriculas/reportes/pdf/', pagina)

    def test_ausencia_justificada_de_personal_exige_observacion(self):
        from datetime import date

        from .forms_subdireccion import AsistenciaPersonalForm

        datos = {
            'empleado': self.usuario.empleado.pk,
            'fecha': date.today().isoformat(),
            'estado': 'JUSTIFICADO',
            'observaciones': '',
        }
        form = AsistenciaPersonalForm(data=datos)

        self.assertFalse(form.is_valid())
        self.assertIn('observaciones', form.errors)

        datos['observaciones'] = 'Cita médica con justificativo.'
        form = AsistenciaPersonalForm(data=datos)
        self.assertTrue(form.is_valid(), form.errors)

    def test_solicitud_publica_valida_parentesco_documentos_y_cedula(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from .forms_subdireccion import SolicitudMatriculaForm

        data = {
            'estudiante_nombre': 'Ana',
            'estudiante_apellido': 'Pérez',
            'estudiante_fecha_nacimiento': '2015-05-10',
            'estudiante_sexo': 'F',
            'estudiante_nacionalidad': 'Venezolana',
            'grado': '1RO',
            'partida_nacimiento': 'PN-123',
            'representante_nombre': 'Luis',
            'representante_apellido': 'Pérez',
            'tipo_identificacion_representante': 'E',
            'representante_cedula': '123456',
            'representante_telefono': '04141234567',
            'representante_parentesco': 'Padre',
            'representante_nacionalidad': 'Extranjera',
        }
        files = {
            'documento_representante': SimpleUploadedFile('cedula.pdf', b'%PDF-1.4'),
            'documento_partida_nacimiento': SimpleUploadedFile('partida.pdf', b'%PDF-1.4'),
        }
        form = SolicitudMatriculaForm(data=data, files=files)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['representante_cedula'], 'E-123456')

    def test_aprobar_matricula_crea_estudiante_y_reutiliza_representante(self):
        from .models import Estudiante, Representante
        from .views_subdireccion import subdireccion_revisar_matricula

        representante = Representante.objects.create(
            nombre='Luis', apellido='Pérez', cedula='V-12345678', telefono='04141234567'
        )
        solicitud = self._solicitud()
        request = self._request(
            'subdireccion_revisar_matricula', [solicitud.pk],
            {'accion': 'aprobar', 'seccion': 'A', 'observaciones': 'Documentos y parentesco verificados.'},
        )
        response = subdireccion_revisar_matricula(request, solicitud.pk)

        solicitud.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(solicitud.estado, 'APROBADA')
        self.assertEqual(solicitud.revisada_por, self.usuario)
        self.assertEqual(solicitud.estudiante.representante, representante)
        self.assertEqual(Estudiante.objects.count(), 1)
        self.assertTrue(solicitud.estudiante.matricula)
        self.assertEqual(solicitud.estudiante.seccion, 'A')
        self.assertEqual(solicitud.revisada_por, self.usuario)
        self.assertEqual(solicitud.estudiante.representante, representante)
        self.assertEqual(Estudiante.objects.count(), 1)
        self.assertTrue(solicitud.estudiante.matricula)

    def test_aprobar_matricula_exige_asignar_seccion(self):
        from .forms_subdireccion import RevisionSolicitudMatriculaForm

        form = RevisionSolicitudMatriculaForm(data={
            'accion': 'aprobar',
            'observaciones': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('seccion', form.errors)

    def test_aprobar_matricula_envia_confirmacion_al_representante(self):
        from django.conf import settings

        from .views_subdireccion import subdireccion_revisar_matricula

        solicitud = self._solicitud(representante_email='familia@example.com')
        request = self._request(
            'subdireccion_revisar_matricula', [solicitud.pk],
            {'accion': 'aprobar', 'seccion': 'A', 'observaciones': 'Documentos verificados.'},
        )
        with patch('escuelaApp.views_subdireccion.send_mail', return_value=1) as enviar:
            response = subdireccion_revisar_matricula(request, solicitud.pk)

        self.assertEqual(response.status_code, 302)
        enviar.assert_called_once()
        asunto, cuerpo, remitente, destinatarios = enviar.call_args.args
        self.assertEqual(asunto, 'Matrícula registrada correctamente')
        self.assertIn('Ana Pérez', cuerpo)
        self.assertIn('Primero', cuerpo)
        self.assertIn('sección A', cuerpo)
        self.assertEqual(remitente, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(destinatarios, ['familia@example.com'])

    def test_fallo_de_correo_no_revierte_matricula_aprobada(self):
        from django.contrib.messages import get_messages

        from .views_subdireccion import subdireccion_revisar_matricula

        solicitud = self._solicitud(representante_email='familia@example.com')
        request = self._request(
            'subdireccion_revisar_matricula', [solicitud.pk],
            {'accion': 'aprobar', 'seccion': 'A', 'observaciones': 'Documentos verificados.'},
        )
        with patch('escuelaApp.views_subdireccion.send_mail', side_effect=OSError('SMTP unavailable')):
            with self.assertLogs('escuelaApp.views_subdireccion', level='ERROR'):
                response = subdireccion_revisar_matricula(request, solicitud.pk)

        solicitud.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(solicitud.estado, 'APROBADA')
        self.assertIsNotNone(solicitud.estudiante_id)
        self.assertTrue(any('no se pudo enviar' in str(mensaje) for mensaje in get_messages(request)))

    def test_rechazo_exige_motivo_y_guarda_observaciones(self):
        from unittest.mock import patch

        from django.http import HttpResponse

        from .models import SolicitudMatricula
        from .views_subdireccion import subdireccion_revisar_matricula

        solicitud = self._solicitud()
        request = self._request(
            'subdireccion_revisar_matricula', [solicitud.pk],
            {'accion': 'rechazar', 'observaciones': ''},
        )
        with patch('escuelaApp.views_subdireccion.render', return_value=HttpResponse()) as render_page:
            response = subdireccion_revisar_matricula(request, solicitud.pk)

        solicitud.refresh_from_db()
        form = render_page.call_args.args[2]['form']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(solicitud.estado, 'PENDIENTE')
        self.assertIn('observaciones', form.errors)

        request = self._request(
            'subdireccion_revisar_matricula', [solicitud.pk],
            {'accion': 'rechazar', 'observaciones': 'No se puede validar el parentesco.'},
        )
        response = subdireccion_revisar_matricula(request, solicitud.pk)
        solicitud.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(solicitud.estado, 'RECHAZADA')
        self.assertEqual(solicitud.observaciones_revision, 'No se puede validar el parentesco.')

    def test_reportes_mensuales_descargan_pdf_y_word(self):
        from django.utils import timezone

        from .models import AsistenciaPersonal

        hoy = timezone.localdate()
        self._solicitud()
        AsistenciaPersonal.objects.create(
            empleado=self.usuario.empleado,
            fecha=hoy,
            estado='JUSTIFICADO',
            observaciones='Cita médica',
            registrado_por=self.usuario,
        )
        rutas = (
            ('subdireccion_reporte_asistencia', 'pdf', b'%PDF-'),
            ('subdireccion_reporte_asistencia', 'docx', b'PK'),
            ('subdireccion_reporte_matricula', 'pdf', b'%PDF-'),
            ('subdireccion_reporte_matricula', 'docx', b'PK'),
        )
        with patch('escuelaApp.views_subdireccion.enviar_reporte_a_directora') as enviar:
            for nombre, formato, firma in rutas:
                with self.subTest(nombre=nombre, formato=formato):
                    path = reverse(nombre, args=[formato])
                    request = self.factory.get(path, {'mes': hoy.month, 'anio': hoy.year})
                    request.user = self.usuario
                    request.session = {'staff_session_token': 'subdirectora-test'}
                    request.resolver_match = resolve(path)
                    response = resolve(path).func(request, formato)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content.startswith(firma))

        self.assertEqual(enviar.call_count, 4)

    def test_solicitud_publica_se_guarda_pendiente_en_storage_privado(self):
        from django.conf import settings
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone

        from .models import SolicitudMatricula
        from .views_subdireccion import subdireccion_descargar_documento
        from .views_portal import portal_registro_rapido

        hoy = timezone.localdate()
        data = {
            'estudiante_nombre': 'Sofía',
            'estudiante_apellido': 'Rojas',
            'estudiante_fecha_nacimiento': '2016-04-12',
            'estudiante_sexo': 'F',
            'estudiante_nacionalidad': 'Venezolana',
            'grado': '2DO',
            'partida_nacimiento': 'PN-456',
            'representante_nombre': 'Marta',
            'representante_apellido': 'Rojas',
            'tipo_identificacion_representante': 'E',
            'representante_cedula': '123456',
            'representante_telefono': '04141234567',
            'representante_parentesco': 'Madre',
            'representante_nacionalidad': 'Venezolana',
        }
        files = {
            'documento_representante': SimpleUploadedFile('cedula.pdf', b'%PDF-1.4'),
            'documento_partida_nacimiento': SimpleUploadedFile('partida.pdf', b'%PDF-1.4'),
        }
        path = reverse('portal_registro_rapido')
        request = self.factory.post(path, data={**data, **files})
        request.session = {}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)

        response = portal_registro_rapido(request)
        solicitud = SolicitudMatricula.objects.get(representante_cedula='E-123456')
        try:
            self.assertEqual(response.status_code, 302)
            self.assertEqual(solicitud.estado, 'PENDIENTE')
            self.assertNotEqual(solicitud.documento_representante.storage.location, settings.MEDIA_ROOT)
            descarga_path = reverse('subdireccion_descargar_documento', args=[solicitud.pk, 'representante'])
            request_descarga = self.factory.get(descarga_path)
            request_descarga.user = self.usuario
            request_descarga.session = {'staff_session_token': 'subdirectora-test'}
            request_descarga.resolver_match = resolve(descarga_path)
            descarga = subdireccion_descargar_documento(request_descarga, solicitud.pk, 'representante')
            self.assertEqual(descarga.status_code, 200)
            contenido_documento = b''.join(descarga.streaming_content)
            descarga.file_to_stream.close()
            self.assertEqual(contenido_documento, b'%PDF-1.4')
        finally:
            solicitud.documento_representante.delete(save=False)
            solicitud.documento_partida_nacimiento.delete(save=False)

    def test_coordinador_no_puede_abrir_modulos_de_subdireccion(self):
        from django.contrib.messages.storage.fallback import FallbackStorage

        from .views_subdireccion import subdireccion_solicitudes_matricula

        coordinador = User.objects.create_user(username='coord-solicitudes', is_staff=True)
        Empleado.objects.create(user=coordinador, cedula='V-99887766', cargo='COORD')
        path = reverse('subdireccion_solicitudes_matricula')
        request = self.factory.get(path)
        request.user = coordinador
        request.session = {'staff_session_token': 'coord-test'}
        request._messages = FallbackStorage(request)
        request.resolver_match = resolve(path)

        response = subdireccion_solicitudes_matricula(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_panel'))


class DocenteEstudiantesTests(TestCase):
    def setUp(self):
        from .models import Docente

        self.usuario = User.objects.create_user(
            username='directora-asignaciones',
            password='Password123',
            is_staff=True,
        )
        Empleado.objects.create(
            user=self.usuario,
            cedula='V-76543219',
            cargo='DIRECTORA',
        )
        self.docente = Docente.objects.create(
            nombre='María',
            apellido='Pérez',
            cedula='V-76543220',
        )
        self.estudiante_primero = Estudiante.objects.create(
            nombre='Ana',
            apellido='Rojas',
            cedula='V-76543221',
            grado='1RO',
            seccion='A',
        )
        self.estudiante_segundo = Estudiante.objects.create(
            nombre='Sara',
            apellido='Díaz',
            cedula='V-76543223',
            grado='2DO',
            seccion='B',
        )
        self.estudiante_sin_asignar = Estudiante.objects.create(
            nombre='Eva',
            apellido='León',
            cedula='V-76543224',
            grado='1RO',
            seccion='B',
        )
        self.client.force_login(self.usuario)
        self.url = reverse(
            'admin_asignar_estudiantes_docente',
            args=[self.docente.cedula],
        )

    def test_asigna_estudiantes_por_grado_y_conserva_los_demas_grados(self):
        respuesta_primero = self.client.post(self.url, {
            'grado': '1RO',
            'seccion': 'A',
            'estudiantes': [self.estudiante_primero.pk],
        })
        respuesta_segundo = self.client.post(self.url, {
            'grado': '2DO',
            'seccion': 'B',
            'estudiantes': [self.estudiante_segundo.pk],
        })

        self.assertEqual(respuesta_primero.status_code, 302)
        self.assertEqual(respuesta_segundo.status_code, 302)
        self.assertEqual(
            list(self.docente.estudiantes_asignados.order_by('pk')),
            [self.estudiante_primero, self.estudiante_segundo],
        )

        from .views import _datos_estudiantes_docente

        _, grupos = _datos_estudiantes_docente(self.docente)
        estudiantes_mostrados = {
            estudiante
            for grupo in grupos
            for estudiante in grupo['estudiantes']
        }
        self.assertEqual(
            estudiantes_mostrados,
            {self.estudiante_primero, self.estudiante_segundo},
        )
        self.assertEqual(
            [grupo['nombre'] for grupo in grupos],
            ['Primero - Sección A', 'Segundo - Sección B'],
        )
        from .docente_scope import docente_puede_atender_estudiante, estudiantes_del_docente

        self.assertEqual(
            list(estudiantes_del_docente(self.docente)),
            [self.estudiante_primero, self.estudiante_segundo],
        )
        self.assertTrue(docente_puede_atender_estudiante(
            self.docente, self.estudiante_primero
        ))
        self.assertFalse(docente_puede_atender_estudiante(
            self.docente, self.estudiante_sin_asignar
        ))

    def test_asigna_todo_el_grupo_de_una_seccion_en_una_sola_accion(self):
        from .models import DocenteEstudiante

        estudiante_mismo_grupo = Estudiante.objects.create(
            nombre='Luis',
            apellido='Rojas',
            cedula='V-76543225',
            grado='1RO',
            seccion='A',
        )
        DocenteEstudiante.objects.create(
            docente=self.docente,
            estudiante=self.estudiante_segundo,
        )

        respuesta = self.client.post(self.url, {
            'grado': '1RO',
            'seccion': 'A',
            'asignar_grupo_completo': '1',
        })

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            set(self.docente.estudiantes_asignados.all()),
            {self.estudiante_primero, estudiante_mismo_grupo, self.estudiante_segundo},
        )

    def test_filtra_estudiantes_por_grado_y_seccion(self):
        from .forms import DocenteEstudiantesForm

        form = DocenteEstudiantesForm(
            initial={'grado': '1RO', 'seccion': 'A'},
            docente=self.docente,
        )

        self.assertEqual(
            [valor for valor, _ in form.fields['seccion'].choices],
            ['', 'A', 'B', 'C'],
        )
        self.assertEqual(
            list(form.fields['estudiantes'].queryset),
            [self.estudiante_primero],
        )

    def test_formularios_ofrecen_secciones_de_la_a_a_la_c(self):
        from .forms import DocenteEstudiantesForm, EstudianteForm
        from .models import Docente

        form = EstudianteForm()
        asignacion_form = DocenteEstudiantesForm(
            initial={'grado': '1RO'},
            docente=Docente(),
        )

        self.assertEqual(
            [valor for valor, _ in form.fields['seccion'].choices],
            ['', 'A', 'B', 'C'],
        )
        self.assertEqual(
            [valor for valor, _ in asignacion_form.fields['seccion'].choices],
            ['', 'A', 'B', 'C'],
        )
        self.assertFalse(form.fields['seccion'].required)
        self.assertFalse(form.fields['grado'].required)

    def test_formularios_rechazan_secciones_fuera_de_a_a_c(self):
        from .forms import DocenteEstudiantesForm, EstudianteForm
        from .models import Docente

        estudiante_form = EstudianteForm(data={
            'nombre': 'Ana',
            'apellido': 'Rojas',
            'grado': '1RO',
            'seccion': 'D',
            'sexo': 'F',
            'nacionalidad': 'Venezolana',
            'representante': '',
        })
        asignacion_form = DocenteEstudiantesForm(data={
            'grado': '1RO',
            'seccion': 'D',
            'estudiantes': [self.estudiante_primero.pk],
        }, docente=Docente())

        self.assertFalse(estudiante_form.is_valid())
        self.assertIn('seccion', estudiante_form.errors)
        self.assertFalse(asignacion_form.is_valid())
        self.assertIn('seccion', asignacion_form.errors)

    def test_selectores_de_notas_y_asistencia_muestran_y_ordenan_por_grado_y_seccion(self):
        from .forms_asistencia import AsistenciaForm
        from .forms_registro_academico import RegistroAcademicoForm

        esperados = [
            self.estudiante_primero,
            self.estudiante_sin_asignar,
            self.estudiante_segundo,
        ]
        for form in (RegistroAcademicoForm(), AsistenciaForm()):
            with self.subTest(form=form.__class__.__name__):
                estudiantes = list(form.fields['estudiante_cedula'].queryset)
                self.assertEqual(estudiantes, esperados)
                etiqueta = form.fields['estudiante_cedula'].label_from_instance(
                    self.estudiante_primero
                )
                self.assertIn('1RO - Sección A', etiqueta)

    def test_horario_fallback_respeta_grupo_explicito_por_seccion(self):
        from .docente_scope import estudiantes_del_docente
        from .models import DocenteEstudiante, Horario
        from .views import _datos_estudiantes_docente

        Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=self.docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        DocenteEstudiante.objects.create(
            docente=self.docente,
            estudiante=self.estudiante_primero,
        )

        self.assertEqual(
            list(estudiantes_del_docente(self.docente)),
            [self.estudiante_primero, self.estudiante_sin_asignar],
        )
        _, grupos = _datos_estudiantes_docente(self.docente)
        estudiantes_mostrados = {
            estudiante
            for grupo in grupos
            for estudiante in grupo['estudiantes']
        }
        self.assertEqual(
            estudiantes_mostrados,
            {self.estudiante_primero, self.estudiante_sin_asignar},
        )

    def test_no_permite_asignar_estudiante_de_otra_seccion(self):
        from .forms import DocenteEstudiantesForm

        form = DocenteEstudiantesForm(data={
            'grado': '1RO',
            'seccion': 'A',
            'estudiantes': [self.estudiante_sin_asignar.pk],
        }, docente=self.docente)

        self.assertFalse(form.is_valid())
        self.assertIn('estudiantes', form.errors)
        self.assertFalse(self.docente.estudiantes_asignados.exists())

    def test_asignar_otro_grado_conserva_el_grupo_de_horario_existente(self):
        from .models import Horario

        Horario.objects.create(
            ano='1ANO',
            materia='Matemáticas',
            docente=self.docente,
            dia='LU',
            hora_inicio='08:00',
            hora_fin='09:00',
        )
        self.client.post(self.url, {
            'grado': '2DO',
            'seccion': 'B',
            'estudiantes': [self.estudiante_segundo.pk],
        })

        from .views import _datos_estudiantes_docente

        _, grupos = _datos_estudiantes_docente(self.docente)
        estudiantes_mostrados = {
            estudiante
            for grupo in grupos
            for estudiante in grupo['estudiantes']
        }
        self.assertEqual(
            estudiantes_mostrados,
            {
                self.estudiante_primero,
                self.estudiante_sin_asignar,
                self.estudiante_segundo,
            },
        )
