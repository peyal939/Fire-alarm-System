from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def healthz(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def readyz(request):
    return Response({"status": "ready"})
