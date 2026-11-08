from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateDocumentsStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.BASE_DIR / 'private_uploads')

    def url(self, name):
        raise ValueError('Los documentos privados solo se sirven desde vistas autorizadas.')