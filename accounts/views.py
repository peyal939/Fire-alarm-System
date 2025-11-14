from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema, OpenApiExample

from .serializers import (
    UserSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
    AdminUserUpdateSerializer,
    ChangePasswordSerializer,
)

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
    summary="Get or update current user profile",
    description=(
        "Returns the authenticated user's full profile including owned devices.\n\n"
        "PATCH allows partial updates of: full_name, phone_number, address. \n"
        "Role and email cannot be changed via this endpoint."
    ),
    request=UserUpdateSerializer,
    responses={200: UserDetailSerializer, 400: None, 401: None},
    examples=[
        OpenApiExample(
            "GetProfileResponse",
            value={
                "id": 7,
                "email": "user@example.com",
                "phone_number": "+8801712345678",
                "role": "user",
                "full_name": "Jane Operator",
                "address": "123 Flame Ave, Dhaka",
                "devices": [
                    {
                        "id": 21,
                        "hardware_identifier": "FD-ABC123",
                        "device_name": "Kitchen Detector",
                        "device_role": "master",
                        "latitude": 23.78001,
                        "longitude": 90.41002,
                        "status": "normal",
                        "last_seen": "2025-10-05T06:30:00Z",
                    }
                ],
            },
            response_only=True,
        ),
        OpenApiExample(
            "PatchProfileRequest",
            value={
                "full_name": "Jane Firewatch",
                "address": "456 Smoke Rd, Dhaka",
                "phone_number": "+8801999887766",
            },
            request_only=True,
        ),
        OpenApiExample(
            "PatchProfileResponse",
            value={
                "id": 7,
                "email": "user@example.com",
                "phone_number": "+8801999887766",
                "role": "user",
                "full_name": "Jane Firewatch",
                "address": "456 Smoke Rd, Dhaka",
                "devices": [],
            },
            response_only=True,
        ),
    ],
)
@api_view(["GET", "PATCH"])
def me(request):
    """Get enriched current user profile or partially update own profile fields."""
    base_qs = User.objects.filter(id=request.user.id).prefetch_related("devices")
    user = (
        base_qs.only(
            "id", "email", "phone_number", "role", "full_name", "address"
        ).first()
        or request.user
    )
    if request.method == "PATCH":
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            # Refresh from DB for detail serializer consistency
            user = base_qs.first() or user
            return Response(UserDetailSerializer(user).data)
        return Response(serializer.errors, status=400)
    return Response(UserDetailSerializer(user).data)


@extend_schema(
    tags=["Auth"],
    summary="Change current user password",
    description=(
        "Allows an authenticated user to update their password by providing the current "
        "password along with a new password (entered twice for confirmation)."
    ),
    request=ChangePasswordSerializer,
    responses={204: None, 400: None, 401: None},
    examples=[
        OpenApiExample(
            "ChangePasswordRequest",
            value={
                "current_password": "Passw0rd!",
                "new_password": "N3wPassw0rd!",
                "confirm_new_password": "N3wPassw0rd!",
            },
            request_only=True,
        )
    ],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(
        data=request.data, context={"request": request}
    )
    if serializer.is_valid():
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Users"],
    summary="Admin: get or update user detail by ID",
    description=(
        "Allows staff/superusers to retrieve or partially update a user.\n\n"
        "Updatable fields: full_name, phone_number, address, role.\n"
        "Email and privilege flags (is_staff/is_superuser) are not exposed here."
    ),
    request=AdminUserUpdateSerializer,
    responses={200: UserDetailSerializer, 400: None, 403: None, 404: None},
    examples=[
        OpenApiExample(
            "AdminGetUserResponse",
            value={
                "id": 4,
                "email": "client@example.com",
                "phone_number": "+8801700112233",
                "role": "user",
                "full_name": "Client A",
                "address": "10 Alarm Street",
                "devices": [
                    {
                        "id": 55,
                        "hardware_identifier": "FD-XYZ987",
                        "device_name": "Lobby Detector",
                        "device_role": "master",
                        "latitude": 23.70001,
                        "longitude": 90.42002,
                        "status": "normal",
                        "last_seen": "2025-10-05T05:57:10Z",
                    }
                ],
            },
            response_only=True,
        ),
        OpenApiExample(
            "AdminPatchUserRequest",
            value={"full_name": "Client Alpha", "role": "superadmin"},
            request_only=True,
        ),
        OpenApiExample(
            "AdminPatchUserResponse",
            value={
                "id": 4,
                "email": "client@example.com",
                "phone_number": "+8801700112233",
                "role": "superadmin",
                "full_name": "Client Alpha",
                "address": "10 Alarm Street",
                "devices": [],
            },
            response_only=True,
        ),
    ],
)
@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def user_detail_admin(request, pk: int):
    try:
        base_qs = User.objects.filter(id=pk).prefetch_related("devices")
        user = base_qs.only(
            "id",
            "email",
            "phone_number",
            "role",
            "full_name",
            "address",
        ).get()
    except User.DoesNotExist:
        return Response({"detail": "Not found"}, status=404)
    if request.method == "PATCH":
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            # Prevent privilege escalation beyond role field (no flags here)
            serializer.save()
            user = base_qs.first() or user
            return Response(UserDetailSerializer(user).data)
        return Response(serializer.errors, status=400)
    return Response(UserDetailSerializer(user).data)
