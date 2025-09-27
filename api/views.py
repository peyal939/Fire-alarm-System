from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes


@api_view(["GET"])
@extend_schema(
    tags=["System"],
    summary="Liveness probe",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Service is alive",
            examples=[OpenApiExample("ok", value={"status": "ok"}, response_only=True)],
        )
    },
)
def healthz(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@extend_schema(
    tags=["System"],
    summary="Readiness probe",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Service is ready",
            examples=[
                OpenApiExample("ready", value={"status": "ready"}, response_only=True)
            ],
        )
    },
)
def readyz(request):
    return Response({"status": "ready"})
