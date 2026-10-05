"""
Custom authentication backend for Firebase token verification
"""

from rest_framework import authentication, exceptions
from django.contrib.auth import get_user_model
from .utils import verify_firebase_token

User = get_user_model()


class FirebaseAuthentication(authentication.BaseAuthentication):
    """
    Custom authentication backend to verify Firebase ID tokens
    This allows users who login via Google/Apple to authenticate with Firebase tokens
    """
    
    def authenticate(self, request):
        """
        Authenticate user using Firebase ID token
        
        Args:
            request: Django request object
            
        Returns:
            tuple: (user, auth_data) if authentication successful, None otherwise
            
        The authorization header should be in format:
        Authorization: Bearer <firebase_id_token>
        """
        # Get authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        # Check if it's a Bearer token
        if not auth_header.startswith('Bearer '):
            return None
        
        # Extract token
        id_token = auth_header.split('Bearer ')[1].strip()
        
        if not id_token:
            return None
        
        try:
            # Verify Firebase token
            decoded_token = verify_firebase_token(id_token)
            
            # Extract user information from token
            firebase_uid = decoded_token.get('uid')
            email = decoded_token.get('email')
            
            if not firebase_uid:
                raise exceptions.AuthenticationFailed('Invalid Firebase token: missing UID')
            
            # Try to get user by Firebase UID
            try:
                user = User.objects.get(firebase_uid=firebase_uid)
            except User.DoesNotExist:
                raise exceptions.AuthenticationFailed(
                    'User not found with this Firebase UID. Please authenticate via /api/users/firebase-auth/ first.'
                )
            
            # Check if user is active
            if not user.is_active:
                raise exceptions.AuthenticationFailed('User account is disabled')
            
            # Return user and auth data
            return (user, decoded_token)
        
        except exceptions.AuthenticationFailed:
            # Re-raise our custom authentication errors
            raise
        
        except Exception as e:
            # For any other error, return None (not authenticated via Firebase)
            # This allows the request to try other authentication methods (JWT)
            return None
    
    def authenticate_header(self, request):
        """
        Return authentication header for 401 responses
        """
        return 'Bearer realm="api"'