from __future__ import annotations

from django.db import models
from django.utils.text import slugify


class Division(models.Model):
    """Administrative division for Bangladesh fire services."""

    name_bn = models.CharField("Name (Bangla)", max_length=128, unique=True)
    name_en = models.CharField("Name (English)", max_length=128, unique=True)
    slug = models.SlugField(max_length=160, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name_en",)
        verbose_name = "Division"
        verbose_name_plural = "Divisions"

    def __str__(self) -> str:  # pragma: no cover - human readable string
        return self.name_en

    def save(self, *args, **kwargs) -> None:
        if not self.slug or slugify(self.name_en) != self.slug:
            self.slug = slugify(self.name_en)
        super().save(*args, **kwargs)


class District(models.Model):
    """District that belongs to a division."""

    division = models.ForeignKey(
        Division, related_name="districts", on_delete=models.CASCADE
    )
    name_bn = models.CharField("Name (Bangla)", max_length=128)
    name_en = models.CharField("Name (English)", max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("division__name_en", "name_en")
        unique_together = (("division", "name_bn"), ("division", "name_en"))
        verbose_name = "District"
        verbose_name_plural = "Districts"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name_en} ({self.division.name_en})"


class FireStation(models.Model):
    """Individual fire service office/station entry."""

    district = models.ForeignKey(
        District, related_name="stations", on_delete=models.CASCADE
    )
    name_bn = models.CharField("Name (Bangla)", max_length=256)
    name_en = models.CharField("Name (English)", max_length=256)
    serial = models.IntegerField(blank=True, null=True)
    contact_text = models.TextField(blank=True, default="")
    contact_numbers = models.TextField(blank=True, default="")
    source_pdf = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("district__division__name_en", "district__name_en", "serial")
        indexes = [
            models.Index(fields=("district", "serial")),
            models.Index(fields=("district", "name_en")),
            models.Index(fields=("name_en", "name_bn"), name="fire_name_idx"),
        ]
        verbose_name = "Fire Station"
        verbose_name_plural = "Fire Stations"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name_en} ({self.district.name_en})"

    @property
    def contact_number_list(self) -> list[str]:
        """Return the contact numbers as a list for easy consumption."""

        numbers = [
            chunk.strip()
            for chunk in (self.contact_numbers or "").split("|")
            if chunk.strip()
        ]
        return numbers
