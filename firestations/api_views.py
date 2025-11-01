from django.db.models import Q
from rest_framework import filters, viewsets
from rest_framework.pagination import LimitOffsetPagination

from .models import FireStation
from .serializers import FireStationSerializer


class FireStationPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 500


class FireStationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FireStationSerializer
    pagination_class = FireStationPagination
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = (
        "name_en",
        "name_bn",
        "district__name_en",
        "district__name_bn",
        "district__division__name_en",
        "district__division__name_bn",
    )
    ordering_fields = (
        "name_en",
        "name_bn",
        "serial",
        "district__name_en",
        "district__division__name_en",
    )
    ordering = (
        "district__division__name_en",
        "district__name_en",
        "serial",
        "name_en",
    )

    def get_queryset(self):
        qs = FireStation.objects.select_related("district", "district__division").all()

        params = self.request.query_params
        division = params.get("division")
        district = params.get("district")

        if division:
            qs = qs.filter(
                Q(district__division__name_en__icontains=division)
                | Q(district__division__name_bn__icontains=division)
                | Q(district__division__id__iexact=division)
            )

        if district:
            qs = qs.filter(
                Q(district__name_en__icontains=district)
                | Q(district__name_bn__icontains=district)
                | Q(district__id__iexact=district)
            )

        return qs
