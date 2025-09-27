from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema, OpenApiExample

from .serializers import UserSerializer, RegisterSerializer

User = get_user_model()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = getattr(user, "role", "user")
        return token


@extend_schema(
    tags=["Auth"],
    summary="Login with email & password",
    examples=[
        OpenApiExample(
            name="LoginRequest",
            value={"email": "user@example.com", "password": "Passw0rd!"},
            request_only=True,
        ),
        OpenApiExample(
            name="LoginResponse",
            value={
                "refresh": "<jwt-refresh>",
                "access": "<jwt-access>",
            },
            response_only=True,
        ),
    ],
)
class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


@extend_schema(
    tags=["Auth"],
    summary="Register a new user",
    request=RegisterSerializer,
    responses={201: UserSerializer, 409: None, 400: None},
    examples=[
        OpenApiExample(
            "RegisterRequest",
            value={
                "email": "user@example.com",
                "password": "Passw0rd!",
                "phone_number": "+8801712345678",
            },
            request_only=True,
        ),
        OpenApiExample(
            "RegisterResponse",
            value={
                "id": 1,
                "email": "user@example.com",
                "phone_number": "+8801712345678",
                "role": "user",
            },
            response_only=True,
        ),
    ],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    email = request.data.get("email", "").strip().lower()
    phone = request.data.get("phone_number", "").strip()
    password = request.data.get("password", "")
    if not email or not password:
        return Response({"detail": "email and password required"}, status=400)
    if User.objects.filter(email=email).exists():
        return Response({"detail": "email already registered"}, status=409)
    user = User.objects.create_user(email=email, password=password, phone_number=phone)
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Auth"],
    summary="Get current user profile",
    responses={200: UserSerializer, 401: None},
)
@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)
