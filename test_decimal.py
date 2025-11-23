import os
import django
from decimal import Decimal
from rest_framework import serializers

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

class TestSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)

data = TestSerializer({"lat": Decimal("23.810300")}).data
print(f"Serialized Decimal: {data['lat']} (Type: {type(data['lat'])})")
