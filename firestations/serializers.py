from rest_framework import serializers

from .models import Division, District, FireStation


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ("id", "name_en", "name_bn", "slug")


class DistrictSerializer(serializers.ModelSerializer):
    division = DivisionSerializer(read_only=True)

    class Meta:
        model = District
        fields = ("id", "name_en", "name_bn", "division")


class FireStationSerializer(serializers.ModelSerializer):
    division_en = serializers.CharField(
        source="district.division.name_en", read_only=True
    )
    division_bn = serializers.CharField(
        source="district.division.name_bn", read_only=True
    )
    district_en = serializers.CharField(source="district.name_en", read_only=True)
    district_bn = serializers.CharField(source="district.name_bn", read_only=True)
    contact_number_list = serializers.SerializerMethodField()

    class Meta:
        model = FireStation
        fields = (
            "id",
            "name_en",
            "name_bn",
            "serial",
            "contact_text",
            "contact_numbers",
            "contact_number_list",
            "source_pdf",
            "division_en",
            "division_bn",
            "district_en",
            "district_bn",
        )

    def get_contact_number_list(self, obj: FireStation) -> list[str]:
        return obj.contact_number_list
