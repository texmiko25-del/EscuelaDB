from functools import partial

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from .comunicados import enviar_comunicado_representantes
from .decorators import active_staff_required, role_required
from .forms_comunicados import ComunicadoRepresentantesForm
from .models import ComunicadoRepresentantes

staff_member_required = partial(django_staff_member_required, login_url='login')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def comunicados_representantes(request):
    if request.method == 'POST':
        form = ComunicadoRepresentantesForm(request.POST)
        if form.is_valid():
            try:
                comunicado, entregas = enviar_comunicado_representantes(
                    form.cleaned_data['asunto'],
                    form.cleaned_data['mensaje'],
                    form.cleaned_data['representantes'],
                    request.user,
                    docentes=form.cleaned_data['docentes'],
                )
            except RuntimeError as error:
                messages.error(request, str(error))
            else:
                exitos = sum(entrega.estado == 'ENVIADO' for entrega in entregas)
                errores = len(entregas) - exitos
                if errores:
                    messages.warning(
                        request,
                        f'Comunicado {comunicado.pk} guardado: {exitos} enviados y {errores} con error.',
                    )
                else:
                    messages.success(request, f'Comunicado enviado individualmente a {exitos} destinatario(s).')
                return redirect('comunicados_representantes')
    else:
        form = ComunicadoRepresentantesForm()

    comunicados = ComunicadoRepresentantes.objects.annotate(
        entregas_exitosas=Count('entregas', filter=Q(entregas__estado='ENVIADO')),
        entregas_fallidas=Count('entregas', filter=Q(entregas__estado='ERROR')),
    )[:10]
    return render(request, 'escuelaApp/admin_custom/comunicados_representantes.html', {
        'form': form,
        'comunicados': comunicados,
    })