from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Permite autenticar usuarios utilizando indistintamente su `username` o su `email`.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or not password:
            return None

        termino = str(username).strip()
        try:
            user = User.objects.filter(
                Q(username__iexact=termino) | Q(email__iexact=termino)
            ).first()
            if user and user.check_password(password) and self.user_can_authenticate(user):
                return user
        except Exception:
            return None

        return None

