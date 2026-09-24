from drf_spectacular.extensions import OpenApiAuthenticationExtension


class FirebaseAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'users.authentication.FirebaseAuthentication'
    name = 'FirebaseTokenAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'Firebase JWT',
            'description': 'Firebase ID Token obtained from Google/Apple sign-in (Header: `Authorization: Bearer <token>`).',
        }
