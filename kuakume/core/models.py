import re

from django.contrib.auth.models import (
    AbstractUser,
)
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):

    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    phone = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Phone Number",
        help_text="Format: +4475836648484",
    )
    email = models.EmailField(max_length=255, null=True, blank=True,unique=True,)

    REQUIRED_FIELDS = ["phone", "email", "first_name", "last_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.phone} {self.first_name} {self.last_name}"

    def clean(self):
        """Validate the mobile number format, and email existence"""
        if self.phone:
            cleaned = re.sub(r"\s+", "", self.phone)
            if not cleaned.startswith("+"):
                raise ValidationError(
                    {
                        "phone": "Mobile number must include country code (e.g., +4475836648484)"
                    }
                )
            if not re.match(r"^\+\d{7,15}$", cleaned):
                raise ValidationError(
                    {
                        "phone": "Invalid mobile number format. Use format: +4475836648484"
                    }
                )

    def save(self, *args, **kwargs):
        # self.full_clean() automatically calls self.clean()
        self.full_clean()
        super().save(*args, **kwargs)