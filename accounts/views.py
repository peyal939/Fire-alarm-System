from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema, OpenApiExample

from otp.models import PhoneOTP
from otp.services import OTPSessionManager

from .serializers import (
    UserSerializer,
    RegisterSerializer,
    RegistrationInitSerializer,
    RegistrationVerifySerializer,
    LoginOTPVerifySerializer,
    PasswordResetInitSerializer,
    PasswordResetCompleteSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
    AdminUserUpdateSerializer,
    ChangePasswordSerializer,
)
from .phone_utils import phone_variants

User = get_user_model()


def _mask_phone(phone: str) -> str:
    phone = phone or ""
    if len(phone) <= 4:
        return phone
    return "*" * (len(phone) - 4) + phone[-4:]


def _resolve_user(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if "@" in identifier:
        return User.objects.filter(email=identifier.lower()).first()
    variants = phone_variants(identifier) or [identifier]
    return User.objects.filter(phone_number__in=variants).first()


class IsSuperOrRoleSuperAdmin(BasePermission):
    """Allow access only to superusers or users with role='superadmin'."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_superuser", False):
            return True
        return getattr(user, "role", "") == "superadmin"


@extend_schema(
    tags=["Admin"],
    summary="List users (admin only)",
    responses={200: UserDetailSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([IsSuperOrRoleSuperAdmin])
def user_list_admin(request):
    """Return all users or filter by email/phone via ?q= for admin dashboard."""

    q = (request.query_params.get("q") or "").strip()
    qs = User.objects.all().order_by("id")
    if q:
        if "@" in q:
            qs = qs.filter(email__icontains=q.lower())
        else:
            variants = phone_variants(q) or [q]
            qs = qs.filter(phone_number__in=variants)

    serializer = UserDetailSerializer(qs[:200], many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = getattr(user, "role", "user")
        return token


@extend_schema(
    tags=["Auth"],
    summary="Login with email or phone plus password",
    examples=[
        OpenApiExample(
            name="LoginRequestEmail",
            value={"email": "user@example.com", "password": "Passw0rd!"},
            request_only=True,
        ),
        OpenApiExample(
            name="LoginRequestPhone",
            value={"phone_number": "+8801700000000", "password": "Passw0rd!"},
            request_only=True,
        ),
        OpenApiExample(
            name="LoginOTPChallenge",
            value={
                "session_id": "7f9d19f8-2c4f-4d28-8bd6-1e7ee7d9f5d0",
                "otp_sent_to": "********0000",
                "expires_in": 300,
                "resend_cooldown": 60,
            },
            response_only=True,
        ),
    ],
)
class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        data = request.data.copy()
        identifier = (
            data.get("identifier")
            or data.get("email")
            or data.get("phone_number")
            or ""
        )
        identifier = identifier.strip()

        if identifier and "@" not in identifier:
            variants = phone_variants(identifier) or [identifier]
            user = User.objects.filter(phone_number__in=variants).first()
            if user:
                data["email"] = user.email
        elif identifier:
            data["email"] = identifier.lower()

        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        if not settings.OTP_SETTINGS.get("login_enforced", False):
            return Response(serializer.validated_data, status=status.HTTP_200_OK)

        user = serializer.user
        phone_number = user.phone_number or ""
        if not phone_number:
            return Response(
                {"detail": "Phone number is required for OTP login."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        manager = OTPSessionManager(purpose=PhoneOTP.Purpose.LOGIN)
        metadata = {
            "email": user.email,
            "user_id": user.id,
            "client_ip": request.META.get("REMOTE_ADDR"),
        }
        try:
            session = manager.create_session(
                phone_number=phone_number,
                user=user,
                metadata=metadata,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        masked = _mask_phone(phone_number)
        payload = {
            "session_id": str(session.session_id),
            "otp_sent_to": masked,
            "expires_in": settings.OTP_SETTINGS["ttl_seconds"],
            "resend_cooldown": settings.OTP_SETTINGS["resend_cooldown_seconds"],
        }
        return Response(payload, status=status.HTTP_202_ACCEPTED)


@extend_schema(
    tags=["Auth"],
    summary="Begin registration (send OTP)",
    request=RegistrationInitSerializer,
    responses={201: None, 400: None, 409: None, 429: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def register_init(request):
    serializer = RegistrationInitSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    email = data["email"].strip().lower()
    phone_number = data["phone_number"].strip()

    if User.objects.filter(email=email).exists():
        return Response({"detail": "Email already registered"}, status=409)

    metadata = {
        "email": email,
        "phone_number": phone_number,
        "full_name": data.get("full_name", ""),
        "address": data.get("address", ""),
        "password_hash": make_password(data["password"]),
        "client_ip": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT"),
    }

    manager = OTPSessionManager(purpose=PhoneOTP.Purpose.REGISTER)
    try:
        session = manager.create_session(
            phone_number=phone_number,
            metadata=metadata,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    payload = {
        "session_id": str(session.session_id),
        "expires_at": session.expires_at,
        "expires_in": settings.OTP_SETTINGS["ttl_seconds"],
        "resend_cooldown": settings.OTP_SETTINGS["resend_cooldown_seconds"],
    }
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Auth"],
    summary="Complete registration with OTP",
    request=RegistrationVerifySerializer,
    responses={201: UserSerializer, 400: None, 404: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register_verify(request):
    serializer = RegistrationVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    session = get_object_or_404(
        PhoneOTP,
        session_id=serializer.validated_data["session_id"],
        purpose=PhoneOTP.Purpose.REGISTER,
    )

    manager = OTPSessionManager(purpose=PhoneOTP.Purpose.REGISTER)
    if not session.is_verified:
        is_valid_code = manager.verify_code(session, serializer.validated_data["code"])
        if not is_valid_code:
            return Response(
                {"detail": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    metadata = session.metadata or {}
    completed_before = bool(metadata.get("completed"))
    user = None
    if metadata.get("completed") and metadata.get("user_id"):
        user = User.objects.filter(id=metadata["user_id"]).first()
    if user is None:
        email = metadata.get("email")
        password_hash = metadata.get("password_hash")
        if not email or not password_hash:
            return Response(
                {"detail": "Registration session no longer valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered"}, status=409)

        user = User(
            email=email,
            phone_number=metadata.get("phone_number", ""),
            full_name=metadata.get("full_name", ""),
            address=metadata.get("address", ""),
        )
        user.password = password_hash
        user.save()

        metadata.pop("password_hash", None)
        metadata["completed"] = True
        metadata["user_id"] = user.id
        session.metadata = metadata
        session.save(update_fields=["metadata"])

    refresh = RefreshToken.for_user(user)
    response_payload = {
        "user": UserSerializer(user).data,
        "tokens": {"refresh": str(refresh), "access": str(refresh.access_token)},
    }
    status_code = status.HTTP_200_OK if completed_before else status.HTTP_201_CREATED
    return Response(response_payload, status=status_code)


@extend_schema(
    tags=["Auth"],
    summary="Complete login with OTP",
    request=LoginOTPVerifySerializer,
    responses={200: None, 400: None, 404: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def login_verify(request):
    serializer = LoginOTPVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if not settings.OTP_SETTINGS.get("login_enforced", False):
        return Response(
            {"detail": "OTP login not enforced."}, status=status.HTTP_400_BAD_REQUEST
        )

    session = get_object_or_404(
        PhoneOTP,
        session_id=serializer.validated_data["session_id"],
        purpose=PhoneOTP.Purpose.LOGIN,
    )

    manager = OTPSessionManager(purpose=PhoneOTP.Purpose.LOGIN)
    if not manager.verify_code(session, serializer.validated_data["code"]):
        return Response(
            {"detail": "Invalid or expired OTP."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = session.user
    if user is None:
        user_id = (session.metadata or {}).get("user_id")
        user = User.objects.filter(id=user_id).first()
    if user is None:
        return Response(
            {"detail": "Login session no longer valid."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    refresh = RefreshToken.for_user(user)
    payload = {"refresh": str(refresh), "access": str(refresh.access_token)}
    return Response(payload, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Auth"],
    summary="Start forgot-password flow (send OTP)",
    request=PasswordResetInitSerializer,
    responses={201: None, 400: None, 404: None, 429: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def password_reset_init(request):
    serializer = PasswordResetInitSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    identifier = serializer.validated_data["identifier"]
    user = _resolve_user(identifier)
    if not user:
        return Response(
            {"detail": "No account matches that email or phone number."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not user.phone_number:
        return Response(
            {"detail": "This account is missing a verified phone number."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    manager = OTPSessionManager(purpose=PhoneOTP.Purpose.PASSWORD_RESET)
    metadata = {
        "user_id": user.id,
        "email": user.email,
        "identifier": identifier,
        "purpose": "password_reset",
    }
    try:
        session = manager.create_session(
            phone_number=user.phone_number,
            user=user,
            metadata=metadata,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    payload = {
        "session_id": str(session.session_id),
        "otp_sent_to": _mask_phone(user.phone_number),
        "expires_in": settings.OTP_SETTINGS["ttl_seconds"],
        "resend_cooldown": settings.OTP_SETTINGS["resend_cooldown_seconds"],
    }
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Auth"],
    summary="Complete forgot-password with OTP",
    request=PasswordResetCompleteSerializer,
    responses={200: None, 400: None, 404: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_complete(request):
    serializer = PasswordResetCompleteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    session = get_object_or_404(
        PhoneOTP,
        session_id=serializer.validated_data["session_id"],
        purpose=PhoneOTP.Purpose.PASSWORD_RESET,
    )

    manager = OTPSessionManager(purpose=PhoneOTP.Purpose.PASSWORD_RESET)
    if not manager.verify_code(session, serializer.validated_data["code"]):
        return Response(
            {"detail": "Invalid or expired OTP."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = session.user
    if user is None:
        user_id = (session.metadata or {}).get("user_id")
        user = User.objects.filter(id=user_id).first()
    if user is None:
        return Response(
            {"detail": "Password reset session is no longer valid."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    new_password = serializer.validated_data["new_password"]
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return Response(
        {"detail": "Password updated successfully."}, status=status.HTTP_200_OK
    )


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
